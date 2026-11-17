"""End-to-end blueprint tests over the real P1 pipeline.

The discovery objects here come from :func:`p1.pipeline.run` (directory, ZIP
and local Git inputs), so they carry exactly what the orchestrator will hand
to the blueprint.  The Stage 1 finding lists are empty (the detectors are
produced elsewhere); the blueprint must still be complete, valid and
deterministic.
"""

from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

import blueprint_helpers as H
from conftest import (
    AMBIGUOUS_APP,
    CONSOLE_APP,
    GUI_APP,
    REPO_ROOT,
    make_zip,
    run_pipeline,
    write_tree,
)
from enterprise_app import ENTERPRISE_APP
from p1.blueprint import build_blueprint, write_blueprint_outputs
from p1.schemacheck import validate

SCHEMA = json.loads((REPO_ROOT / "docs" / "stage1" / "schemas" /
                     "application-blueprint.schema.json").read_text("utf-8"))
GIT = shutil.which("git")


def _dump(document: Any) -> str:
    return json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True)


def _staging(result: Any) -> tuple[str, ...]:
    return (str(result.discovery.ingestion.staging_root),)


# ---------------------------------------------------------------------------
# directory input
# ---------------------------------------------------------------------------


def test_blueprint_over_a_pipeline_run_is_valid_and_writes_outputs(
        tmp_path: Path) -> None:
    root = H.enterprise_tree(tmp_path / "ent")
    result = run_pipeline(root, tmp_path / "p1-out", origin_label="ent")
    out = tmp_path / "bp-out"
    paths = write_blueprint_outputs(result.discovery, out,
                                    staging_roots=_staging(result))

    blueprint = json.loads(Path(paths["blueprint"]).read_text("utf-8"))
    assert validate(blueprint, SCHEMA) == []
    # beside - not instead of - the three P1 outputs
    p1_out = {p.name for p in (tmp_path / "p1-out").iterdir()}
    assert p1_out == {"application-manifest.json", "dependency-graph.json",
                      "discovery-report.md"}
    assert blueprint["summary"]["total_files"] == len(ENTERPRISE_APP)
    assert blueprint["project"]["name"] == "ent"
    manifest = json.loads(
        (tmp_path / "p1-out" / "application-manifest.json").read_text("utf-8"))
    assert len(manifest["files"]) == blueprint["inventory"]["file_count"]
    assert blueprint["dialect"]["primary"] == "delphi"
    assert blueprint["dialect"]["version"]["value"] == "ProjectVersion 19.2"


def test_blueprint_is_consistent_with_the_p1_manifest(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "app", CONSOLE_APP)
    result = run_pipeline(root, tmp_path / "out")
    manifest = json.loads(
        (tmp_path / "out" / "application-manifest.json").read_text("utf-8"))
    blueprint = build_blueprint(result.discovery)
    assert blueprint["file_distribution"]["by_class"] == manifest[
        "classification"]
    assert len(blueprint["projects"]) == len(manifest["project_roots"])
    assert blueprint["graphs"]["unit"]["unresolved"] == manifest[
        "dependency_summary"]["unresolved"]
    assert blueprint["diagnostics"] == [
        {**d, "severity": d.get("severity", "warning")}
        for d in manifest["diagnostics"]]
    flat = {(u["id"]) for u in blueprint["unresolved"]}
    assert "native-library:foo.dll" in flat
    assert validate(blueprint, SCHEMA) == []


def test_every_unresolved_graph_edge_survives_into_the_blueprint(
        tmp_path: Path) -> None:
    root = write_tree(tmp_path / "app", CONSOLE_APP)
    result = run_pipeline(root, tmp_path / "out")
    document = build_blueprint(result.discovery)
    located = {
        (r["file"], r["line"], r["column"])
        for item in document["unresolved"] for r in item["referenced_by"]}
    for edge in result.discovery.graph.unresolved():
        assert (edge.file, edge.line, edge.column) in located


@pytest.mark.parametrize("tree", [CONSOLE_APP, AMBIGUOUS_APP, GUI_APP,
                                  ENTERPRISE_APP])
def test_blueprint_is_deterministic_across_pipeline_runs(
        tree: dict, tmp_path: Path) -> None:
    root = write_tree(tmp_path / "t", tree)
    first = run_pipeline(root, tmp_path / "o1", origin_label="x")
    second = run_pipeline(root, tmp_path / "o2", origin_label="x")
    one, two = tmp_path / "b1", tmp_path / "b2"
    write_blueprint_outputs(first.discovery, one,
                            staging_roots=_staging(first))
    write_blueprint_outputs(second.discovery, two,
                            staging_roots=_staging(second))
    for path in sorted(one.iterdir()):
        assert path.read_bytes() == (two / path.name).read_bytes(), path.name
    assert validate(json.loads(
        (one / "application-blueprint.json").read_text("utf-8")), SCHEMA) == []


