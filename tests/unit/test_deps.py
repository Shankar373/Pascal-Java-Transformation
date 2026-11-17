"""Unit tests for dependency-graph construction (tasks D1, D2, D4).

Every reference in a scanned source must land somewhere: resolved against
the input, or unresolved with a *reason* from the closed set.  Nothing may
be silently dropped, and nothing may be invented.
"""

from __future__ import annotations

from p1.deps import build_graph
from p1.dialects import analyse_source
from p1.graph import UNRESOLVED_REASONS, RELATIONS
from p1.limits import DEFAULT_LIMITS
from p1.model import AnalysedFile, IngestedFile
from p1.plex import scan as scan_source
from p1.projects import ProjectRoot

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def _make(
    path: str,
    text: str = "",
    *,
    cls: str | None = None,
    sha: str = "ab" * 32,
) -> AnalysedFile:
    """Build an AnalysedFile the way the pipeline would for *text*."""

    if cls is None:
        cls = (
            "pascal_program" if path.endswith((".dpr", ".lpr"))
            else "pascal_include" if path.endswith(".inc")
            else "pascal_unit"
        )
    scan = scan_source(text, path=path, limits=DEFAULT_LIMITS)
    analysis = analyse_source(scan, path) if text else None
    return AnalysedFile(
        inventory=IngestedFile(path=path, sha256=sha, size=len(text)),
        cls=cls,
        class_evidence=("extension",),
        discovery_only=False,
        scan=scan,
        analysis=analysis,
    )


def _inventory_only(path: str, cls: str = "sql",
                    text: str = "select 1;\n") -> AnalysedFile:
    return AnalysedFile(
        inventory=IngestedFile(path=path, sha256="cd" * 32, size=len(text)),
        cls=cls,
        class_evidence=("extension",),
        discovery_only=True,
    )


APP_TEXT = (
    "program App;\n"
    "\n"
    "{$I shared.inc}\n"
    "\n"
    "uses\n"
    "  SysUtils, Windows, Forms, DB, Indy, ZzzUnknown, uMath, uReport;\n"
    "\n"
    "const\n"
    "  DLL = 'foo.dll';\n"
    "\n"
    "procedure Go; external 'bar.dll';\n"
    "\n"
    "begin\n"
    "  LoadLibrary('x.dll');\n"
    "end.\n"
)


def _console_build():
    analysed = [
        _make("src/App.dpr", APP_TEXT),
        _make("src/uMath.pas",
              "unit uMath;\ninterface\nimplementation\nend.\n"),
        _make("src/uReport.pas",
              "unit uReport;\ninterface\nimplementation\nend.\n"),
        _make("shared.inc", "{ helpers }\n"),
        _inventory_only("sql/orders.sql"),
    ]
    roots = [ProjectRoot(path="src/App.dpr", kind="program")]
    return build_graph(analysed, roots)


def _codes(build) -> list[str]:
    return sorted({str(d["code"]) for d in build.diagnostics})


# ---------------------------------------------------------------------------
# Application node and entry points
# ---------------------------------------------------------------------------


def test_application_node_and_entry_point_edge() -> None:
    build = _console_build()
    graph = build.graph

    assert graph.nodes["application:main"].kind == "application"
    entry = [
        e for e in graph.edges() if e.relation == "entry-point"
    ]
    assert len(entry) == 1
    assert entry[0].src == "application:main"
    assert entry[0].dst == "file:src/App.dpr"
    assert entry[0].clause == "program"
    assert entry[0].resolution == "resolved"
    assert entry[0].file == "src/App.dpr"
    assert entry[0].line == 1
    assert entry[0].column == 1


def test_origin_id_is_configurable() -> None:
    analysed = [_make("src/App.dpr", "program App;\nbegin\nend.\n")]
    roots = [ProjectRoot(path="src/App.dpr", kind="program")]
    build = build_graph(analysed, roots, origin_id="pinned-1234")
    assert "application:pinned-1234" in build.graph.nodes
    assert build.graph.unresolved() == []


