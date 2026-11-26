"""Blueprint sections about dependencies.

``unresolved``, ``dependencies`` (including the top-5 ``key`` list) and
``graphs`` (design section 6).

Policy, stated once
-------------------

* **Nothing is pruned.**  Every unresolved graph edge becomes (part of) an
  ``unresolved`` item; libraries and runtime dependencies that are not
  satisfied by the input are added to it.  Items for things that are
  *absent by design* (RTL, platform, framework and database units) are kept
  with severity ``info`` so the list is a superset of the graph's unresolved
  edges, yet only ``error``/``warning`` items count as actionable.
* **Remediation text is static.**  No generated prose of any kind.
* **One missing thing is one item.**  The same absent dependency is often seen
  by several detectors (the unit graph, the library catalogue, the runtime
  scan).  Their items are folded into one, kept at the *highest* severity of
  the facets, with every referencing location merged and the folded facets
  named in ``remediation``: ``runtime:dll`` / ``runtime:bpl-package`` fold
  into the ``native-library`` or ``unit`` item of the same name, and
  ``library:<x>`` folds into ``unit:<x>``.  Counts (``summary``, the
  ``UNRESOLVED_DEPENDENCIES`` blocker) therefore count de-duplicated items.
* **A library file shipped in the input** satisfies a reference to its
  basename: the item is kept but downgraded to ``info`` and says where the
  file is.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Iterable

from .blueprint_common import (
    Ctx,
    canonical_sort,
    clean_text,
    evidence_list,
    file_evidence,
)
from .dialects import classify_unit
from .graph import Edge

__all__ = [
    "build_unresolved",
    "actionable",
    "build_dependencies",
    "build_graphs",
    "external_dependency_count",
    "KEY_DEPENDENCY_LIMIT",
]

KEY_DEPENDENCY_LIMIT = 5
_KEY_EVIDENCE = 3
_ALL_EVIDENCE = 1_000_000

_SEVERITY_BY_REASON = {
    "missing-unit": "error",
    "include-missing": "error",
    "unparsable": "error",
    "external-library": "warning",
    "rtl-unit": "info",
    "platform-unit": "info",
    "framework-unit": "info",
    "database-unit": "info",
}

#: Runtime kinds that are files the application ships; the rest are provided
#: by the host (registry, environment, services ...) and cannot be "in input".
_SHIPPED_RUNTIME_KINDS = frozenset(
    {"bpl-package", "configuration-file", "data-file", "dll"}
)

#: Standard run-time packages of the Delphi and Free Pascal/Lazarus
#: distributions.  A ``requires`` clause naming one of them is satisfied by
#: the toolchain, not by the input, so it is reported but not actionable.
_STANDARD_PACKAGES = frozenset({
    "rtl", "vcl", "vclx", "vcldb", "dbrtl", "xmlrtl", "vclimg",
    "vclactnband", "soaprtl", "dsnap", "inet", "adortl", "designide",
    "lcl", "lclbase", "fcl", "fcl-base", "fcl-db", "fcl-xml", "fcl-web",
    "fcl-json", "fcl-net", "rtl-objpas", "rtl-generics",
})

_REMEDIATION = {
    "standard-package": (
        "None required: standard run-time package of the compiler "
        "distribution."
    ),
    "missing-unit": (
        "Add the unit source (.pas) or compiled unit (.dcu/.ppu) to the "
        "input, or add the package that provides it to the search path."
    ),
    "include-missing": (
        "Add the missing include file to the input or correct the include "
        "path in the directive."
    ),
    "unparsable": (
        "Correct the malformed clause; the unit cannot be read as written."
    ),
    "external-library": (
        "Supply the third-party library (source or binary) with the input, "
        "or record it as an externally managed dependency."
    ),
    "native-library": (
        "Supply the native library with the input, or plan a replacement "
        "for it on the target platform."
    ),
    "native-library-present": (
        "The library file is present in the input; confirm it is the "
        "version the application was built against."
    ),
    "rtl-unit": (
        "None required: standard runtime library unit provided by the "
        "compiler distribution."
    ),
    "platform-unit": (
        "None required for discovery: operating-system specific unit "
        "provided by the platform."
    ),
    "framework-unit": (
        "None required for discovery: UI framework unit provided by the "
        "toolchain."
    ),
    "database-unit": (
        "None required for discovery: data-access unit provided by the "
        "toolchain."
    ),
    "unresolved-library": (
        "Identify the library, then supply it with the input or record it "
        "as an externally managed dependency."
    ),
    "runtime-file": (
        "Supply the file with the input or document where it is deployed."
    ),
    "runtime-host": (
        "Provided by the host environment; record it as an environment "
        "requirement of the deployment."
    ),
    "project-file": (
        "Add the entry-point source (.dpr/.lpr/.dpk/.lpk) that belongs to "
        "this project file."
    ),
}


def _binaries_by_name(ctx: Ctx) -> dict[str, str]:
    """lower-case basename -> first path of every binary in the input."""

    out: dict[str, str] = {}
    for item in ctx.analysed:
        if item.cls == "binary":
            out.setdefault(PurePosixPath(item.path).name.lower(), item.path)
    return out


def _edge_target(edge: Edge) -> tuple[str, str]:
    rest = edge.dst.partition(":")[2] or edge.dst
    if edge.relation == "include":
        return "include", rest
    if edge.relation == "external":
        return "native-library", rest
    return "unit", rest


def _ref(file: str, line: int, column: int) -> dict[str, object]:
    return {"column": column, "file": file, "line": line}


def _merge(items: dict[str, dict[str, Any]], item: dict[str, Any]) -> None:
    known = items.get(item["id"])
    if known is None:
        items[item["id"]] = item
        return
    known["referenced_by"].extend(item["referenced_by"])


def _make(item_id: str, kind: str, name: str, reason: str, severity: str,
          refs: list[dict[str, object]], remediation: str) -> dict[str, Any]:
    return {
        "id": item_id,
        "kind": kind,
        "name": clean_text(name),
        "reason": clean_text(reason),
        "severity": severity,
        "referenced_by": refs,
        "remediation": remediation,
    }


def _edge_severity(edge: Edge, kind: str, name: str,
                   external_units: set[str]) -> tuple[str, str]:
    """``(severity, remediation-key)`` of one unresolved graph edge."""

    reason = edge.reason
    if kind == "native-library":
        return _SEVERITY_BY_REASON.get(reason, "warning"), "native-library"
    if edge.relation == "requires" and name in _STANDARD_PACKAGES:
        return "info", "standard-package"
    if reason == "missing-unit" and name in external_units:
        # The unit belongs to a recognised third-party library: the missing
        # library is the actionable fact, so the severity matches it.
        return "warning", "external-library"
    return _SEVERITY_BY_REASON.get(reason, "warning"), reason


def _edge_items(ctx: Ctx, binaries: dict[str, str]) -> list[dict[str, Any]]:
    external_units = {u.lower() for lib in ctx.discovery.libraries
                      if lib.origin == "external" for u in lib.units}
    out = []
    for edge in ctx.edges:
        if edge.resolution != "unresolved":
            continue
        kind, name = _edge_target(edge)
        reason = edge.reason
        severity, key = _edge_severity(edge, kind, name, external_units)
        remediation = _REMEDIATION.get(key, "")
        present = binaries.get(PurePosixPath(name).name.lower())
        if kind == "native-library" and present:
            severity = "info"
            remediation = (f"{_REMEDIATION['native-library-present']} "
                           f"Found at {present}.")
        out.append(_make(f"{kind}:{name}", kind, name, reason, severity,
                         [_ref(edge.file, edge.line, edge.column)],
                         remediation))
    return out


def _refs(finding: Any, ctx: Ctx, files: tuple[str, ...]) -> list[dict]:
    refs = [_ref(e["file"], e["line"], e["column"])
            for e in evidence_list(finding.evidence, ctx)]
    covered = {r["file"] for r in refs}
    refs.extend(_ref(f, 0, 0) for f in sorted(set(files)) if f not in covered)
    return refs


def _library_items(ctx: Ctx) -> list[dict[str, Any]]:
    out = []
    for lib in ctx.discovery.libraries:
        if lib.origin not in ("external", "unresolved") or lib.resolved:
            continue
        reason = ("external-library" if lib.origin == "external"
                  else "unresolved-library")
        out.append(_make(
            f"library:{lib.name.lower()}", "library", lib.name, reason,
            "warning", _refs(lib, ctx, lib.referenced_by),
            _REMEDIATION["external-library" if lib.origin == "external"
                         else "unresolved-library"]))
    return out


def _runtime_items(ctx: Ctx) -> list[dict[str, Any]]:
    out = []
    for dep in ctx.discovery.runtime_dependencies:
        if dep.resolved_in_input:
            continue
        shipped = dep.kind in _SHIPPED_RUNTIME_KINDS
        out.append(_make(
            f"runtime:{dep.kind}:{dep.name.lower()}", "runtime", dep.name,
            f"{dep.kind} not present in the input", "warning" if shipped
            else "info", _refs(dep, ctx, dep.required_by),
            _REMEDIATION["runtime-file" if shipped else "runtime-host"]))
    return out


def _project_file_items(ctx: Ctx) -> list[dict[str, Any]]:
    return [
        _make(f"project-file:{root.path}", "project-file", root.path,
              "entry-point-missing", "warning", [_ref(root.path, 1, 1)],
              _REMEDIATION["project-file"])
        for root in ctx.roots if root.kind == "unknown"
    ]


_SEVERITY_RANK = {"info": 0, "warning": 1, "error": 2}
_FOLDED_RUNTIME = ("dll", "bpl-package")


def _stem(name: str) -> str:
    return name[:name.rfind(".")] if "." in name else name


def _anchor_index(items: dict[str, dict[str, Any]]) -> dict[str, str]:
    """lower-case name -> id of the ``unit`` / ``native-library`` items."""

    out: dict[str, str] = {}
    for item_id in sorted(items):
        item = items[item_id]
        if item["kind"] == "unit":
            out.setdefault(item["name"].lower(), item_id)
        elif item["kind"] == "native-library":
            name = PurePosixPath(item["name"]).name.lower()
            out.setdefault(name, item_id)
    return out


def _fold_target(item: dict[str, Any], anchors: dict[str, str]) -> str:
    """Id of the item that already reports *item*'s dependency, or ``""``."""

    name = item["name"].lower()
    if item["kind"] == "library":
        target = anchors.get(name, "")
        return target if target.startswith("unit:") else ""
    parts = item["id"].split(":", 2)
    if item["kind"] != "runtime" or parts[1] not in _FOLDED_RUNTIME:
        return ""
    keys = [PurePosixPath(name).name]
    if parts[1] == "bpl-package":
        keys.append(_stem(keys[0]))
    return next((anchors[k] for k in keys if k in anchors), "")


