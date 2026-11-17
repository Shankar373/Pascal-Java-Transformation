"""Unit tests for the Stage 1 Application Blueprint (``p1.blueprint``).

Trees are scanned with the real P1 pipeline pieces; the Stage 1 finding lists
(libraries, integrations, runtime dependencies, build scripts, compiler
configs, directories) are filled by hand, standing in for the detectors.
"""

from __future__ import annotations

import copy
import csv
import dataclasses
import io
import json
import random
from pathlib import Path
from typing import Any

import pytest

import blueprint_helpers as H
from conftest import AMBIGUOUS_APP, CONSOLE_APP, GUI_APP, REPO_ROOT, write_tree
from p1 import findings as F
from p1.blueprint import (
    BLUEPRINT_SCHEMA,
    LIMITATIONS,
    build_blueprint,
    render_inventory_csv,
    write_blueprint_outputs,
)
from p1.blueprint_common import evidence_list, locate, make_ctx
from p1.blueprint_sections import percentages
from p1.blueprint_structure import CHILD_LIMIT, COMPONENT_IDS
from p1.findings import Evidence, LibraryFinding
from p1.schemacheck import validate
from p1.statuses import STATUSES

SCHEMA_PATH = REPO_ROOT / "docs" / "stage1" / "schemas" / (
    "application-blueprint.schema.json")
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

TOP_KEYS = {
    "schema_version", "generator", "stage", "project", "summary",
    "file_distribution", "dialect", "projects", "structure", "dependencies",
    "unresolved", "graphs", "components", "inventory", "diagnostics",
    "blockers", "capability_states", "limitations",
}


def _dump(document: Any) -> str:
    return json.dumps(document, sort_keys=True, indent=2, ensure_ascii=True)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def enterprise_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return H.enterprise_tree(tmp_path_factory.mktemp("ent") / "app")


@pytest.fixture(scope="module")
def plain(enterprise_root: Path):
    return H.discovery_from_tree(enterprise_root, origin="legacy-erp")


@pytest.fixture(scope="module")
def full(enterprise_root: Path, plain):
    return H.with_stage1_findings(plain, enterprise_root)


@pytest.fixture(scope="module")
def bp(full) -> dict[str, Any]:
    return build_blueprint(full)


# ---------------------------------------------------------------------------
# schema and shape
# ---------------------------------------------------------------------------


def test_schema_enums_equal_the_findings_vocabularies() -> None:
    defs = SCHEMA["$defs"]
    pairs = {
        ("libraryFinding", "category"): F.LIBRARY_CATEGORIES,
        ("libraryFinding", "origin"): F.LIBRARY_ORIGINS,
        ("integrationFinding", "category"): F.INTEGRATION_CATEGORIES,
        ("runtimeFinding", "kind"): F.RUNTIME_KINDS,
        ("buildScriptFinding", "kind"): F.BUILD_SCRIPT_KINDS,
        ("compilerConfigFinding", "kind"): F.COMPILER_CONFIG_KINDS,
    }
    for (definition, prop), expected in pairs.items():
        actual = defs[definition]["properties"][prop]["enum"]
        assert tuple(actual) == tuple(expected), (definition, prop)
    assert tuple(defs["confidence"]["enum"]) == F.CONFIDENCE_LEVELS
    assert tuple(defs["status"]["enum"]) == STATUSES
    assert "VERIFIED" not in defs["status"]["enum"]


def test_schema_is_closed_at_top_level_and_on_finding_objects() -> None:
    assert SCHEMA["additionalProperties"] is False
    assert set(SCHEMA["required"]) == TOP_KEYS == set(SCHEMA["properties"])
    for name in ("libraryFinding", "integrationFinding", "runtimeFinding",
                 "buildScriptFinding", "compilerConfigFinding", "evidence",
                 "nativeLibrary", "database", "sqlFile", "keyDependency"):
        assert SCHEMA["$defs"][name]["additionalProperties"] is False, name
    assert SCHEMA["$schema"].endswith("2020-12/schema")


def test_blueprint_has_exactly_the_design_keys(bp: dict[str, Any]) -> None:
    assert set(bp) == TOP_KEYS
    assert bp["schema_version"] == BLUEPRINT_SCHEMA
    assert bp["generator"] == {"llm_assisted": False, "stage": 1,
                               "tool": "tools/p1"}


def test_enterprise_blueprint_is_schema_valid(bp: dict[str, Any]) -> None:
    assert validate(bp, SCHEMA) == []


def test_enterprise_blueprint_without_stage1_findings_is_valid(plain) -> None:
    document = build_blueprint(plain)
    assert validate(document, SCHEMA) == []
    assert document["dependencies"]["libraries"] == []
    assert document["inventory"]["directories"], "derived from file paths"


def test_capability_states_never_contain_verified(bp: dict[str, Any]) -> None:
    statuses = {s["status"] for s in bp["capability_states"]}
    assert statuses and "VERIFIED" not in statuses
    assert statuses <= set(STATUSES)


def test_limitations_are_stated(bp: dict[str, Any]) -> None:
    assert bp["limitations"] == list(LIMITATIONS)
    joined = " ".join(bp["limitations"]).lower()
    for phrase in ("semantic", "decompiled", "compiler", "connected"):
        assert phrase in joined


# ---------------------------------------------------------------------------
# stage / project / summary
# ---------------------------------------------------------------------------


