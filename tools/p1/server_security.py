"""Request-validation helpers for the local dashboard API (design section 8).

Everything here is a small pure function so the security rules can be tested
without a socket: Host/Origin allow-lists, id and name validation, local-root
containment, Git URL gatekeeping and message scrubbing.

The server never builds a filesystem path from user input except from an id
that matched :data:`ID_PATTERN` and a name from :data:`ARTIFACT_NAMES`.

Host / Origin policy (design section 8, enforced by :func:`allowed_hosts`):
the ``Host`` header (and the ``Origin`` of a POST, as ``http://<host>``) must
equal the bound ``host:port``.  Only when the server is bound to a loopback
address are ``localhost:<port>`` and ``[::1]:<port>`` accepted as well; no
other alias is implied (a server bound to ``127.0.0.1`` does not answer to
``127.0.0.2``, and one bound to ``::1`` does not answer to ``127.0.0.1``).
Operator-supplied ``--allow-host`` names are added verbatim as ``name:<port>``.
A request carrying more than one ``Host`` header is refused with 400.

Git requests are gated by ``p1.remotegit_policy`` itself (``parse_remote_url``
and ``validate_ref_name``) plus a non-network check of literal/loopback hosts,
so the API is never weaker than the worker; the DNS-based public-address check
stays in the worker.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Iterable

from p1.errors import IngestionError
from p1.remotegit_policy import (
    NetworkPolicy,
    check_host_public,
    parse_remote_url,
    validate_ref_name,
)

__all__ = [
    "ID_PATTERN",
    "CHECKPOINT_PATTERN",
    "ARTIFACT_NAMES",
    "SECURITY_HEADERS",
    "RequestRejected",
    "allowed_hosts",
    "host_is_allowed",
    "origin_is_allowed",
    "is_loopback_host",
    "safe_upload_name",
    "looks_like_zip",
    "redact_url",
    "resolve_local_directory",
    "validate_git_request",
    "scrub_message",
]

ID_PATTERN = re.compile(r"^[0-9a-f]{16}\Z")
CHECKPOINT_PATTERN = re.compile(r"^CP-[0-9a-f]{12}\Z")

#: artifact name -> (content type, served as attachment)
ARTIFACT_NAMES: dict[str, tuple[str, bool]] = {
    "application-blueprint.json": ("application/json", True),
    "application-manifest.json": ("application/json", True),
    "dependency-graph.json": ("application/json", True),
    "unresolved-dependencies.json": ("application/json", True),
    "diagnostics.json": ("application/json", True),
    "checkpoint-manifest.json": ("application/json", True),
    "project-inventory.json": ("application/json", True),
    "architecture-report.json": ("application/json", True),
    "inventory.csv": ("text/csv; charset=utf-8", True),
    "discovery-report.md": ("text/plain; charset=utf-8", False),
}

SECURITY_HEADERS: tuple[tuple[str, str], ...] = (
    ("Content-Security-Policy",
     "default-src 'self'; frame-ancestors 'none'; base-uri 'none'; "
     "form-action 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("X-Frame-Options", "DENY"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
)

_MAX_URL = 2048
_MAX_REF = 256
_MAX_NAME = 100
_MAX_PATH = 1024
_NAME_CHARS = re.compile(r"[^A-Za-z0-9._-]")
_CONTROL = re.compile(r"[\x00-\x20\x7f]")
_ZIP_MAGIC = (b"PK\x03\x04", b"PK\x05\x06")


class RequestRejected(Exception):
    """A request failed validation: carries an HTTP status and stable code."""

    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


def is_loopback_host(host: str) -> bool:
    """True for ``localhost`` and loopback IP literals."""

    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _host_forms(host: str, port: int) -> set[str]:
    bare = host.strip("[]")
    return {f"[{bare}]:{port}" if ":" in bare else f"{bare}:{port}"}


def allowed_hosts(host: str, port: int, extra: Iterable[str] = ()) -> frozenset[str]:
    """Exact ``Host`` header values the server answers to (see module docstring)."""

    forms = _host_forms(host, port)
    if is_loopback_host(host):
        forms |= _host_forms("localhost", port) | _host_forms("::1", port)
    for item in extra:
        forms |= _host_forms(item, port)
    return frozenset(f.lower() for f in forms)


def host_is_allowed(header: str | None, allowed: frozenset[str]) -> bool:
    """Reject missing Host headers and anything outside the allow-list."""

    return bool(header) and header.strip().lower() in allowed  # type: ignore[union-attr]


def origin_is_allowed(origin: str | None, allowed: frozenset[str]) -> bool:
    """A POST may omit Origin (non-browser) but never carry a foreign one."""

    if origin is None:
        return True
    value = origin.strip().lower()
    return any(value == f"http://{host}" for host in allowed)


def safe_upload_name(raw: str | None) -> str:
    """Return a safe display basename ending in ``.zip`` or raise."""

    if not raw or len(raw) > 4 * _MAX_NAME or _CONTROL.search(raw.replace(" ", "")):
        raise RequestRejected(400, "INVALID_NAME", "upload name is missing or invalid")
    base = raw.replace("\\", "/").rsplit("/", 1)[-1].strip()
    base = _NAME_CHARS.sub("_", base).lstrip(".")
    if not base.lower().endswith(".zip") or len(base) <= 4:
        raise RequestRejected(400, "INVALID_NAME", "upload name must end in .zip")
    if len(base) > _MAX_NAME:
        base = base[-_MAX_NAME:]
    return base


def looks_like_zip(head: bytes) -> bool:
    """Cheap magic-byte check; the real validation is ``zipingest``."""

    return head.startswith(_ZIP_MAGIC)


def resolve_local_directory(raw: object, roots: Iterable[Path]) -> Path:
    """Resolve *raw* and require it to live inside an allowed root."""

    root_list = list(roots)
    if not root_list:
        raise RequestRejected(
            403, "LOCAL_DIRECTORY_DISABLED",
            "local directory ingestion is disabled on this server")
    if not isinstance(raw, str) or not raw or len(raw) > _MAX_PATH or "\x00" in raw:
        raise RequestRejected(400, "INVALID_PATH", "path is missing or invalid")
    try:
        resolved = Path(raw).resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise RequestRejected(400, "INVALID_PATH", "path is not an existing directory") from None
    if not resolved.is_dir():
        raise RequestRejected(400, "INVALID_PATH", "path is not an existing directory")
    for root in root_list:
        if resolved == root or root in resolved.parents:
            return resolved
    raise RequestRejected(
        403, "PATH_NOT_ALLOWED", "path is not inside an allowed local root")


_LOCAL_NAME = re.compile(r"(^|\.)localhost\.?$", re.I)
_URL_REFUSAL = "repository URL is not acceptable"


def _refuse_url(exc: IngestionError, allow_ssh: bool) -> RequestRejected:
    if exc.code == "SSH_NOT_CONFIGURED" and not allow_ssh:
        return RequestRejected(403, "SSH_DISABLED", "SSH sources are disabled on this server")
    return RequestRejected(400, exc.code, _URL_REFUSAL)


def _check_host_literal(host: str) -> None:
    """Refuse loopback names and non-public IP literals; never touches the network."""

    refusal = RequestRejected(400, "HOST_NOT_PUBLIC", "repository host is not a public address")
    if _LOCAL_NAME.search(host):
        raise refusal
    bare = host.strip("[]")
    try:
        ipaddress.ip_address(bare)
    except ValueError:
        return  # a DNS name: the worker resolves and checks it
    try:
        check_host_public(host, NetworkPolicy())
    except IngestionError:
        raise refusal from None


def _check_remote_to_orchestrator(url: str) -> None:
    """The orchestrator must see this URL as remote, never as a local path."""

    from p1.stage1 import is_remote_git  # lazy: stage1 pulls in the whole pipeline

    if not is_remote_git(url):
        raise RequestRejected(400, "UNSUPPORTED_URL", _URL_REFUSAL)


def validate_git_request(url: object, ref: object, allow_ssh: bool) -> tuple[str, str | None]:
    """Gatekeep a remote Git request before it reaches ``discover``.

    Uses the same parser and ref rules as ``p1.remotegit`` so the API is never
    weaker than the worker, and confirms ``p1.stage1.is_remote_git`` agrees so a
    ``git`` request can never be treated as a local path.
    """

    if not isinstance(url, str) or not url or len(url) > _MAX_URL or _CONTROL.search(url):
        raise RequestRejected(400, "INVALID_URL", "repository URL is missing or invalid")
    try:
        spec = parse_remote_url(url, allow_ssh=allow_ssh)
    except IngestionError as exc:
        raise _refuse_url(exc, allow_ssh) from None
    _check_host_literal(spec.host)
    _check_remote_to_orchestrator(url)
    if ref is None or ref == "":
        return url, None
    try:
        return url, validate_ref_name(ref)  # type: ignore[arg-type]
    except IngestionError:
        raise RequestRejected(
            400, "INVALID_REF", "branch or ref contains unsupported characters") from None


def redact_url(url: str) -> str:
    """Display form of a URL with any userinfo removed."""

    return re.sub(r"^([a-zA-Z][a-zA-Z0-9+.-]*://)[^/@]*@", r"\1", url)


_WIN_PATH = re.compile(r"(?:[A-Za-z]:[\\/]|\\\\)[^\s'\"<>|]*")
_POSIX_PATH = re.compile(r"(?<![\w:/.])/(?:[\w.@+~-]+/)+[\w.@+~-]*")
_URL_USERINFO = re.compile(r"(://)[^/@\s]+@")
_TOKEN_KV = re.compile(r"(?i)\b(token|password|passwd|secret|authorization|bearer)\b\s*[:=]?\s*\S+")
_TOKEN_SHAPES = re.compile(
    r"\b(?:gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{16,}|glpat-[A-Za-z0-9_-]{12,}"
    r"|[A-Fa-f0-9]{32,}|[A-Za-z0-9+/_-]{40,}={0,2})\b")


def scrub_message(message: str, limit: int = 300) -> str:
    """Remove filesystem paths, URL credentials and token-like strings."""

    text = _URL_USERINFO.sub(r"\1", str(message))
    text = _TOKEN_KV.sub(lambda m: f"{m.group(1)} [redacted]", text)
    text = _TOKEN_SHAPES.sub("[redacted]", text)
    text = _WIN_PATH.sub("[path]", text)
    text = _POSIX_PATH.sub("[path]", text)
    text = " ".join(text.split())
    return text[:limit]
