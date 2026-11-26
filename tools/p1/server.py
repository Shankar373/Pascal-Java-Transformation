"""Local dashboard server (design section 8): stdlib ``http.server`` only.

Serves the static dashboard from ``p1/web`` and a small JSON API backed by
:class:`p1.jobs.JobManager`.  Security posture, enforced on every request:

* ``Host`` must be one of the server's own addresses (DNS rebinding);
* a POST may not carry a foreign ``Origin`` and must send ``X-P1-Request: 1``;
* ids match ``^[0-9a-f]{16}$`` and artefact names come from an allow-list, so
  no filesystem path is ever built from user input;
* bodies are bounded; uploads stream to a temp file under a hard byte cap and
  the temp file is removed on every failure path;
* local directories are only accepted inside an operator-supplied root;
* errors use ``{"error": {"code", "message"}}`` with sanitised messages.

There is no authentication until Stage 6: bind to loopback only.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import secrets
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import parse_qs

from p1.errors import IngestionError
from p1.jobs import BLUEPRINT_NAME, JobManager, JobRequest
from p1.limits import DEFAULT_LIMITS
from p1.server_uploads import (
    MAX_CONCURRENT_UPLOADS,
    MAX_CONNECTIONS,
    UPLOAD_BASE_DEADLINE,
    UPLOAD_MIN_BYTES_PER_SECOND,
    UploadGate,
    sweep_uploads,
    upload_deadline,
)
from p1.tenancy import (
    DEFAULT_TENANT,
    MAX_TENANTS,
    list_tenants,
    tenant_root,
    validate_tenant,
)
from p1.server_security import (
    ARTIFACT_NAMES,
    ID_PATTERN,
    SECURITY_HEADERS,
    RequestRejected,
    allowed_hosts,
    host_is_allowed,
    is_loopback_host,
    looks_like_zip,
    origin_is_allowed,
    resolve_local_directory,
    safe_upload_name,
    scrub_message,
    validate_git_request,
)

__all__ = ["create_app", "App", "main", "DEFAULT_HOST", "DEFAULT_PORT"]

LOG = logging.getLogger("p1.server")

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
MAX_JSON_BODY = 16 * 1024
DRAIN_LIMIT = 1024 * 1024
DRAIN_TIMEOUT = 0.5
DRAIN_DEADLINE = 1.0  # total time spent discarding an unread body after an error reply
CHUNK = 64 * 1024
REQUEST_TIMEOUT = 30
_WEB_DIR = Path(__file__).resolve().parent / "web"

_STATIC: dict[str, tuple[str, str]] = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
}
_ZIP_TYPES = ("application/zip", "application/x-zip-compressed", "application/octet-stream")
_STATUS_FOR_CODE = {"QUEUE_FULL": 429}
_GENERIC = {
    400: "bad request", 404: "not found", 405: "method not allowed", 408: "request timed out",
    411: "length required", 413: "payload too large", 414: "uri too long",
    429: "too many requests", 431: "headers too large", 501: "not supported",
    503: "server busy",
}
_ALLOWED = {"GET", "HEAD", "OPTIONS", "POST"}
_DIGITS = re.compile(r"^[0-9]{1,15}$")


_BUSY_REPLY = (b"HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n"
               b"Connection: close\r\nRetry-After: 1\r\n\r\n")


class _Server(ThreadingHTTPServer):
    """Threaded server that serves at most ``max_connections`` connections at once."""

    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def __init__(self, address: tuple[str, int], handler: type, ipv6: bool,
                 max_connections: int = MAX_CONNECTIONS) -> None:
        if ipv6:
            self.address_family = socket.AF_INET6
        self._connection_slots = threading.BoundedSemaphore(max_connections)
        super().__init__(address, handler)

    def process_request(self, request: Any, client_address: Any) -> None:
        if not self._connection_slots.acquire(blocking=False):
            try:
                request.sendall(_BUSY_REPLY)
            except OSError:
                pass
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self._connection_slots.release()
            raise

    def process_request_thread(self, request: Any, client_address: Any) -> None:
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._connection_slots.release()


class App:
    """The server plus its job manager; the object tests and ``main`` drive."""

    def __init__(
        self,
        store: Path,
        host: str,
        port: int,
        allow_local_roots: Sequence[Path] = (),
        allow_ssh: bool = False,
        discover_fn: Callable[..., Any] | None = None,
        max_upload_bytes: int | None = None,
        max_queue: int = 8,
        extra_hosts: Sequence[str] = (),
        max_connections: int = MAX_CONNECTIONS,
        max_concurrent_uploads: int = MAX_CONCURRENT_UPLOADS,
    ) -> None:
        self.store = Path(store).resolve()
        self.uploads = self.store / "uploads"
        self.uploads.mkdir(parents=True, exist_ok=True)
        self.roots = tuple(Path(r).resolve() for r in allow_local_roots)
        self.allow_ssh = allow_ssh
        self.max_upload_bytes = max_upload_bytes or DEFAULT_LIMITS.max_total_bytes
        self.upload_gate = UploadGate(max_concurrent_uploads)
        self.jobs = JobManager(self.store, discover_fn=discover_fn, max_queue=max_queue,
                               allowed_roots=self.roots)
        self._discover_fn = discover_fn
        self._max_queue = max_queue
        self._managers: dict[str, JobManager] = {DEFAULT_TENANT: self.jobs}
        self._managers_lock = threading.Lock()
        for tenant in list_tenants(self.store):
            self._manager_for(tenant)
        self.sweep_all_uploads()
        handler = type("P1Handler", (_Handler,), {"app": self})
        self._httpd = _Server((host, port), handler, ipv6=":" in host,
                              max_connections=max_connections)
        self.allowed = allowed_hosts(host, self._httpd.server_address[1], extra_hosts)
        self._serving = threading.Event()

    @property
    def server_address(self) -> tuple[str, int]:
        return self._httpd.server_address[:2]  # type: ignore[return-value]

    # -------------------------------------------------------- tenancy

    def _manager_for(self, tenant: str) -> JobManager:
        """The job manager of *tenant*, created on first use."""

        with self._managers_lock:
            manager = self._managers.get(tenant)
            if manager is None:
                if len(self._managers) >= MAX_TENANTS:
                    raise RequestRejected(429, "TOO_MANY_TENANTS", "tenant limit reached")
                manager = JobManager(
                    self.store, discover_fn=self._discover_fn,
                    max_queue=self._max_queue, allowed_roots=self.roots,
                    tenant=tenant)
                self._managers[tenant] = manager
            return manager

    def jobs_for(self, tenant: str) -> JobManager:
        """Job manager scoped to *tenant* (validated before any path use)."""

        return self._manager_for(validate_tenant(tenant))

    def uploads_for(self, tenant: str) -> Path:
        """Upload directory of *tenant*, created on first use."""

        path = tenant_root(self.store, validate_tenant(tenant)) / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def sweep_all_uploads(self) -> None:
        """Discard abandoned uploads in every tenant directory."""

        sweep_uploads(self.uploads)
        for tenant in list_tenants(self.store):
            sweep_uploads(tenant_root(self.store, tenant) / "uploads")

    def config(self) -> dict[str, Any]:
        return {"local_directory_enabled": bool(self.roots), "ssh_enabled": self.allow_ssh,
                "max_upload_bytes": self.max_upload_bytes, "stage": 1,
                "tenancy": True}

    def serve_forever(self) -> None:
        self._serving.set()
        self._httpd.serve_forever(poll_interval=0.05)

    def shutdown(self) -> None:
        if self._serving.is_set():
            self._httpd.shutdown()
        self._httpd.server_close()
        with self._managers_lock:
            managers = list(self._managers.values())
        for manager in managers:
            manager.shutdown()


def create_app(
    store: Path,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    allow_local_roots: Sequence[Path] = (),
    allow_ssh: bool = False,
    discover_fn: Callable[..., Any] | None = None,
    **options: Any,
) -> App:
    """Build a bound (not yet serving) application; ``port=0`` picks a free one."""

    return App(Path(store), host, port, allow_local_roots, allow_ssh, discover_fn, **options)


class _Handler(BaseHTTPRequestHandler):
    app: App
    server_version = "p1"
    sys_version = ""
    timeout = REQUEST_TIMEOUT
    protocol_version = "HTTP/1.0"
    _unread: int | None = None
    _rfile_dead = False
    _tenant_id: str | None = None

    # ------------------------------------------------------------ plumbing

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        LOG.debug("%s %s", self.address_string(), format % args)

    def end_headers(self) -> None:
        for name, value in SECURITY_HEADERS:
            self.send_header(name, value)
        super().end_headers()

    def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        headers = {"Cache-Control": "no-store", **(extra or {})}  # one value per name
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, status: int, payload: Any, extra: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        self._send(status, body, "application/json; charset=utf-8", extra)

    def _error(self, status: int, code: str, message: str) -> None:
        extra = {"Allow": "GET, HEAD, OPTIONS, POST"} if status == 405 else None
        self._json(status, {"error": {"code": code, "message": message}}, extra)

    def send_error(self, code: int, message: str | None = None, explain: str | None = None) -> None:
        self.close_connection = True
        self._error(code, f"HTTP_{code}", _GENERIC.get(code, "request failed"))

    def _read(self, size: int, partial: bool = False) -> bytes:
        """Read body bytes, tracking how much of the declared body is unread.

        ``partial`` returns whatever one socket read yields, so a deadline check
        can run between reads even when the client trickles bytes.
        """

        if self._rfile_dead:  # a timed-out buffered reader refuses every later read
            data = self.connection.recv(size)
        else:
            data = self.rfile.read1(size) if partial else self.rfile.read(size)
        if self._unread is not None:
            self._unread = max(0, self._unread - len(data))
        return data

    def _drain(self) -> None:
        """Discard a bounded part of an unread body so the client sees our reply."""

        if self._unread is None:
            raw = self.headers.get("Content-Length", "")
            if not _DIGITS.match(raw):
                return
            self._unread = int(raw)
        remaining = min(self._unread, DRAIN_LIMIT)
        deadline = time.monotonic() + DRAIN_DEADLINE
        try:
            while remaining > 0 and time.monotonic() < deadline:
                self.connection.settimeout(DRAIN_TIMEOUT)
                data = self._read(min(CHUNK, remaining), partial=True)
                if not data:
                    return
                remaining -= len(data)
        except OSError:
            return

    # ------------------------------------------------------------ dispatch

    def _tenant(self) -> str:
        """Validated tenant of this request (``X-P1-Tenant``, else default).

        The identifier is validated before it is used to select a job
        manager or an upload directory, so a hostile header can never reach
        the filesystem.  An invalid tenant fails the request closed.
        """

        if self._tenant_id is None:
            raw = self.headers.get("X-P1-Tenant")
            self._tenant_id = (DEFAULT_TENANT if raw is None
                               else validate_tenant(raw.strip()))
        return self._tenant_id

    def _dispatch(self) -> None:
        post = self.command == "POST"
        self._unread = None
        try:
            self._guard(post)
            raw = self.path.split("?", 1)
            path, query = raw[0], (raw[1] if len(raw) > 1 else "")
            if not path.startswith("/") or path.startswith("//"):
                raise RequestRejected(400, "BAD_PATH", "malformed request path")
            if self.command == "OPTIONS":
                self._send(204, b"", "text/plain", {"Allow": "GET, HEAD, OPTIONS, POST"})
                return
            self._route(path, query)
        except RequestRejected as exc:
            self._error(exc.status, exc.code, exc.message)
            if post:
                self._drain()
        except IngestionError as exc:
            self._error(_STATUS_FOR_CODE.get(exc.code, 400), exc.code, scrub_message(exc.message))
            if post:
                self._drain()
        except (socket.timeout, ConnectionError):
            self.close_connection = True
        except Exception:
            LOG.exception("unhandled error serving a request")
            self._error(500, "INTERNAL_ERROR", "internal server error")

    def _check_host(self) -> None:
        hosts = self.headers.get_all("Host") or []
        if len(hosts) > 1:
            raise RequestRejected(400, "BAD_HOST", "exactly one Host header is required")
        if not host_is_allowed(hosts[0] if hosts else None, self.app.allowed):
            raise RequestRejected(403, "HOST_NOT_ALLOWED", "request host is not allowed")

    def _guard(self, post: bool) -> None:
        self._check_host()
        if not post:
            return
        if not origin_is_allowed(self.headers.get("Origin"), self.app.allowed):
            raise RequestRejected(403, "ORIGIN_NOT_ALLOWED", "cross-origin requests are refused")
        if self.headers.get("X-P1-Request") != "1":
            raise RequestRejected(403, "CSRF_HEADER_REQUIRED", "missing X-P1-Request header")

    def _route(self, path: str, query: str) -> None:
        method = self.command
        read = method in ("GET", "HEAD")
        if path in _STATIC:
            return self._static(path) if read else self._method_not_allowed()
        if path == "/favicon.ico":
            return self._send(204, b"", "image/x-icon")
        if path == "/api/config":
            return self._json(200, self.app.config()) if read else self._method_not_allowed()
        parts = path.split("/")
        if parts[:3] != ["", "api", "discoveries"]:
            raise RequestRejected(404, "NOT_FOUND", "not found")
        rest = parts[3:]
        if not rest or rest == [""]:
            return self._collection(method)
        if rest == ["upload"]:
            return self._upload(query) if method == "POST" else self._method_not_allowed()
        if not read:
            return self._method_not_allowed()
        self._item(rest)

    def _method_not_allowed(self) -> None:
        raise RequestRejected(405, "METHOD_NOT_ALLOWED", "method not allowed for this path")

    def do_GET(self) -> None: self._dispatch()  # noqa: E704
    def do_HEAD(self) -> None: self._dispatch()  # noqa: E704
    def do_POST(self) -> None: self._dispatch()  # noqa: E704
    def do_OPTIONS(self) -> None: self._dispatch()  # noqa: E704
    def do_PUT(self) -> None: self._dispatch_unsupported()  # noqa: E704
    def do_DELETE(self) -> None: self._dispatch_unsupported()  # noqa: E704
    def do_PATCH(self) -> None: self._dispatch_unsupported()  # noqa: E704

    def _dispatch_unsupported(self) -> None:
        self.close_connection = True
        try:
            self._check_host()
        except RequestRejected as exc:
            return self._error(exc.status, exc.code, exc.message)
        self._error(405, "METHOD_NOT_ALLOWED", "method not allowed for this path")

    # ------------------------------------------------------------- handlers

    def _static(self, path: str) -> None:
        name, ctype = _STATIC[path]
        try:
            body = (_WEB_DIR / name).read_bytes()
        except OSError:
            raise RequestRejected(404, "NOT_FOUND", "not found") from None
        self._send(200, body, ctype, {"Cache-Control": "no-cache"})

    def _collection(self, method: str) -> None:
        manager = self.app.jobs_for(self._tenant())
        if method in ("GET", "HEAD"):
            return self._json(200, {"items": manager.list()})
        if method == "POST":
            return self._create(manager)
        self._method_not_allowed()

    def _read_json_body(self) -> dict[str, Any]:
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            raise RequestRejected(411, "LENGTH_REQUIRED", "Content-Length is required")
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            raise RequestRejected(400, "BAD_CONTENT_TYPE", "expected application/json")
        length = self._content_length()
        if length > MAX_JSON_BODY:
            raise RequestRejected(413, "BODY_TOO_LARGE", "request body is too large")
        try:
            data = json.loads(self._read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise RequestRejected(400, "BAD_JSON", "request body is not valid JSON") from None
        if not isinstance(data, dict):
            raise RequestRejected(400, "BAD_JSON", "request body must be a JSON object")
        return data

    def _content_length(self) -> int:
        raw = self.headers.get("Content-Length")
        if raw is None:
            raise RequestRejected(411, "LENGTH_REQUIRED", "Content-Length is required")
        if not _DIGITS.match(raw):
            raise RequestRejected(400, "BAD_LENGTH", "invalid Content-Length")
        self._unread = int(raw)
        return self._unread

    def _create(self, manager: JobManager) -> None:
        data = self._read_json_body()
        kind = data.get("kind")
        if kind == "git":
            url, ref = validate_git_request(data.get("url"), data.get("ref"), self.app.allow_ssh)
            request = JobRequest(kind="git", source=url, ref=ref, allow_ssh=self.app.allow_ssh)
        elif kind == "directory":
            path = resolve_local_directory(data.get("path"), self.app.roots)
            request = JobRequest(kind="directory", source=str(path), label=path.name)
        else:
            raise RequestRejected(400, "INVALID_KIND", "kind must be 'git' or 'directory'")
        job_id = manager.submit(request)
        self._json(202, {"id": job_id, "status": "queued", "tenant": manager.tenant})

    def _upload(self, query: str) -> None:
        tenant = self._tenant()
        names = parse_qs(query, max_num_fields=8).get("name") or [None]
        name = safe_upload_name(names[0])
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype not in _ZIP_TYPES:
            raise RequestRejected(400, "BAD_CONTENT_TYPE", "expected application/zip")
        if "chunked" in (self.headers.get("Transfer-Encoding") or "").lower():
            raise RequestRejected(411, "LENGTH_REQUIRED", "Content-Length is required")
        length = self._content_length()
        if length > self.app.max_upload_bytes:
            raise RequestRejected(413, "UPLOAD_TOO_LARGE", "the upload exceeds the size limit")
        if length == 0:
            raise RequestRejected(400, "EMPTY_UPLOAD", "the upload is empty")
        if not self.app.upload_gate.try_acquire():
            raise RequestRejected(429, "BUSY", "too many uploads in progress; try again shortly")
        try:
            self._accept_upload(tenant, name, length)
        finally:
            self.app.upload_gate.release()

    def _accept_upload(self, tenant: str, name: str, length: int) -> None:
        """Reserve queue capacity, then stream the body; both undone on any failure."""

        jobs = self.app.jobs_for(tenant)
        jobs.reserve_slot()  # QUEUE_FULL here costs no disk and no body read
        try:
            target = self._stream_to_file(self.app.uploads_for(tenant), length)
        except BaseException:
            jobs.release_slot()
            raise
        try:
            job_id = jobs.submit(
                JobRequest(kind="zip", source=str(target), label=name), cleanup=target, reserved=True)
        except BaseException:
            target.unlink(missing_ok=True)
            raise
        self._json(202, {"id": job_id, "status": "queued", "tenant": tenant})

    def _read_within(self, size: int, deadline: float) -> bytes:
        """One body read that cannot outlive the upload's wall-clock *deadline*."""

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            self._abandon_body()
            raise RequestRejected(408, "UPLOAD_TIMEOUT", "the upload took too long")
        self.connection.settimeout(min(REQUEST_TIMEOUT, remaining))
        try:
            return self._read(size, partial=True)
        except socket.timeout:
            self._rfile_dead = True
            self._abandon_body()
            raise RequestRejected(408, "UPLOAD_TIMEOUT", "the upload took too long") from None

    def _abandon_body(self) -> None:
        """A too-slow client is cut off: the connection closes after a short drain."""

        self.close_connection = True

    def _stream_to_file(self, uploads: Path, length: int) -> Path:
        """Write the body to ``uploads/<random>.zip``; remove it on any failure."""

        final = uploads / f"{secrets.token_hex(8)}.zip"
        partial = final.with_suffix(".zip.part")
        deadline = time.monotonic() + upload_deadline(
            length, UPLOAD_BASE_DEADLINE, UPLOAD_MIN_BYTES_PER_SECOND)
        received = 0
        try:
            with partial.open("wb") as handle:
                while received < length:
                    chunk = self._read_within(min(CHUNK, length - received), deadline)
                    if not chunk:
                        raise RequestRejected(400, "INCOMPLETE_UPLOAD", "the upload ended early")
                    if received == 0 and not looks_like_zip(chunk):
                        raise RequestRejected(400, "NOT_A_ZIP", "the upload is not a ZIP archive")
                    received += len(chunk)
                    handle.write(chunk)
            partial.replace(final)
        except BaseException:
            partial.unlink(missing_ok=True)
            final.unlink(missing_ok=True)
            raise
        return final

    def _item(self, rest: list[str]) -> None:
        manager = self.app.jobs_for(self._tenant())
        job_id = rest[0]
        if not ID_PATTERN.match(job_id):
            raise RequestRejected(400, "INVALID_ID", "invalid discovery id")
        if len(rest) == 1:
            view = manager.get(job_id)
            if view is None:
                raise RequestRejected(404, "NOT_FOUND", "discovery not found")
            return self._json(200, view)
        if rest[1] in ("blueprint", "report") and len(rest) == 2:
            name = BLUEPRINT_NAME if rest[1] == "blueprint" else "discovery-report.md"
            return self._artifact(manager, job_id, name)
        if rest[1] == "artifacts" and len(rest) == 3:
            if rest[2] not in ARTIFACT_NAMES:
                raise RequestRejected(404, "NOT_FOUND", "artifact not found")
            return self._artifact(manager, job_id, rest[2])
        raise RequestRejected(404, "NOT_FOUND", "not found")

    def _artifact(self, manager: JobManager, job_id: str, name: str) -> None:
        if manager.status(job_id) is None:
            raise RequestRejected(404, "NOT_FOUND", "discovery not found")
        directory = manager.blueprint_path(job_id)
        if directory is None:
            raise RequestRejected(409, "NOT_COMPLETED", "the discovery has not completed")
        ctype, attachment = ARTIFACT_NAMES[name]
        try:
            body = (directory / name).read_bytes()
        except OSError:
            raise RequestRejected(404, "NOT_FOUND", "artifact not found") from None
        extra = {}
        if attachment:
            stem, _, suffix = name.rpartition(".")
            extra["Content-Disposition"] = f'attachment; filename="{stem}-{job_id}.{suffix}"'
        self._send(200, body, ctype, extra)


