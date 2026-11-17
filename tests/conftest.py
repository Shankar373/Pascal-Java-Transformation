"""Shared fixtures and helpers for the P1 test suite.

Two jobs:

1. Make ``tools/`` importable as the package root so ``import p1`` works with
   no installation step and no ``PYTHONPATH`` juggling.
2. Provide *builders* for hostile inputs and representative applications, so
   individual tests state the attack or the feature they cover rather than
   re-deriving zip headers and directory trees inline.

Every builder returns something deterministic: no clocks, no randomness, no
network.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from typing import Any, Iterable, Mapping

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_ROOT = REPO_ROOT / "tools"

if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

#: Fixed timestamp for every archive entry: source-derived, never "now".
FIXED_ZIP_TIME = (2020, 1, 2, 3, 4, 6)


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def write_tree(root: Path, files: Mapping[str, str | bytes]) -> Path:
    """Materialise ``relative/path -> content`` under *root* (POSIX keys)."""

    root.mkdir(parents=True, exist_ok=True)
    for relative, content in files.items():
        target = root / Path(*relative.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            # utf-8 with no BOM: fixtures must not depend on the platform
            # default code page.
            target.write_bytes(content.encode("utf-8"))
        else:
            target.write_bytes(content)
    return root


def make_zip(path: Path, entries: Iterable[Any]) -> Path:
    """Write a ZIP built from *entries*.

    Each entry is either ``(name, data)`` or a mapping with:

    ``name``     entry name (default archive path)
    ``raw_name`` name to force *after* construction, for names the ZIP
                 library would otherwise rewrite on Windows
    ``data``     payload bytes
    ``mode``     Unix mode bits stored in the high word of ``external_attr``
    ``compress_type`` ``zipfile.ZIP_*`` (default DEFLATED)
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for entry in entries:
            if isinstance(entry, Mapping):
                name = entry["name"]
                info = zipfile.ZipInfo(
                    name, date_time=entry.get("date_time", FIXED_ZIP_TIME)
                )
                info.external_attr = int(entry.get("mode", 0o100644)) << 16
                info.compress_type = entry.get(
                    "compress_type", zipfile.ZIP_DEFLATED
                )
                forced = entry.get("raw_name")
                if forced is not None:
                    # ZipInfo's constructor rewrites "\" to "/" on Windows;
                    # forcing the field afterwards is the only way to test a
                    # genuine backslash name on this platform.
                    info.filename = forced
                archive.writestr(info, entry.get("data", b""))
            else:
                info = zipfile.ZipInfo(entry[0], date_time=FIXED_ZIP_TIME)
                info.external_attr = 0o100644 << 16
                archive.writestr(info, entry[1])
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def artifact_bytes(outdir: Path, name: str) -> bytes:
    return (Path(outdir) / name).read_bytes()


def codes_of(exc: BaseException) -> list[str]:
    """All ``code`` values reachable from *exc* (class attribute or instance)."""

    out: list[str] = []
    seen: set[type] = set()
    for cls in type(exc).__mro__:
        if cls in seen:
            continue
        seen.add(cls)
        code = cls.__dict__.get("code")
        if isinstance(code, str):
            out.append(code)
    code = getattr(exc, "code", None)
    if isinstance(code, str) and code not in out:
        out.append(code)
    return out


def diagnostic_codes(manifest: Mapping[str, Any]) -> list[str]:
    return sorted({str(d.get("code")) for d in manifest["diagnostics"]})


# ---------------------------------------------------------------------------
# Representative applications
# ---------------------------------------------------------------------------

