"""Builders and walkers shared by the blueprint tests.

``discovery_from_tree`` assembles a :class:`~p1.emit.Discovery` the same way
:func:`p1.pipeline.run` does - but without writing outputs - so the blueprint
can be exercised on real, scanned trees.  ``with_stage1_findings`` then fills
the Stage 1 finding lists by hand, standing in for the detectors that produce
them elsewhere.  ``synthetic_discovery`` builds a Discovery with no files on
disk at all (for hostile file names).
"""

from __future__ import annotations

import dataclasses
import os
import random
import sys
from pathlib import Path
from typing import Any, Iterator

from conftest import REPO_ROOT

_FIXTURES = REPO_ROOT / "tests" / "fixtures" / "stage1"
if str(_FIXTURES) not in sys.path:
    sys.path.insert(0, str(_FIXTURES))

from enterprise_app import write_enterprise_app  # noqa: E402

from p1.deps import build_graph  # noqa: E402
from p1.emit import Discovery  # noqa: E402
from p1.errors import DiagnosticSink  # noqa: E402
from p1.findings import (  # noqa: E402
    BuildScriptFinding,
    CompilerConfigFinding,
    DirectoryEntry,
    Evidence,
    IntegrationFinding,
    LibraryFinding,
    RuntimeDependencyFinding,
)
from p1.graph import DependencyGraph  # noqa: E402
from p1.limits import DEFAULT_LIMITS  # noqa: E402
from p1.metadata import (  # noqa: E402
    build_requirements,
    detect_database,
    detect_native_libs,
    detect_os_dependencies,
    detect_sql_files,
)
from p1.model import (  # noqa: E402
    AnalysedFile,
    IngestedFile,
    IngestionResult,
    ingest_directory,
)
from p1.pipeline import (  # noqa: E402
    _attach_staging,
    _text_index,
    analyse_tree,
    build_roots,
)

SECRET = "S3cr3t!Pass"


def enterprise_tree(root: Path) -> Path:
    """Write the enterprise fixture under *root*."""

    return write_enterprise_app(root)


def discovery_from_tree(root: Path, *, origin: str = "fixture") -> Discovery:
    """Run the P1 pipeline pieces over *root* and return a Discovery."""

    sink = DiagnosticSink(DEFAULT_LIMITS.max_diagnostics)
    ingestion = ingest_directory(
        Path(root), origin=origin, kind="directory", skip=(".git",),
        skip_reason="version-control metadata", sink=sink,
        limits=DEFAULT_LIMITS)
    analysed = analyse_tree(ingestion, DEFAULT_LIMITS, sink)
    _attach_staging(analysed, ingestion.staging_root)
    roots, profiles, _ = build_roots(analysed, sink)
    build = build_graph(analysed, roots, sink=sink)
    for payload in build.diagnostics:
        sink.add(_diag(payload))
    requirements = build_requirements(
        analysed, roots, profiles, build.unresolved_units,
        has_project_files=any(r.meta_files for r in roots), sink=sink)
    return Discovery(
        ingestion=ingestion, analysed=analysed, roots=roots,
        graph=build.graph, database=detect_database(analysed),
        sql_files=detect_sql_files(
            analysed, _text_index(analysed, ingestion, DEFAULT_LIMITS)),
        native_libs=detect_native_libs(analysed),
        os_dependencies=detect_os_dependencies(analysed),
        build_requirements=requirements, diagnostics=sink.to_list(),
        origin_label=origin, limits=DEFAULT_LIMITS)


def _diag(payload: dict[str, Any]):
    from p1.errors import Diagnostic

    return Diagnostic.make(
        str(payload.get("code", "X")), str(payload.get("message", "")),
        severity=str(payload.get("severity", "warning")),
        path=payload.get("file"), line=payload.get("line"),
        column=payload.get("column"))


def real_directories(root: Path) -> list[DirectoryEntry]:
    """Every directory of *root*, including empty ones (stand-in detector)."""

    out = []
    for current, dirs, files in os.walk(root):
        for name in dirs:
            rel = (Path(current) / name).relative_to(root).as_posix()
            below = [p for p in (root / rel).rglob("*") if p.is_file()]
            out.append(DirectoryEntry(
                path=rel, depth=rel.count("/") + 1,
                file_count=sum(1 for p in (root / rel).iterdir() if p.is_file()),
                total_file_count=len(below),
                total_bytes=sum(p.stat().st_size for p in below),
                empty=not below))
    return sorted(out, key=lambda d: d.path)


def _ev(file: str, line: int, text: str) -> tuple[Evidence, ...]:
    return (Evidence(file=file, line=line, column=3, text=text),)


