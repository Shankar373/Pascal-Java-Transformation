"""Tenant isolation: unit rules for tenant ids and the storage layout."""

from __future__ import annotations

from pathlib import Path

import pytest

from p1.errors import IngestionError
from p1.tenancy import (
    DEFAULT_TENANT,
    MAX_TENANT_LENGTH,
    TENANT_PATTERN,
    list_tenants,
    tenant_root,
    validate_tenant,
)


@pytest.mark.parametrize("tenant", [
    "default", "acme", "acme-corp", "t1", "a", "0", "a_b-c9",
])
def test_valid_tenants_are_accepted(tenant: str) -> None:
    assert validate_tenant(tenant) == tenant


@pytest.mark.parametrize("tenant", [
    "", ".", "..", "../evil", "a/b", "a\\b", "ACME", "acme corp", "ac me",
    "-lead", "_lead", "x" * (MAX_TENANT_LENGTH + 1), "c:", "c:/x",
    "tenants", "jobs\0", "ténant", None, 5, "a\nb", " ",
])
def test_invalid_tenants_are_refused(tenant) -> None:
    with pytest.raises(IngestionError) as exc:
        validate_tenant(tenant)
    assert exc.value.code == "INVALID_TENANT"


def test_pattern_never_matches_a_path_escape() -> None:
    for hostile in ("../x", "..", "/etc", "a/b", "a\\b", "C:\\x", "a\0b"):
        assert not TENANT_PATTERN.fullmatch(hostile)


def test_default_tenant_keeps_the_store_root(tmp_path: Path) -> None:
    assert tenant_root(tmp_path, DEFAULT_TENANT) == tmp_path


def test_other_tenants_are_nested_under_tenants(tmp_path: Path) -> None:
    root = tenant_root(tmp_path, "acme")
    assert root == tmp_path / "tenants" / "acme"
    # always inside the store, whatever the id
    assert root.is_relative_to(tmp_path)


def test_unknown_tenant_is_refused_before_any_path_is_built(
        tmp_path: Path) -> None:
    with pytest.raises(IngestionError):
        tenant_root(tmp_path, "../escape")


def test_list_tenants_only_returns_real_directories(tmp_path: Path) -> None:
    assert list_tenants(tmp_path) == []
    (tmp_path / "tenants" / "b").mkdir(parents=True)
    (tmp_path / "tenants" / "a").mkdir(parents=True)
    (tmp_path / "tenants" / "Bad Name").mkdir(parents=True)
    (tmp_path / "tenants" / "file").write_text("x", encoding="utf-8")
    assert list_tenants(tmp_path) == ["a", "b"]