def test_a_root_that_is_not_pascal_still_gets_a_node() -> None:
    analysed = [_inventory_only("conf/App.dproj", cls="pascal_project")]
    roots = [ProjectRoot(path="conf/App.dproj", kind="unknown")]
    build = build_graph(analysed, roots)

    node = build.graph.nodes["file:conf/App.dproj"]
    assert node.kind == "project"
    assert node.path == "conf/App.dproj"
    assert build.graph.stats()["edges"] == 1


def test_every_root_contributes_exactly_one_entry_point_edge() -> None:
    analysed = [
        _make("alpha/Alpha.dpr", "program Alpha;\nbegin\nend.\n"),
        _make("beta/Beta.lpr", "program Beta;\nbegin\nend.\n"),
    ]
    roots = [
        ProjectRoot(path="alpha/Alpha.dpr", kind="program"),
        ProjectRoot(path="beta/Beta.lpr", kind="program"),
    ]
    build = build_graph(analysed, roots)
    entries = [e for e in build.graph.edges()
               if e.relation == "entry-point"]
    assert sorted(e.dst for e in entries) == [
        "file:alpha/Alpha.dpr", "file:beta/Beta.lpr",
    ]


# ---------------------------------------------------------------------------
# Resolution of `uses` items
# ---------------------------------------------------------------------------


def test_present_units_resolve_to_file_nodes() -> None:
    build = _console_build()
    resolved = {
        e.dst for e in build.graph.edges() if e.resolution == "resolved"
        and e.relation == "uses"
    }
    assert {"file:src/uMath.pas", "file:src/uReport.pas"} <= resolved


def test_absent_units_resolve_to_unit_nodes_with_a_reason() -> None:
    build = _console_build()
    by_dst = {
        e.dst: e for e in build.graph.edges() if e.relation == "uses"
    }

    expectations = {
        "unit:sysutils": "rtl-unit",
        "unit:windows": "platform-unit",
        "unit:forms": "framework-unit",
        "unit:db": "database-unit",
        "unit:indy": "external-library",
        "unit:zzzunknown": "missing-unit",
    }
    for dst, reason in expectations.items():
        edge = by_dst[dst]
        assert edge.resolution == "unresolved", dst
        assert edge.reason == reason, dst
        assert reason in UNRESOLVED_REASONS
        assert edge.file == "src/App.dpr"
        assert edge.line >= 1
        assert edge.column >= 1


def test_unresolved_target_node_origins_follow_the_reason() -> None:
    build = _console_build()
    nodes = build.graph.nodes

    assert nodes["unit:sysutils"].origin == "rtl"
    assert nodes["unit:windows"].origin == "platform"
    assert nodes["unit:forms"].origin == "platform"
    assert nodes["unit:db"].origin == "external"
    assert nodes["unit:indy"].origin == "external"
    assert nodes["unit:zzzunknown"].origin == "absent"


def test_unresolved_unit_names_only_report_missing_units() -> None:
    """An RTL unit is absent *by design*; only a genuinely unknown name is
    an unresolved reference."""

    build = _console_build()
    assert build.unresolved_units == ["zzzunknown"]


def test_unresolved_references_are_announced_as_a_diagnostic() -> None:
    build = _console_build()
    assert "UNRESOLVED_UNIT_REFERENCES" in _codes(build)


def test_every_unresolved_edge_is_in_both_the_edge_list_and_the_projection() -> None:
    build = _console_build()
    graph = build.graph
    unresolved = graph.unresolved()
    assert unresolved
    for edge in unresolved:
        assert edge in graph.edges()
        assert edge.reason in UNRESOLVED_REASONS
    assert graph.stats()["unresolved"] == len(unresolved)


def test_requires_clauses_are_tracked_as_their_own_relation() -> None:
    text = (
        "package Pkg;\n"
        "requires\n"
        "  SysUtils;\n"
        "begin\n"
        "end.\n"
    )
    analysed = [_make("src/Pkg.dpk", text, cls="pascal_package")]
    roots = [ProjectRoot(path="src/Pkg.dpk", kind="package")]
    build = build_graph(analysed, roots)

    edges = [e for e in build.graph.edges() if e.relation == "requires"]
    assert len(edges) == 1
    assert edges[0].dst == "unit:sysutils"
    assert edges[0].reason == "rtl-unit"
    assert edges[0].clause == "package"


