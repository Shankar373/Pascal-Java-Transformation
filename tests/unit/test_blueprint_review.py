"""Regression tests for the confirmed review findings of the Stage 1 blueprint.

One group per finding: de-duplicated unresolved items, evidence paths,
scrub roots / single build, key-dependency ranking, unit attribution and the
low-severity items (``.dpk`` ownership, inventory CSV, typed requirements).
"""

from __future__ import annotations

import csv
import dataclasses
import io
import json
from pathlib import Path
from typing import Any

import pytest

import blueprint_helpers as H
from conftest import REPO_ROOT, write_tree
from p1 import blueprint as blueprint_module
from p1.blueprint import (
    build_blueprint,
    render_inventory_csv,
    write_blueprint_outputs,
)
from p1.blueprint_common import locate, make_ctx
from p1.schemacheck import validate
from p1.stage1 import DiscoveryRequest, discover

SCHEMA = json.loads((REPO_ROOT / "docs" / "stage1" / "schemas" /
                     "application-blueprint.schema.json").read_text("utf-8"))
_UNIT = "unit X;\ninterface\nimplementation\nend.\n"


@pytest.fixture(scope="module")
def stage1(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = tmp_path_factory.mktemp("rev")
    app = H.enterprise_tree(root / "app")
    return discover(DiscoveryRequest("directory", str(app), label="rev"),
                    root / "store").blueprint


def _dump(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True)


# ---------------------------------------------------------------------------
# 1. one missing thing = one unresolved item
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", ["vendorui", "umissingvendor", "vendor.dll"])
def test_a_missing_dependency_appears_exactly_once(stage1, name) -> None:
    hits = [u["id"] for u in stage1["unresolved"]
            if u["name"].lower() == name]
    assert len(hits) == 1, hits
    assert not any(i.startswith(("runtime:dll:vendor", "library:vendorui",
                                 "library:umissingvendor",
                                 "runtime:bpl-package:vendorui"))
                   for i in (u["id"] for u in stage1["unresolved"]))


def test_merged_item_takes_the_maximum_severity_and_all_locations(
        stage1) -> None:
    items = {u["id"]: u for u in stage1["unresolved"]}
    assert items["unit:vendorui"]["severity"] == "error"
    assert items["unit:umissingvendor"]["severity"] == "error"
    assert items["native-library:vendor.dll"]["severity"] == "warning"
    assert items["unit:vendorui"]["referenced_by"]  # locations are merged
    assert "bpl-package" in items["unit:vendorui"]["remediation"]


def test_counts_use_the_de_duplicated_items(stage1) -> None:
    todo = [u for u in stage1["unresolved"]
            if u["severity"] in ("error", "warning")]
    assert stage1["summary"]["unresolved_dependencies"] == len(todo)
    detail = next(b["detail"] for b in stage1["blockers"]
                  if b["code"] == "UNRESOLVED_DEPENDENCIES")
    errors = sum(1 for u in todo if u["severity"] == "error")
    assert detail.startswith(f"{len(todo)} unresolved dependencies")
    assert f"({errors} error, {len(todo) - errors} warning)" in detail


# ---------------------------------------------------------------------------
# 2. evidence files are always real input paths
# ---------------------------------------------------------------------------


def test_locate_never_returns_a_non_input_path() -> None:
    ctx = make_ctx(H.synthetic_discovery(
        {"x/Util.pas": 1, "a/Util.pas": 1, "y/Other.pas": 1}))
    ambiguous = locate({"source": "Util.pas", "line": 3, "evidence": "e"}, ctx)
    assert ambiguous["file"] == "a/Util.pas"  # lexicographically first
    assert locate({"source": "Other.pas", "evidence": "e"}, ctx)["file"] == (
        "y/Other.pas")
    assert locate({"source": "Ghost.pas", "evidence": "e"}, ctx) is None
    assert locate({"file": "x/Util.pas"}, ctx)["file"] == "x/Util.pas"


_EXTERNAL = ("unit Util;\ninterface\nfunction F: Integer;\nimplementation\n"
             "function F; external 'vendor.dll';\nend.\n")


def test_same_named_files_yield_full_path_evidence(tmp_path: Path) -> None:
    root = write_tree(tmp_path / "t", {
        "App.dpr": "program App;\nuses Util in 'a/Util.pas';\nbegin\nend.\n",
        "a/Util.pas": _EXTERNAL, "b/Util.pas": _EXTERNAL})
    discovery = H.discovery_from_tree(root)
    for finding in discovery.native_libs:
        assert {e["source"] for e in finding.evidence} <= {
            "a/Util.pas", "b/Util.pas"}
    document = build_blueprint(discovery)
    paths = {f["path"] for f in document["inventory"]["directories"]}
    inputs = {a.path for a in discovery.analysed}
    for _, item in H.evidence_owners(document):
        for entry in item["evidence"]:
            assert entry["file"] in inputs, (entry, paths)


# ---------------------------------------------------------------------------
# 3. scrub roots on build_blueprint, no second build
# ---------------------------------------------------------------------------

_ROOT = "C:\\Users\\me\\elsewhere-staging"


def _leaky(discovery):
    forms = [_ROOT + "\\x", _ROOT.replace("\\", "/") + "/x",
             _ROOT.replace("\\", "\\\\") + "\\\\x"]
    return dataclasses.replace(discovery, diagnostics=[
        {"code": "LEAK", "severity": "info", "message": f"at {m}",
         "file": "a", "line": 1, "column": 1} for m in forms])


def test_build_blueprint_applies_scrub_roots() -> None:
    discovery = _leaky(H.synthetic_discovery({"a.pas": 1}))
    assert "elsewhere-staging" in _dump(build_blueprint(discovery))
    scrubbed = build_blueprint(discovery, scrub_roots=(_ROOT,))
    assert "elsewhere-staging" not in _dump(scrubbed)
    assert "<staging>" in _dump(scrubbed)


def test_scrub_roots_apply_to_dict_and_files_alike(tmp_path: Path) -> None:
    discovery = _leaky(H.synthetic_discovery({"a.pas": 1}))
    document = build_blueprint(discovery, scrub_roots=(_ROOT,))
    out = tmp_path / "o"
    write_blueprint_outputs(discovery, out, staging_roots=(_ROOT,),
                            blueprint=document)
    for path in out.iterdir():
        assert "elsewhere-staging" not in path.read_text(encoding="utf-8")
    written = json.loads((out / "application-blueprint.json").read_text())
    assert written == json.loads(_dump(document))


def test_writer_uses_a_prebuilt_blueprint_without_rebuilding(
        tmp_path: Path, monkeypatch) -> None:
    discovery = H.synthetic_discovery({"a.pas": 1})
    document = build_blueprint(discovery)

    def boom(*_a: Any, **_k: Any) -> None:
        raise AssertionError("second build")

    monkeypatch.setattr(blueprint_module, "build_blueprint", boom)
    paths = write_blueprint_outputs(discovery, tmp_path / "o",
                                    blueprint=document)
    assert set(paths) == {"blueprint", "unresolved", "diagnostics",
                          "inventory"}


def test_writer_scrubs_a_prebuilt_blueprint_too(tmp_path: Path) -> None:
    discovery = _leaky(H.synthetic_discovery({"a.pas": 1}))
    document = build_blueprint(discovery)  # not scrubbed
    out = tmp_path / "o"
    write_blueprint_outputs(discovery, out, staging_roots=(_ROOT,),
                            blueprint=document)
    assert "elsewhere-staging" not in (
        out / "application-blueprint.json").read_text()


# ---------------------------------------------------------------------------
# 4. key dependencies
# ---------------------------------------------------------------------------


def test_key_dependencies_rank_unresolved_first_then_references(stage1) -> None:
    key = stage1["dependencies"]["key"]
    order = [(k["status"] != "unresolved", -k["references"],
              k["name"].lower(), k["kind"]) for k in key]
    assert order == sorted(order)


def test_key_dependencies_suppress_units_covered_by_a_library(stage1) -> None:
    key = stage1["dependencies"]["key"]
    names = {k["name"].lower() for k in key}
    assert not names & {"cxgrid", "dxbarmanager", "idhttp", "idftp"}
    kinds = {(k["kind"], k["name"].lower()) for k in key}
    assert ("library", "indy") in kinds or ("library", "devexpress") in kinds


def test_references_count_distinct_referencing_files(stage1) -> None:
    key = {(k["kind"], k["name"]): k for k in stage1["dependencies"]["key"]}
    databases = {d["technology"]: d
                 for d in stage1["dependencies"]["databases"]}
    for (kind, name), item in key.items():
        if kind == "database":
            files = {e["file"] for e in databases[name]["evidence"]}
            assert item["references"] == len(files)
        assert item["references"] >= 1
    for item in key.values():
        for entry in item["evidence"]:
            assert entry["file"] and entry["line"] >= 0


# ---------------------------------------------------------------------------
# 5. unit attribution
# ---------------------------------------------------------------------------

_ATTR = {
    "App.dpr": "program App;\nuses uA in 'uA.pas', uB in 'uB.pas';\n"
               "{$I defs.inc}\nbegin\nend.\n",
    "uA.pas": "unit uA;\ninterface\nimplementation\n{$I defs.inc}\nend.\n",
    "uB.pas": "unit uB;\ninterface\nimplementation\nend.\n",
    "defs.inc": "{$DEFINE X}\n",
    "Other.dpr": "program Other;\nuses uB in 'uB.pas';\nbegin\nend.\n",
}


@pytest.fixture(scope="module")
def attr_bp(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    root = write_tree(tmp_path_factory.mktemp("attr") / "t", _ATTR)
    return build_blueprint(H.discovery_from_tree(root))


def _node(tree: dict[str, Any], path: str) -> dict[str, Any]:
    return next(c for c in tree["children"] if c["path"] == path)


def test_unit_count_counts_pascal_units_only(attr_bp) -> None:
    projects = {p["path"]: p for p in attr_bp["projects"]}
    assert projects["App.dpr"]["unit_count"] == 2
    assert projects["Other.dpr"]["unit_count"] == 1  # shared uB, per project


def test_structure_units_exclude_includes_and_programs(attr_bp) -> None:
    app = _node(attr_bp["structure"], "App.dpr")
    units = next(g for g in app["children"] if g["name"] == "Units")
    assert sorted(f["name"] for f in units["children"]) == [
        "uA.pas", "uB.pas"]  # uB is shared and owned by the primary project
    assert app["counts"]["units"] == 2
    assert app["counts"]["includes"] == 1
    assert app["counts"]["programs"] == 1
    assert app["counts"]["files"] == sum(
        g["counts"]["files"] for g in app["children"])


def test_shared_unit_is_owned_by_one_project_in_the_tree(attr_bp) -> None:
    owners = [p["path"] for p in attr_bp["structure"]["children"]
              if any(f["name"] == "uB.pas" for g in p["children"]
                     for f in g["children"])]
    assert len(owners) == 1
    assert validate(attr_bp, SCHEMA) == []


# ---------------------------------------------------------------------------
# 6. low severity items
# ---------------------------------------------------------------------------


def test_a_package_that_is_a_project_root_belongs_to_itself(tmp_path) -> None:
    root = write_tree(tmp_path / "t", {
        "Main.dpk": "package Main;\nrequires Pkg;\ncontains uA in 'uA.pas';\n"
                    "end.\n",
        "Pkg.dpk": "package Pkg;\ncontains uB in 'uB.pas';\nend.\n",
        "uA.pas": _UNIT, "uB.pas": _UNIT})
    document = build_blueprint(H.discovery_from_tree(root))
    tree = document["structure"]
    roots = [p["path"] for p in document["projects"]]
    assert "Pkg.dpk" in roots

    def owns(project: str, name: str) -> bool:
        return any(f["name"] == name for g in _node(tree, project)["children"]
                   for f in g["children"])

    assert owns("Pkg.dpk", "Pkg.dpk") and not owns("Main.dpk", "Pkg.dpk")


@pytest.mark.parametrize("name", ["=x.pas", "-x.pas", "+x.pas", "@x.pas"])
def test_inventory_csv_path_guard_is_documented_and_reversible(name) -> None:
    text = render_inventory_csv(H.synthetic_discovery({name: 1}))
    rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    cell = rows[1][0]
    # A spreadsheet evaluates any cell that starts with = + - @, and no CSV
    # quoting can prevent that, so the path cell keeps the apostrophe guard.
    # The real path is recoverable by removing exactly one leading apostrophe.
    assert cell == "'" + name and cell[1:] == name
    assert not cell.startswith(("=", "+", "-", "@"))


def test_inventory_csv_leaves_ordinary_paths_untouched() -> None:
    text = render_inventory_csv(H.synthetic_discovery({"a,b \"q\".pas": 1}))
    rows = list(csv.reader(io.StringIO(text, newline=""), strict=True))
    assert rows[1][0] == 'a,b "q".pas'


def test_requirements_are_typed_in_the_schema(stage1) -> None:
    assert validate(stage1, SCHEMA) == []
    broken = json.loads(_dump(stage1))
    reqs = broken["dependencies"]["build"]["requirements"]
    reqs["blockers"][0].pop("code")
    assert validate(broken, SCHEMA)
    broken = json.loads(_dump(stage1))
    reqs = broken["dependencies"]["build"]["requirements"]
    reqs["compiler_evidence"]["delphi"] = "x"
    assert validate(broken, SCHEMA)
    broken = json.loads(_dump(stage1))
    broken["dependencies"]["build"]["requirements"]["blockers"].append(
        {"code": "X", "detail": "y", "extra": 1})
    assert validate(broken, SCHEMA)


def test_stage_status_follows_the_blocker_list(stage1) -> None:
    assert stage1["stage"]["status"] == "COMPLETED_WITH_BLOCKERS"
