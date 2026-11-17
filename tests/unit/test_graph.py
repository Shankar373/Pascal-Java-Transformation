"""Unit tests for the dependency graph model (task D2).

Three invariants are under test:

* an edge cannot exist without a source file and a span;
* unresolved edges are data — kept in ``edges`` *and* projected into
  ``unresolved``, never dropped;
* serialisation is canonical, so two runs over the same facts are
  byte-identical.
"""

from __future__ import annotations

import pytest

from p1.graph import (
    RELATIONS,
    RESOLUTIONS,
    UNRESOLVED_REASONS,
    DependencyGraph,
    Edge,
    Node,
)

# ---------------------------------------------------------------------------
# Construction guards
# ---------------------------------------------------------------------------


def _edge(**overrides: object) -> Edge:
    base: dict[str, object] = {
        "src": "file:src/a.pas",
        "dst": "unit:sysutils",
        "relation": "uses",
        "clause": "interface",
        "file": "src/a.pas",
        "line": 3,
        "column": 7,
        "text": "SysUtils",
    }
    base.update(overrides)
    return Edge(**base)  # type: ignore[arg-type]


def test_edge_requires_a_source_file_and_a_span() -> None:
    edge = _edge()
    assert edge.file == "src/a.pas"
    assert edge.line == 3
    assert edge.column == 7
    assert edge.resolution == "resolved"
    assert edge.reason == ""


def test_invalid_resolution_is_refused() -> None:
    graph = DependencyGraph()
    with pytest.raises(ValueError):
        graph.add_edge(_edge(resolution="maybe"))


def test_unresolved_edge_needs_a_reason_from_the_closed_set() -> None:
    graph = DependencyGraph()
    with pytest.raises(ValueError):
        graph.add_edge(_edge(resolution="unresolved", reason="who-knows"))


@pytest.mark.parametrize("reason", UNRESOLVED_REASONS)
def test_every_documented_reason_is_accepted(reason: str) -> None:
    graph = DependencyGraph()
    assert graph.add_edge(
        _edge(resolution="unresolved", reason=reason)
    ) is True


def test_a_resolved_edge_must_not_carry_an_unresolved_reason() -> None:
    graph = DependencyGraph()
    with pytest.raises(ValueError):
        graph.add_edge(_edge(reason="missing-unit"))


def test_vocabulary_is_closed() -> None:
    assert set(RESOLUTIONS) == {"resolved", "unresolved"}
    assert "entry-point" in RELATIONS
    assert "missing-unit" in UNRESOLVED_REASONS
    assert tuple(sorted(UNRESOLVED_REASONS)) == UNRESOLVED_REASONS


# ---------------------------------------------------------------------------
# De-duplication and counting
# ---------------------------------------------------------------------------


def test_exact_duplicate_is_counted_not_repeated() -> None:
    graph = DependencyGraph()
    assert graph.add_edge(_edge()) is True
    assert graph.add_edge(_edge()) is False
    assert graph.stats()["edges"] == 1
    assert graph.stats()["duplicate_edges_ignored"] == 1


def test_edges_differing_only_by_span_are_distinct() -> None:
    graph = DependencyGraph()
    assert graph.add_edge(_edge()) is True
    assert graph.add_edge(_edge(line=4)) is True
    assert graph.stats()["edges"] == 2


def test_edges_differing_only_by_reason_are_distinct() -> None:
    graph = DependencyGraph()
    graph.add_edge(_edge(resolution="unresolved", reason="rtl-unit"))
    graph.add_edge(_edge(resolution="unresolved", reason="missing-unit"))
    assert graph.stats()["edges"] == 2


def test_stats_arithmetic() -> None:
    graph = DependencyGraph()
    graph.add_node(Node(id="file:src/a.pas", kind="unit", path="src/a.pas"))
    graph.add_edge(_edge(resolution="unresolved", reason="rtl-unit"))
    graph.add_edge(_edge(dst="unit:forms",
                         resolution="unresolved", reason="framework-unit"))
    graph.add_edge(_edge(dst="file:src/b.pas", resolution="resolved"))

    stats = graph.stats()
    assert stats["nodes"] == 1
    assert stats["edges"] == 3
    assert stats["resolved"] == 1
    assert stats["unresolved"] == 2
    assert stats["resolved"] + stats["unresolved"] == stats["edges"]


# ---------------------------------------------------------------------------
# Canonical ordering
# ---------------------------------------------------------------------------


def test_edges_are_sorted_by_their_identity_key() -> None:
    graph = DependencyGraph()
    graph.add_edge(_edge(dst="unit:zeta"))
    graph.add_edge(_edge(dst="unit:alpha"))
    graph.add_edge(_edge(dst="unit:middle", line=9))

    keys = [e.key() for e in graph.edges()]
    assert keys == sorted(keys)
    assert graph.edges()[0].key() == (
        "file:src/a.pas", "unit:alpha", "uses", "interface",
        "src/a.pas", 3, 7, "",
    )


def test_unresolved_is_a_projection_of_edges_not_a_second_store() -> None:
    graph = DependencyGraph()
    graph.add_edge(_edge(resolution="unresolved", reason="rtl-unit"))
    graph.add_edge(_edge(dst="file:src/b.pas", resolution="resolved"))

    unresolved = graph.unresolved()
    assert len(unresolved) == 1
    assert unresolved[0] in graph.edges()
    assert all(e.resolution == "unresolved" for e in unresolved)