#: A console application exercising entry points, includes, profiles, native
#: references, SQL and a database unit.  Single root, so the layout is
#: unambiguous and the primary root is deterministic.
CONSOLE_APP: dict[str, str] = {
    "src/MiniApp.dpr": (
        "program MiniApp;\n"
        "\n"
        "{$APPTYPE CONSOLE}\n"
        "{$MODE OBJFPC}\n"
        "{$DEFINE VERBOSE}\n"
        "\n"
        "uses\n"
        "  SysUtils,\n"
        "  uMath,\n"
        "  uReport,\n"
        "  uData;\n"
        "\n"
        "{$I shared.inc}\n"
        "\n"
        "const\n"
        "  DLL = 'kernel32.dll';\n"
        "\n"
        "procedure Go; external 'foo.dll';\n"
        "\n"
        "begin\n"
        "  LoadLibrary('x.dll');\n"
        "  Go;\n"
        "  WriteLn(Report(2, 3));\n"
        "end.\n"
    ),
    "src/uMath.pas": (
        "unit uMath;\n"
        "\n"
        "{$MODE OBJFPC}\n"
        "\n"
        "interface\n"
        "\n"
        "function Report(a, b: Integer): Integer;\n"
        "\n"
        "implementation\n"
        "\n"
        "function Report(a, b: Integer): Integer;\n"
        "begin\n"
        "  Result := a + b;\n"
        "end;\n"
        "\n"
        "end.\n"
    ),
    "src/uReport.pas": (
        "unit uReport;\n"
        "\n"
        "interface\n"
        "\n"
        "uses SysUtils, uMath;\n"
        "\n"
        "function Emit(const S: string): string;\n"
        "\n"
        "implementation\n"
        "\n"
        "function Emit(const S: string): string;\n"
        "begin\n"
        "  Result := S;\n"
        "end;\n"
        "\n"
        "end.\n"
    ),
    "src/uData.pas": (
        "unit uData;\n"
        "\n"
        "interface\n"
        "\n"
        "uses\n"
        "  SysUtils, DB, SqlExpr;\n"
        "\n"
        "type\n"
        "  TOrderStore = class\n"
        "  private\n"
        "    FConn: TSQLConnection;\n"
        "  public\n"
        "    constructor Create;\n"
        "  end;\n"
        "\n"
        "implementation\n"
        "\n"
        "constructor TOrderStore.Create;\n"
        "begin\n"
        "  inherited Create;\n"
        "  FConn := TSQLConnection.Create(nil);\n"
        "end;\n"
        "\n"
        "end.\n"
    ),
    "shared.inc": (
        "{ shared helpers for MiniApp }\n"
        "const SHARED_VERSION = '1.0.0';\n"
    ),
    "sql/orders.sql": (
        "CREATE TABLE orders (\n"
        "  id INTEGER PRIMARY KEY AUTOINCREMENT,\n"
        "  total NUMERIC NOT NULL\n"
        ");\n"
        "PRAGMA foreign_keys = ON;\n"
    ),
    "src/MiniApp.dproj": (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<Project xmlns="http://schemas.microsoft.com/developer/'
        'msbuild/2003">\n'
        "  <PropertyGroup>\n"
        "    <MainSource>MiniApp.dpr</MainSource>\n"
        "    <AppType>Console</AppType>\n"
        "    <Platform>Win32</Platform>\n"
        "    <DCC_Define>DEBUG;CONDITIONALEXPRESSIONS</DCC_Define>\n"
        "    <DCC_UnitSearchPath>src;lib</DCC_UnitSearchPath>\n"
        "    <DCC_ExeOutput>.\\Win32\\Debug</DCC_ExeOutput>\n"
        "  </PropertyGroup>\n"
        "</Project>\n"
    ),
    "README.md": "# Console fixture\n",
    "data/notes.dat": b"\x00\x01\x02\x03BINARYBLOB\xff\xfe",
    "data/empty.txt": b"",
}


@pytest.fixture()
def app_tree(tmp_path: Path) -> Path:
    """The representative console application (single unambiguous root)."""

    return write_tree(tmp_path / "app", CONSOLE_APP)


#: Two project roots in one tree: the layout is genuinely ambiguous, so the
#: primary root must be reported as UNKNOWN rather than guessed.
AMBIGUOUS_APP: dict[str, str] = {
    "alpha/Alpha.dpr": "program Alpha;\nbegin\nend.\n",
    "alpha/Alpha.dproj": "<Project><PropertyGroup/></Project>\n",
    "beta/Beta.dpr": "program Beta;\nbegin\nend.\n",
    "beta/Beta.lpi": "<CONFIG><ProjectOptions/></CONFIG>\n",
}


@pytest.fixture()
def ambiguous_tree(tmp_path: Path) -> Path:
    return write_tree(tmp_path / "ambiguous", AMBIGUOUS_APP)