def with_stage1_findings(discovery: Discovery, root: Path) -> Discovery:
    """Return a copy of *discovery* with hand-built Stage 1 findings."""

    libraries = [
        LibraryFinding("VCL", "framework", "framework", "Embarcadero",
                       ("forms", "controls"), ("src/MainForm.pas",), False,
                       _ev("src/MainForm.pas", 6, "uses Forms")),
        LibraryFinding("RTL", "rtl", "rtl", "Embarcadero", ("sysutils",),
                       ("src/uConfig.pas",), False,
                       _ev("src/uConfig.pas", 6, "uses SysUtils")),
        LibraryFinding("DevExpress", "ui-components", "external",
                       "Developer Express", ("cxgrid", "dxbarmanager"),
                       ("src/uGrids.pas",), False,
                       _ev("src/uGrids.pas", 7, "uses cxGrid")),
        LibraryFinding("FastReport", "reporting", "external", "Fast Reports",
                       ("frxclass",), ("src/uReports.pas",), False,
                       _ev("src/uReports.pas", 6, "uses frxClass")),
        LibraryFinding("JEDI", "ui-components", "bundled", "JEDI",
                       ("jvedit",), ("src/uGrids.pas",), True,
                       _ev("lib/jedi/JvEdit.pas", 1, "unit JvEdit")),
        LibraryFinding("Indy", "networking", "external", "Indy",
                       ("idhttp", "idftp"),
                       ("src/uHttpClient.pas", "src/uTransfer.pas"), False,
                       _ev("src/uHttpClient.pas", 6, "uses IdHTTP")),
    ]
    integrations = [
        IntegrationFinding("http-client", "Indy",
                           ("https://api.example.com/v1/orders",),
                           _ev("src/uHttpClient.pas", 12, "TIdHTTP.Create")),
        IntegrationFinding("soap-webservice", "SOAPHTTPClient",
                           ("http://billing.corp.example.com:8080/x.asmx",),
                           _ev("src/uSoapClient.pas", 14, "THTTPRIO.URL")),
        IntegrationFinding("com-ole", "ComObj", ("Excel.Application",),
                           _ev("src/uOffice.pas", 12, "CreateOleObject")),
        IntegrationFinding("windows-service", "TService", (),
                           _ev("src/uTransfer.pas", 8, "TService")),
        IntegrationFinding("ftp", "Indy", ("ftp.partner.example.org",),
                           _ev("src/uTransfer.pas", 14, "TIdFTP")),
    ]
    runtime = [
        RuntimeDependencyFinding("dll", "legacy.dll", ("src/uLegacy.pas",),
                                 True, _ev("src/uLegacy.pas", 11, "external")),
        RuntimeDependencyFinding("dll", "vendor.dll", ("src/uLegacy.pas",),
                                 False, _ev("src/uLegacy.pas", 12, "external")),
        RuntimeDependencyFinding("configuration-file", "erp.ini",
                                 ("src/uConfig.pas",), True,
                                 _ev("src/uConfig.pas", 14, "TIniFile")),
        RuntimeDependencyFinding("environment-variable", "ERP_HOME",
                                 ("src/uConfig.pas",), False,
                                 _ev("src/uConfig.pas", 17, "GetEnv")),
        RuntimeDependencyFinding("registry-key", "\\Software\\Contoso\\ERP",
                                 ("src/uConfig.pas",), False,
                                 _ev("src/uConfig.pas", 16, "OpenKey")),
    ]
    scripts = [
        BuildScriptFinding("build.bat", "batch", ("dcc32", "msbuild"),
                           ("ERPSystem.dproj",),
                           _ev("build.bat", 3, "msbuild ERPSystem.dproj")),
        BuildScriptFinding("Makefile", "makefile", ("lazbuild", "make"), (),
                           _ev("Makefile", 2, "lazbuild ERPSystem.lpi")),
    ]
    configs = [CompilerConfigFinding(
        "dcc32.cfg", "dcc-cfg", "global", (("-U", "lib\\jedi;core"),),
        ("ERP_BUILD",), ("lib\\jedi",), _ev("dcc32.cfg", 3, "-U..."))]
    return dataclasses.replace(
        discovery, directories=real_directories(root), libraries=libraries,
        integrations=integrations, runtime_dependencies=runtime,
        build_scripts=scripts, compiler_configs=configs)


def shuffled(discovery: Discovery, seed: int) -> Discovery:
    """A copy of *discovery* whose every list is in a different order."""

    rng = random.Random(seed)
    changes: dict[str, Any] = {}
    for field in dataclasses.fields(discovery):
        value = getattr(discovery, field.name)
        if isinstance(value, list):
            items = list(value)
            rng.shuffle(items)
            changes[field.name] = items
    return dataclasses.replace(discovery, **changes)


def synthetic_discovery(files: dict[str, bytes | int]) -> Discovery:
    """A Discovery of in-memory files (``path -> size``) with no analysis."""

    ingested = []
    analysed = []
    for path, size in files.items():
        length = size if isinstance(size, int) else len(size)
        entry = IngestedFile(path=path, sha256="0" * 64, size=length)
        ingested.append(entry)
        cls = "pascal_unit" if path.lower().endswith(".pas") else "unknown"
        analysed.append(AnalysedFile(inventory=entry, cls=cls,
                                     encoding="ascii"))
    ingestion = IngestionResult(
        kind="directory", origin="synthetic",
        staging_root=Path("/synthetic-staging-root"), files=ingested,
        entry_count=len(ingested),
        total_bytes=sum(f.size for f in ingested))
    return Discovery(ingestion=ingestion, analysed=analysed, roots=[],
                     graph=DependencyGraph(), origin_label="synthetic")


# ---------------------------------------------------------------------------
# walkers
# ---------------------------------------------------------------------------


def evidence_owners(blueprint: dict[str, Any]) -> Iterator[tuple[str, Any]]:
    """Yield ``(where, item)`` for every item bound by the evidence rule."""

    deps = blueprint["dependencies"]
    for key in ("key", "libraries", "native_libraries", "databases",
                "sql_files", "integrations", "runtime"):
        for item in deps[key]:
            yield f"dependencies.{key}", item
    for key in ("scripts", "compiler_configs"):
        for item in deps["build"][key]:
            yield f"dependencies.build.{key}", item
    for item in blueprint["projects"]:
        yield "projects", item
    for item in blueprint["components"]:
        if item["present"]:
            yield f"components.{item['id']}", item
    if blueprint["dialect"]["primary"] != "unknown":
        yield "dialect", blueprint["dialect"]


def all_strings(value: Any) -> Iterator[str]:
    """Every string (keys included) anywhere inside *value*."""

    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from all_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from all_strings(item)
