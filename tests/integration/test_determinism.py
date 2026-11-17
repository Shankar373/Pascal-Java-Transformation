"""Determinism tests (task E2, IR invariant I6).

Same input, same tool version, different run directory ⇒ byte-identical
artefacts.  Anything else makes the discovery report unusable as evidence:
a reader cannot tell a real change from a reordering.
"""

from __future__ import annotations

import json
from pathlib import Path

from conftest import (
    artifact_bytes,
    make_zip,
    read_json,
    run_pipeline,
    write_tree,
    CONSOLE_APP,
)

from p1.emit import render_report

ARTEFACTS = (
    "application-manifest.json",
    "dependency-graph.json",
    "discovery-report.md",
)

MANIFEST_KEYS = {
    "build_requirements",
    "capability_states",
    "classification",
    "database",
    "dependency_summary",
    "diagnostics",
    "dialects",
    "files",
    "generator",
    "limits",
    "mode_visibility",
    "native_libs",
    "os_dependencies",
    "profiles",
    "project_roots",
    "schema_version",
    "shapes",
    "source",
    "sql_files",
}

GRAPH_KEYS = {"edges", "nodes", "schema_version", "stats", "unresolved"}


# ---------------------------------------------------------------------------
# Two runs, byte for byte
# ---------------------------------------------------------------------------


def test_two_runs_produce_identical_artefacts(
    app_tree: Path, tmp_path: Path
) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    run_pipeline(app_tree, first)
    run_pipeline(app_tree, second)

    for name in ARTEFACTS:
        assert artifact_bytes(first, name) == artifact_bytes(second, name), (
            f"{name} differs between two runs over the same input"
        )


def test_two_runs_of_the_same_archive_are_identical(
    app_tree: Path, tmp_path: Path
) -> None:
    archive = make_zip(
        tmp_path / "app.zip",
        [(path, (app_tree / Path(*path.split("/"))).read_bytes())
         for path in sorted(CONSOLE_APP)],
    )
    first = tmp_path / "one"
    second = tmp_path / "two"
    run_pipeline(archive, first, kind="zip")
    run_pipeline(archive, second, kind="zip")

    for name in ARTEFACTS:
        assert artifact_bytes(first, name) == artifact_bytes(second, name), (
            f"{name} differs between two runs over the same archive"
        )


def test_the_output_directory_name_does_not_leak_into_the_output(
    app_tree: Path, tmp_path: Path
) -> None:
    first = tmp_path / "alpha-output-directory"
    second = tmp_path / "zeta-output-directory"
    run_pipeline(app_tree, first)
    run_pipeline(app_tree, second)

    assert artifact_bytes(first, "application-manifest.json") == (
        artifact_bytes(second, "application-manifest.json")
    )
    assert artifact_bytes(first, "discovery-report.md") == (
        artifact_bytes(second, "discovery-report.md")
    )


