"""Tenant identity and storage layout for Stage 1.

Stage 1 is single-process and has no authentication until Stage 6, so a
tenant here is a *storage and API isolation boundary*, not an authenticated
principal: the operator (or the hosting deployment) supplies the tenant,
and everything a tenant can see — jobs, uploads, checkpoints, discoveries
and artefacts — lives under that tenant's root.

Layout (design section 9)::

    <store>/                      the default tenant (backwards compatible)
    <store>/tenants/<tenant>/     every other tenant
        jobs/  uploads/  checkpoints/  discoveries/

Tenant identifiers are validated before they are ever joined to a path: only
``[a-z0-9][a-z0-9_-]{0,62}`` is accepted, so a tenant can never contain a
path separator, ``..``, a drive letter or a name that escapes the store.
"""

from __future__ import annotations

import re
from pathlib import Path

from .errors import IngestionError

__all__ = [
    "DEFAULT_TENANT",
    "TENANT_PATTERN",
    "MAX_TENANT_LENGTH",
    "RESERVED_TENANTS",
    "MAX_TENANTS",
    "validate_tenant",
    "tenant_root",
    "list_tenants",
]

#: The implicit tenant used when no tenant is supplied.
DEFAULT_TENANT = "default"
MAX_TENANT_LENGTH = 63
TENANT_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")

_TENANTS_DIR = "tenants"
#: Most tenants one service process will host; bounds threads and directories.
MAX_TENANTS = 64
#: Names of the store's own directories; a tenant may not shadow them.
RESERVED_TENANTS = frozenset(
    {"tenants", "jobs", "uploads", "checkpoints", "discoveries"})


def validate_tenant(raw: object) -> str:
    """Return *raw* as a validated tenant id or raise ``INVALID_TENANT``.

    Validation is a fail-closed allow-list: anything that is not a short,
    lower-case, separator-free slug is refused before it reaches a path.
    """

    if (not isinstance(raw, str) or not TENANT_PATTERN.fullmatch(raw)
            or raw in RESERVED_TENANTS):
        raise IngestionError(
            "tenant must match [a-z0-9][a-z0-9_-]{0,62} and not be a "
            "reserved store name",
            code="INVALID_TENANT",
            path=None,
        )
    return raw


def tenant_root(store: Path | str, tenant: str = DEFAULT_TENANT) -> Path:
    """The storage root of *tenant* inside *store* (validated, never raw)."""

    tenant = validate_tenant(tenant)
    base = Path(store)
    if tenant == DEFAULT_TENANT:
        return base
    return base / _TENANTS_DIR / tenant


def list_tenants(store: Path | str) -> list[str]:
    """Sorted tenant ids that already have a directory in *store*."""

    root = Path(store) / _TENANTS_DIR
    if not root.is_dir():
        return []
    found = [
        entry.name for entry in root.iterdir()
        if entry.is_dir() and not entry.is_symlink()
        and TENANT_PATTERN.fullmatch(entry.name)
    ]
    return sorted(found)