# ------------------------------------------------------------------- CLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="p1 serve",
        description="Local Stage 1 dashboard. No authentication exists until Stage 6: "
                    "keep it on loopback.")
    parser.add_argument("--store", default=".stage1-store", metavar="DIR")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--allow-local-root", action="append", default=[], metavar="DIR",
                        help="enable local-directory ingestion inside DIR (repeatable)")
    parser.add_argument("--allow-ssh", action="store_true", help="accept ssh Git sources")
    parser.add_argument("--allow-remote-bind", action="store_true",
                        help="permit a non-loopback --host (UNAUTHENTICATED; use with care)")
    parser.add_argument("--allow-host", action="append", default=[], metavar="HOST",
                        help="extra Host header name to accept (repeatable)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for ``p1 serve``; returns a process exit code."""

    args = build_parser().parse_args(list(argv) if argv is not None else None)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    if not is_loopback_host(args.host) and not args.allow_remote_bind:
        LOG.error("refusing to bind %s: no authentication exists until Stage 6 "
                  "(pass --allow-remote-bind to override)", args.host)
        return 2
    if not 0 <= args.port <= 65535:
        LOG.error("invalid port")
        return 2
    roots = [Path(r) for r in args.allow_local_root]
    missing = [r for r in roots if not r.is_dir()]
    if missing:
        LOG.error("--allow-local-root must name existing directories")
        return 2
    app = create_app(Path(args.store), args.host, args.port, roots, args.allow_ssh,
                     extra_hosts=args.allow_host)
    host, port = app.server_address
    LOG.info("Stage 1 dashboard on http://%s:%s/ (store: %s)", host, port, app.store)
    try:
        app.serve_forever()
    except KeyboardInterrupt:
        LOG.info("stopping")
    finally:
        app.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover  (run as: python -m p1.server)
    sys.exit(main())