#: A Lazarus GUI tree: shape detection must report a GUI shape and surface the
#: ``FAIL-DEPENDENCY`` unit gap rather than claiming the application builds.
GUI_APP: dict[str, str] = {
    "lcl/App.lpr": (
        "program App;\n"
        "\n"
        "{$MODE OBJFPC}\n"
        "\n"
        "uses\n"
        "  Interfaces, // this includes the LCL widgetset\n"
        "  Forms, uMainForm;\n"
        "\n"
        "{$R *.res}\n"
        "\n"
        "begin\n"
        "  Application.Initialize;\n"
        "  Application.Run;\n"
        "end.\n"
    ),
    "lcl/uMainForm.pas": (
        "unit uMainForm;\n"
        "\n"
        "{$MODE OBJFPC}\n"
        "\n"
        "interface\n"
        "\n"
        "uses\n"
        "  Classes, SysUtils, Forms, Controls, Graphics;\n"
        "\n"
        "type\n"
        "  TMainForm = class(TForm)\n"
        "  end;\n"
        "\n"
        "var\n"
        "  MainForm: TMainForm;\n"
        "\n"
        "implementation\n"
        "\n"
        "end.\n"
    ),
    "lcl/App.lpi": (
        "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
        "<CONFIG>\n"
        "  <ProjectOptions>\n"
        "    <Version Value=\"12\"/>\n"
        "    <General>\n"
        "      <Flags>\n"
        "        <MainUnitHasCreateFormStatements Value=\"True\"/>\n"
        "      </Flags>\n"
        "    </General>\n"
        "    <BuildModes>\n"
        "      <Item Name=\"Default\" Default=\"True\"/>\n"
        "    </BuildModes>\n"
        "  </ProjectOptions>\n"
        "</CONFIG>\n"
    ),
}


@pytest.fixture()
def gui_tree(tmp_path: Path) -> Path:
    return write_tree(tmp_path / "gui", GUI_APP)


# ---------------------------------------------------------------------------
# Run helpers
# ---------------------------------------------------------------------------


def run_pipeline(source: Path | str, outdir: Path, **kwargs: Any):
    """Run the full discovery pipeline against *source*."""

    from p1.pipeline import run

    return run(str(source), Path(outdir), **kwargs)


def ingest_zip_ok(path: Path, staging: Path, **kwargs: Any):
    """Extract a *benign* archive directly (no pipeline, no analysis)."""

    from p1.zipingest import ingest_zip

    return ingest_zip(Path(path), Path(staging), **kwargs)


def expect_refusal(fn, *args: Any, **kwargs: Any) -> str:
    """Call *fn*; assert it raised a typed refusal; return the code."""

    from p1.errors import IngestionError

    try:
        fn(*args, **kwargs)
    except IngestionError as exc:  # the only acceptable outcome
        return str(exc.code)
    raise AssertionError(
        f"{getattr(fn, '__name__', fn)} accepted hostile input without "
        "raising an IngestionError"
    )


def assert_nothing_extracted(staging: Path, sentinels: Iterable[Path]) -> None:
    """A phase-1 refusal must leave staging empty and sentinels untouched.

    ``ingest_zip`` validates the whole central directory before writing, so
    any refusal raised from phase 1 proves that *nothing* was materialised.
    ``sentinels`` are files placed outside the staging root; a traversal that
    succeeded would have overwritten or created siblings there.
    """

    assert list(Path(staging).iterdir()) == [], (
        f"staging was populated by a refused archive: "
        f"{sorted(p.name for p in Path(staging).iterdir())}"
    )
    for sentinel in sentinels:
        assert sentinel.exists(), f"sentinel disappeared: {sentinel}"


__all__ = [
    "REPO_ROOT",
    "TOOLS_ROOT",
    "CONSOLE_APP",
    "AMBIGUOUS_APP",
    "GUI_APP",
    "FIXED_ZIP_TIME",
    "write_tree",
    "make_zip",
    "read_json",
    "artifact_bytes",
    "codes_of",
    "diagnostic_codes",
    "run_pipeline",
    "ingest_zip_ok",
    "expect_refusal",
    "assert_nothing_extracted",
]
