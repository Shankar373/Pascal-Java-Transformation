#!/usr/bin/env python3
"""Fixture-corpus regression gate (task E5).

Runs the P0 compiler sweep and scores every fixture against
``corpus/expectations.txt``.  Any new ``MISMATCH``, any fixture with no
expectation and any expectation with no fixture exits non-zero, so the
corpus cannot drift away from its contract without failing the build.

Two runners, one comparator:

``--host``
    Invokes ``tools/p0/sweep-fpc.ps1`` with the host Free Pascal.
``--docker``
    Invokes ``tools/p0/sweep-fpc-docker.sh`` inside the *pinned* container
    image, mounted read-only.

Both emit the same ``PASS|<mode>|<rel>`` / ``FAIL|<mode>|<rel>|<detail>``
records, which are normalised here and compared once, in this module, so the
host and container verdicts are scored by identical logic.

Usage:
    python tools/p1/sweep.py --host    [--out <file>] [--fpc <path>]
    python tools/p1/sweep.py --docker  [--out <file>]
    python tools/p1/sweep.py --input <recorded-output> [--platform linux]

Exit codes: 0 = every expectation matched, 1 = at least one MISMATCH,
2 = environment or usage failure (the sweep did not run).
"""

from __future__ import annotations

import argparse
import platform as _platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]

#: Fixtures are exactly the extensions the P0 sweeps compile.
FIXTURE_SUFFIXES = (".pas", ".dpr", ".lpr")

DEFAULT_EXPECTATIONS = REPO / "corpus" / "expectations.txt"
HOST_SCRIPT = REPO / "tools" / "p0" / "sweep-fpc.ps1"
DOCKER_SCRIPT = "tools/p0/sweep-fpc-docker.sh"

#: Pinned container image (docs/p0/TOOLCHAIN_FEASIBILITY.md).  Pinned by
#: digest: a floating tag would make the gate non-reproducible.
CONTAINER_IMAGE = (
    "freepascal/fpc:3.2.2-bookworm-full"
    "@sha256:6c951541251e24e67d358ec7a5b2dfb3121069cdf73fd0252226868dbecd3872"
)

DEFAULT_FPC = r"C:\FPC\3.2.2\bin\i386-Win32\fpc.exe"

#: Expected-verdict vocabulary (corpus/README.md).
EXPECTED_VERDICTS = ("PASS", "FAIL-DEPENDENCY")

#: Which expected verdict a compiler FAIL satisfies.  A declared
#: ``FAIL-DEPENDENCY`` is *satisfied* by a FAIL; a declared ``PASS`` is not.
FAIL_SATISFIES = ("FAIL-DEPENDENCY",)


class GateError(RuntimeError):
    """Environment or usage failure: the sweep did not run."""


# ---------------------------------------------------------------------------
# Expectations
# ---------------------------------------------------------------------------


def load_expectations(path: Path) -> dict[str, tuple[str, dict[str, str]]]:
    """Parse ``corpus/expectations.txt`` into ``rel -> (verdict, overrides)``.

    Raises :class:`GateError` on a malformed line: a broken expectation table
    must not silently degrade into "everything passes".
    """

    if not path.is_file():
        raise GateError(f"expectations file not found: {path}")

    table: dict[str, tuple[str, dict[str, str]]] = {}
    for number, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        parts = [part.strip() for part in line.split("|")]
        if len(parts) < 2 or not parts[0] or not parts[1]:
            raise GateError(f"{path}:{number}: malformed line: {raw!r}")

        rel = parts[0].replace("\\", "/")
        verdict = parts[1]
        if verdict not in EXPECTED_VERDICTS:
            raise GateError(
                f"{path}:{number}: unknown expectation {verdict!r}; "
                f"expected one of {EXPECTED_VERDICTS}"
            )

        overrides: dict[str, str] = {}
        if len(parts) > 2 and parts[2]:
            for entry in parts[2].split(","):
                entry = entry.strip()
                if not entry:
                    continue
                if "=" not in entry:
                    raise GateError(
                        f"{path}:{number}: bad platform override {entry!r}"
                    )
                os_name, value = (piece.strip() for piece in entry.split("=", 1))
                if value not in EXPECTED_VERDICTS:
                    raise GateError(
                        f"{path}:{number}: bad override verdict {value!r}"
                    )
                overrides[os_name.lower()] = value

        if rel in table:
            raise GateError(f"{path}:{number}: duplicate entry for {rel}")
        table[rel] = (verdict, overrides)

    if not table:
        raise GateError(f"{path}: no expectations declared")
    return table


def expected_for(
    table: dict[str, tuple[str, dict[str, str]]], rel: str, os_name: str
) -> str | None:
    """Verdict expected for *rel* on *os_name*, or None if undeclared."""

    entry = table.get(rel)
    if entry is None:
        return None
    base, overrides = entry
    return overrides.get(os_name.lower(), base)


# ---------------------------------------------------------------------------
# Fixture discovery and sweep parsing
# ---------------------------------------------------------------------------