def test_stage_is_completed_with_blockers_when_unresolved_exist(bp) -> None:
    assert bp["stage"]["id"] == 1
    assert bp["stage"]["status"] == "COMPLETED_WITH_BLOCKERS"
    assert [s["id"] for s in bp["stage"]["steps"]] == [
        "ingestion", "checkpoint", "scanning_inventory",
        "dependency_analysis", "blueprint"]
    assert {s["status"] for s in bp["stage"]["steps"]} <= {
        "COMPLETED", "COMPLETED_WITH_WARNINGS"}


def test_stage_is_completed_when_nothing_blocks(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "ok", {
        "src/Hello.dpr": "program Hello;\n{$APPTYPE CONSOLE}\nbegin\nend.\n",
        "src/Hello.dproj": (
            '<Project xmlns="http://schemas.microsoft.com/developer/msbuild/'
            '2003"><PropertyGroup><MainSource>Hello.dpr</MainSource>'
            "<AppType>Console</AppType></PropertyGroup></Project>"),
    })
    discovery = H.discovery_from_tree(root)
    discovery.build_requirements["blockers"] = []
    document = build_blueprint(discovery)
    assert document["blockers"] == []
    assert document["stage"]["status"] == "COMPLETED"
    assert validate(document, SCHEMA) == []


def test_summary_matches_the_inventory(bp, full) -> None:
    summary = bp["summary"]
    assert summary["total_files"] == len(full.analysed)
    assert summary["total_bytes"] == sum(a.inventory.size
                                         for a in full.analysed)
    assert summary["forms"] == 1
    assert summary["projects"] == 2
    assert summary["packages"] == 1
    assert summary["pascal_sources"] == bp["file_distribution"]["groups"][0][
        "count"]
    assert summary["directories"] == len(bp["inventory"]["directories"])
    assert summary["blockers"] == len(bp["blockers"])
    assert summary["unresolved_dependencies"] == sum(
        1 for u in bp["unresolved"] if u["severity"] in ("error", "warning"))
    counts = summary["diagnostics"]
    assert sum(counts.values()) == len(bp["diagnostics"])


def test_directories_include_empty_ones_from_the_finding_list(bp) -> None:
    paths = {d["path"] for d in bp["inventory"]["directories"]}
    assert {"src", "core", "lib/jedi", "config"} <= paths
    assert bp["inventory"]["files_ref"] == "inventory.csv"
    assert bp["inventory"]["file_count"] == bp["summary"]["total_files"]


def test_project_block_without_checkpoint_has_empty_provenance(bp) -> None:
    project = bp["project"]
    assert project["name"] == "legacy-erp"
    assert project["checkpoint"]["id"] == ""
    assert project["ingestion_source"]["kind"] == "directory"
    assert project["ingestion_source"]["commit"] == ""


def test_project_block_uses_checkpoint_and_provenance(full) -> None:
    commit = "a" * 40
    discovery = dataclasses.replace(
        full,
        checkpoint={
            "checkpoint_id": "CP-0123456789ab", "source_digest": "b" * 64,
            "file_count": 28, "directory_count": 12,
            "source": {"kind": "git", "origin": "legacy", "ref": "main",
                       "commit": commit, "tree_id": "c" * 40,
                       "commit_timestamp": "2026-11-16T10:24:00+00:00"}},
        source_provenance={
            "remote": "https://user:tok3n@git.example.com/legacy/erp.git"})
    document = build_blueprint(discovery)
    project = document["project"]
    assert project["checkpoint"] == {
        "id": "CP-0123456789ab", "source_digest": "b" * 64,
        "tree_id": "c" * 40, "file_count": 28, "directory_count": 12}
    source = project["ingestion_source"]
    assert source["commit"] == commit and source["ref"] == "main"
    assert source["origin"] == "https://git.example.com/legacy/erp.git"
    assert "tok3n" not in _dump(document)
    assert validate(document, SCHEMA) == []
    steps = {s["id"]: s["status"] for s in document["stage"]["steps"]}
    assert steps["checkpoint"] == "COMPLETED"


# ---------------------------------------------------------------------------
# file distribution
# ---------------------------------------------------------------------------


def test_file_distribution_groups_and_percentages(bp) -> None:
    dist = bp["file_distribution"]
    assert [g["id"] for g in dist["groups"]] == [
        "pascal_source", "project_package", "form_ui", "config_build",
        "other"]
    assert sum(g["count"] for g in dist["groups"]) == dist["total"]
    assert abs(sum(g["percent"] for g in dist["groups"]) - 100.0) <= 0.1
    for group in dist["groups"]:
        assert round(group["percent"], 1) == group["percent"]
    assert sum(dist["by_class"].values()) == dist["total"]
    assert sum(dist["by_extension"].values()) == dist["total"]
    assert dist["by_extension"][".pas"] == 12


def test_group_membership_follows_extension_then_class(bp) -> None:
    groups = {g["id"]: g["count"] for g in bp["file_distribution"]["groups"]}
    assert groups["pascal_source"] == 13  # 12 .pas + common.inc
    assert groups["project_package"] == 3  # .dpr .dpk .dproj
    assert groups["form_ui"] == 1


def test_percentages_sum_to_100_for_random_inputs() -> None:
    rng = random.Random(7)
    for _ in range(300):
        counts = [rng.choice([0, 0, 1, 2, 7, 99, 1234]) for _ in range(5)]
        total = sum(counts)
        if total == 0:
            continue
        result = percentages(counts, total)
        assert sum(round(p * 10) for p in result) == 1000
        for count, value in zip(counts, result):
            assert abs(value - count * 100 / total) < 0.1 + 1e-9


def test_percentages_with_zero_total_do_not_divide() -> None:
    assert percentages([0, 0, 0, 0, 0], 0) == [0.0] * 5
    assert percentages([], 0) == []