def _absorb(target: dict[str, Any], source: dict[str, Any]) -> None:
    if _SEVERITY_RANK[source["severity"]] > _SEVERITY_RANK[target["severity"]]:
        target["severity"] = source["severity"]
    target["referenced_by"].extend(source["referenced_by"])
    facet = source["id"].split(":", 1)[0]
    if source["kind"] == "runtime":
        facet = "runtime " + source["id"].split(":", 2)[1]
    target["remediation"] = (f"{target['remediation']} Also reported as "
                             f"{facet} {source['name']}.").strip()


def _fold_duplicates(items: dict[str, dict[str, Any]]
                     ) -> dict[str, dict[str, Any]]:
    """One item per missing thing (see the module policy)."""

    anchors = _anchor_index(items)
    kept = dict(items)
    for item_id in sorted(items):
        target = _fold_target(items[item_id], anchors)
        if target and target != item_id:
            _absorb(kept[target], kept.pop(item_id))
    return kept


def build_unresolved(ctx: Ctx) -> list[dict[str, Any]]:
    """The flattened, id-sorted ``unresolved`` list (de-duplicated)."""

    raw: dict[str, dict[str, Any]] = {}
    for item in (_edge_items(ctx, _binaries_by_name(ctx))
                 + _library_items(ctx) + _runtime_items(ctx)
                 + _project_file_items(ctx)):
        _merge(raw, item)
    items = _fold_duplicates(raw)
    for item in items.values():
        unique = {(r["file"], r["line"], r["column"]): r
                  for r in item["referenced_by"]}
        item["referenced_by"] = [unique[k] for k in sorted(unique)]
    return [items[key] for key in sorted(items)]


