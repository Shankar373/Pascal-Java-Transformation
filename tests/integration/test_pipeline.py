"""End-to-end pipeline tests on the representative fixtures (plan §7).

These assert the *shape of the answer* P1 is supposed to give: which
application was found, what dialect and profile it needs, what it depends
on, and where the tool had to say "I do not know".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from conftest import (
    CONSOLE_APP,
    artifact_bytes,
    diagnostic_codes,
    make_zip,
    read_json,
    run_pipeline,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load(out: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    return (
        read_json(out / "application-manifest.json"),
        read_json(out / "dependency-graph.json"),
    )


def _root(manifest: dict[str, Any]) -> dict[str, Any]:
    roots = manifest["project_roots"]
    assert len(roots) == 1, roots
    return roots[0]


def _blockers(manifest: dict[str, Any]) -> list[str]:
    return [b["code"] for b in manifest["build_requirements"]["blockers"]]


def _capability_statuses(manifest: dict[str, Any]) -> set[str]:
    return {s["status"] for s in manifest["capability_states"]}


# ---------------------------------------------------------------------------
# The console application
# ---------------------------------------------------------------------------


def test_console_app_is_discovered_end_to_end(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    result = run_pipeline(app_tree, out)

    assert set(result.outputs) == {"manifest", "graph", "report"}
    for path in result.outputs.values():
        assert Path(path).is_file()
    assert result.staged is False, "a directory input needs no staging"

    manifest, graph = _load(out)
    assert manifest["classification"] == {
        "binary": 1,
        "documentation": 2,
        "pascal_include": 1,
        "pascal_program": 1,
        "pascal_project": 1,
        "pascal_unit": 3,
        "sql": 1,
    }
    assert sum(manifest["classification"].values()) == len(CONSOLE_APP)
    assert graph["stats"]["edges"] == 14


def test_console_app_root_and_entry_point(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    root = _root(read_json(out / "application-manifest.json"))

    assert root["path"] == "src/MiniApp.dpr"
    assert root["kind"] == "program"
    assert root["primary"] is True
    assert root["status"] == "SUPPORTED"

    entry = root["entry_points"][0]
    assert entry["declared_name"] == "MiniApp"
    assert entry["status"] == "SUPPORTED"
    assert entry["location"] == "src/MiniApp.dpr:1:9"
    assert entry["kind"] == "program"

    assert any(e["source"] == "MiniApp.dproj" for e in root["evidence"])


def test_console_app_profile_is_complete(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    manifest = read_json(out / "application-manifest.json")

    profiles = {p["root"]: p for p in manifest["profiles"]}
    profile = profiles["src/MiniApp.dpr"]
    assert profile["mode"] == "objfpc"
    assert profile["defines"] == [
        "CONDITIONALEXPRESSIONS", "DEBUG", "VERBOSE",
    ]
    assert profile["platform"] == "Win32"
    assert profile["unit_search_paths"] == ["lib", "src"]
    assert profile["app_type"] == "console"
    assert profile["output_kind"] == "executable"
    # Nothing was invented for checks no directive or project file states.
    assert profile["range_check"] == "not-specified"
    assert profile["overflow_check"] == "not-specified"
    assert profile["string_model"] == "not-specified"
    assert set(profile["sources"]) == {
        "src/MiniApp.dpr", "src/MiniApp.dproj",
    }
    assert profile["evidence"], "every profile field must cite its source"


def test_console_app_build_requirements(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    requirements = read_json(out / "application-manifest.json")[
        "build_requirements"
    ]

    assert requirements["status"] == "PARTIAL"
    assert requirements["compiler"] == "fpc"
    assert requirements["blockers"] == []
    assert requirements["flags"] == [
        "-Fulib", "-Fusrc", "-Mobjfpc",
        "-dCONDITIONALEXPRESSIONS", "-dDEBUG", "-dVERBOSE",
    ]
    assert requirements["unit_search_paths"] == ["lib", "src"]
    assert requirements["modes"] == ["objfpc"]
    # Discovery never ran a compiler, and the evidence says so.
    assert "no compiler was invoked" in requirements["compiler_evidence"][
        "note"
    ]
    assert "fpc" in requirements["compiler_evidence"]
    assert "delphi" in requirements["compiler_evidence"]


def test_console_app_shape_and_dialects(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    manifest = read_json(out / "application-manifest.json")

    shapes = {s["root"]: s for s in manifest["shapes"]}
    assert shapes["src/MiniApp.dpr"]["shape"] == "console"
    assert shapes["src/MiniApp.dpr"]["confidence"] == "high"
    assert shapes["src/MiniApp.dpr"]["status"] == "SUPPORTED"

    dialects = {d["file"]: d for d in manifest["dialects"]}
    assert dialects["src/MiniApp.dpr"]["dialect"] == "fpc"
    assert dialects["src/MiniApp.dpr"]["mode"] == "objfpc"
    assert dialects["src/MiniApp.dpr"]["confidence"] == "high"
    assert dialects["src/uMath.pas"]["mode"] == "objfpc"
    # No directive and a neutral extension: nothing to claim.
    assert dialects["src/uData.pas"]["dialect"] == "unknown"
    assert dialects["src/uData.pas"]["mode"] == "unknown"
    assert dialects["shared.inc"]["source_kind"] == "unknown"

    for payload in dialects.values():
        assert payload["name_mismatch"] is False


def test_console_app_database_and_sql(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    manifest = read_json(out / "application-manifest.json")

    technologies = {f["technology"] for f in manifest["database"]}
    assert technologies == {"dbExpress", "generic (TDataSet)"}
    for finding in manifest["database"]:
        assert finding["status"] == "PARTIAL"
        assert finding["evidence"]

    assert len(manifest["sql_files"]) == 1
    sql = manifest["sql_files"][0]
    assert sql["path"] == "sql/orders.sql"
    assert sql["dialect"] == "sqlite"
    assert sql["status"] == "PARTIAL"
    assert sql["evidence"]


def test_console_app_native_and_os_dependencies(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    manifest = read_json(out / "application-manifest.json")

    names = sorted(f["name"] for f in manifest["native_libs"])
    assert names == ["foo.dll", "kernel32.dll", "x.dll"]
    for library in manifest["native_libs"]:
        assert library["kind"] == "dll"
        assert library["status"] == "PARTIAL"
        assert library["evidence"]

    platforms = {d["platform"] for d in manifest["os_dependencies"]}
    assert platforms == {"windows"}
    assert manifest["os_dependencies"][0]["status"] == "PARTIAL"


def test_console_app_dependency_graph(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    _, graph = _load(out)

    assert graph["stats"] == {
        "duplicate_edges_ignored": 0,
        "edges": 14,
        "nodes": 12,
        "resolved": 6,
        "unresolved": 8,
    }

    node_ids = {n["id"] for n in graph["nodes"]}
    assert node_ids == {
        "application:main",
        "file:shared.inc",
        "file:src/MiniApp.dpr",
        "file:src/uData.pas",
        "file:src/uMath.pas",
        "file:src/uReport.pas",
        "native:foo.dll",
        "native:kernel32.dll",
        "native:x.dll",
        "unit:db",
        "unit:sqlexpr",
        "unit:sysutils",
    }

    entries = [e for e in graph["edges"] if e["relation"] == "entry-point"]
    assert [e["to"] for e in entries] == ["file:src/MiniApp.dpr"]

    includes = [e for e in graph["edges"] if e["relation"] == "include"]
    assert [e["to"] for e in includes] == ["file:shared.inc"]
    assert includes[0]["resolution"] == "resolved"

    resolved_uses = {
        e["to"] for e in graph["edges"]
        if e["relation"] == "uses" and e["resolution"] == "resolved"
    }
    assert resolved_uses == {
        "file:src/uData.pas", "file:src/uMath.pas", "file:src/uReport.pas",
    }

    reasons = {
        e["to"]: e.get("reason")
        for e in graph["edges"] if e["resolution"] == "unresolved"
    }
    assert reasons["unit:sysutils"] == "rtl-unit"
    assert reasons["unit:db"] == "database-unit"
    assert reasons["unit:sqlexpr"] == "database-unit"
    assert reasons["native:foo.dll"] == "external-library"


def test_console_app_reports_the_compiler_signal_conflict(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    manifest = read_json(out / "application-manifest.json")

    assert "COMPILER_SIGNAL_CONFLICT" in diagnostic_codes(manifest)
    conflict = [
        d for d in manifest["diagnostics"]
        if d["code"] == "COMPILER_SIGNAL_CONFLICT"
    ][0]
    assert conflict["severity"] == "warning"
    assert conflict["message"]


def test_console_app_capability_states_are_complete(
    app_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(app_tree, out)
    manifest = read_json(out / "application-manifest.json")
    states = manifest["capability_states"]

    assert len(states) == 40
    for state in states:
        assert set(state) == {"construct", "mode", "platform", "status",
                              "evidence"}
        assert state["status"] in _capability_statuses(manifest)
        assert state["evidence"] or state["status"] in (
            "UNSUPPORTED", "UNAVAILABLE", "UNKNOWN"
        )


# ---------------------------------------------------------------------------
# The ambiguous application
# ---------------------------------------------------------------------------


def test_ambiguous_layout_reports_unknown_not_a_guess(
    ambiguous_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(ambiguous_tree, out)
    manifest, graph = _load(out)

    roots = manifest["project_roots"]
    assert len(roots) == 2
    for root in roots:
        assert root["status"] == "UNKNOWN"
        assert root["primary"] is False

    assert "MULTIPLE_PROJECT_ROOTS" in diagnostic_codes(manifest)
    assert "AMBIGUOUS_PROJECT_ROOT" in _blockers(manifest)

    # Both entry-point *files* exist, so the edges are resolved; only the
    # question of which one is primary is unknown.
    entries = [e for e in graph["edges"] if e["relation"] == "entry-point"]
    assert len(entries) == 2
    assert all(e["resolution"] == "resolved" for e in entries)
    assert graph["stats"]["unresolved"] == 0

    assert manifest["classification"] == {
        "pascal_program": 2, "pascal_project": 2,
    }
    # An ambiguous root still produces a documented (PARTIAL) requirement set.
    assert manifest["build_requirements"]["status"] == "PARTIAL"


# ---------------------------------------------------------------------------
# The GUI application
# ---------------------------------------------------------------------------


def test_gui_app_is_detected_and_blocked(
    gui_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(gui_tree, out)
    manifest, graph = _load(out)

    root = _root(manifest)
    assert root["path"] == "lcl/App.lpr"
    assert root["primary"] is True
    assert root["status"] == "SUPPORTED"

    shapes = {s["root"]: s for s in manifest["shapes"]}
    assert shapes["lcl/App.lpr"]["shape"] == "gui_lcl"
    assert shapes["lcl/App.lpr"]["confidence"] == "high"
    assert shapes["lcl/App.lpr"]["status"] == "SUPPORTED"
    assert any("lcl" in str(e["evidence"]) for e in
               shapes["lcl/App.lpr"]["evidence"])

    assert "GUI_SHAPE_DETECTED" in _blockers(manifest)
    assert any(
        "gui_lcl" in b["detail"] for b in manifest["build_requirements"][
            "blockers"
        ]
    )


def test_gui_app_framework_gaps_are_unresolved_edges(
    gui_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(gui_tree, out)
    _, graph = _load(out)

    assert graph["stats"] == {
        "duplicate_edges_ignored": 0,
        "edges": 9,
        "nodes": 9,
        "resolved": 2,
        "unresolved": 7,
    }

    framework_gaps = {
        e["to"] for e in graph["unresolved"]
        if e.get("reason") == "framework-unit"
    }
    assert framework_gaps == {
        "unit:controls", "unit:forms", "unit:graphics", "unit:interfaces",
    }
    for edge in graph["unresolved"]:
        assert edge["file"].startswith("lcl/")
        assert edge["line"] >= 1


def test_gui_app_profile_and_requirements(
    gui_tree: Path, tmp_path: Path
) -> None:
    out = tmp_path / "out"
    run_pipeline(gui_tree, out)
    manifest = read_json(out / "application-manifest.json")

    profile = {p["root"]: p for p in manifest["profiles"]}["lcl/App.lpr"]
    assert profile["mode"] == "objfpc"
    assert profile["app_type"] == "not-specified"
    assert manifest["build_requirements"]["flags"] == ["-Mobjfpc"]
    assert manifest["build_requirements"]["compiler"] == "fpc"
    assert manifest["build_requirements"]["status"] == "PARTIAL"


# ---------------------------------------------------------------------------
# Staging lifecycle
# ---------------------------------------------------------------------------


def test_zip_input_leaves_no_staging_directory(
    app_tree: Path, tmp_path: Path
) -> None:
    archive = make_zip(
        tmp_path / "app.zip",
        [(path, (app_tree / Path(*path.split("/"))).read_bytes())
         for path in sorted(CONSOLE_APP)],
    )
    out = tmp_path / "out"
    result = run_pipeline(archive, out, kind="zip")

    assert result.staged is True
    leftovers = sorted(
        p.name for p in Path(result.outdir).parent.glob("p1-stage-*")
    )
    assert leftovers == [], leftovers

    manifest, _ = _load(out)
    assert manifest["source"]["kind"] == "zip"
    assert manifest["source"]["entry_count"] == len(CONSOLE_APP)


def test_zip_and_directory_inventories_agree(
    app_tree: Path, tmp_path: Path
) -> None:
    """The container is transport: it must not change what is discovered."""

    archive = make_zip(
        tmp_path / "app.zip",
        [(path, (app_tree / Path(*path.split("/"))).read_bytes())
         for path in sorted(CONSOLE_APP)],
    )
    from_zip = tmp_path / "from-zip"
    from_dir = tmp_path / "from-dir"
    run_pipeline(archive, from_zip, kind="zip")
    run_pipeline(app_tree, from_dir)

    zip_manifest, zip_graph = _load(from_zip)
    dir_manifest, dir_graph = _load(from_dir)

    assert zip_manifest["classification"] == dir_manifest["classification"]
    assert zip_manifest["build_requirements"] == (
        dir_manifest["build_requirements"]
    )
    assert zip_manifest["shapes"] == dir_manifest["shapes"]
    assert zip_manifest["capability_states"] == (
        dir_manifest["capability_states"]
    )
    assert zip_graph == dir_graph

    zip_files = {f["path"]: f for f in zip_manifest["files"]}
    dir_files = {f["path"]: f for f in dir_manifest["files"]}
    assert set(zip_files) == set(dir_files)
    for path in zip_files:
        assert zip_files[path]["sha256"] == dir_files[path]["sha256"], path
        assert zip_files[path]["class"] == dir_files[path]["class"], path
        # A ZIP carries DOS times; a directory walk carries none.
        assert zip_files[path].get("source_timestamp") is not None