def test_clause_section_is_recorded_on_the_edge() -> None:
    build = _console_build()
    uses = [e for e in build.graph.edges() if e.relation == "uses"]
    assert {e.clause for e in uses} <= {"program", "unit", "interface",
                                        "implementation", "library",
                                        "package", "unknown"}


# ---------------------------------------------------------------------------
# Includes
# ---------------------------------------------------------------------------


def test_present_include_resolves_to_an_include_node() -> None:
    build = _console_build()
    includes = [e for e in build.graph.edges() if e.relation == "include"]
    assert len(includes) == 1
    assert includes[0].dst == "file:shared.inc"
    assert includes[0].resolution == "resolved"
    assert includes[0].text == "{$I shared.inc}"
    node = build.graph.nodes["file:shared.inc"]
    assert node.path == "shared.inc"
    assert node.origin == "input"


def test_missing_include_is_unresolved_and_diagnosed() -> None:
    analysed = [_make("src/App.dpr", "program App;\n{$I nope.inc}\n"
                                    "begin\nend.\n")]
    roots = [ProjectRoot(path="src/App.dpr", kind="program")]
    build = build_graph(analysed, roots)

    includes = [e for e in build.graph.edges() if e.relation == "include"]
    assert len(includes) == 1
    assert includes[0].resolution == "unresolved"
    assert includes[0].reason == "include-missing"
    assert includes[0].dst == "include:nope.inc"
    node = build.graph.nodes["include:nope.inc"]
    assert node.origin == "absent"
    assert "INCLUDE_NOT_FOUND" in _codes(build)


def test_include_is_resolved_case_insensitively() -> None:
    analysed = [
        _make("src/App.dpr", "program App;\n{$I SHARED.INC}\n"
                             "begin\nend.\n"),
        _make("shared.inc", "{ helpers }\n"),
    ]
    roots = [ProjectRoot(path="src/App.dpr", kind="program")]
    build = build_graph(analysed, roots)
    includes = [e for e in build.graph.edges() if e.relation == "include"]
    assert includes[0].resolution == "resolved"
    assert includes[0].dst == "file:shared.inc"


# ---------------------------------------------------------------------------
# Native libraries
# ---------------------------------------------------------------------------


def test_native_references_become_external_nodes() -> None:
    build = _console_build()
    native = [e for e in build.graph.edges() if e.relation == "external"]

    names = sorted(e.dst for e in native)
    assert names == ["native:bar.dll", "native:foo.dll", "native:x.dll"]
    for edge in native:
        assert edge.resolution == "unresolved"
        assert edge.reason == "external-library"
        assert edge.file == "src/App.dpr"
        assert build.graph.nodes[edge.dst].origin == "absent"
        assert build.graph.nodes[edge.dst].kind == "external"


def test_os_api_calls_are_not_reported_as_libraries() -> None:
    """``LoadLibrary`` is an API, not a DLL we must locate."""

    build = _console_build()
    dsts = {e.dst for e in build.graph.edges()}
    assert "native:loadlibrary" not in dsts


def test_identical_native_references_on_one_line_are_counted_once() -> None:
    text = (
        "program App;\n"
        "const A = 'foo.dll', B = 'foo.dll';\n"
        "begin\n"
        "end.\n"
    )
    analysed = [_make("src/App.dpr", text)]
    roots = [ProjectRoot(path="src/App.dpr", kind="program")]
    build = build_graph(analysed, roots)

    native = [e for e in build.graph.edges() if e.relation == "external"]
    assert len(native) == 1
    assert native[0].dst == "native:foo.dll"
    assert native[0].line == 2


def test_every_edge_endpoint_has_a_node() -> None:
    """No edge may point at something the node list does not contain."""

    build = _console_build()
    ids = set(build.graph.nodes)
    for edge in build.graph.edges():
        assert edge.src in ids, edge.src
        assert edge.dst in ids, edge.dst