def actionable(unresolved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The ``error``/``warning`` items - the ones that need a decision."""

    return [u for u in unresolved if u["severity"] in ("error", "warning")]


# ---------------------------------------------------------------------------
# dependencies
# ---------------------------------------------------------------------------

_FRAMEWORK_NAMES = {"vcl": "VCL", "lcl": "LCL", "fmx": "FMX"}


def _native_entry(finding: Any, ctx: Ctx,
                  binaries: dict[str, str]) -> dict[str, Any]:
    data = finding.as_dict()
    path = binaries.get(PurePosixPath(finding.name).name.lower(), "")
    return {
        "name": clean_text(finding.name),
        "kind": finding.kind,
        "status": finding.status,
        "resolved_in_input": bool(path),
        "evidence": evidence_list(data["evidence"], ctx),
    }


def _simple_entry(finding: Any, ctx: Ctx) -> dict[str, Any]:
    data = finding.as_dict()
    data["evidence"] = evidence_list(data.get("evidence", []), ctx)
    if not data["evidence"] and getattr(finding, "path", ""):
        data["evidence"] = [file_evidence(
            finding.path, "SQL file present (dialect markers not found)")]
    return data


def _build_block(ctx: Ctx) -> dict[str, Any]:
    discovery = ctx.discovery
    requirements = dict(discovery.build_requirements)
    return {
        "requirements": requirements,
        "scripts": canonical_sort(
            _with_evidence(s.as_dict(), ctx) for s in discovery.build_scripts),
        "compiler_configs": canonical_sort(
            _with_evidence(c.as_dict(), ctx)
            for c in discovery.compiler_configs),
    }


def _with_evidence(data: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    data["evidence"] = evidence_list(data.get("evidence", []), ctx)
    return data


def build_dependencies(ctx: Ctx) -> dict[str, Any]:
    """The ``dependencies`` block including the top-5 ``key`` list."""

    discovery = ctx.discovery
    binaries = _binaries_by_name(ctx)
    natives = sorted(discovery.native_libs, key=lambda n: n.name)
    return {
        "key": _key_dependencies(ctx, binaries),
        "libraries": canonical_sort(
            _with_evidence(lib.as_dict(), ctx)
            for lib in discovery.libraries),
        "native_libraries": [_native_entry(n, ctx, binaries) for n in natives],
        "databases": canonical_sort(
            _simple_entry(d, ctx) for d in discovery.database),
        "sql_files": canonical_sort(
            _simple_entry(s, ctx) for s in discovery.sql_files),
        "integrations": canonical_sort(
            _with_evidence(i.as_dict(), ctx) for i in discovery.integrations),
        "runtime": canonical_sort(
            _with_evidence(r.as_dict(), ctx)
            for r in discovery.runtime_dependencies),
        "build": _build_block(ctx),
    }


# ---------------------------------------------------------------------------
# key dependencies (top 5)
# ---------------------------------------------------------------------------


def _distinct_files(raws: Iterable[Any], ctx: Ctx) -> int:
    """Number of distinct input files that *raws* (evidence) point into."""

    return len({e["file"] for e in evidence_list(raws, ctx, _ALL_EVIDENCE)})


def _unit_candidates(ctx: Ctx, skip: set[str]) -> list[dict[str, Any]]:
    """Unresolved third-party/missing units and framework families.

    A unit that a library candidate already covers (by library name or by the
    library's unit list) is not repeated: the library is the key dependency.
    """

    groups: dict[tuple[str, str, str], list[Edge]] = {}
    for edge in ctx.edges:
        if edge.resolution != "unresolved" or edge.relation not in (
                "uses", "requires"):
            continue
        _, name = _edge_target(edge)
        if edge.reason in ("missing-unit", "external-library"):
            if name.lower() in skip:
                continue
            key = ("unit", name, edge.reason)
        elif edge.reason == "framework-unit":
            family = _FRAMEWORK_NAMES.get(classify_unit(name)[0], "")
            if not family or family.lower() in skip:
                continue
            key = ("library", family, edge.reason)
        else:
            continue
        groups.setdefault(key, []).append(edge)
    return [_unit_candidate(ctx, key, edges) for key, edges in groups.items()]


def _unit_candidate(ctx: Ctx, key: tuple[str, str, str],
                    edges: list[Edge]) -> dict[str, Any]:
    kind, name, reason = key
    framework = reason == "framework-unit"
    raws = [{"file": e.file, "line": e.line, "column": e.column,
             "text": e.text or name} for e in edges]
    return {
        "name": name,
        "kind": kind,
        "category": "framework" if framework else reason,
        "status": "resolved" if framework else "unresolved",
        "reason": ("UI framework unit provided by the toolchain, not part "
                   "of the input" if framework else
                   "unit is not present in the input"),
        "references": len({e.file for e in edges}),
        "evidence": evidence_list(raws, ctx, _KEY_EVIDENCE),
    }


def _library_candidates(ctx: Ctx) -> list[dict[str, Any]]:
    reasons = {
        "bundled": "library source or binary is bundled in the input",
        "framework": "UI framework provided by the toolchain",
        "external": "recognised third-party library not present in the input",
        "unresolved": "referenced, not present in the input and not "
                      "recognised",
    }
    out = []
    for lib in ctx.discovery.libraries:
        if lib.origin == "rtl":
            continue
        satisfied = lib.resolved or lib.origin in ("bundled", "framework")
        out.append({
            "name": lib.name,
            "kind": "library",
            "category": lib.category,
            "status": "resolved" if satisfied else "unresolved",
            "reason": reasons.get(lib.origin, lib.origin),
            "references": (len(set(lib.referenced_by))
                           or _distinct_files(lib.evidence, ctx)),
            "evidence": evidence_list(lib.evidence, ctx, _KEY_EVIDENCE),
        })
    return out


def _database_candidates(ctx: Ctx) -> list[dict[str, Any]]:
    return [{
        "name": d.technology,
        "kind": "database",
        "category": "database",
        "status": "resolved",
        "reason": ("detected from source; client and driver availability "
                   "is not assessed in Stage 1"),
        "references": _distinct_files(d.evidence, ctx),
        "evidence": evidence_list(d.evidence, ctx, _KEY_EVIDENCE),
    } for d in ctx.discovery.database]


def _native_candidates(ctx: Ctx, binaries: dict[str, str]
                       ) -> list[dict[str, Any]]:
    out = []
    for lib in ctx.discovery.native_libs:
        path = binaries.get(PurePosixPath(lib.name).name.lower(), "")
        out.append({
            "name": clean_text(lib.name),
            "kind": "native-library",
            "category": lib.kind,
            "status": "resolved" if path else "unresolved",
            "reason": (f"library file present in the input ({path})" if path
                       else "library file is not present in the input"),
            "references": _distinct_files(lib.evidence, ctx),
            "evidence": evidence_list(lib.evidence, ctx, _KEY_EVIDENCE),
        })
    return out


def _key_dependencies(ctx: Ctx, binaries: dict[str, str]
                      ) -> list[dict[str, Any]]:
    libraries = _library_candidates(ctx)
    covered = {c["name"].lower() for c in libraries}
    covered.update(u.lower() for lib in ctx.discovery.libraries
                   if lib.origin != "rtl" for u in lib.units)
    pool = (libraries + _unit_candidates(ctx, covered)
            + _database_candidates(ctx) + _native_candidates(ctx, binaries))
    pool = [c for c in pool if c["references"] > 0]
    pool.sort(key=lambda c: (c["status"] != "unresolved", -c["references"],
                             c["name"].lower(), c["kind"]))
    return pool[:KEY_DEPENDENCY_LIMIT]


# ---------------------------------------------------------------------------
# graphs
# ---------------------------------------------------------------------------


def _unresolved_ids_by_file(unresolved: list[dict[str, Any]]
                            ) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for item in actionable(unresolved):
        for ref in item["referenced_by"]:
            out.setdefault(str(ref["file"]), set()).add(item["id"])
    return out


def _requires_names(ctx: Ctx, path: str) -> list[str]:
    return sorted({e.text or e.dst for e in ctx.edges
                   if e.src == f"file:{path}" and e.relation == "requires"})


def _project_graph(ctx: Ctx, root_path: str,
                   by_file: dict[str, set[str]]) -> dict[str, Any]:
    reach = ctx.reach.get(root_path, ())
    units = [p for p in reach if p in ctx.by_path
             and ctx.by_path[p].cls == "pascal_unit"]
    files = set(reach)
    libs = sorted({lib.name for lib in ctx.discovery.libraries
                   if files.intersection(lib.referenced_by)})
    externals = sorted(set().union(*(by_file.get(p, set()) for p in reach)))
    return {"project": root_path, "uses": units,
            "packages": _requires_names(ctx, root_path),
            "libraries": libs, "externals": externals}


def build_graphs(ctx: Ctx, unresolved: list[dict[str, Any]]
                 ) -> dict[str, Any]:
    """The ``graphs`` block: summary of the unit graph plus per-project views."""

    stats = ctx.discovery.graph.stats()
    by_file = _unresolved_ids_by_file(unresolved)
    packages = sorted({r.path for r in ctx.roots if r.kind == "package"}
                      | {a.path for a in ctx.analysed
                         if a.cls == "pascal_package"})
    used_by: dict[str, list[str]] = {}
    for lib in ctx.discovery.libraries:
        used_by[lib.name] = sorted(
            r.path for r in ctx.roots
            if set(ctx.reach.get(r.path, ())).intersection(lib.referenced_by))
    return {
        "unit": {"ref": "dependency-graph.json", "nodes": stats["nodes"],
                 "edges": stats["edges"], "resolved": stats["resolved"],
                 "unresolved": stats["unresolved"]},
        "projects": [_project_graph(ctx, r.path, by_file) for r in ctx.roots],
        "packages": [{"package": p, "requires": _requires_names(ctx, p)}
                     for p in packages],
        "libraries": [{"library": name, "used_by": used_by[name]}
                      for name in sorted(used_by)],
    }


def external_dependency_count(ctx: Ctx) -> int:
    """Third-party libraries + native libraries + database technologies."""

    third_party = {lib.name.lower() for lib in ctx.discovery.libraries
                   if lib.origin in ("bundled", "external", "unresolved")}
    natives = {n.name.lower() for n in ctx.discovery.native_libs}
    databases = {d.technology.lower() for d in ctx.discovery.database}
    return len(third_party) + len(natives) + len(databases)