def discover_fixtures(corpus: Path) -> list[str]:
    """POSIX-relative paths of every compilable fixture, sorted."""

    if not corpus.is_dir():
        raise GateError(f"corpus not found: {corpus}")
    found = [
        path.relative_to(corpus).as_posix()
        for path in corpus.rglob("*")
        if path.is_file() and path.suffix.lower() in FIXTURE_SUFFIXES
    ]
    return sorted(found, key=str.lower)


def parse_records(text: str) -> list[tuple[str, str, str]]:
    """Extract ``(verdict, mode, rel)`` from sweep output.

    Accepts both the host form (``PASS|<mode>|<rel>``) and the container form
    (``RESULT|PASS|<mode>|<rel>``); anything else is ignored, so a header or
    a diagnostic line cannot be mistaken for a verdict.
    """

    records: list[tuple[str, str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("RESULT|"):
            line = line[len("RESULT|"):]
        if line.startswith(("TOOL|", "PLATFORM|", "EXPECTATION|",
                            "SUMMARY|", "FATAL|", "IMAGE|", "DIGEST|",
                            "DOCKER|", "MOUNT|", "SCRIPT|")):
            continue
        parts = line.split("|")
        if len(parts) < 3 or parts[0] not in ("PASS", "FAIL"):
            continue
        verdict, mode, rel = parts[0], parts[1], parts[2]
        records.append((verdict, mode, rel.replace("\\", "/")))
    return records


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------


def _powershell() -> str:
    for candidate in ("powershell", "pwsh"):
        found = shutil.which(candidate)
        if found:
            return found
    raise GateError("no PowerShell found on PATH; cannot run the host sweep")


def resolve_fpc(requested: str) -> str:
    """Resolve the host compiler: the pin if present, else ``fpc`` on PATH.

    The pin is what this repository was validated against; falling back to
    PATH keeps the gate runnable on a Linux CI runner (which reports the
    resolved compiler in the report header, so a fallback is never silent).
    """

    if Path(requested).is_file():
        return requested
    found = shutil.which("fpc")
    if found:
        return found
    raise GateError(
        f"fpc not found at {requested!r} and no 'fpc' on PATH; "
        "install FPC 3.2.2 or pass --fpc"
    )


def compiler_version(fpc: str) -> str:
    """``fpc -iV``, or ``unknown`` if the compiler cannot answer."""

    try:
        done = subprocess.run(
            [fpc, "-iV"], capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    version = (done.stdout or "").strip()
    return version or "unknown"


def compiler_label(raw: str, fallback: str) -> str:
    """``name:version`` for the compiler that produced *raw*.

    The container sweep declares its compiler in a ``TOOL|`` header line; the
    host sweep does not, so its caller supplies a fallback.  Recording it in
    the report means an archived sweep can never claim a toolchain it did not
    use.
    """

    for line in raw.splitlines():
        if line.startswith("TOOL|"):
            parts = line.split("|", 2)
            path = parts[1] if len(parts) > 1 else ""
            version = ""
            if len(parts) > 2 and parts[2].startswith("version="):
                version = parts[2][len("version="):].strip()
            name = Path(path).name or path or "fpc"
            return f"{name}:{version}" if version else name
    return fallback


def run_host(fpc: str) -> str:
    """Run the P0 host sweep and return its raw output."""

    if not Path(fpc).is_file():
        raise GateError(
            f"fpc not found at {fpc!r}; install FPC 3.2.2 or pass --fpc"
        )
    if not HOST_SCRIPT.is_file():
        raise GateError(f"host sweep script missing: {HOST_SCRIPT}")

    command = [
        _powershell(),
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(HOST_SCRIPT),
        "-FpcPath",
        fpc,
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8",
        errors="replace", cwd=str(REPO), timeout=3600,
    )
    if completed.returncode != 0:
        raise GateError(
            "host sweep failed: "
            + (completed.stderr or completed.stdout or "").strip()[:500]
        )
    return completed.stdout


def run_docker() -> str:
    """Run the P0 sweep inside the pinned container and return its output."""

    if shutil.which("docker") is None:
        raise GateError("docker not found on PATH; cannot run the container sweep")

    command = [
        "docker", "run", "--rm",
        "-v", f"{REPO.as_posix()}:/repo:ro",
        CONTAINER_IMAGE,
        "bash", f"/repo/{DOCKER_SCRIPT}",
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, encoding="utf-8",
        errors="replace", cwd=str(REPO), timeout=3600,
    )
    # The container script exits non-zero on its own MISMATCH check; the
    # output is still usable, so it is not treated as an environment failure.
    if completed.returncode not in (0, 1):
        raise GateError(
            "container sweep failed: "
            + (completed.stderr or completed.stdout or "").strip()[:500]
        )
    if not completed.stdout.strip():
        raise GateError("container sweep produced no output")
    return completed.stdout


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def compare(
    records: list[tuple[str, str, str]],
    table: dict[str, tuple[str, dict[str, str]]],
    os_name: str,
    fixtures: list[str],
) -> tuple[list[str], int]:
    """Score *records* against *table*; return (report lines, exit code)."""

    lines: list[str] = []
    mismatches = 0
    seen: dict[str, str] = {}

    for verdict, mode, rel in records:
        if rel in seen:
            lines.append(
                f"RESULT|{verdict}|{mode}|{rel}\n"
                f"EXPECTATION|{rel}|expected=duplicate|actual={verdict}|"
                f"MISMATCH"
            )
            mismatches += 1
            continue
        seen[rel] = verdict
        lines.append(f"RESULT|{verdict}|{mode}|{rel}")

        wanted = expected_for(table, rel, os_name)
        if wanted is None:
            lines.append(
                f"EXPECTATION|{rel}|expected=UNDECLARED|actual={verdict}|"
                f"MISMATCH"
            )
            mismatches += 1
            continue

        agreed = verdict == "FAIL" if wanted in FAIL_SATISFIES else verdict == "PASS"
        lines.append(
            f"EXPECTATION|{rel}|expected={wanted}|actual={verdict}|"
            f"{'MATCH' if agreed else 'MISMATCH'}"
        )
        if not agreed:
            mismatches += 1

    # An expectation with no fixture means the corpus lost a file (or the
    # sweep stopped early): also a failure, not a silent shrink.
    for rel in fixtures:
        if rel not in seen:
            lines.append(
                f"EXPECTATION|{rel}|expected={expected_for(table, rel, os_name)}"
                "|actual=NOT-SWEPT|MISMATCH"
            )
            mismatches += 1

    matched = sum(1 for line in lines if line.endswith("|MATCH"))
    lines.append(
        f"SUMMARY|fixtures={len(records)}|expected={len(fixtures)}"
        f"|MATCH={matched}|MISMATCH={mismatches}"
    )
    return lines, (1 if mismatches else 0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sweep.py", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--host", action="store_true",
                      help="sweep with the host Free Pascal")
    mode.add_argument("--docker", action="store_true",
                      help="sweep inside the pinned container image")
    mode.add_argument("--input", metavar="FILE",
                      help="compare an already-recorded sweep output")
    parser.add_argument("--corpus", default=str(REPO / "corpus"))
    parser.add_argument("--expect", default=str(DEFAULT_EXPECTATIONS))
    parser.add_argument("--fpc", default=DEFAULT_FPC,
                        help="host fpc.exe path (with --host)")
    parser.add_argument("--platform", choices=("windows", "linux"),
                        help="override the platform used for expectations "
                             "(derived automatically when omitted)")
    parser.add_argument("--out", metavar="FILE",
                        help="archive the full report here (baseline mode)")
    args = parser.parse_args(argv)

    # Refuse a clobber before doing any work: an archive that silently
    # overwrites itself retains nothing (A4), and the refusal should not
    # cost a full sweep first.
    out_path = Path(args.out) if args.out else None
    if out_path is not None and out_path.exists():
        print(
            f"GATE|ERROR|refusing to overwrite an existing archive: {out_path}",
            file=sys.stderr,
        )
        return 2

    try:
        corpus = Path(args.corpus)
        expectations = Path(args.expect)
        table = load_expectations(expectations)
        fixtures = discover_fixtures(corpus)

        if args.host:
            fpc = resolve_fpc(args.fpc)
            raw = run_host(fpc)
            fallback = Path(fpc).name + ":" + compiler_version(fpc)
            os_name = args.platform or (
                "windows" if sys.platform.startswith(("win", "cygwin"))
                else "linux"
            )
        elif args.docker:
            raw = run_docker()
            fallback = "fpc"
            os_name = args.platform or "linux"
        else:
            source = Path(args.input)
            if not source.is_file():
                raise GateError(f"input record not found: {source}")
            raw = source.read_text(encoding="utf-8", errors="replace")
            fallback = "recorded"
            os_name = args.platform or (
                "linux" if _platform.system() == "Linux" else "windows"
            )
    except GateError as exc:
        print(f"GATE|ERROR|{exc}", file=sys.stderr)
        return 2

    records = parse_records(raw)
    if not records:
        print("GATE|ERROR|sweep produced no PASS/FAIL records", file=sys.stderr)
        return 2

    report, exit_code = compare(records, table, os_name, fixtures)
    header = [
        f"SWEEP|platform={os_name}|fixtures={len(records)}"
        f"|compiler={compiler_label(raw, fallback)}",
        f"EXPECTATIONS|{expectations.name}|entries={len(table)}",
    ]
    gate = (
        "GATE|"
        + ("PASS" if exit_code == 0 else "FAIL")
        + f"|mismatches={sum(1 for line in report if line.endswith('|MISMATCH'))}"
    )
    # The archive is the report exactly as printed.  It is written with the
    # repository's evidence convention - UTF-8 without a BOM, CRLF line
    # endings - so it lines up with docs/p0/evidence/*.txt in a diff.
    text = "\n".join(header + report + [gate]) + "\n"
    sys.stdout.write(text)

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8", newline="\r\n")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
