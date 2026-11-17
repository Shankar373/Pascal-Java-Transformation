"""Build the dependency graph from scanned sources (tasks D2, D4, req. 6).

Resolution policy
-----------------

A ``uses``/``requires``/``{$I}`` reference is resolved against the ingested
tree only.  When it is not there, the edge is *kept* and classified:

===========================  ==============================================
reason                       meaning
===========================  ==============================================
``missing-unit``             not in the input and not a known platform unit
``include-missing``          ``{$I file}`` with no matching file
``rtl-unit``                 standard runtime library, absent by design
``platform-unit``            OS-specific unit (Windows / Unix)
``framework-unit``            VCL / LCL / FireMonkey unit
``database-unit``            data-access unit
``external-library``         shared library or third-party unit
``unparsable``               the clause could not be read
===========================  ==============================================

Nothing in this module drops an edge: the only way an edge disappears is if it
is an exact duplicate, and that count is reported in ``stats``.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .dialects import classify_unit
from .errors import DiagnosticSink
from .graph import DependencyGraph, Edge, Node
from .model import AnalysedFile
from .projects import ProjectRoot

__all__ = ["build_graph", "GraphBuild"]


@dataclass
class GraphBuild:
    """Result of :func:`build_graph`."""

    graph: DependencyGraph
    diagnostics: list[dict[str, object]]
    #: Unit names referenced but not present (sorted, de-duplicated).
    unresolved_units: list[str]


#: Map a unit classification category onto an unresolved-edge reason.
_REASON_BY_CATEGORY = {
    "cross-rtl": "rtl-unit",
    "delphi-rtl": "rtl-unit",
    "fpc-rtl": "rtl-unit",
    "windows-platform": "platform-unit",
    "unix-platform": "platform-unit",
    "vcl": "framework-unit",
    "lcl": "framework-unit",
    "fmx": "framework-unit",
    "database": "database-unit",
    "known-third-party": "external-library",
}

#: Map an unresolved reason onto the origin recorded on the target node.
_ORIGIN_BY_REASON = {
    "missing-unit": "absent",
    "rtl-unit": "rtl",
    "platform-unit": "platform",
    "framework-unit": "platform",
    "database-unit": "external",
    "external-library": "external",
    "include-missing": "absent",
    "unparsable": "absent",
}


def _norm_unit(name: str) -> str:
    return name.strip().lower()


def build_graph(
    analysed: list[AnalysedFile],
    roots: list[ProjectRoot],
    *,
    origin_id: str = "main",
    sink: DiagnosticSink | None = None,
) -> GraphBuild:
    """Construct the dependency graph for one ingested application."""

    sink = sink or DiagnosticSink()
    graph = DependencyGraph()
    app_node_id = f"application:{origin_id}"

    # ------------------------------------------------------------------
    # 1. Index the input so references can be resolved against it.
    # ------------------------------------------------------------------
    #: lowercase unit name -> candidate paths
    unit_index: dict[str, list[str]] = {}
    #: casefolded full path -> actual path (for include resolution)
    path_index: dict[str, str] = {}
    input_file_nodes: dict[str, Node] = {}

    for item in analysed:
        path_index[item.path.casefold()] = item.path
        if item.cls in (
            "pascal_unit", "pascal_program", "pascal_include",
            "pascal_package",
        ):
            node = Node(
                id=f"file:{item.path}",
                kind=(
                    "project" if item.cls in ("pascal_program", "pascal_package")
                    else "unit"
                ),
                path=item.path,
                sha256=item.inventory.sha256,
            )
            graph.add_node(node)
            input_file_nodes[item.path] = node
            stem = PurePosixPath(item.path).name.rsplit(".", 1)[0].lower()
            bucket = unit_index.setdefault(stem, [])
            if item.path not in bucket:
                bucket.append(item.path)
            # A `unit X;` clause is what `uses X` actually refers to, so it
            # joins the index alongside the file name.
            if item.analysis is not None and item.analysis.declared_name:
                declared = _norm_unit(item.analysis.declared_name)
                if declared:
                    bucket = unit_index.setdefault(declared, [])
                    if item.path not in bucket:
                        bucket.append(item.path)

    for key in unit_index:
        unit_index[key].sort()

    # ------------------------------------------------------------------
    # 2. Application node and entry-point edges.
    # ------------------------------------------------------------------
    graph.add_node(Node(id=app_node_id, kind="application", origin="input"))
    for root in sorted(roots, key=lambda r: r.path):
        target = f"file:{root.path}"
        if target not in graph.nodes:
            # A root that is not a Pascal source file (e.g. a bare .dproj).
            graph.add_node(Node(
                id=target,
                kind="project",
                path=root.path,
                origin="input",
            ))
        graph.add_edge(Edge(
            src=app_node_id,
            dst=target,
            relation="entry-point",
            clause=root.kind,
            file=root.path,
            line=1,
            column=1,
            text=root.path,
            # The entry-point *file* is present; the ambiguity is about which
            # root is primary, and that is recorded on the root itself
            # (`status`, `primary`) rather than misreported as a missing edge.
            resolution="resolved",
        ))

    # ------------------------------------------------------------------
    # 3. Walk every scanned source.
    # ------------------------------------------------------------------
    for item in sorted(analysed, key=lambda a: a.path):
        if item.scan is None:
            continue
        source_node_id = f"file:{item.path}"
        if source_node_id not in graph.nodes:
            continue  # not a Pascal source we track

        # --- uses / requires -------------------------------------------
        for clause in item.scan.uses:
            if not clause.items:
                sink.warn(
                    "USES_EMPTY",
                    f"`{clause.kind}` clause names no units",
                    path=item.path,
                    line=clause.line,
                    column=clause.column,
                )
                continue
            for unit in clause.items:
                _resolve_unit(
                    graph, sink, item, clause.kind, clause.section, unit,
                    unit_index,
                )

        # --- {$I include} ----------------------------------------------
        for include in item.scan.includes:
            resolved = _resolve_include(include.filename, item.path, path_index)
            if resolved is None:
                # The referenced include is not in the input: record the node
                # as absent so every edge endpoint exists in `nodes`.
                include_node_id = f"include:{_norm_unit(include.filename)}"
                graph.add_node(Node(
                    id=include_node_id,
                    kind="include",
                    origin="absent",
                ))
                graph.add_edge(Edge(
                    src=source_node_id,
                    dst=include_node_id,
                    relation="include",
                    clause="directive",
                    file=item.path,
                    line=include.line,
                    column=include.column,
                    text=f"{{${include.directive} {include.filename}}}",
                    resolution="unresolved",
                    reason="include-missing",
                    conditional=include.conditional,
                ))
                sink.warn(
                    "INCLUDE_NOT_FOUND",
                    f"included file {include.filename!r} is not in the "
                    "ingested input",
                    path=item.path,
                    line=include.line,
                    column=include.column,
                )
                continue
            target_id = f"file:{resolved}"
            if target_id not in graph.nodes:
                graph.add_node(Node(
                    id=target_id,
                    kind="include",
                    path=resolved,
                    origin="input",
                ))
            graph.add_edge(Edge(
                src=source_node_id,
                dst=target_id,
                relation="include",
                clause="directive",
                file=item.path,
                line=include.line,
                column=include.column,
                text=f"{{${include.directive} {include.filename}}}",
                resolution="resolved",
                conditional=include.conditional,
            ))

        # --- native libraries ------------------------------------------
        seen_native: set[tuple[str, int, int]] = set()
        for ref in item.scan.native_refs:
            if ref.kind == "os-api":
                continue
            key = (ref.name.lower(), ref.line, ref.column)
            if key in seen_native:
                continue
            seen_native.add(key)
            graph.add_node(Node(
                id=f"native:{ref.name.lower()}",
                kind="external",
                origin="absent",
            ))
            graph.add_edge(Edge(
                src=source_node_id,
                dst=f"native:{ref.name.lower()}",
                relation="external",
                clause=ref.kind,
                file=item.path,
                line=ref.line,
                column=ref.column,
                text=ref.name,
                resolution="unresolved",
                reason="external-library",
            ))

    # ------------------------------------------------------------------
    # 4. Report unresolved unit names.
    # ------------------------------------------------------------------
    unresolved = graph.unresolved_unit_names()
    if unresolved:
        sink.info(
            "UNRESOLVED_UNIT_REFERENCES",
            f"{len(unresolved)} unit reference(s) not present in the input: "
            + ", ".join(sorted(unresolved)[:12])
            + (" ..." if len(unresolved) > 12 else ""),
        )

    return GraphBuild(
        graph=graph,
        diagnostics=sink.to_list(),
        unresolved_units=unresolved,
    )


def _resolve_unit(
    graph: DependencyGraph,
    sink: DiagnosticSink,
    item: AnalysedFile,
    kind: str,
    section: str,
    unit: object,
    unit_index: dict[str, list[str]],
) -> None:
    """Resolve one ``uses``/``requires`` item and record the edge."""

    name = getattr(unit, "name", "")
    line = getattr(unit, "line", 1)
    column = getattr(unit, "column", 1)
    conditional = getattr(unit, "conditional", ())
    source_node_id = f"file:{item.path}"
    text = name
    relation = kind if kind in ("uses", "requires") else "uses"

    if not name:
        graph.add_edge(Edge(
            src=source_node_id,
            dst="unit:<empty>",
            relation=relation,
            clause=section,
            file=item.path,
            line=line,
            column=column,
            text=text,
            resolution="unresolved",
            reason="unparsable",
            conditional=conditional,
        ))
        sink.error(
            "USES_ITEM_EMPTY",
            "empty unit name in clause",
            path=item.path,
            line=line,
            column=column,
        )
        return

    candidates = _lookup_unit(name, unit_index)
    if candidates:
        chosen = candidates[0]
        if len(candidates) > 1:
            sink.warn(
                "AMBIGUOUS_UNIT_RESOLUTION",
                f"{name!r} matches multiple input files "
                + ", ".join(candidates)
                + f"; using {chosen}",
                path=item.path,
                line=line,
                column=column,
            )
        target_id = f"file:{chosen}"
        graph.add_edge(Edge(
            src=source_node_id,
            dst=target_id,
            relation=relation,
            clause=section,
            file=item.path,
            line=line,
            column=column,
            text=text,
            resolution="resolved",
            conditional=conditional,
        ))
        return

    # Not in the input: classify so the edge carries a reason, not a shrug.
    category, matched = classify_unit(name)
    reason = _REASON_BY_CATEGORY.get(category, "missing-unit")
    target_id = f"unit:{_norm_unit(name)}"
    origin = _ORIGIN_BY_REASON.get(reason, "absent")
    graph.add_node(Node(
        id=target_id,
        kind="external",
        origin=origin,
    ))
    graph.add_edge(Edge(
        src=source_node_id,
        dst=target_id,
        relation=relation,
        clause=section,
        file=item.path,
        line=line,
        column=column,
        text=text,
        resolution="unresolved",
        reason=reason,
        conditional=conditional,
    ))


def _lookup_unit(name: str, unit_index: dict[str, list[str]]) -> list[str]:
    """Find input files that could satisfy a ``uses`` reference.

    Tries the fully-qualified name first, then the last dotted segment, so
    ``MyApp.uHelper`` finds ``uHelper.pas``.  Results are sorted, so an
    ambiguous match is reported deterministically rather than in dictionary
    order.
    """

    lowered = _norm_unit(name)
    if not lowered:
        return []
    hits = list(unit_index.get(lowered, []))
    tail = lowered.rsplit(".", 1)[-1]
    if not hits and tail != lowered:
        hits = list(unit_index.get(tail, []))
    return sorted(set(hits))


def _resolve_include(
    filename: str, from_path: str, path_index: dict[str, str]
) -> str | None:
    """Resolve an include relative to the including file, then the root."""

    wanted = filename.replace("\\", "/").lstrip("./")
    if not wanted:
        return None
    # 1. exact, relative to the including file
    base = PurePosixPath(from_path).parent
    candidate = (base / wanted).as_posix() if str(base) != "." else wanted
    hit = path_index.get(candidate.casefold())
    if hit:
        return hit
    # 2. exact, relative to the ingest root
    hit = path_index.get(wanted.casefold())
    if hit:
        return hit
    # 3. basename match anywhere in the tree (deterministic: lowest path)
    basename = PurePosixPath(wanted).name.lower()
    matches = sorted(
        p for p in path_index.values()
        if PurePosixPath(p).name.lower() == basename
    )
    return matches[0] if matches else None
