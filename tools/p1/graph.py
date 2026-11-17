"""Dependency graph model and deterministic serialisation (task D2).

Design constraints inherited from IR invariants I5 and I6:

* **Every edge is traceable.**  An edge without a source file and a
  ``(line, column)`` span cannot exist — the constructor requires them.
* **Unresolved edges are data, not noise.**  ``resolution="unresolved"``
  edges are kept in the main edge list *and* projected into ``unresolved``;
  deleting one is a test failure (task D2, E4).
* **Byte-identical output.**  Nodes and edges are keyed and sorted by stable
  strings; no set iteration order, no clock, no absolute paths.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "Node",
    "Edge",
    "DependencyGraph",
    "RESOLUTIONS",
    "UNRESOLVED_REASONS",
    "RELATIONS",
]

#: Closed set of edge resolutions.
RESOLUTIONS = ("resolved", "unresolved")

#: Closed set of reasons an edge can be unresolved.  Adding one is a schema
#: change: tests assert that every unresolved edge carries a reason from here.
UNRESOLVED_REASONS = (
    "database-unit",
    "external-library",
    "framework-unit",
    "include-missing",
    "missing-unit",
    "platform-unit",
    "rtl-unit",
    "unparsable",
)

#: Closed set of edge relations.
RELATIONS = ("entry-point", "external", "include", "requires", "uses")


@dataclass(frozen=True)
class Node:
    """A vertex: something a dependency edge points at or comes from."""

    id: str
    kind: str  # "project" | "unit" | "include" | "package" | "external"
    path: str = ""
    sha256: str = ""
    #: Where the node came from: ``input`` (present in the ingested tree) or
    #: ``absent`` (referenced but not present).
    origin: str = "input"

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {"id": self.id, "kind": self.kind}
        if self.path:
            out["path"] = self.path
        if self.sha256:
            out["sha256"] = self.sha256
        if self.origin != "input":
            out["origin"] = self.origin
        return out


@dataclass(frozen=True)
class Edge:
    """A dependency with its exact source location and resolution."""

    src: str
    dst: str
    relation: str
    clause: str
    file: str
    line: int
    column: int
    text: str = ""
    resolution: str = "resolved"
    reason: str = ""
    conditional: tuple[str, ...] = ()

    def key(self) -> tuple[object, ...]:
        """Identity used for de-duplication and sorting."""

        return (
            self.src, self.dst, self.relation, self.clause,
            self.file, self.line, self.column, self.reason,
        )

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "clause": self.clause,
            "column": self.column,
            "file": self.file,
            "from": self.src,
            "line": self.line,
            "relation": self.relation,
            "resolution": self.resolution,
            "to": self.dst,
        }
        if self.text:
            out["text"] = self.text
        if self.reason:
            out["reason"] = self.reason
        if self.conditional:
            out["conditional"] = list(self.conditional)
        return out


@dataclass
class DependencyGraph:
    """Accumulates nodes and edges, then emits them in canonical order."""

    nodes: dict[str, Node] = field(default_factory=dict)
    _edges: dict[tuple[object, ...], Edge] = field(default_factory=dict)
    #: Counters for the report, kept as plain ints (no clock, no randomness).
    dropped_edges: int = 0

    def add_node(self, node: Node) -> Node:
        """Insert *node*, keeping the first version seen (ids are canonical)."""

        existing = self.nodes.get(node.id)
        if existing is None:
            self.nodes[node.id] = node
            return node
        # Prefer a node that carries a path/hash over a bare placeholder.
        if not existing.path and node.path:
            self.nodes[node.id] = node
            return node
        return existing

    def add_edge(self, edge: Edge) -> bool:
        """Insert *edge* if new.  Returns False when it was a duplicate."""

        if edge.resolution not in RESOLUTIONS:  # pragma: no cover - guard
            raise ValueError(f"invalid resolution {edge.resolution!r}")
        if edge.resolution == "unresolved" and edge.reason not in (
            UNRESOLVED_REASONS
        ):  # pragma: no cover - guard
            raise ValueError(
                f"unresolved edge needs a known reason, got {edge.reason!r}"
            )
        if edge.resolution == "resolved" and edge.reason:
            raise ValueError("a resolved edge must not carry an unresolved reason")
        key = edge.key()
        if key in self._edges:
            self.dropped_edges += 1
            return False
        self._edges[key] = edge
        return True

    def edges(self) -> list[Edge]:
        """All edges in canonical order."""

        return [self._edges[k] for k in sorted(self._edges)]

    def unresolved(self) -> list[Edge]:
        return [e for e in self.edges() if e.resolution == "unresolved"]

    def stats(self) -> dict[str, int]:
        edges = self.edges()
        resolved = sum(1 for e in edges if e.resolution == "resolved")
        return {
            "duplicate_edges_ignored": self.dropped_edges,
            "edges": len(edges),
            "nodes": len(self.nodes),
            "resolved": resolved,
            "unresolved": len(edges) - resolved,
        }

    def to_dict(self) -> dict[str, object]:
        """Canonical ``dependency-graph.json`` payload (IR invariant I6)."""

        edges = self.edges()
        return {
            "edges": [e.as_dict() for e in edges],
            "nodes": [
                self.nodes[k].as_dict() for k in sorted(self.nodes)
            ],
            "schema_version": "p1.dependency-graph/1.0",
            "stats": self.stats(),
            "unresolved": [
                e.as_dict() for e in edges if e.resolution == "unresolved"
            ],
        }

    def unresolved_unit_names(self) -> list[str]:
        """Sorted, de-duplicated names behind ``missing-unit`` edges."""

        names: set[str] = set()
        for edge in self.unresolved():
            if edge.reason == "missing-unit":
                names.add(edge.dst.split(":", 1)[-1])
        return sorted(names)
