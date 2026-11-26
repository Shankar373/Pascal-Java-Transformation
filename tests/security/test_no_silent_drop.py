"""Silent-drop guard (task E4, IR invariant I2).

Nothing an input contains may disappear without a trace:

* every inventoried file is in the manifest, with its digest and a
  capability status;
* syntax the lexer cannot make sense of becomes a diagnostic with a
  location, not a shrug;
* every unresolved dependency edge is kept in ``edges`` **and** projected
  into ``unresolved``, and both ends of it exist as nodes;
* prefixes that are deliberately excluded are announced, not skipped
  quietly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from conftest import CONSOLE_APP, read_json, run_pipeline, write_tree

from p1.classify import INVENTORY_ONLY_CLASSES
from p1.limits import Limits

PASCAL_CLASSES = {
    "pascal_program", "pascal_unit", "pascal_include", "pascal_package",
}


def _manifest(outdir: Path) -> dict[str, Any]:
    return read_json(outdir / "application-manifest.json")


def _graph(outdir: Path) -> dict[str, Any]:
    return read_json(outdir / "dependency-graph.json")


def _by_path(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["path"]: f for f in manifest["files"]}


def _edge_key(edge: dict[str, Any]) -> tuple[Any, ...]:
    return (
        edge["from"], edge["to"], edge["line"], edge["column"],
        edge.get("reason", ""), edge["relation"],
    )


# ---------------------------------------------------------------------------
# Nothing is dropped from the inventory
# ---------------------------------------------------------------------------


def test_every_input_file_appears_in_the_manifest(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    manifest = _manifest(out)

    paths = [f["path"] for f in manifest["files"]]
    assert sorted(paths) == sorted(CONSOLE_APP), (
        "the manifest lost or invented files"
    )
    assert len(paths) == len(set(paths)), "duplicate manifest entries"


def test_every_manifest_entry_is_preserved_and_statused(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)

    for entry in _manifest(out)["files"]:
        assert entry["preserved"] is True, entry["path"]
        assert entry["capability_status"] in (
            "SUPPORTED", "PARTIAL", "UNKNOWN", "UNSUPPORTED", "UNAVAILABLE"
        ), entry["path"]
        assert len(entry["sha256"]) == 64, entry["path"]
        assert entry["class_evidence"], entry["path"]


def test_digests_match_the_files_on_disk(
    app_tree: Path, tmp_path: Path
) -> None:
    """P1 never rewrites an input: the recorded digest is the file's."""

    from p1.hashing import sha256_file

    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    manifest = _manifest(out)

    for entry in manifest["files"]:
        original = app_tree / Path(*entry["path"].split("/"))
        assert original.is_file(), entry["path"]
        assert entry["sha256"] == sha256_file(original), entry["path"]