def test_a_repeated_run_into_the_same_directory_is_idempotent(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    before = {name: artifact_bytes(out, name) for name in ARTEFACTS}
    run_pipeline(app_tree, out)
    after = {name: artifact_bytes(out, name) for name in ARTEFACTS}
    assert before == after


def test_different_inputs_produce_different_outputs(
    app_tree: Path, tmp_path: Path
) -> None:
    """Determinism must not be achieved by ignoring the input."""

    other = write_tree(tmp_path / "other", dict(CONSOLE_APP))
    (other / "README.md").write_text("# changed\n", encoding="utf-8")

    first = tmp_path / "one"
    second = tmp_path / "two"
    run_pipeline(app_tree, first)
    run_pipeline(other, second)

    assert artifact_bytes(first, "application-manifest.json") != (
        artifact_bytes(second, "application-manifest.json")
    )


# ---------------------------------------------------------------------------
# Serialisation contract
# ---------------------------------------------------------------------------


def test_manifest_has_the_documented_top_level_keys(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    manifest = read_json(out / "application-manifest.json")

    assert set(manifest) == MANIFEST_KEYS
    assert manifest["schema_version"] == "p1.application-manifest/1.0"
    assert manifest["generator"] == {
        "llm_assisted": False,
        "phase": "P1",
        "tool": "tools/p1",
    }


def test_graph_has_the_documented_top_level_keys(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    graph = read_json(out / "dependency-graph.json")

    assert set(graph) == GRAPH_KEYS
    assert graph["schema_version"] == "p1.dependency-graph/1.0"


def test_json_documents_round_trip_through_the_documented_serialiser(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)

    for name in ("application-manifest.json", "dependency-graph.json"):
        raw = artifact_bytes(out, name)
        assert raw.endswith(b"\n"), name
        payload = json.loads(raw.decode("utf-8"))
        rendered = (
            json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True)
            + "\n"
        )
        assert rendered.encode("utf-8") == raw, name


def _assert_keys_sorted(payload: object, where: str = "$") -> None:
    if isinstance(payload, dict):
        keys = list(payload)
        assert keys == sorted(keys), f"{where} is not key-sorted: {keys}"
        for key, value in payload.items():
            _assert_keys_sorted(value, f"{where}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            _assert_keys_sorted(value, f"{where}[{index}]")


def test_every_json_object_is_key_sorted(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)

    for name in ("application-manifest.json", "dependency-graph.json"):
        payload = json.loads(artifact_bytes(out, name).decode("utf-8"))
        _assert_keys_sorted(payload, name)


def test_json_is_ascii_escaped(
    app_tree: Path, tmp_path: Path
) -> None:
    """``ensure_ascii`` keeps the artefacts byte-stable across locales."""

    out = tmp_path / "out"
    run_pipeline(app_tree, out)

    for name in ("application-manifest.json", "dependency-graph.json"):
        raw = artifact_bytes(out, name)
        assert all(byte < 128 for byte in raw), (
            f"{name} contains a non-ASCII byte; ensure_ascii was not used"
        )


# ---------------------------------------------------------------------------
# The report cannot disagree with the JSON
# ---------------------------------------------------------------------------


def test_report_renders_identically_from_the_shipped_json(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)

    manifest = read_json(out / "application-manifest.json")
    graph = read_json(out / "dependency-graph.json")
    rendered = render_report(manifest, graph)
    on_disk = (out / "discovery-report.md").read_bytes().decode("utf-8")

    assert rendered == on_disk


def test_report_is_stable_across_runs(app_tree: Path, tmp_path: Path) -> None:
    first = tmp_path / "one"
    second = tmp_path / "two"
    run_pipeline(app_tree, first)
    run_pipeline(app_tree, second)

    a = read_json(first / "application-manifest.json")
    b = read_json(second / "application-manifest.json")
    assert render_report(a, read_json(first / "dependency-graph.json")) == (
        render_report(b, read_json(second / "dependency-graph.json"))
    )


# ---------------------------------------------------------------------------
# No machine-local state in the artefacts
# ---------------------------------------------------------------------------


def test_no_absolute_or_staging_path_in_any_artefact(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)

    for name in ARTEFACTS:
        text = artifact_bytes(out, name).decode("utf-8").lower()
        assert "p1-stage-" not in text, name
        assert str(tmp_path).lower() not in text, name
        assert str(app_tree).lower() not in text, name


def test_no_wall_clock_timestamp_in_the_manifest(
    app_tree: Path, tmp_path: Path
) -> None:
    """A directory input carries no timestamps at all — never "now"."""

    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    source = read_json(out / "application-manifest.json")["source"]

    assert source["source_timestamp"] == ""
    assert set(source) == {
        "commit", "entry_count", "kind", "origin", "source_timestamp",
        "total_bytes",
    }
    assert source["origin"] == "app", "origin must be a path-free label"


def test_mode_visibility_never_claims_verified(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    manifest = read_json(out / "application-manifest.json")

    assert manifest["mode_visibility"], "the mode table must be reported"
    for entry in manifest["mode_visibility"]:
        assert entry["result_visible"] in ("SUPPORTED", "UNSUPPORTED", "UNKNOWN")
        assert entry["bare_assignfile_visible"] in (
            "SUPPORTED", "UNSUPPORTED", "UNKNOWN"
        )
        assert "VERIFIED" not in entry.values()


def test_capability_states_never_claim_verified(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    states = read_json(out / "application-manifest.json")["capability_states"]

    assert states, "capability states must be reported"
    for state in states:
        assert state["status"] in (
            "SUPPORTED", "PARTIAL", "UNSUPPORTED", "UNAVAILABLE", "UNKNOWN"
        ), state
        assert state["status"] != "VERIFIED"
