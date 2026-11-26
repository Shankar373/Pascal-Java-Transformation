"""End-to-end: the derived reports are published with every discovery."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fixtures.stage1.enterprise_app import EXPECTED, write_enterprise_app

from p1.reports import (
    ARCHITECTURE_REPORT_SCHEMA,
    CHECKPOINT_MANIFEST_SCHEMA,
    PROJECT_INVENTORY_SCHEMA,
)
from p1.stage1 import DiscoveryRequest, discover


@pytest.fixture()
def app(tmp_path: Path) -> Path:
    return write_enterprise_app(tmp_path / "app")


def _discover(tmp_path: Path, app: Path, store: str = "store"):
    return discover(DiscoveryRequest("directory", str(app),
                                     label="legacy-erp"),
                    tmp_path / store)


def test_derived_reports_are_published(tmp_path: Path, app: Path) -> None:
    result = _discover(tmp_path, app)
    outdir = Path(result.outdir)

    manifest = json.loads((outdir / "checkpoint-manifest.json").read_text("utf-8"))
    assert manifest["schema_version"] == CHECKPOINT_MANIFEST_SCHEMA
    assert manifest["checkpoint_id"] == result.blueprint["project"]["checkpoint"]["id"]
    # every inventoried file is listed with its hash
    assert manifest["file_count"] == result.blueprint["summary"]["total_files"]
    listed = {f["path"] for f in manifest["integrity"]["files"]}
    assert len(listed) == manifest["file_count"]
    assert manifest["integrity"]["sealed"] is True

    inventory = json.loads((outdir / "project-inventory.json").read_text("utf-8"))
    assert inventory["schema_version"] == PROJECT_INVENTORY_SCHEMA
    assert inventory["project"]["name"] == "legacy-erp"
    assert inventory["entry_points"]

    architecture = json.loads((outdir / "architecture-report.json").read_text("utf-8"))
    assert architecture["schema_version"] == ARCHITECTURE_REPORT_SCHEMA
    assert architecture["stage"]["id"] == 1
    assert architecture["dialect_and_compiler"]["label"] == (
        result.blueprint["dialect"]["label"])
    assert architecture["file_classes"]


def test_derived_reports_are_deterministic(tmp_path: Path, app: Path) -> None:
    first = _discover(tmp_path, app, "store-a")
    second = _discover(tmp_path, app, "store-b")
    for name in ("checkpoint-manifest.json", "project-inventory.json",
                 "architecture-report.json"):
        assert (Path(first.outdir, name).read_bytes()
                == Path(second.outdir, name).read_bytes()), name


def test_derived_reports_carry_no_secret_and_no_store_path(
        tmp_path: Path, app: Path) -> None:
    result = _discover(tmp_path, app)
    needles = {str(tmp_path), str(tmp_path).replace("\\", "/")}
    for name in ("checkpoint-manifest.json", "project-inventory.json",
                 "architecture-report.json"):
        text = Path(result.outdir, name).read_text("utf-8")
        assert EXPECTED["secret_in_source"] not in text, name
        for needle in needles:
            assert needle not in text, name


def test_derived_reports_are_downloadable(tmp_path: Path, app: Path) -> None:
    from p1.server_security import ARTIFACT_NAMES
    for name in ("checkpoint-manifest.json", "project-inventory.json",
                 "architecture-report.json"):
        assert name in ARTIFACT_NAMES


def test_scrub_needles_cover_json_escaped_windows_paths_and_ignore_trivial_roots():
    from p1.reports import _needles
    root = r"C:\Users\x\p1-staging-abc"
    forms = _needles(root)
    assert root.replace("\\", "\\\\") in forms
    assert "C:/Users/x/p1-staging-abc" in forms
    assert _needles("/", "", "/t") == []
