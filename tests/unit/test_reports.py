"""The three derived Stage 1 reports: projection, refusal and determinism."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from p1.errors import IngestionError
from p1.reports import (
    ARCHITECTURE_REPORT_SCHEMA,
    CHECKPOINT_MANIFEST_SCHEMA,
    PROJECT_INVENTORY_SCHEMA,
    build_architecture_report,
    build_checkpoint_manifest,
    build_project_inventory,
    write_derived_reports,
)

BLUEPRINT = json.loads(
    (Path(__file__).resolve().parents[2]
     / "tests/fixtures/stage1/sample_blueprint.json").read_text("utf-8"))

CHECKPOINT = {
    "schema_version": "stage1.checkpoint/1.0",
    "checkpoint_id": "CP-dd38b7112162",
    "source": {"kind": "directory", "origin": "legacy-pascal-erp", "ref": "",
               "commit": "", "tree_id": "", "commit_timestamp": ""},
    "source_digest": "12163e6e6c512e9deaa842ea968550ec5da24a3162a684892c7d265624cfc7d6",
    "file_count": 2,
    "directory_count": 1,
    "total_bytes": 10,
    "directories": ["src"],
    "files": [{"path": "src/b.pas", "sha256": "b" * 64, "size": 4},
              {"path": "a.dpr", "sha256": "a" * 64, "size": 6}],
    "read_only": True,
    "seal_kind": "sha256",
    "seal": "c" * 64,
}


# --------------------------------------------------------------- checkpoint


def test_checkpoint_manifest_is_a_versioned_projection() -> None:
    manifest = build_checkpoint_manifest(CHECKPOINT)
    assert manifest["schema_version"] == CHECKPOINT_MANIFEST_SCHEMA
    assert manifest["checkpoint_id"] == "CP-dd38b7112162"
    assert manifest["source"] == CHECKPOINT["source"]
    assert manifest["read_only"] is True
    assert manifest["integrity"]["content_algorithm"] == "sha256"
    assert manifest["integrity"]["seal_kind"] == "sha256"
    assert manifest["integrity"]["sealed"] is True
    assert manifest["seal"] == "c" * 64


def test_checkpoint_manifest_lists_every_file_sorted() -> None:
    manifest = build_checkpoint_manifest(CHECKPOINT)
    files = manifest["integrity"]["files"]
    assert [f["path"] for f in files] == ["a.dpr", "src/b.pas"]
    assert files[0]["sha256"] == "a" * 64
    assert files[1]["size"] == 4


def test_checkpoint_manifest_refuses_incomplete_metadata() -> None:
    broken = dict(CHECKPOINT)
    del broken["source_digest"]
    with pytest.raises(IngestionError) as exc:
        build_checkpoint_manifest(broken)
    assert exc.value.code == "CHECKPOINT_INVALID"


def test_checkpoint_manifest_refuses_malformed_file_list() -> None:
    broken = dict(CHECKPOINT, files="not-a-list")
    with pytest.raises(IngestionError) as exc:
        build_checkpoint_manifest(broken)
    assert exc.value.code == "CHECKPOINT_INVALID"


def test_checkpoint_manifest_is_deterministic() -> None:
    assert (json.dumps(build_checkpoint_manifest(CHECKPOINT), sort_keys=True)
            == json.dumps(build_checkpoint_manifest(dict(CHECKPOINT)),
                          sort_keys=True))


# --------------------------------------------------------- project inventory


def test_project_inventory_carries_projects_and_entry_points() -> None:
    inventory = build_project_inventory(BLUEPRINT)
    assert inventory["schema_version"] == PROJECT_INVENTORY_SCHEMA
    assert inventory["project"]["name"] == "legacy-pascal-erp"
    assert inventory["dialect"]["label"] == "Delphi / Object Pascal"
    assert len(inventory["projects"]) == len(BLUEPRINT["projects"])
    assert inventory["entry_points"][0]["entry_point"]["file"].endswith(".dpr")
    assert inventory["counts"]["total_files"] == (
        BLUEPRINT["summary"]["total_files"])


def test_project_inventory_has_no_wall_clock_or_paths() -> None:
    text = json.dumps(build_project_inventory(BLUEPRINT))
    assert "generated_at" not in text
    assert "<staging>" not in text


# ------------------------------------------------------ architecture report


def test_architecture_report_covers_the_required_domains() -> None:
    report = build_architecture_report(BLUEPRINT)
    assert report["schema_version"] == ARCHITECTURE_REPORT_SCHEMA
    assert report["stage"]["id"] == 1
    assert report["dialect_and_compiler"] == BLUEPRINT["dialect"]
    assert report["application"]["projects"]
    assert report["build_requirements"]["scripts"] == (
        BLUEPRINT["dependencies"]["build"]["scripts"])
    assert report["runtime_requirements"]["count"] == len(
        BLUEPRINT["dependencies"]["runtime"])
    assert report["databases"] == BLUEPRINT["dependencies"]["databases"]
    assert report["integrations"] == BLUEPRINT["dependencies"]["integrations"]
    assert report["libraries"] == BLUEPRINT["dependencies"]["libraries"]
    assert report["file_classes"] == (
        BLUEPRINT["file_distribution"]["by_class"])
    assert report["modernization_blockers"] == BLUEPRINT["blockers"]
    assert report["missing_source_and_unresolved"]["count"] == len(
        BLUEPRINT["unresolved"])
    assert report["capability_states"] == BLUEPRINT["capability_states"]
    assert report["limitations"] == BLUEPRINT["limitations"]


def test_architecture_report_indexes_diagnostics_and_unresolved() -> None:
    report = build_architecture_report(BLUEPRINT)
    diagnostics = report["security_diagnostics"]
    assert diagnostics["by_severity"] == {"warning": 2}
    assert diagnostics["items"] == BLUEPRINT["diagnostics"]
    unresolved = report["missing_source_and_unresolved"]
    assert unresolved["by_severity"].get("error", 0) >= 1
    assert unresolved["by_kind"].get("include", 0) >= 1


def test_architecture_report_is_deterministic() -> None:
    first = json.dumps(build_architecture_report(BLUEPRINT), sort_keys=True)
    second = json.dumps(build_architecture_report(json.loads(
        json.dumps(BLUEPRINT))), sort_keys=True)
    assert first == second


# ------------------------------------------------------------------- writing


def test_write_derived_reports_writes_three_files(tmp_path: Path) -> None:
    paths = write_derived_reports(BLUEPRINT, CHECKPOINT, tmp_path)
    assert set(paths) == {"checkpoint_manifest", "project_inventory",
                          "architecture_report"}
    for path in paths.values():
        assert Path(path).is_file()
    manifest = json.loads((tmp_path / "checkpoint-manifest.json")
                          .read_text("utf-8"))
    assert manifest["checkpoint_id"] == "CP-dd38b7112162"


def test_written_reports_are_byte_identical_on_rerun(tmp_path: Path) -> None:
    first = write_derived_reports(BLUEPRINT, CHECKPOINT, tmp_path / "a")
    second = write_derived_reports(BLUEPRINT, CHECKPOINT, tmp_path / "b")
    for key in first:
        assert (Path(first[key]).read_bytes()
                == Path(second[key]).read_bytes()), key


def test_written_reports_scrub_staging_roots(tmp_path: Path) -> None:
    staged = str(tmp_path / "p1-stage-x")
    paths = write_derived_reports(BLUEPRINT, CHECKPOINT, tmp_path,
                                  staging_roots=(staged,))
    for path in paths.values():
        assert staged not in Path(path).read_text("utf-8")


def test_write_derived_reports_refuses_a_broken_checkpoint(
        tmp_path: Path) -> None:
    with pytest.raises(IngestionError) as exc:
        write_derived_reports(BLUEPRINT, {"checkpoint_id": "CP-x"}, tmp_path)
    assert exc.value.code == "CHECKPOINT_INVALID"
    assert not (tmp_path / "checkpoint-manifest.json").exists()
