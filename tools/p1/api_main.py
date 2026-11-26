"""Entry points for the FastAPI front end: ``p1 api`` and ``p1 tenant-token``."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Sequence

from p1.errors import IngestionError
from p1.server_security import is_loopback_host

__all__ = ["main", "issue_main"]

LOG = logging.getLogger("p1.api")
DEFAULT_PORT = 8766
TOKEN_FILE_ENV = "P1_TENANT_TOKENS_FILE"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="p1 api",
        description="Stage 1 FastAPI service and React workbench. Without a tenant "
                    "token file there is no authentication: keep it on loopback.")
    parser.add_argument("--store", default=".stage1-store", metavar="DIR")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--allow-local-root", action="append", default=[], metavar="DIR")
    parser.add_argument("--allow-ssh", action="store_true")
    parser.add_argument("--allow-host", action="append", default=[], metavar="HOST")
    parser.add_argument("--tenant-tokens-file", default=os.environ.get(TOKEN_FILE_ENV),
                        metavar="FILE",
                        help="bind every request to a tenant via bearer tokens "
                             f"(default: ${TOKEN_FILE_ENV})")
    parser.add_argument("--ssl-certfile", metavar="FILE", help="serve HTTPS directly")
    parser.add_argument("--ssl-keyfile", metavar="FILE")
    parser.add_argument("--behind-tls-proxy", action="store_true",
                        help="TLS is terminated by a trusted proxy; accept https:// origins")
    parser.add_argument("--allow-remote-bind", action="store_true",
                        help="permit a non-loopback --host without tenant tokens (UNSAFE)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from p1.tenant_auth import TokenTable

    tokens = None
    if args.tenant_tokens_file:
        try:
            tokens = TokenTable.load(args.tenant_tokens_file)
        except IngestionError as exc:
            LOG.error("%s", exc)
            return 2
    if not is_loopback_host(args.host) and tokens is None and not args.allow_remote_bind:
        LOG.error("refusing to bind %s without tenant tokens (--tenant-tokens-file)", args.host)
        return 2
    tls = bool(args.ssl_certfile and args.ssl_keyfile)
    if tokens is not None and not is_loopback_host(args.host) and not (
            tls or args.behind_tls_proxy):
        LOG.error("refusing to send bearer tokens over cleartext HTTP on %s: pass "
                  "--ssl-certfile/--ssl-keyfile or --behind-tls-proxy", args.host)
        return 2
    roots = [Path(r) for r in args.allow_local_root]
    if any(not r.is_dir() for r in roots):
        LOG.error("--allow-local-root must name existing directories")
        return 2
    import uvicorn

    from p1.fastapi_app import create_api

    try:
        app = create_api(Path(args.store), args.host, args.port, roots, args.allow_ssh,
                         extra_hosts=args.allow_host, tokens=tokens,
                         behind_tls_proxy=args.behind_tls_proxy or tls)
    except IngestionError as exc:
        LOG.error("%s", exc)
        return 2
    LOG.info("Stage 1 API on http://%s:%s/ (store: %s, auth: %s)", args.host, args.port,
             app.state.p1.store, "tenant tokens" if tokens else "none")
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning",
                server_header=False, date_header=False, timeout_keep_alive=5,
                ssl_certfile=args.ssl_certfile if tls else None,
                ssl_keyfile=args.ssl_keyfile if tls else None,
                limit_concurrency=64, h11_max_incomplete_event_size=16384)
    return 0


def issue_main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="p1 tenant-token")
    parser.add_argument("--tokens-file", required=True, metavar="FILE")
    parser.add_argument("--tenant", required=True)
    args = parser.parse_args(list(argv) if argv is not None else None)
    from p1.tenant_auth import issue_token

    try:
        token = issue_token(args.tokens_file, args.tenant)
    except IngestionError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(f"tenant {args.tenant}: token (shown once, store it safely):\n{token}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
