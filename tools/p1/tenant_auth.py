"""Per-tenant bearer tokens for the FastAPI front end.

Stage 1 has no identity provider (OIDC/RBAC is Stage 6).  To make tenant
isolation enforceable rather than a trusted header, an operator may issue
opaque bearer tokens, each bound to exactly one tenant.  Only the SHA-256 of a
token is stored (``<tenant>:<sha256 hex>`` per line); the token itself is
shown once at creation.  When a token file is configured, a request's tenant
is *derived from its token* and the ``X-P1-Tenant`` header is ignored.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from pathlib import Path

from .errors import IngestionError
from .tenancy import validate_tenant

__all__ = ["TokenTable", "generate_token", "hash_token", "issue_token"]

_LINE = re.compile(r"^([a-z0-9][a-z0-9_-]{0,62}):([0-9a-f]{64})$")


def generate_token() -> str:
    """A fresh 256-bit URL-safe token."""

    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenTable:
    """Immutable tenant/token-hash table with constant-time lookup."""

    def __init__(self, entries: tuple[tuple[str, str], ...]) -> None:
        self._entries = entries

    @classmethod
    def load(cls, path: Path | str) -> "TokenTable":
        """Read a token file; a malformed line fails closed."""

        try:
            lines = Path(path).read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise IngestionError("the tenant token file cannot be read",
                                 code="TOKEN_FILE_INVALID") from exc
        entries = []
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            match = _LINE.match(line)
            if not match:
                raise IngestionError("the tenant token file has a malformed line",
                                     code="TOKEN_FILE_INVALID")
            entries.append((validate_tenant(match.group(1)), match.group(2)))
        if not entries:
            raise IngestionError("the tenant token file has no entries",
                                 code="TOKEN_FILE_INVALID")
        return cls(tuple(entries))

    def resolve(self, token: str) -> str | None:
        """The tenant owning *token*, or None.  Compares every entry."""

        digest = hash_token(token)
        found: str | None = None
        for tenant, stored in self._entries:
            if hmac.compare_digest(stored, digest):
                found = tenant
        return found


def issue_token(path: Path | str, tenant: str) -> str:
    """Create a token for *tenant*, append its hash to *path*, return the token."""

    tenant = validate_tenant(tenant)
    token = generate_token()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    fd = os.open(target, flags, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        if target.stat().st_size and not target.read_text(encoding="utf-8").endswith("\n"):
            handle.write("\n")
        handle.write(f"{tenant}:{hash_token(token)}\n")
    return token