def test_percentages_match_the_mock_up_shape() -> None:
    # 2376 + 254 + 387 + 298 + 1577 = 4892 files (the reference screen).
    result = percentages([2376, 254, 387, 298, 1577], 4892)
    assert result[0] == 48.6
    assert abs(sum(result) - 100.0) < 1e-9


# ---------------------------------------------------------------------------
# dialect
# ---------------------------------------------------------------------------


def test_dialect_for_the_delphi_fixture(bp) -> None:
    dialect = bp["dialect"]
    assert dialect["primary"] == "delphi"
    assert dialect["label"] == "Delphi / Object Pascal"
    assert dialect["status"] == "PARTIAL"
    assert dialect["compiler"]["name"] == "Embarcadero Delphi"
    assert dialect["compiler"]["status"] == "PARTIAL"
    assert dialect["by_dialect"]["delphi"] == 2
    files = {e["file"] for e in dialect["evidence"]}
    assert {"ERPSystem.dpr", "ERPSystem.dproj"} <= files


def test_dialect_version_reports_the_stated_project_version(bp) -> None:
    version = bp["dialect"]["version"]
    assert version["value"] == "ProjectVersion 19.2"
    assert version["status"] == "PARTIAL"
    assert "ERPSystem.dproj" in version["source"]
    assert "19.2" in version["source"]


def test_dialect_version_is_unknown_when_nothing_states_it(tmp_path) -> None:
    root = write_tree(tmp_path / "gui", GUI_APP)  # .lpi has <Version Value=12>
    document = build_blueprint(H.discovery_from_tree(root))
    version = document["dialect"]["version"]
    assert version["value"] == "unknown"
    assert version["status"] == "UNKNOWN"
    assert document["dialect"]["label"] == "Free Pascal / Lazarus"
    assert document["dialect"]["primary"] == "fpc"


def test_dialect_is_unknown_without_pascal(tmp_path) -> None:
    root = write_tree(tmp_path / "docs", {"README.md": "# nothing\n"})
    dialect = build_blueprint(H.discovery_from_tree(root))["dialect"]
    assert dialect["primary"] == "unknown"
    assert dialect["label"] == "Unknown"
    assert dialect["status"] == "UNKNOWN"
    assert dialect["evidence"] == []
    assert dialect["compiler"]["name"] == "Unknown"


# ---------------------------------------------------------------------------
# projects and structure
# ---------------------------------------------------------------------------

_REACH_TREE = {
    "app/App.dpr": "program App;\nuses uA, uB;\nbegin\nend.\n",
    "app/App.dproj": "<Project><PropertyGroup/></Project>\n",
    "app/uA.pas": ("unit uA;\ninterface\nuses uB, SysUtils;\n"
                   "implementation\nend.\n"),
    "app/uA.dfm": "object FormA: TForm\nend\n",
    "app/readme.md": "# app\n",
    "shared/uB.pas": "unit uB;\ninterface\nimplementation\nend.\n",
    "tool/Tool.dpr": "program Tool;\nuses uB;\nbegin\nend.\n",
    "tool/notes.txt": "notes\n",
    "loose/orphan.pas": "unit orphan;\ninterface\nimplementation\nend.\n",
}


