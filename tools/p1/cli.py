"""Command-line entry point for P1.

    python tools/p1/cli.py ingest <source> --out <dir>
    python tools/p1/cli.py guard  [--root <dir>] [--json]
    python tools/p1/cli.py gate   <source> --out <dir>
    python tools/p1/cli.py discover <source> --store <dir> [--ref REF]
    python tools/p1/cli.py checkpoint verify <checkpoint-dir>
    python tools/p1/cli.py serve [--store <dir>] [--port N]

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
import os
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

    discover = subparsers.add_parser(
        "discover",
        help="Stage 1: ingest, checkpoint and write the application blueprint",
    )
    discover.add_argument(
        "source",
        help="ZIP archive, Git URL (https/ssh) or local repository, or a "
             "plain directory",
    )
    discover.add_argument("--store", required=True, metavar="DIR",
                          help="checkpoint/discovery store directory")
    discover.add_argument("--kind", choices=("zip", "git", "directory"),
                          default=None, help="override input-kind detection")
    discover.add_argument("--ref", default=None, metavar="REF",
                          help="git branch, tag or commit to pin")
    discover.add_argument("--label", default=None, metavar="NAME",
                          help="display name; a name, never a path")
    discover.add_argument("--allow-ssh", action="store_true",
                          help="permit ssh:// and scp-style remotes (needs "
                               "P1_GIT_SSH_KEY and P1_GIT_KNOWN_HOSTS)")
    discover.add_argument("--allow-host", action="append", default=[],
                          metavar="HOST",
                          help="operator allow-list entry that bypasses the "
                               "public-address rule (repeatable)")
    discover.add_argument("--tenant", default=None, metavar="ID",
                          help="tenant whose isolated store subtree is used "
                               "(default tenant writes to the store root)")

    checkpoint = subparsers.add_parser(
        "checkpoint", help="inspect immutable checkpoints"
    )
    checkpoint_sub = checkpoint.add_subparsers(dest="checkpoint_command",
                                               required=True)
    verify = checkpoint_sub.add_parser(
        "verify", help="re-hash a checkpoint and report any tampering"
    )
    verify.add_argument("path", help="<store>/checkpoints/<CP-id>")

    serve = subparsers.add_parser(
        "serve", help="run the local Stage 1 dashboard and API"
    )
    serve.add_argument("--store", default=".stage1-store", metavar="DIR")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--allow-local-root", action="append", default=[],
                       metavar="DIR",
                       help="enable local-directory ingestion inside DIR "
                            "(repeatable)")
    serve.add_argument("--allow-ssh", action="store_true")
    serve.add_argument("--allow-host", action="append", default=[],
                       metavar="HOST")
    serve.add_argument("--allow-remote-bind", action="store_true",
                       help="permit a non-loopback --host (no authentication "
                            "exists before Stage 6)")

    api = subparsers.add_parser(
        "api", help="run the FastAPI service and React workbench",
        add_help=False)
    api.add_argument("rest", nargs=argparse.REMAINDER)
    tenant_token = subparsers.add_parser(
        "tenant-token", help="issue a bearer token bound to one tenant",
        add_help=False)
    tenant_token.add_argument("rest", nargs=argparse.REMAINDER)

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


def _network_policy(extra_hosts: list[str]):
    """Operator allow-list from ``--allow-host`` and ``P1_GIT_ALLOW_HOSTS``."""

    from p1.remotegit import NetworkPolicy

    env_hosts = [h.strip() for h in
                 os.environ.get("P1_GIT_ALLOW_HOSTS", "").split(",")
                 if h.strip()]
    return NetworkPolicy(allow_hosts=tuple(sorted({*env_hosts, *extra_hosts})))


def _command_discover(args: argparse.Namespace) -> int:
    from p1.pipeline import resolve_kind
    from p1.stage1 import DiscoveryRequest, discover
    from p1.tenancy import tenant_root

    kind = resolve_kind(args.source, args.kind)
    if kind == "directory" and (Path(args.source) / ".git").exists():
        kind = "git"
        print("note: the directory is a Git repository; the committed HEAD "
              "(or --ref) is ingested, not the working tree",
              file=sys.stderr)
    request = DiscoveryRequest(
        kind=kind, source=args.source, ref=args.ref, label=args.label,
        allow_ssh=args.allow_ssh,
        network_policy=_network_policy(args.allow_host),
    )
    store = tenant_root(args.store, args.tenant or "default")
    result = discover(
        request, store,
        progress=lambda step, status, msg: print(
            f"[{step}] {status}{': ' + msg if msg else ''}"),
    )
    blueprint = result.blueprint
    summary = blueprint["summary"]
    print(f"checkpoint : {result.checkpoint.checkpoint_id}"
          f"{' (reused)' if result.reused else ''}")
    print(f"status     : {blueprint['stage']['status']}")
    print(f"files      : {summary['total_files']} "
          f"(directories {summary['directories']})")
    print(f"projects   : {summary['projects']}")
    print(f"unresolved : {summary['unresolved_dependencies']}")
    print(f"blockers   : {summary['blockers']}")
    for name in sorted(result.outputs):
        print(f"{name:<12}: {result.outputs[name]}")
    return EXIT_OK


def _command_checkpoint(args: argparse.Namespace) -> int:
    from p1.checkpoint import verify_checkpoint

    report = verify_checkpoint(Path(args.path))
    print(f"checkpoint: {'OK' if report.ok else 'TAMPERED OR INVALID'}")
    for label, items in (("modified", report.modified),
                         ("missing", report.missing),
                         ("extra", report.extra), ("errors", report.errors)):
        for item in items:
            print(f"  {label}: {item}")
    return EXIT_OK if report.ok else EXIT_FAIL


def _command_serve(args: argparse.Namespace) -> int:
    from p1 import server

    argv = ["--store", args.store, "--host", args.host,
            "--port", str(args.port)]
    for root in args.allow_local_root:
        argv += ["--allow-local-root", root]
    if args.allow_ssh:
        argv.append("--allow-ssh")
    for host in args.allow_host:
        argv += ["--allow-host", host]
    if args.allow_remote_bind:
        argv.append("--allow-remote-bind")
    return int(server.main(argv) or 0)


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw[:1] == ["api"]:  # own option set; argparse REMAINDER cannot lead with a flag
        from p1 import api_main
        return api_main.main(raw[1:])
    if raw[:1] == ["tenant-token"]:
        from p1 import api_main
        return api_main.issue_main(raw[1:])
    parser = build_parser()
    args = parser.parse_args(raw)

    if args.command == "guard":
        return _command_guard(args)

    if args.command in ("discover", "checkpoint", "serve"):
        handler = {"discover": _command_discover,
                   "checkpoint": _command_checkpoint,
                   "serve": _command_serve}[args.command]
        try:
            return handler(args)
        except IngestionError as exc:
            print(f"refused: {exc}", file=sys.stderr)
            return EXIT_FAIL
        except OSError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return EXIT_FAIL

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
