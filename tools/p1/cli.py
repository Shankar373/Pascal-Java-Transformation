"""Command-line entry point for P1.

    python tools/p1/cli.py ingest <source> --out <dir>
    python tools/p1/cli.py guard  [--root <dir>] [--json]
    python tools/p1/cli.py gate   <source> --out <dir>

Exit codes
----------

``0``
    The command succeeded.
``1``
    A gate failed, or the input was refused.  The refusal code is printed.
``2``
    Usage error (bad arguments).

Running the file directly bootstraps ``sys.path`` so no ``PYTHONPATH`` and no
packaging step is required; running it as ``python -m p1.cli`` takes the same
path through the same code.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

if __package__ in (None, ""):  # direct execution: `python tools/p1/cli.py`
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from p1 import guard as guard_module  # noqa: E402
from p1.errors import IngestionError  # noqa: E402
from p1.limits import DEFAULT_LIMITS  # noqa: E402
from p1.pipeline import run as run_pipeline  # noqa: E402

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


def _add_source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "source",
        help="ZIP archive, git repository (local path or file:// URL), "
             "or a plain directory",
    )
    parser.add_argument("--out", required=True, metavar="DIR",
                        help="directory for the three output documents")
    parser.add_argument("--kind", choices=("zip", "git", "directory"),
                        default=None,
                        help="override input-kind detection")
    parser.add_argument("--commit", default=None, metavar="SHA",
                        help="git commit to pin (required for reproducible "
                             "git ingestion)")
    parser.add_argument("--label", default=None, metavar="NAME",
                        help="origin label recorded in the manifest; a name, "
                             "never a path")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="p1",
        description="Secure ingestion and deterministic Pascal application "
                    "discovery (no compiler, no model, no network).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser(
        "ingest", help="ingest an input and write the discovery documents"
    )
    _add_source_arguments(ingest)

    gate = subparsers.add_parser(
        "gate", help="run the no-LLM gate first, then ingest"
    )
    _add_source_arguments(gate)
    gate.add_argument("--root", default=None, metavar="DIR",
                      help="repository root the gate scans (default: cwd)")

    guard = subparsers.add_parser(
        "guard", help="run the ADR 0005 no-LLM dependency gate only"
    )
    guard.add_argument("--root", default=None, metavar="DIR",
                       help="repository root to scan (default: cwd)")
    guard.add_argument("--json", action="store_true",
                       help="emit the machine-readable summary")
    return parser


def _command_guard(args: argparse.Namespace) -> int:
    root = Path(args.root) if args.root else Path.cwd()
    summary = guard_module.summary(root)
    if args.json:
        print(json.dumps(summary, sort_keys=True, indent=2))
    else:
        print(f"gate: {summary['result']}  "
              f"(findings: {summary['total_findings']})")
        for finding in summary["findings"]:
            print(f"  {finding['file']}:{finding['line']}: "
                  f"{finding['category']}: {finding['excerpt']}")
    return EXIT_OK if summary["result"] == "PASS" else EXIT_FAIL


def _command_ingest(args: argparse.Namespace) -> int:
    result = run_pipeline(
        args.source,
        args.out,
        kind=args.kind,
        commit=args.commit,
        limits=DEFAULT_LIMITS,
        origin_label=args.label,
    )
    discovery = result.discovery
    stats = discovery.graph.stats()
    manifest = json.loads(
        Path(result.outputs["manifest"]).read_text(encoding="utf-8")
    )
    print(f"input      : {discovery.ingestion.kind} "
          f"({manifest['source']['origin']})")
    print(f"files      : {manifest['source']['entry_count']}")
    print(f"classes    : {json.dumps(manifest['classification'], sort_keys=True)}")
    print(f"roots      : {len(manifest['project_roots'])}")
    print(f"edges      : {stats['edges']} "
          f"(resolved {stats['resolved']}, unresolved {stats['unresolved']})")
    print(f"blockers   : {len(manifest['build_requirements']['blockers'])}")
    print(f"diagnostics: {len(manifest['diagnostics'])}")
    for name in ("manifest", "graph", "report"):
        print(f"{name:<12}: {result.outputs[name]}")
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "guard":
        return _command_guard(args)

    if args.command == "gate":
        status = _command_guard(argparse.Namespace(root=args.root, json=False))
        if status != EXIT_OK:
            print("gate: refusing to ingest while the no-LLM gate fails",
                  file=sys.stderr)
            return status

    try:
        return _command_ingest(args)
    except IngestionError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return EXIT_FAIL
    except OSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":
    raise SystemExit(main())
