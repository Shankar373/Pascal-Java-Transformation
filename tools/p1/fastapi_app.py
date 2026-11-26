"""FastAPI front end for Stage 1 (serves the React workbench and the JSON API).

A thin adapter over the same tested core as the stdlib server: ``JobManager``
runs discoveries, ``server_security`` validates requests, ``tenancy`` isolates
storage.  The API contract is identical to :mod:`p1.server`.

Every request passes :class:`GuardMiddleware` first:

* exactly one allowed ``Host`` (DNS rebinding);
* a POST may not carry a foreign ``Origin`` and must send ``X-P1-Request: 1``;
* only GET/HEAD/POST/OPTIONS; paths must be absolute and not ``//``;
* tenant resolution: with a token file the tenant comes from the bearer token
  (401 otherwise); without one it comes from ``X-P1-Tenant`` (default tenant);
* security headers on every response.

No filesystem path is built from user input except from a validated id and an
allow-listed artefact name; static files are served from a table built at
start-up.  Bodies are bounded; uploads stream to a temp file under a byte cap
and a wall-clock deadline.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import ClientDisconnect
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from p1.errors import IngestionError
from p1.jobs import BLUEPRINT_NAME, JobManager, JobRequest
from p1.limits import DEFAULT_LIMITS
from p1.server_security import (
    ARTIFACT_NAMES,
    ID_PATTERN,
    SECURITY_HEADERS,
    RequestRejected,
    allowed_hosts,
    host_is_allowed,
    looks_like_zip,
    origin_is_allowed,
    resolve_local_directory,
    safe_upload_name,
    scrub_message,
    validate_git_request,
)
from p1.server_uploads import (
    MAX_CONCURRENT_UPLOADS,
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
from p1.tenant_auth import TokenTable

__all__ = ["create_api", "ApiState"]

LOG = logging.getLogger("p1.api")

MAX_JSON_BODY = 16 * 1024
JSON_READ_DEADLINE = 10.0
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024
CHUNK_TIMEOUT = 30.0
_DIGITS = re.compile(r"^[0-9]{1,15}$")
_ZIP_TYPES = ("application/zip", "application/x-zip-compressed", "application/octet-stream")
_ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST", "OPTIONS"})
_GENERIC = {
    400: "bad request", 401: "authentication required", 404: "not found",
    405: "method not allowed", 408: "request timed out", 411: "length required",
    413: "payload too large", 422: "bad request", 429: "too many requests",
}
_WEB_DIR = Path(__file__).resolve().parent / "web"
_DIST_DIR = Path(__file__).resolve().parents[2] / "frontend" / "dist"
_STATIC_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".ico": "image/x-icon",
    ".png": "image/png", ".json": "application/json", ".map": "application/json",
    ".woff2": "font/woff2",
}


def _error_body(status: int, code: str, message: str) -> bytes:
    return json.dumps({"error": {"code": code, "message": message}},
                      sort_keys=True).encode("utf-8")


class ApiState:
    """Everything the routes share: store, limits, per-tenant job managers."""

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
        extra_hosts: Iterable[str] = (),
        tokens: TokenTable | None = None,
        static_dir: Path | None = None,
        behind_tls_proxy: bool = False,
    ) -> None:
        self.store = Path(store).resolve()
        self.roots = tuple(Path(r).resolve() for r in allow_local_roots)
        for root in self.roots:
            if root == self.store or root in self.store.parents or self.store in root.parents:
                raise IngestionError(
                    "a local root may not contain or lie inside the store",
                    code="ROOT_OVERLAPS_STORE")
        self.behind_tls_proxy = behind_tls_proxy
        self.allow_ssh = allow_ssh
        self.max_upload_bytes = max_upload_bytes or DEFAULT_LIMITS.max_total_bytes
        self.allowed = allowed_hosts(host, port, extra_hosts)
        self.tokens = tokens
        self.gate = UploadGate(MAX_CONCURRENT_UPLOADS)
        self._tenant_gates: dict[str, UploadGate] = {}
        self._discover_fn = discover_fn
        self._max_queue = max_queue
        self._managers: dict[str, JobManager] = {}
        self._lock = threading.Lock()
        self.store.mkdir(parents=True, exist_ok=True)
        self.static = _static_table(static_dir)
        existing = list_tenants(self.store)
        if len(existing) >= MAX_TENANTS:
            raise IngestionError(
                f"the store holds {len(existing)} tenants; the limit is {MAX_TENANTS}",
                code="TOO_MANY_TENANTS")
        for tenant in (DEFAULT_TENANT, *existing):
            self.jobs_for(tenant)
            sweep_uploads(self.uploads_for(tenant))

    def jobs_for(self, tenant: str) -> JobManager:
        tenant = validate_tenant(tenant)
        with self._lock:
            manager = self._managers.get(tenant)
            if manager is None:
                if len(self._managers) >= MAX_TENANTS:
                    raise RequestRejected(429, "TOO_MANY_TENANTS", "tenant limit reached")
                manager = JobManager(
                    self.store, discover_fn=self._discover_fn, max_queue=self._max_queue,
                    allowed_roots=self.roots, tenant=tenant)
                self._managers[tenant] = manager
            return manager

    def tenant_gate(self, tenant: str) -> UploadGate:
        """One in-flight upload per tenant, so one tenant cannot hold every slot."""

        with self._lock:
            gate = self._tenant_gates.get(tenant)
            if gate is None:
                gate = self._tenant_gates[tenant] = UploadGate(1)
            return gate

    def uploads_for(self, tenant: str) -> Path:
        path = tenant_root(self.store, validate_tenant(tenant)) / "uploads"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def config(self) -> dict[str, Any]:
        return {"local_directory_enabled": bool(self.roots), "ssh_enabled": self.allow_ssh,
                "max_upload_bytes": self.max_upload_bytes, "stage": 1, "tenancy": True,
                "auth_required": self.tokens is not None, "ui": self.static["kind"]}

    def shutdown(self) -> None:
        with self._lock:
            managers = list(self._managers.values())
        for manager in managers:
            manager.shutdown()


def _static_table(static_dir: Path | None) -> dict[str, Any]:
    """URL path -> (file, content type), from the React build or the legacy UI."""

    root = static_dir if static_dir is not None else _DIST_DIR
    kind = "react"
    if not (root / "index.html").is_file():
        root, kind = _WEB_DIR, "legacy"
    files: dict[str, tuple[Path, str]] = {}
    if root.is_dir():
        for path in sorted(root.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            ctype = _STATIC_TYPES.get(path.suffix.lower())
            if ctype is None:
                continue
            files["/" + path.relative_to(root).as_posix()] = (path, ctype)
    if "/index.html" in files:
        files["/"] = files["/index.html"]
    return {"kind": kind, "files": files}


class GuardMiddleware:
    """Pure-ASGI request gate: host, origin, CSRF header, method, tenant, headers."""

    def __init__(self, app: ASGIApp, state: ApiState) -> None:
        self.app = app
        self.state = state

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {k.lower() for k, _ in headers}
                for name, value in SECURITY_HEADERS:
                    if name.lower().encode() not in present:
                        headers.append((name.lower().encode(), value.encode()))
                if scope["path"].startswith("/api/") and b"cache-control" not in present:
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        try:
            self._check(scope)
        except RequestRejected as exc:
            body = _error_body(exc.status, exc.code, exc.message)
            await send_with_headers({
                "type": "http.response.start", "status": exc.status,
                "headers": [(b"content-type", b"application/json; charset=utf-8"),
                            (b"content-length", str(len(body)).encode()),
                            (b"connection", b"close")]})
            await send_with_headers({"type": "http.response.body", "body": body})
            return
        await self.app(scope, receive, send_with_headers)

    def _check(self, scope: Scope) -> None:
        values: dict[bytes, str] = {}
        hosts = 0
        for key, value in scope["headers"]:
            lowered = bytes(key).lower()
            if lowered == b"host":
                hosts += 1
            values.setdefault(lowered, bytes(value).decode("latin-1"))
        if hosts > 1:
            raise RequestRejected(400, "BAD_HOST", "exactly one Host header is required")
        if not host_is_allowed(values.get(b"host"), self.state.allowed):
            raise RequestRejected(403, "HOST_NOT_ALLOWED", "request host is not allowed")
        method = scope["method"]
        if method not in _ALLOWED_METHODS:
            raise RequestRejected(405, "METHOD_NOT_ALLOWED", "method not allowed for this path")
        path = scope["path"]
        if not path.startswith("/") or path.startswith("//"):
            raise RequestRejected(400, "BAD_PATH", "malformed request path")
        if method == "POST":
            if not self._origin_ok(values.get(b"origin")):
                raise RequestRejected(403, "ORIGIN_NOT_ALLOWED", "cross-origin requests are refused")
            if values.get(b"x-p1-request") != "1":
                raise RequestRejected(403, "CSRF_HEADER_REQUIRED", "missing X-P1-Request header")
        scope.setdefault("state", {})["tenant"] = self._tenant(values, path)

    def _origin_ok(self, origin: str | None) -> bool:
        if origin_is_allowed(origin, self.state.allowed):
            return True
        if not self.state.behind_tls_proxy or origin is None:
            return False
        value = origin.strip().lower()
        return any(value == f"https://{host}" for host in self.state.allowed)

    def _tenant(self, values: dict[bytes, str], path: str) -> str:
        if self.state.tokens is None:
            raw = values.get(b"x-p1-tenant")
            if raw is None:
                return DEFAULT_TENANT
            try:
                return validate_tenant(raw.strip())
            except IngestionError:
                raise RequestRejected(400, "INVALID_TENANT", "invalid tenant") from None
        if not path.startswith("/api/") or path == "/api/config":
            return DEFAULT_TENANT
        auth = values.get(b"authorization", "")
        scheme, _, token = auth.partition(" ")
        tenant = self.state.tokens.resolve(token.strip()) if scheme.lower() == "bearer" else None
        if tenant is None:
            raise RequestRejected(401, "UNAUTHENTICATED", "a valid bearer token is required")
        return tenant


def _tenant(request: Request) -> str:
    return str(request.scope["state"]["tenant"])


async def _read_json(request: Request) -> dict[str, Any]:
    """Bounded JSON object body; never reads past ``MAX_JSON_BODY``."""

    if "chunked" in (request.headers.get("transfer-encoding") or "").lower():
        raise RequestRejected(411, "LENGTH_REQUIRED", "Content-Length is required")
    ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if ctype != "application/json":
        raise RequestRejected(400, "BAD_CONTENT_TYPE", "expected application/json")
    length = _content_length(request)
    if length > MAX_JSON_BODY:
        raise RequestRejected(413, "BODY_TOO_LARGE", "request body is too large")
    body = bytearray()

    async def collect() -> None:
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_JSON_BODY:
                raise RequestRejected(413, "BODY_TOO_LARGE", "request body is too large")

    try:
        await asyncio.wait_for(collect(), JSON_READ_DEADLINE)
    except asyncio.TimeoutError:
        raise RequestRejected(408, "REQUEST_TIMEOUT", "the request took too long") from None
    try:
        data = json.loads(bytes(body).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise RequestRejected(400, "BAD_JSON", "request body is not valid JSON") from None
    if not isinstance(data, dict):
        raise RequestRejected(400, "BAD_JSON", "request body must be a JSON object")
    return data


def _content_length(request: Request) -> int:
    raw = request.headers.get("content-length")
    if raw is None:
        raise RequestRejected(411, "LENGTH_REQUIRED", "Content-Length is required")
    if not _DIGITS.match(raw):
        raise RequestRejected(400, "BAD_LENGTH", "invalid Content-Length")
    return int(raw)


async def _stream_upload(request: Request, uploads: Path, length: int) -> Path:
    """Write the body to ``uploads/<random>.zip``; remove it on any failure."""

    final = uploads / f"{secrets.token_hex(8)}.zip"
    partial = final.with_suffix(".zip.part")
    deadline = time.monotonic() + upload_deadline(
        length, UPLOAD_BASE_DEADLINE, UPLOAD_MIN_BYTES_PER_SECOND)
    received = 0
    head = b""
    stream = request.stream().__aiter__()
    try:
        with partial.open("wb") as handle:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise RequestRejected(408, "UPLOAD_TIMEOUT", "the upload took too long")
                try:
                    chunk = await asyncio.wait_for(
                        stream.__anext__(), min(CHUNK_TIMEOUT, remaining))
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    raise RequestRejected(
                        408, "UPLOAD_TIMEOUT", "the upload took too long") from None
                if not chunk:
                    continue
                if len(head) < 4:
                    head += chunk[: 4 - len(head)]
                if len(head) >= 4 and not looks_like_zip(head):
                    raise RequestRejected(400, "NOT_A_ZIP", "the upload is not a ZIP archive")
                received += len(chunk)
                if received > length:
                    raise RequestRejected(400, "BAD_LENGTH", "body exceeds Content-Length")
                handle.write(chunk)
        if received != length:
            raise RequestRejected(400, "INCOMPLETE_UPLOAD", "the upload ended early")
        if not looks_like_zip(head):
            raise RequestRejected(400, "NOT_A_ZIP", "the upload is not a ZIP archive")
        partial.replace(final)
    except BaseException:
        partial.unlink(missing_ok=True)
        final.unlink(missing_ok=True)
        raise
    return final


def create_api(
    store: Path,
    host: str = "127.0.0.1",
    port: int = 8766,
    allow_local_roots: Sequence[Path] = (),
    allow_ssh: bool = False,
    discover_fn: Callable[..., Any] | None = None,
    **options: Any,
) -> FastAPI:
    """Build the ASGI application; ``app.state.p1`` is the :class:`ApiState`."""

    state = ApiState(Path(store), host, port, allow_local_roots, allow_ssh, discover_fn, **options)
    app = FastAPI(title="Pascal-to-Java Stage 1", docs_url=None, redoc_url=None,
                  openapi_url=None)
    app.state.p1 = state
    app.add_middleware(GuardMiddleware, state=state)
    app.router.on_shutdown.append(state.shutdown)
    _register_errors(app)
    _register_routes(app, state)
    return app


def _register_errors(app: FastAPI) -> None:
    def respond(status: int, code: str, message: str) -> JSONResponse:
        headers = {name: value for name, value in SECURITY_HEADERS}
        headers["Cache-Control"] = "no-store"
        return JSONResponse({"error": {"code": code, "message": message}},
                            status_code=status, headers=headers)

    @app.exception_handler(RequestRejected)
    async def _rejected(_: Request, exc: RequestRejected) -> JSONResponse:
        return respond(exc.status, exc.code, exc.message)

    @app.exception_handler(IngestionError)
    async def _ingestion(_: Request, exc: IngestionError) -> JSONResponse:
        status = 429 if exc.code == "QUEUE_FULL" else 400
        return respond(status, exc.code, scrub_message(exc.message))

    @app.exception_handler(ClientDisconnect)
    async def _disconnected(_: Request, __: ClientDisconnect) -> JSONResponse:
        # the client is gone and cannot read this; not a server fault, so no error log
        return respond(400, "CLIENT_DISCONNECT", "the client disconnected")

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        return respond(exc.status_code, f"HTTP_{exc.status_code}",
                       _GENERIC.get(exc.status_code, "request failed"))

    @app.exception_handler(RequestValidationError)
    async def _invalid(_: Request, __: RequestValidationError) -> JSONResponse:
        return respond(400, "BAD_REQUEST", "bad request")

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception) -> JSONResponse:
        LOG.error("unhandled error serving a request: %s", type(exc).__name__)
        return respond(500, "INTERNAL_ERROR", "internal server error")


def _register_routes(app: FastAPI, state: ApiState) -> None:
    read = ["GET", "HEAD"]

    @app.api_route("/api/config", methods=read)
    def config() -> dict[str, Any]:
        return state.config()

    @app.api_route("/api/discoveries", methods=read)
    def list_discoveries(request: Request) -> dict[str, Any]:
        return {"items": state.jobs_for(_tenant(request)).list()}

    @app.post("/api/discoveries", status_code=202)
    async def create(request: Request) -> dict[str, Any]:
        manager = state.jobs_for(_tenant(request))
        data = await _read_json(request)
        job = await run_in_threadpool(_job_request, state, data)
        job_id = await run_in_threadpool(manager.submit, job)
        return {"id": job_id, "status": "queued", "tenant": manager.tenant}

    @app.post("/api/discoveries/upload", status_code=202)
    async def upload(request: Request) -> dict[str, Any]:
        tenant = _tenant(request)
        name = safe_upload_name(request.query_params.get("name"))
        ctype = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
        if ctype not in _ZIP_TYPES:
            raise RequestRejected(400, "BAD_CONTENT_TYPE", "expected application/zip")
        if "chunked" in (request.headers.get("transfer-encoding") or "").lower():
            raise RequestRejected(411, "LENGTH_REQUIRED", "Content-Length is required")
        length = _content_length(request)
        if length > state.max_upload_bytes:
            raise RequestRejected(413, "UPLOAD_TOO_LARGE", "the upload exceeds the size limit")
        if length == 0:
            raise RequestRejected(400, "EMPTY_UPLOAD", "the upload is empty")
        if not state.gate.try_acquire():
            raise RequestRejected(429, "BUSY", "too many uploads in progress; try again shortly")
        gate = state.tenant_gate(tenant)
        if not gate.try_acquire():
            state.gate.release()
            raise RequestRejected(429, "BUSY", "an upload is already in progress for this tenant")
        try:
            return await _accept_upload(request, state, tenant, name, length)
        finally:
            gate.release()
            state.gate.release()

    @app.api_route("/api/discoveries/{job_id}", methods=read)
    def item(job_id: str, request: Request) -> dict[str, Any]:
        view = state.jobs_for(_tenant(request)).get(_valid_id(job_id))
        if view is None:
            raise RequestRejected(404, "NOT_FOUND", "discovery not found")
        return view

    @app.api_route("/api/discoveries/{job_id}/blueprint", methods=read)
    def blueprint(job_id: str, request: Request) -> Response:
        return _artifact(state, _tenant(request), job_id, BLUEPRINT_NAME)

    @app.api_route("/api/discoveries/{job_id}/report", methods=read)
    def report(job_id: str, request: Request) -> Response:
        return _artifact(state, _tenant(request), job_id, "discovery-report.md")

    @app.api_route("/api/discoveries/{job_id}/artifacts/{name}", methods=read)
    def artifact(job_id: str, name: str, request: Request) -> Response:
        if name not in ARTIFACT_NAMES:
            raise RequestRejected(404, "NOT_FOUND", "artifact not found")
        return _artifact(state, _tenant(request), job_id, name)

    @app.api_route("/{path:path}", methods=read + ["POST"], include_in_schema=False)
    def static(path: str, request: Request) -> Response:
        url = "/" + path
        if request.method == "POST" or url.startswith("/api/"):
            raise RequestRejected(404 if url.startswith("/api/") else 405,
                                  "NOT_FOUND" if url.startswith("/api/") else "METHOD_NOT_ALLOWED",
                                  "not found")
        if url == "/favicon.ico" and url not in state.static["files"]:
            return Response(status_code=204, media_type="image/x-icon")
        entry = state.static["files"].get(url)
        if entry is None:
            raise RequestRejected(404, "NOT_FOUND", "not found")
        try:
            body = entry[0].read_bytes()
        except OSError:
            raise RequestRejected(404, "NOT_FOUND", "not found") from None
        return Response(body, media_type=entry[1], headers={"Cache-Control": "no-cache"})


def _valid_id(job_id: str) -> str:
    if not ID_PATTERN.match(job_id):
        raise RequestRejected(400, "INVALID_ID", "invalid discovery id")
    return job_id


def _job_request(state: ApiState, data: dict[str, Any]) -> JobRequest:
    kind = data.get("kind")
    if kind == "git":
        url, ref = validate_git_request(data.get("url"), data.get("ref"), state.allow_ssh)
        return JobRequest(kind="git", source=url, ref=ref, allow_ssh=state.allow_ssh)
    if kind == "directory":
        path = resolve_local_directory(data.get("path"), state.roots)
        return JobRequest(kind="directory", source=str(path), label=path.name)
    raise RequestRejected(400, "INVALID_KIND", "kind must be 'git' or 'directory'")


async def _accept_upload(request: Request, state: ApiState, tenant: str, name: str,
                         length: int) -> dict[str, Any]:
    jobs = state.jobs_for(tenant)
    jobs.reserve_slot()  # QUEUE_FULL costs no disk and no body read
    try:
        target = await _stream_upload(request, state.uploads_for(tenant), length)
    except BaseException:
        jobs.release_slot()
        raise
    try:
        job_id = jobs.submit(JobRequest(kind="zip", source=str(target), label=name),
                             cleanup=target, reserved=True)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return {"id": job_id, "status": "queued", "tenant": tenant}


def _artifact(state: ApiState, tenant: str, job_id: str, name: str) -> Response:
    manager = state.jobs_for(tenant)
    job_id = _valid_id(job_id)
    if manager.status(job_id) is None:
        raise RequestRejected(404, "NOT_FOUND", "discovery not found")
    directory = manager.blueprint_path(job_id)
    if directory is None:
        raise RequestRejected(409, "NOT_COMPLETED", "the discovery has not completed")
    ctype, attachment = ARTIFACT_NAMES[name]
    try:
        target = directory / name
        if target.stat().st_size > MAX_ARTIFACT_BYTES:
            raise RequestRejected(413, "ARTIFACT_TOO_LARGE", "artifact is too large to serve")
        body = target.read_bytes()
    except OSError:
        raise RequestRejected(404, "NOT_FOUND", "artifact not found") from None
    headers = {}
    if attachment:
        stem, _, suffix = name.rpartition(".")
        headers["Content-Disposition"] = f'attachment; filename="{stem}-{job_id}.{suffix}"'
    return Response(body, media_type=ctype, headers=headers)