# ---------------------------------------------------------------------------
# Diagnostics for malformed clauses
# ---------------------------------------------------------------------------


def test_empty_uses_clause_is_diagnosed_not_ignored() -> None:
    analysed = [_make("src/App.dpr", "program App;\nuses;\nbegin\nend.\n")]
    roots = [ProjectRoot(path="src/App.dpr", kind="program")]
    build = build_graph(analysed, roots)

    assert "USES_EMPTY" in _codes(build)
    empty = [d for d in build.diagnostics if d["code"] == "USES_EMPTY"][0]
    assert empty["file"] == "src/App.dpr"
    assert empty["line"] == 2
    # The clause contributed no edge, and that is stated rather than silent.
    assert not [e for e in build.graph.edges() if e.relation == "uses"]


def test_ambiguous_unit_resolution_is_reported_with_a_deterministic_choice() -> None:
    analysed = [
        _make("src/App.dpr", "program App;\nuses uData;\nbegin\nend.\n"),
        _make("src/uData.pas", "unit uData;\ninterface\nend.\n"),
        _make("lib/uData.pas", "unit uData;\ninterface\nend.\n"),
    ]
    roots = [ProjectRoot(path="src/App.dpr", kind="program")]
    build = build_graph(analysed, roots)

    assert "AMBIGUOUS_UNIT_RESOLUTION" in _codes(build)
    resolved = [
        e for e in build.graph.edges()
        if e.relation == "uses" and e.resolution == "resolved"
    ]
    # Sorted candidates: the first one alphabetically wins, every run.
    assert [e.dst for e in resolved] == ["file:lib/uData.pas"]


# ---------------------------------------------------------------------------
# Scope: only Pascal source contributes nodes
# ---------------------------------------------------------------------------


def test_inventory_only_files_never_become_graph_nodes() -> None:
    build = _console_build()
    node_ids = set(build.graph.nodes)
    assert not any(n.startswith("file:sql/") for n in node_ids)
    assert "file:README.md" not in node_ids


def test_sources_with_no_references_contribute_no_edges() -> None:
    analysed = [
        _make("src/App.dpr", "program App;\nuses uMath;\nbegin\nend.\n"),
        _make("src/uMath.pas", ""),
    ]
    roots = [ProjectRoot(path="src/App.dpr", kind="program")]
    build = build_graph(analysed, roots)

    uses = [e for e in build.graph.edges() if e.relation == "uses"]
    assert [e.dst for e in uses] == ["file:src/uMath.pas"]


def test_a_source_that_could_not_be_scanned_still_gets_its_node() -> None:
    """``scan is None`` (too large / unreadable) must not remove the file."""

    item = AnalysedFile(
        inventory=IngestedFile(path="src/Huge.pas", sha256="ef" * 32,
                               size=10 ** 9),
        cls="pascal_unit",
        class_evidence=("extension",),
        analysis_blocker="too-large",
        scan=None,
        analysis=None,
    )
    build = build_graph([item], [])

    assert "file:src/Huge.pas" in build.graph.nodes
    assert build.graph.nodes["file:src/Huge.pas"].sha256 == "ef" * 32
    assert build.graph.stats()["edges"] == 0


def test_empty_input_still_produces_a_valid_graph() -> None:
    build = build_graph([], [])
    stats = build.graph.stats()
    assert stats["nodes"] == 1  # only the application node
    assert stats["edges"] == 0
    assert build.unresolved_units == []
    assert build.graph.to_dict()["edges"] == []


def test_diagnostics_are_serialisable() -> None:
    import json

    build = _console_build()
    json.dumps(build.diagnostics, sort_keys=True)
    for diagnostic in build.diagnostics:
        assert "code" in diagnostic
        assert diagnostic["code"]


def test_relations_used_are_from_the_closed_set() -> None:
    build = _console_build()
    for edge in build.graph.edges():
        assert edge.relation in RELATIONS