def test_non_pascal_assets_are_inventoried_but_not_parsed(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    entries = _by_path(_manifest(out))

    inventory_only = [
        "README.md", "sql/orders.sql", "data/notes.dat", "data/empty.txt",
        "src/MiniApp.dproj",
    ]
    for path in inventory_only:
        entry = entries[path]
        assert entry["preserved"] is True
        # None of these is Pascal source, so none may claim a Pascal scan;
        # the project file is analysed by projects.parse_project_file.
        assert entry["class"] not in PASCAL_CLASSES, path
    assert entries["src/MiniApp.dproj"]["class"] == "pascal_project"
    assert entries["sql/orders.sql"]["class"] in INVENTORY_ONLY_CLASSES


def test_pascal_sources_are_marked_as_analysed(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    entries = _by_path(_manifest(out))

    for path, entry in entries.items():
        if entry["class"] in PASCAL_CLASSES:
            assert entry.get("analysis_blocker") in (None, ""), path


# ---------------------------------------------------------------------------
# Unknown syntax becomes a located diagnostic
# ---------------------------------------------------------------------------


def test_unknown_syntax_produces_a_diagnostic_with_file_line_column(
    tmp_path: Path,
) -> None:
    tree = write_tree(tmp_path / "bad", {
        "src/Bad.pas": (
            "unit Bad;\n"
            "interface\n"
            "const S = 'never closed\n"
            "implementation\n"
            "end.\n"
        ),
    })
    out = tmp_path / "out"
    run_pipeline(tree, out)

    located = [
        d for d in _manifest(out)["diagnostics"]
        if d["code"] == "UNTERMINATED_STRING"
    ]
    assert located, "the lexer swallowed an unterminated literal"
    diagnostic = located[0]
    assert diagnostic["file"] == "src/Bad.pas"
    assert isinstance(diagnostic["line"], int) and diagnostic["line"] >= 1
    assert isinstance(diagnostic["column"], int) and diagnostic["column"] >= 1
    assert diagnostic["severity"] in ("info", "warning", "error")
    assert diagnostic["message"]


def test_unterminated_comment_is_located(tmp_path: Path) -> None:
    tree = write_tree(tmp_path / "bad", {
        "src/Bad.pas": "unit Bad;\ninterface\n{ never closed\nend.\n",
    })
    out = tmp_path / "out"
    run_pipeline(tree, out)

    located = [
        d for d in _manifest(out)["diagnostics"]
        if d["code"] == "UNTERMINATED_COMMENT"
    ]
    assert located
    assert located[0]["file"] == "src/Bad.pas"
    assert located[0]["line"] == 3


def test_a_file_is_inventoried_even_when_it_cannot_be_analysed(
    tmp_path: Path,
) -> None:
    tree = write_tree(tmp_path / "big", {
        "src/Big.pas": "unit Big;\n" + ("{ padding }\n" * 40),
    })
    out = tmp_path / "out"
    run_pipeline(tree, out, limits=Limits(max_source_bytes=32))

    entry = _by_path(_manifest(out))["src/Big.pas"]
    assert entry["analysis_blocker"] == "too-large"
    assert entry["preserved"] is True
    assert entry["capability_status"] == "PARTIAL"
    assert len(entry["sha256"]) == 64


def test_every_diagnostic_code_is_from_a_known_vocabulary(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    for diagnostic in _manifest(out)["diagnostics"]:
        code = diagnostic["code"]
        assert isinstance(code, str) and code, diagnostic
        # Upper-case, underscore-separated, no spaces: the convention every
        # diagnostic in the tool follows.
        assert code == code.upper(), code
        assert " " not in code, code
        assert code.replace("_", "").isalnum(), code


# ---------------------------------------------------------------------------
# Unresolved dependencies are preserved
# ---------------------------------------------------------------------------


def test_unresolved_edges_are_in_both_the_edge_list_and_the_projection(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    graph = _graph(out)

    unresolved_in_edges = {
        _edge_key(e) for e in graph["edges"] if e["resolution"] != "resolved"
    }
    projected = {_edge_key(e) for e in graph["unresolved"]}

    assert unresolved_in_edges, "the fixture must produce unresolved edges"
    assert unresolved_in_edges == projected
    assert graph["stats"]["unresolved"] == len(graph["unresolved"])
    assert graph["stats"]["resolved"] + graph["stats"]["unresolved"] == (
        graph["stats"]["edges"]
    )


def test_every_edge_endpoint_exists_as_a_node(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    graph = _graph(out)
    node_ids = {n["id"] for n in graph["nodes"]}

    for edge in graph["edges"]:
        assert edge["from"] in node_ids, edge
        assert edge["to"] in node_ids, edge


def test_unresolved_edges_carry_a_reason_and_a_location(
    app_tree: Path, tmp_path: Path
) -> None:
    from p1.graph import UNRESOLVED_REASONS

    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    graph = _graph(out)

    assert graph["unresolved"], "the fixture must produce unresolved edges"
    for edge in graph["unresolved"]:
        assert edge["reason"] in UNRESOLVED_REASONS, edge
        assert edge["file"], edge
        assert edge["line"] >= 1 and edge["column"] >= 1, edge


def test_a_missing_unit_is_never_silently_omitted(tmp_path: Path) -> None:
    tree = write_tree(tmp_path / "gap", {
        "src/App.dpr": (
            "program App;\n"
            "uses SysUtils, TotallyAbsentUnit;\n"
            "begin\n"
            "end.\n"
        ),
    })
    out = tmp_path / "out"
    run_pipeline(tree, out)
    graph = _graph(out)

    missing = [
        e for e in graph["unresolved"]
        if e.get("reason") == "missing-unit" and e["to"] == "unit:totallyabsentunit"
    ]
    assert len(missing) == 1
    assert missing[0]["file"] == "src/App.dpr"
    assert missing[0]["line"] == 2


# ---------------------------------------------------------------------------
# Exclusions are announced
# ---------------------------------------------------------------------------


def test_excluded_prefixes_are_announced_not_skipped_quietly(
    tmp_path: Path,
) -> None:
    tree = write_tree(tmp_path / "vcs", {
        ".git/config": "[core]\nrepositoryformatversion = 0\n",
        "src/App.dpr": "program App;\nbegin\nend.\n",
    })
    out = tmp_path / "out"
    # kind is pinned: a directory containing ".git" would otherwise be
    # auto-detected as a Git repository and refused as a broken one.
    run_pipeline(tree, out, kind="directory")
    manifest = _manifest(out)

    paths = [f["path"] for f in manifest["files"]]
    assert not any(p.startswith(".git") for p in paths), paths
    assert "src/App.dpr" in paths

    codes = {d["code"] for d in manifest["diagnostics"]}
    assert "PATH_EXCLUDED_FROM_INVENTORY" in codes


def test_no_staging_or_temporary_path_leaks_into_any_artefact(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)

    for name in ("application-manifest.json", "dependency-graph.json",
                 "discovery-report.md"):
        text = (out / name).read_text(encoding="utf-8")
        lowered = text.lower()
        assert "p1-stage-" not in lowered, name
        assert str(tmp_path).lower() not in lowered, name
        assert "appdata" not in lowered, name


def test_the_source_tree_is_untouched(
    app_tree: Path, tmp_path: Path
) -> None:
    before = sorted(p.name for p in app_tree.rglob("*"))
    run_pipeline(app_tree, tmp_path / "out")
    after = sorted(p.name for p in app_tree.rglob("*"))
    assert before == after