def test_no_staging_or_absolute_paths_leak(tmp_path: Path) -> None:
    root = H.enterprise_tree(tmp_path / "ent")
    result = run_pipeline(root, tmp_path / "o")
    out = tmp_path / "bp"
    write_blueprint_outputs(result.discovery, out,
                            staging_roots=_staging(result))
    for path in out.iterdir():
        text = path.read_text("utf-8")
        assert H.SECRET not in text, path.name
        assert str(root) not in text and root.as_posix() not in text
        assert str(root).replace("\\", "\\\\") not in text


def test_secret_never_reaches_the_blueprint_even_with_detectors(
        tmp_path: Path) -> None:
    root = H.enterprise_tree(tmp_path / "ent")
    discovery = H.with_stage1_findings(H.discovery_from_tree(root), root)
    text = _dump(build_blueprint(discovery))
    assert H.SECRET not in text
    assert "Password=<redacted>" in text or "Password" not in text


def test_gui_lcl_tree_reports_a_gui_component_and_fpc(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "gui", GUI_APP)
    document = build_blueprint(run_pipeline(root, tmp_path / "o").discovery)
    comps = {c["id"]: c for c in document["components"]}
    assert comps["gui_application"]["present"]
    assert document["projects"][0]["shape"] == "gui_lcl"
    assert document["dialect"]["primary"] == "fpc"
    assert "GUI_SHAPE_DETECTED" in {b["code"] for b in document["blockers"]}
    assert validate(document, SCHEMA) == []


def test_ambiguous_tree_blueprint_has_no_primary_project(
        tmp_path: Path) -> None:
    root = write_tree(tmp_path / "amb", AMBIGUOUS_APP)
    document = build_blueprint(run_pipeline(root, tmp_path / "o").discovery)
    assert [p["primary"] for p in document["projects"]] == [False, False]
    assert document["stage"]["status"] == "COMPLETED_WITH_BLOCKERS"
    assert any(d["code"] == "MULTIPLE_PROJECT_ROOTS"
               for d in document["diagnostics"])


# ---------------------------------------------------------------------------
# ZIP and Git inputs give the same blueprint modulo provenance
# ---------------------------------------------------------------------------


def _entries(tree: dict[str, str | bytes]) -> list[tuple[str, bytes]]:
    return [(name, data if isinstance(data, bytes) else data.encode("utf-8"))
            for name, data in sorted(tree.items())]


#: Diagnostics that describe *how* the bytes arrived, not what they contain.
_PROVENANCE_CODES = {"ZIP_INGESTED", "GIT_INGESTED",
                     "PATH_EXCLUDED_FROM_INVENTORY", "VCS_METADATA_REMOVED"}


def _comparable(document: dict[str, Any]) -> dict[str, Any]:
    """The blueprint modulo source provenance (kind, ref, ingestion notes)."""

    copied = copy.deepcopy(document)
    copied["project"]["ingestion_source"] = {}
    kept = [d for d in copied["diagnostics"]
            if d["code"] not in _PROVENANCE_CODES]
    copied["diagnostics"] = kept
    copied["summary"]["diagnostics"] = {
        level: sum(1 for d in kept if d["severity"] == level)
        for level in ("error", "warning", "info")}
    return copied


def test_zip_and_directory_inputs_give_the_same_blueprint(
        tmp_path: Path) -> None:
    root = H.enterprise_tree(tmp_path / "dir")
    archive = make_zip(tmp_path / "ent.zip", _entries(ENTERPRISE_APP))
    from_dir = run_pipeline(root, tmp_path / "o1", origin_label="ent")
    from_zip = run_pipeline(archive, tmp_path / "o2", kind="zip",
                            origin_label="ent")
    blueprint_dir = build_blueprint(from_dir.discovery)
    blueprint_zip = build_blueprint(from_zip.discovery)
    assert blueprint_zip["project"]["ingestion_source"]["kind"] == "zip"
    assert _dump(_comparable(blueprint_dir)) == _dump(
        _comparable(blueprint_zip))
    assert validate(blueprint_zip, SCHEMA) == []


@pytest.mark.skipif(GIT is None, reason="git executable required")
def test_git_input_gives_the_same_blueprint_as_the_directory(
        tmp_path: Path) -> None:
    root = H.enterprise_tree(tmp_path / "repo")
    for args in (("init", "-q"), ("add", "-A"),
                 ("-c", "user.email=p1@example.invalid", "-c", "user.name=P1",
                  "-c", "commit.gpgsign=false", "commit", "-q", "-m", "x")):
        subprocess.run([str(GIT), *args], cwd=str(root), check=True,
                       capture_output=True, timeout=120)
    from_git = run_pipeline(root, tmp_path / "o1", kind="git",
                            origin_label="ent")
    from_dir = run_pipeline(root, tmp_path / "o2", kind="directory",
                            origin_label="ent")
    blueprint_git = build_blueprint(from_git.discovery)
    source = blueprint_git["project"]["ingestion_source"]
    assert source["kind"] == "git" and len(source["commit"]) == 40
    assert _dump(_comparable(blueprint_git)) == _dump(
        _comparable(build_blueprint(from_dir.discovery)))
    assert blueprint_git["summary"]["total_files"] == len(ENTERPRISE_APP)
    assert validate(blueprint_git, SCHEMA) == []