@pytest.fixture(scope="module")
def reach_bp(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = write_tree(tmp_path_factory.mktemp("reach") / "t", _REACH_TREE)
    return build_blueprint(H.discovery_from_tree(root))


def test_projects_are_primary_first_with_counts(reach_bp) -> None:
    projects = reach_bp["projects"]
    assert [p["path"] for p in projects] == ["app/App.dpr", "tool/Tool.dpr"]
    assert [p["primary"] for p in projects] == [True, False]
    app, tool = projects
    assert (app["unit_count"], app["form_count"]) == (2, 1)
    assert (tool["unit_count"], tool["form_count"]) == (1, 0)
    assert app["entry_point"]["file"] == "app/App.dpr"
    assert app["entry_point"]["line"] == 1
    assert app["meta_files"] == ["app/App.dproj"]
    for project in projects:
        assert project["evidence"]


def test_structure_assigns_every_file_to_exactly_one_project(reach_bp) -> None:
    tree = reach_bp["structure"]
    assert tree["kind"] == "application"
    assert [c["path"] for c in tree["children"]] == [
        "app/App.dpr", "tool/Tool.dpr"]
    seen: list[str] = []
    for project in tree["children"]:
        assert project["kind"] == "project"
        assert [g["name"] for g in project["children"]] == [
            "Units", "Forms", "Packages", "Libraries", "Resources", "Config",
            "Scripts", "Docs", "Other"]
        assert project["counts"]["files"] == sum(
            g["counts"]["files"] for g in project["children"])
        for group in project["children"]:
            seen.extend(f["path"] for f in group["children"])
    assert sorted(seen) == sorted(_REACH_TREE)
    assert tree["counts"]["files"] == len(_REACH_TREE)
    assert tree["counts"]["projects"] == 2


def test_structure_primary_flag_only_on_project_nodes(reach_bp) -> None:
    first = reach_bp["structure"]["children"][0]
    assert first["primary"] is True
    assert "primary" not in reach_bp["structure"]
    assert validate(reach_bp, SCHEMA) == []


def test_structure_is_bounded_and_flags_truncation(tmp_path: Path) -> None:
    files = {"App.dpr": "program App;\nbegin\nend.\n"}
    for index in range(CHILD_LIMIT + 10):
        files[f"u{index:03d}.pas"] = f"unit u{index:03d};\ninterface\nimpl" \
                                     "ementation\nend.\n"
    root = write_tree(tmp_path / "many", files)
    tree = build_blueprint(H.discovery_from_tree(root))["structure"]
    units = tree["children"][0]["children"][0]
    assert units["name"] == "Units"
    assert units["counts"]["files"] == CHILD_LIMIT + 10  # App.dpr: Other
    assert len(units["children"]) == CHILD_LIMIT
    assert units["truncated"] is True
    forms = tree["children"][0]["children"][1]
    assert forms["truncated"] is False and forms["children"] == []


def test_structure_without_projects_hangs_groups_on_the_application(
        tmp_path: Path) -> None:
    root = write_tree(tmp_path / "noproj", {"a/u.pas": "unit u;\n"})
    tree = build_blueprint(H.discovery_from_tree(root))["structure"]
    assert tree["kind"] == "application"
    assert tree["children"][0]["kind"] == "group"


def test_projects_for_the_ambiguous_tree_have_no_primary(tmp_path) -> None:
    root = write_tree(tmp_path / "amb", AMBIGUOUS_APP)
    document = build_blueprint(H.discovery_from_tree(root))
    assert [p["primary"] for p in document["projects"]] == [False, False]
    assert {p["status"] for p in document["projects"]} == {"UNKNOWN"}
    codes = {b["code"] for b in document["blockers"]}
    assert "AMBIGUOUS_PROJECT_ROOT" in codes
    assert validate(document, SCHEMA) == []


# ---------------------------------------------------------------------------
# unresolved
# ---------------------------------------------------------------------------


def _by_id(bp: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {u["id"]: u for u in bp["unresolved"]}


def test_unresolved_ids_are_unique_and_sorted(bp) -> None:
    ids = [u["id"] for u in bp["unresolved"]]
    assert ids == sorted(ids) and len(ids) == len(set(ids))


def test_unresolved_is_a_superset_of_the_graph_edges(bp, full) -> None:
    items = _by_id(bp)
    edges = full.graph.unresolved()
    assert edges, "fixture must have unresolved edges"
    for edge in edges:
        tail = edge.dst.partition(":")[2] or edge.dst
        kind = {"include": "include", "external": "native-library"}.get(
            edge.relation, "unit")
        item = items[f"{kind}:{tail}"]
        assert {"file": edge.file, "line": edge.line,
                "column": edge.column} in item["referenced_by"]


def test_unresolved_severities_follow_the_policy(bp) -> None:
    items = _by_id(bp)
    assert items["include:gone.inc"]["severity"] == "error"
    assert items["unit:sysutils"]["severity"] == "info"  # rtl: by design
    assert items["unit:forms"]["severity"] == "info"  # framework
    assert items["unit:frxclass"]["severity"] == "warning"  # known library
    assert items["library:devexpress"]["severity"] == "warning"
    assert items["native-library:vendor.dll"]["severity"] == "warning"
    present = items["native-library:legacy.dll"]
    assert present["severity"] == "info"
    assert "lib/legacy.dll" in present["remediation"]
    assert "runtime:dll:vendor.dll" not in items  # folded, not duplicated
    assert "runtime dll vendor.dll" in (
        items["native-library:vendor.dll"]["remediation"])
    assert items["runtime:environment-variable:erp_home"]["severity"] == "info"
    assert "unit:rtl" in items and items["unit:rtl"]["severity"] == "info"
    assert items["unit:vendorui"]["severity"] == "error"


def test_resolved_runtime_and_libraries_are_not_unresolved(bp) -> None:
    items = _by_id(bp)
    assert "runtime:dll:legacy.dll" not in items
    assert "library:jedi" not in items
    assert "library:vcl" not in items


def test_every_unresolved_item_is_complete(bp) -> None:
    for item in bp["unresolved"]:
        assert item["name"] and item["reason"]
        assert item["remediation"], item["id"]
        assert item["referenced_by"], item["id"]
        assert item["severity"] in ("error", "warning", "info")


def test_unresolved_blocker_is_added_when_actionable_items_exist(bp) -> None:
    codes = [b["code"] for b in bp["blockers"]]
    assert "UNRESOLVED_DEPENDENCIES" in codes
    assert codes == sorted(codes)


def test_project_file_without_entry_point_is_unresolved(tmp_path) -> None:
    root = write_tree(tmp_path / "lonely", {"Lost.dproj": "<Project/>\n"})
    document = build_blueprint(H.discovery_from_tree(root))
    item = _by_id(document)["project-file:Lost.dproj"]
    assert item["kind"] == "project-file" and item["severity"] == "warning"


def test_standard_requires_packages_are_informational(bp) -> None:
    items = _by_id(bp)
    for name in ("rtl", "vcl", "dbrtl"):
        assert items[f"unit:{name}"]["severity"] == "info"


# ---------------------------------------------------------------------------
# dependencies
# ---------------------------------------------------------------------------


def test_key_dependencies_are_top_five_sorted_by_references(bp) -> None:
    key = bp["dependencies"]["key"]
    assert 1 <= len(key) <= 5
    order = [(k["status"] != "unresolved", -k["references"],
              k["name"].lower(), k["kind"]) for k in key]
    assert order == sorted(order)
    for item in key:
        assert item["status"] in ("resolved", "unresolved")
        assert item["reason"] and item["references"] >= 1
    statuses = [k["status"] for k in key]
    assert statuses == sorted(statuses, key=lambda v: v != "unresolved")
    assert "cxgrid" not in {k["name"] for k in key}  # covered by DevExpress


def test_parse_project_file_records_the_stated_project_version() -> None:
    from p1.projects import parse_project_file

    profile, _ = parse_project_file(
        "a.dproj", "<Project><PropertyGroup><ProjectVersion>19.2"
                   "</ProjectVersion></PropertyGroup></Project>")
    assert any(e.get("evidence") == "project_version=19.2"
               for e in profile.evidence)


def test_version_can_come_from_a_compiler_config_finding(plain) -> None:
    config = F.CompilerConfigFinding(
        "ERPSystem.dproj", "delphi-project", "project",
        (("ProjectVersion", "20.1"),), (), (),
        (Evidence("ERPSystem.dproj", 5, 5, "ProjectVersion"),))
    bare = dataclasses.replace(plain, roots=[], compiler_configs=[config])
    version = build_blueprint(bare)["dialect"]["version"]
    assert version["value"] == "ProjectVersion 20.1"
    assert "ERPSystem.dproj" in version["source"]


def test_scheduled_job_component_comes_from_integration_findings(
        plain) -> None:
    job = F.IntegrationFinding(
        "scheduled-job", "schtasks", (), (Evidence("build.bat", 2, 1, "x"),))
    document = build_blueprint(dataclasses.replace(plain, integrations=[job]))
    component = next(c for c in document["components"]
                     if c["id"] == "scheduled_jobs")
    assert component["present"] and component["count"] == 1
    assert component["evidence"][0]["file"] == "build.bat"


def test_key_dependencies_mark_bundled_resolved_and_absent_unresolved(
        full) -> None:
    libs = [
        LibraryFinding("Zeta", "other", "bundled", "", (), ("a.pas", "b.pas"),
                       True, (Evidence("a.pas", 1, 1, "uses zeta"),)),
        LibraryFinding("Alpha", "other", "external", "", (), ("a.pas", "b.pas"),
                       False, (Evidence("a.pas", 2, 1, "uses alpha"),)),
        LibraryFinding("Mid", "other", "unresolved", "", (), ("a.pas",),
                       False, (Evidence("a.pas", 3, 1, "uses mid"),)),
    ]
    document = build_blueprint(dataclasses.replace(
        full, libraries=libs, database=[], native_libs=[], graph=type(
            full.graph)()))
    key = document["dependencies"]["key"]
    assert [(k["name"], k["status"]) for k in key] == [
        ("Alpha", "unresolved"), ("Mid", "unresolved"), ("Zeta", "resolved")]


def test_finding_lists_are_passed_through_with_located_evidence(
        bp, full) -> None:
    deps = bp["dependencies"]
    assert len(deps["libraries"]) == len(full.libraries)
    assert len(deps["integrations"]) == len(full.integrations)
    assert len(deps["runtime"]) == len(full.runtime_dependencies)
    assert len(deps["build"]["scripts"]) == 2
    assert len(deps["build"]["compiler_configs"]) == 1
    assert [d["technology"] for d in deps["databases"]]
    assert deps["sql_files"][0]["path"] == "sql/schema_oracle.sql"
    legacy = next(n for n in deps["native_libraries"]
                  if n["name"] == "legacy.dll")
    assert legacy["resolved_in_input"] is True
    vendor = next(n for n in deps["native_libraries"]
                  if n["name"] == "vendor.dll")
    assert vendor["resolved_in_input"] is False
    assert deps["build"]["requirements"]["compiler"] == "delphi"


# ---------------------------------------------------------------------------
# the evidence rule
# ---------------------------------------------------------------------------


def _assert_located(evidence: list[dict[str, Any]], known: set[str],
                    where: str) -> None:
    assert evidence, f"{where}: no evidence"
    for entry in evidence:
        assert set(entry) == {"file", "line", "column", "text"}, where
        assert isinstance(entry["file"], str) and entry["file"], where
        assert isinstance(entry["line"], int) and entry["line"] >= 0
        assert isinstance(entry["column"], int) and entry["column"] >= 0
        assert isinstance(entry["text"], str)
        assert entry["file"] in known, f"{where}: unknown file {entry}"


def test_evidence_rule_over_every_item(bp, full) -> None:
    known = {a.path for a in full.analysed}
    count = 0
    for where, item in H.evidence_owners(bp):
        _assert_located(item["evidence"], known, where)
        count += 1
    assert count > 30


def test_present_components_cite_located_evidence(bp, full) -> None:
    known = {a.path for a in full.analysed}
    by_id = {c["id"]: c for c in bp["components"]}
    assert list(by_id) == list(COMPONENT_IDS)
    for component in bp["components"]:
        if component["present"]:
            assert component["count"] >= 1
            _assert_located(component["evidence"], known, component["id"])
        else:
            assert component["count"] == 0 and component["evidence"] == []


def test_component_presence_for_the_enterprise_fixture(bp) -> None:
    present = {c["id"]: c["present"] for c in bp["components"]}
    assert present == {
        "gui_application": True, "database": True, "com_activex": True,
        "reports": True, "scheduled_jobs": False, "services": True,
        "build_scripts": True, "documentation": True, "integrations": True,
    }
    assert [c["id"] for c in bp["components"]] == [
        "gui_application", "database", "com_activex", "reports",
        "scheduled_jobs", "services", "build_scripts", "documentation",
        "integrations"]


def test_components_without_detectors_fall_back_to_files(plain) -> None:
    document = build_blueprint(plain)
    by_id = {c["id"]: c for c in document["components"]}
    assert by_id["build_scripts"]["present"]  # build.bat / Makefile files
    assert by_id["documentation"]["present"]
    assert not by_id["integrations"]["present"]
    assert by_id["com_activex"]["present"]  # ComObj / ActiveX unit refs


def test_evidence_text_is_redacted_and_capped() -> None:
    discovery = H.synthetic_discovery({"a.pas": 10})
    ctx = make_ctx(discovery)
    leaked = Evidence("a.pas", 1, 1, "Password=hunter2;Server=x " + "z" * 300)
    entry = locate(leaked, ctx)
    assert entry is not None
    assert "hunter2" not in entry["text"] and len(entry["text"]) <= 120
    many = [Evidence("a.pas", n, 1, "x") for n in range(1, 200)]
    assert len(evidence_list(many, ctx)) == 25


def test_legacy_evidence_basenames_always_resolve_to_input_paths() -> None:
    discovery = H.synthetic_discovery({"x/Unit1.pas": 1, "y/Other.pas": 1,
                                       "z/Unit1.pas": 1})
    ctx = make_ctx(discovery)
    unique = locate({"source": "Other.pas", "line": 3, "evidence": "e"}, ctx)
    ambiguous = locate({"source": "Unit1.pas", "line": 3, "evidence": "e"},
                       ctx)
    assert unique["file"] == "y/Other.pas"
    assert ambiguous["file"] == "x/Unit1.pas"  # first input path, always real
    assert locate({"line": 1}, ctx) is None
    assert locate("just text", ctx) is None


# ---------------------------------------------------------------------------
# graphs
# ---------------------------------------------------------------------------


def test_graphs_block(reach_bp, bp, full) -> None:
    graphs = bp["graphs"]
    stats = full.graph.stats()
    assert graphs["unit"] == {
        "ref": "dependency-graph.json", "nodes": stats["nodes"],
        "edges": stats["edges"], "resolved": stats["resolved"],
        "unresolved": stats["unresolved"]}
    assert [p["package"] for p in graphs["packages"]] == [
        "packages/ErpCore.dpk"]
    assert {"rtl", "vcl", "dbrtl", "vendorui"} <= set(
        graphs["packages"][0]["requires"])
    projects = reach_bp["graphs"]["projects"]
    assert projects[0]["uses"] == ["app/uA.pas", "shared/uB.pas"]
    assert projects[1]["uses"] == ["shared/uB.pas"]
    used = {x["library"]: x["used_by"] for x in graphs["libraries"]}
    assert "DevExpress" in used


# ---------------------------------------------------------------------------
# degenerate and hostile trees
# ---------------------------------------------------------------------------


def _hostile_trees() -> dict[str, dict[str, str | bytes]]:
    return {
        "empty": {},
        "only_binaries": {"a.dll": b"MZ\x90\x00" + bytes(40),
                          "b.exe": b"MZ\x00\x00" + bytes(20),
                          "c.bin": bytes(range(200))},
        "zero_pascal": {"README.md": "# hi\n", "data.csv": "a,b\n"},
        "two_roots_ambiguous": dict(AMBIGUOUS_APP),
        "gui_lcl": dict(GUI_APP),
        "console": dict(CONSOLE_APP),
        "weird_names": {"sp ace/ü.pas": "unit x;\n", "=cmd.txt": "x",
                        "a,b.txt": "x"},
    }


@pytest.mark.parametrize("name", sorted(_hostile_trees()))
def test_degenerate_trees_produce_valid_blueprints(
        name: str, tmp_path: Path) -> None:
    root = write_tree(tmp_path / name, _hostile_trees()[name])
    discovery = H.discovery_from_tree(root)
    document = build_blueprint(discovery)
    assert validate(document, SCHEMA) == [], name
    dist = document["file_distribution"]
    assert dist["total"] == len(discovery.analysed)
    if dist["total"] == 0:
        assert [g["percent"] for g in dist["groups"]] == [0.0] * 5
        assert document["summary"]["total_files"] == 0
        assert document["dialect"]["primary"] == "unknown"
    else:
        assert abs(sum(g["percent"] for g in dist["groups"]) - 100) <= 0.1
    known = {a.path for a in discovery.analysed}
    for where, item in H.evidence_owners(document):
        _assert_located(item["evidence"], known, f"{name}:{where}")
    assert document["stage"]["status"] in (
        "COMPLETED", "COMPLETED_WITH_BLOCKERS")


def test_empty_tree_is_completed_with_blockers(tmp_path: Path) -> None:
    (tmp_path / "void").mkdir()
    document = build_blueprint(H.discovery_from_tree(tmp_path / "void"))
    assert document["stage"]["status"] == "COMPLETED_WITH_BLOCKERS"
    assert "NO_PROJECT_ROOT" in {b["code"] for b in document["blockers"]}
    assert document["projects"] == [] and document["unresolved"] == []
    assert all(not c["present"] for c in document["components"])


# ---------------------------------------------------------------------------
# determinism and leakage
# ---------------------------------------------------------------------------


def test_blueprint_is_byte_identical_on_rerun(full) -> None:
    assert _dump(build_blueprint(full)) == _dump(build_blueprint(full))


@pytest.mark.parametrize("seed", [1, 2, 3, 99])
def test_blueprint_is_independent_of_list_order(full, bp, seed: int) -> None:
    other = build_blueprint(H.shuffled(full, seed))
    assert _dump(other) == _dump(bp)


def test_build_blueprint_does_not_mutate_the_discovery(full) -> None:
    before = copy.deepcopy(full.build_requirements)
    build_blueprint(full)
    assert full.build_requirements == before


def test_no_absolute_paths_or_secrets_anywhere(
        full, bp, enterprise_root: Path, tmp_path: Path) -> None:
    out = tmp_path / "out"
    write_blueprint_outputs(full, out)
    blobs = [_dump(bp)] + [p.read_text(encoding="utf-8")
                           for p in sorted(out.iterdir())]
    needles = {str(enterprise_root), enterprise_root.as_posix(),
               str(enterprise_root).replace("\\", "\\\\"),
               str(enterprise_root.parent), H.SECRET}
    for blob in blobs:
        for needle in needles:
            assert needle not in blob, needle


def test_credentials_are_redacted_from_every_string(full) -> None:
    leaky = dataclasses.replace(full, diagnostics=[{
        "code": "X", "severity": "warning", "file": "src/uConfig.pas",
        "message": "connect Password=hunter2 failed", "line": 1,
        "column": 1}])
    document = build_blueprint(leaky)
    assert "hunter2" not in _dump(document)


def test_staging_paths_in_messages_are_scrubbed(full, tmp_path: Path) -> None:
    staging = tmp_path / "p1-stage-abc123"
    discovery = dataclasses.replace(
        full,
        ingestion=dataclasses.replace(full.ingestion, staging_root=staging),
        diagnostics=[{"code": "LEAK", "severity": "warning",
                      "message": f"failed under {staging}", "file": "a",
                      "line": 1, "column": 1}])
    document = build_blueprint(discovery)
    text = _dump(document)
    assert "p1-stage-abc123" not in text and "<staging>" in text


def test_explicit_staging_roots_are_scrubbed_from_written_files(
        full, tmp_path: Path) -> None:
    secret_dir = str(tmp_path / "elsewhere-staging")
    discovery = dataclasses.replace(full, diagnostics=[{
        "code": "LEAK", "severity": "info", "message": secret_dir + "\\x",
        "file": "a", "line": 1, "column": 1}])
    out = tmp_path / "o"
    write_blueprint_outputs(discovery, out, staging_roots=(secret_dir,))
    for path in out.iterdir():
        assert "elsewhere-staging" not in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# mutation tests (the validator must reject broken documents)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(TOP_KEYS))
def test_deleting_any_required_top_level_key_is_rejected(
        bp, key: str) -> None:
    broken = copy.deepcopy(bp)
    del broken[key]
    assert validate(broken, SCHEMA)


def _set(document: dict[str, Any], path: str, value: Any) -> None:
    node: Any = document
    parts = path.split(".")
    for part in parts[:-1]:
        node = node[int(part)] if part.isdigit() else node[part]
    last = parts[-1]
    if last.isdigit():
        node[int(last)] = value
    else:
        node[last] = value


@pytest.mark.parametrize(
    "path, value",
    [
        ("summary.total_files", "28"),
        ("summary.total_files", -1),
        ("stage.status", "FAILED"),
        ("stage.id", 2),
        ("generator.llm_assisted", True),
        ("schema_version", "stage1.application-blueprint/9.9"),
        ("projects", {}),
        ("file_distribution.groups.0.percent", 100.5),
        ("file_distribution.groups.0.id", "bogus"),
        ("dependencies.libraries.0.origin", "bogus"),
        ("dependencies.libraries.0.category", "bogus"),
        ("dependencies.libraries.0.confidence", "certain"),
        ("dependencies.integrations.0.category", "bogus"),
        ("dependencies.runtime.0.kind", "bogus"),
        ("dependencies.build.scripts.0.kind", "bogus"),
        ("dependencies.build.compiler_configs.0.kind", "bogus"),
        ("dependencies.key.0.status", "maybe"),
        ("dependencies.key.0.evidence", []),
        ("unresolved.0.severity", "fatal"),
        ("unresolved.0.kind", "other"),
        ("unresolved.0.id", "no-colon"),
        ("capability_states.0.status", "VERIFIED"),
        ("dialect.status", "VERIFIED"),
        ("project.checkpoint.id", "CP-xyz"),
        ("projects.0.evidence", []),
        ("components.0.id", "bogus"),
        ("inventory.files_ref", "files.csv"),
        ("structure.kind", "forest"),
    ],
)
def test_mutated_values_are_rejected(bp, path: str, value: Any) -> None:
    broken = copy.deepcopy(bp)
    _set(broken, path, value)
    assert validate(broken, SCHEMA), (path, value)


def test_extra_keys_are_rejected_at_top_and_on_findings(bp) -> None:
    top = copy.deepcopy(bp)
    top["surprise"] = 1
    assert validate(top, SCHEMA)
    finding = copy.deepcopy(bp)
    finding["dependencies"]["libraries"][0]["surprise"] = 1
    assert validate(finding, SCHEMA)
    evidence = copy.deepcopy(bp)
    evidence["dependencies"]["libraries"][0]["evidence"][0]["extra"] = 1
    assert validate(evidence, SCHEMA)


def test_component_presence_invariants_are_enforced(bp) -> None:
    absent = next(c for c in bp["components"] if not c["present"])
    index = bp["components"].index(absent)
    bad_count = copy.deepcopy(bp)
    bad_count["components"][index]["count"] = 3
    assert validate(bad_count, SCHEMA)
    no_evidence = copy.deepcopy(bp)
    present = next(i for i, c in enumerate(bp["components"]) if c["present"])
    no_evidence["components"][present]["evidence"] = []
    assert validate(no_evidence, SCHEMA)
    short = copy.deepcopy(bp)
    short["components"].pop()
    assert validate(short, SCHEMA)


def test_missing_required_keys_inside_nested_objects_are_rejected(bp) -> None:
    for path in ("summary", "dialect", "dependencies", "graphs", "stage"):
        broken = copy.deepcopy(bp)
        key = sorted(broken[path])[0]
        del broken[path][key]
        assert validate(broken, SCHEMA), path
    broken = copy.deepcopy(bp)
    del broken["dependencies"]["libraries"][0]["name"]
    assert validate(broken, SCHEMA)


# ---------------------------------------------------------------------------
# inventory.csv
# ---------------------------------------------------------------------------

_HOSTILE = {
    "=cmd|' /C calc'!A0.pas": 5,
    'a,b "quoted".txt': 7,
    "+plus.txt": 1,
    "-minus.txt": 1,
    "@at.txt": 1,
    "plain.pas": 3,
    "zz/ünï.pas": 2,
    "new\nline.txt": 4,
}


def _read_csv(text: str) -> list[list[str]]:
    return list(csv.reader(io.StringIO(text, newline=""), strict=True))


def test_inventory_csv_is_sorted_lf_and_injection_safe() -> None:
    discovery = H.synthetic_discovery(_HOSTILE)
    text = render_inventory_csv(discovery)
    assert "\r" not in text and text.endswith("\n")
    rows = _read_csv(text)
    assert rows[0] == ["path", "class", "extension", "size", "sha256",
                       "encoding", "analysis_blocker"]
    body = rows[1:]
    assert len(body) == len(_HOSTILE)
    paths = [r[0] for r in body]
    assert paths == sorted(paths, key=lambda p: p.lstrip("'"))
    by_path = {r[0].lstrip("'"): r for r in body}
    for original in _HOSTILE:
        row = by_path[original]
        assert row[3] == str(_HOSTILE[original])
        if original[0] in "=+-@":
            assert row[0] == "'" + original  # neutralised formula prefix
        else:
            assert row[0] == original  # commas, quotes, newlines round-trip
    for row in body:
        assert row[1:3] and not row[2].startswith(("=", "+", "-", "@"))


def test_inventory_csv_columns_for_real_files(full) -> None:
    rows = _read_csv(render_inventory_csv(full))[1:]
    assert len(rows) == len(full.analysed)
    dpr = next(r for r in rows if r[0] == "ERPSystem.dpr")
    assert dpr[1] == "pascal_program" and dpr[2] == ".dpr"
    assert len(dpr[4]) == 64
    assert [r[0] for r in rows] == sorted(r[0] for r in rows)


# ---------------------------------------------------------------------------
# write_blueprint_outputs
# ---------------------------------------------------------------------------


def test_write_blueprint_outputs_writes_exactly_four_files(
        full, bp, tmp_path: Path) -> None:
    out = tmp_path / "out"
    paths = write_blueprint_outputs(full, out)
    assert set(paths) == {"blueprint", "unresolved", "diagnostics",
                          "inventory"}
    assert sorted(p.name for p in out.iterdir()) == [
        "application-blueprint.json", "diagnostics.json", "inventory.csv",
        "unresolved-dependencies.json"]
    for name in ("run-record.json", "application-manifest.json",
                 "dependency-graph.json", "discovery-report.md"):
        assert not (out / name).exists()
    text = (out / "application-blueprint.json").read_bytes().decode("ascii")
    assert text.endswith("}\n") and not text.endswith("\n\n")
    assert "\r" not in text
    assert text == _dump(json.loads(text)) + "\n"
    assert json.loads(text) == json.loads(_dump(bp))


def test_auxiliary_documents(full, bp, tmp_path: Path) -> None:
    out = tmp_path / "aux"
    write_blueprint_outputs(full, out)
    unresolved = json.loads((out / "unresolved-dependencies.json").read_text())
    assert unresolved["schema_version"] == "stage1.unresolved/1.0"
    assert unresolved["count"] == len(unresolved["items"]) == len(
        bp["unresolved"])
    diagnostics = json.loads((out / "diagnostics.json").read_text())
    assert diagnostics["schema_version"] == "stage1.diagnostics/1.0"
    assert diagnostics["counts"] == bp["summary"]["diagnostics"]
    assert diagnostics["items"] == bp["diagnostics"]


def test_written_outputs_are_byte_identical_on_rerun(
        full, tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    write_blueprint_outputs(full, first)
    write_blueprint_outputs(H.shuffled(full, 5), second)
    for path in sorted(first.iterdir()):
        assert path.read_bytes() == (second / path.name).read_bytes()


def test_csv_is_written_utf8_with_lf_and_hostile_names(tmp_path: Path) -> None:
    discovery = H.synthetic_discovery(_HOSTILE)
    out = tmp_path / "csv"
    write_blueprint_outputs(discovery, out)
    raw = (out / "inventory.csv").read_bytes()
    assert b"\r" not in raw
    text = raw.decode("utf-8")
    assert "ünï.pas" in text and "'=cmd" in text
    assert validate(json.loads(
        (out / "application-blueprint.json").read_text()), SCHEMA) == []


# ---------------------------------------------------------------------------
# diagnostics
# ---------------------------------------------------------------------------


def test_diagnostics_are_merged_sorted_and_counted(bp) -> None:
    items = bp["diagnostics"]
    assert items
    for item in items:
        assert item["severity"] in ("error", "warning", "info")
        assert item["code"] and isinstance(item["message"], str)
    keys = [(i["code"], i.get("file", ""), i.get("line", 0),
             i.get("column", 0), i["message"]) for i in items]
    assert keys == sorted(keys)


def test_a_diagnostic_without_severity_defaults_to_warning(full) -> None:
    discovery = dataclasses.replace(full, diagnostics=[
        {"code": "NO_SEV", "message": "m", "file": "a", "line": 1,
         "column": 1}])
    document = build_blueprint(discovery)
    item = next(d for d in document["diagnostics"] if d["code"] == "NO_SEV")
    assert item["severity"] == "warning"
    assert validate(document, SCHEMA) == []