def test_unresolved_is_deterministic_across_insertion_orders() -> None:
    first = DependencyGraph()
    first.add_edge(_edge(dst="unit:a", resolution="unresolved",
                         reason="rtl-unit"))
    first.add_edge(_edge(dst="unit:b", resolution="unresolved",
                         reason="missing-unit"))

    second = DependencyGraph()
    second.add_edge(_edge(dst="unit:b", resolution="unresolved",
                          reason="missing-unit"))
    second.add_edge(_edge(dst="unit:a", resolution="unresolved",
                          reason="rtl-unit"))

    assert [e.key() for e in first.edges()] == [e.key() for e in second.edges()]
    assert first.to_dict() == second.to_dict()


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------


def test_add_node_fills_in_details_but_never_loses_them() -> None:
    graph = DependencyGraph()
    bare = Node(id="file:src/a.pas", kind="unit")
    rich = Node(id="file:src/a.pas", kind="unit", path="src/a.pas",
                sha256="ab" * 32)

    assert graph.add_node(bare) is bare
    # A placeholder is upgraded by the first node that carries a path...
    assert graph.add_node(rich) is rich
    assert graph.nodes["file:src/a.pas"].path == "src/a.pas"
    # ...and is never downgraded back to a bare one.
    assert graph.add_node(bare) is rich
    assert graph.nodes["file:src/a.pas"].path == "src/a.pas"


def test_add_node_upgrades_a_placeholder_with_a_real_path() -> None:
    graph = DependencyGraph()
    bare = Node(id="file:src/a.pas", kind="unit")
    rich = Node(id="file:src/a.pas", kind="unit", path="src/a.pas",
                sha256="ab" * 32)
    graph.add_node(rich)
    assert graph.add_node(bare) is rich
    assert graph.nodes["file:src/a.pas"].path == "src/a.pas"


def test_node_as_dict_omits_empty_optional_fields() -> None:
    minimal = Node(id="unit:sysutils", kind="external", origin="rtl").as_dict()
    assert minimal == {"id": "unit:sysutils", "kind": "external",
                       "origin": "rtl"}

    full = Node(id="file:src/a.pas", kind="unit", path="src/a.pas",
                sha256="ab" * 32).as_dict()
    assert set(full) == {"id", "kind", "path", "sha256"}


def test_node_origin_is_only_emitted_when_it_is_not_input() -> None:
    assert "origin" not in Node(id="x", kind="unit").as_dict()
    assert Node(id="x", kind="unit", origin="absent").as_dict()["origin"] == (
        "absent"
    )


def test_edge_as_dict_omits_empty_optional_fields() -> None:
    minimal = _edge().as_dict()
    assert set(minimal) == {
        "clause", "column", "file", "from", "line", "relation",
        "resolution", "text", "to",
    }
    assert minimal["text"] == "SysUtils"

    rich = _edge(
        text="SysUtils",
        resolution="unresolved",
        reason="rtl-unit",
        conditional=("MSWINDOWS",),
    ).as_dict()
    assert rich["text"] == "SysUtils"
    assert rich["reason"] == "rtl-unit"
    assert rich["conditional"] == ["MSWINDOWS"]


def test_edge_key_excludes_the_fields_it_must_not() -> None:
    """Identity is *where* the reference is, not how it was spelled."""

    a = _edge(text="SysUtils")
    b = _edge(text="sysutils")
    assert a.key() == b.key()
    assert a.key() != _edge(line=99).key()


# ---------------------------------------------------------------------------
# Serialisation
# ---------------------------------------------------------------------------


def test_to_dict_has_the_documented_top_level_keys() -> None:
    graph = DependencyGraph()
    graph.add_node(Node(id="file:src/a.pas", kind="unit", path="src/a.pas"))
    graph.add_edge(_edge(resolution="unresolved", reason="rtl-unit"))

    payload = graph.to_dict()
    assert set(payload) == {
        "edges", "nodes", "schema_version", "stats", "unresolved",
    }
    assert payload["schema_version"] == "p1.dependency-graph/1.0"


def test_unresolved_in_the_payload_is_the_same_objects_as_in_edges() -> None:
    graph = DependencyGraph()
    graph.add_edge(_edge(resolution="unresolved", reason="rtl-unit"))
    graph.add_edge(_edge(dst="file:src/b.pas", resolution="resolved"))

    payload = graph.to_dict()
    unresolved_keys = [e["to"] for e in payload["unresolved"]]
    assert unresolved_keys == ["unit:sysutils"]
    assert len(payload["edges"]) == 2


def test_to_dict_is_stable_and_json_safe() -> None:
    import json

    graph = DependencyGraph()
    graph.add_node(Node(id="file:src/a.pas", kind="unit", path="src/a.pas"))
    graph.add_edge(_edge(resolution="unresolved", reason="rtl-unit"))

    first = json.dumps(graph.to_dict(), sort_keys=True)
    second = json.dumps(graph.to_dict(), sort_keys=True)
    assert first == second


def test_unresolved_unit_names_are_sorted_and_deduplicated() -> None:
    graph = DependencyGraph()
    graph.add_edge(_edge(dst="unit:zeta", resolution="unresolved",
                         reason="missing-unit"))
    graph.add_edge(_edge(dst="unit:alpha", resolution="unresolved",
                         reason="missing-unit"))
    graph.add_edge(_edge(dst="unit:zeta", line=99, resolution="unresolved",
                         reason="missing-unit"))
    graph.add_edge(_edge(dst="unit:forms", resolution="unresolved",
                         reason="framework-unit"))

    # Only `missing-unit` edges count: an RTL unit is known-absent-by-design,
    # not an unresolved *name*.
    assert graph.unresolved_unit_names() == ["alpha", "zeta"]


def test_unresolved_unit_names_strips_the_id_prefix() -> None:
    graph = DependencyGraph()
    graph.add_edge(_edge(dst="unit:myapp.uhelper", resolution="unresolved",
                         reason="missing-unit"))
    assert graph.unresolved_unit_names() == ["myapp.uhelper"]
