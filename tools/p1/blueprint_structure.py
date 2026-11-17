"""Blueprint sections ``structure`` (the tree) and ``components``.

Structure
---------

``application -> project (primary first) -> groups -> files``.  Each file is
assigned to exactly one project, so group counts add up to the number of
files.  Ownership rule, in order:

1. a unit, include or form reachable (through resolved ``uses`` / ``requires``
   / include edges) from a project belongs to that project; when several
   projects reach it, the one whose directory contains it wins, then the
   deepest directory, then the first project in output order;
2. any other file belongs to the project with the deepest directory that
   contains it;
3. otherwise to the first project (primary first).

A project root (a ``.dpr``/``.dpk`` that is itself a project) always belongs to
its *own* project, whoever reaches it.

Counts.  ``units`` is the number of ``pascal_unit`` files only (the same
definition as ``projects[].unit_count``); include files and the program file
sit in the ``Other`` group and are also counted under their own keys,
``includes`` and ``programs`` (these two are subsets of ``other``, not extra
groups).  A unit reached by several projects appears once in the tree (under
its owner) but is counted for every project that reaches it in
``projects[].unit_count``.

Without any project the groups hang directly under the application node.
Every group lists at most :data:`CHILD_LIMIT` files (``truncated`` says so).

Components
----------

Nine fixed components.  ``present`` means at least one located observation
backs it; ``count`` is the number of supporting findings, files or
references and is ``0`` exactly when ``present`` is false.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Any, Callable

from .blueprint_common import (
    Ctx,
    clean_text,
    evidence_list,
    extension_of,
    file_evidence,
)
from .blueprint_sections import directory_entries
from .model import AnalysedFile
from .projects import ProjectRoot

__all__ = [
    "build_structure",
    "build_components",
    "structure_group",
    "CHILD_LIMIT",
    "STRUCTURE_GROUPS",
    "COMPONENT_IDS",
]

CHILD_LIMIT = 50
_COMPONENT_EVIDENCE = 5

STRUCTURE_GROUPS: tuple[tuple[str, str], ...] = (
    ("units", "Units"),
    ("forms", "Forms"),
    ("packages", "Packages"),
    ("libraries", "Libraries"),
    ("resources", "Resources"),
    ("config", "Config"),
    ("scripts", "Scripts"),
    ("docs", "Docs"),
    ("other", "Other"),
)

_LIBRARY_EXT = (".dll", ".so", ".dylib", ".ocx", ".lib", ".a")


def structure_group(item: AnalysedFile) -> str:
    """The structure-group id of one file."""

    cls, ext = item.cls, extension_of(item.path)
    if cls == "pascal_unit":
        return "units"
    if cls == "ui_definition":
        return "forms"
    if cls == "pascal_package" or ext == ".bpl":
        return "packages"
    if cls == "binary" and ext in _LIBRARY_EXT:
        return "libraries"
    if cls in ("resource", "sql", "database"):
        return "resources"
    if cls in ("configuration", "pascal_project"):
        return "config"
    if cls == "build_script":
        return "scripts"
    if cls in ("documentation", "licence"):
        return "docs"
    return "other"


# ---------------------------------------------------------------------------
# tree
# ---------------------------------------------------------------------------


def _node(name: str, path: str, kind: str, counts: dict[str, int],
          children: list[dict[str, Any]], truncated: bool = False
          ) -> dict[str, Any]:
    return {"name": clean_text(name), "path": path, "kind": kind,
            "counts": counts, "children": children, "truncated": truncated}


def _file_node(item: AnalysedFile) -> dict[str, Any]:
    return _node(PurePosixPath(item.path).name, item.path, "file",
                 {"bytes": item.inventory.size}, [])


def _group_nodes(files: list[AnalysedFile]) -> tuple[list[dict], dict]:
    """Group nodes (fixed order) and the per-group file counts."""

    buckets: dict[str, list[AnalysedFile]] = {g: [] for g, _ in
                                              STRUCTURE_GROUPS}
    for item in sorted(files, key=lambda a: a.path):
        buckets[structure_group(item)].append(item)
    nodes = []
    for group_id, label in STRUCTURE_GROUPS:
        members = buckets[group_id]
        nodes.append(_node(
            label, "", "group", {"files": len(members)},
            [_file_node(m) for m in members[:CHILD_LIMIT]],
            len(members) > CHILD_LIMIT))
    counts = {g: len(m) for g, m in buckets.items()}
    counts["includes"] = sum(1 for f in files if f.cls == "pascal_include")
    counts["programs"] = sum(1 for f in files if f.cls == "pascal_program")
    return nodes, counts


def _inside(path: str, directory: str) -> bool:
    return directory == "" or path.startswith(directory + "/")


def _root_dir(root: ProjectRoot) -> str:
    parent = PurePosixPath(root.path).parent.as_posix()
    return "" if parent == "." else parent


def _owner(path: str, dirs: list[str], reach: list[set[str]],
           own: dict[str, int]) -> int:
    if path in own:
        return own[path]
    reachers = [i for i, r in enumerate(reach) if path in r]
    within = [i for i, d in enumerate(dirs) if _inside(path, d)]
    pool = ([i for i in reachers if i in within] or reachers) or within
    if not pool:
        return 0
    return max(pool, key=lambda i: (len(dirs[i]), -i))


def _assign(ctx: Ctx) -> list[list[AnalysedFile]]:
    dirs = [_root_dir(r) for r in ctx.roots]
    reach = [set(ctx.reach[r.path]) for r in ctx.roots]
    own = {r.path: i for i, r in enumerate(ctx.roots)}
    owned: list[list[AnalysedFile]] = [[] for _ in ctx.roots]
    for item in ctx.analysed:
        owned[_owner(item.path, dirs, reach, own)].append(item)
    return owned


def _project_node(root: ProjectRoot, files: list[AnalysedFile]
                  ) -> dict[str, Any]:
    groups, counts = _group_nodes(files)
    node = _node(PurePosixPath(root.path).name, root.path, "project",
                 {"files": len(files), **counts}, groups)
    node["primary"] = root.primary
    return node


def build_structure(ctx: Ctx, app_name: str) -> dict[str, Any]:
    """The bounded ``structure`` tree."""

    counts = {"files": len(ctx.analysed),
              "directories": len(directory_entries(ctx)),
              "projects": len(ctx.roots)}
    if not ctx.roots:
        groups, _ = _group_nodes(list(ctx.analysed))
        return _node(app_name, "", "application", counts, groups)
    owned = _assign(ctx)
    nodes = [_project_node(r, f) for r, f in zip(ctx.roots, owned)]
    return _node(app_name, "", "application", counts, nodes[:CHILD_LIMIT],
                 len(nodes) > CHILD_LIMIT)


# ---------------------------------------------------------------------------
# components
# ---------------------------------------------------------------------------

_COM_UNITS = frozenset({"comobj", "activex", "ole2", "oleauto", "comserv"})
_REPORT_UNITS = frozenset({"frxclass", "frxdbset", "quickrpt", "qrctrls",
                           "raveprinter"})
_SERVICE_UNITS = frozenset({"svcmgr", "svcmanager"})
_REPORT_EXT = (".fr3", ".frx", ".qrp", ".rav", ".rpt", ".rtm")

COMPONENTS: tuple[tuple[str, str], ...] = (
    ("gui_application", "GUI Application"),
    ("database", "Database"),
    ("com_activex", "COM/ActiveX"),
    ("reports", "Reports"),
    ("scheduled_jobs", "Scheduled Jobs"),
    ("services", "Services"),
    ("build_scripts", "Build Scripts"),
    ("documentation", "Documentation"),
    ("integrations", "Integrations"),
)
COMPONENT_IDS = tuple(c for c, _ in COMPONENTS)

#: ``(count, raw evidence)`` produced by one component detector.
_Hits = tuple[int, list[Any]]


def _files(ctx: Ctx, test: Callable[[AnalysedFile], bool], what: str
           ) -> _Hits:
    hits = [a.path for a in ctx.analysed if test(a)]
    return len(hits), [file_evidence(p, what) for p in hits]


def _unit_refs(ctx: Ctx, names: frozenset[str]) -> _Hits:
    edges = [e for e in ctx.edges if e.relation in ("uses", "requires")
             and e.dst.partition(":")[2].lower() in names]
    raws = [{"file": e.file, "line": e.line, "column": e.column,
             "text": f"references unit {e.text or e.dst}"} for e in edges]
    return len({e.dst for e in edges}), raws


def _finding_ev(finding: Any) -> list[Any]:
    evidence = getattr(finding, "evidence", None)
    if evidence is None:
        evidence = finding.as_dict().get("evidence", [])
    return list(evidence)


def _from_findings(findings: list[Any]) -> _Hits:
    raws = [e for f in findings for e in _finding_ev(f)]
    return len(findings), raws


def _join(*parts: _Hits) -> _Hits:
    return sum(p[0] for p in parts), [e for p in parts for e in p[1]]


def _integrations(ctx: Ctx, *categories: str) -> _Hits:
    return _from_findings([i for i in ctx.discovery.integrations
                           if not categories or i.category in categories])


def _gui(ctx: Ctx) -> _Hits:
    roots = [r for r in ctx.roots if r.shape.startswith("gui_")]
    raws = [dict(e, file=r.path) for r in roots for e in r.shape_evidence]
    raws += [file_evidence(r.path, f"{r.shape} application entry point")
             for r in roots]
    if roots:
        return len(roots), raws
    return _files(ctx, lambda a: a.cls == "ui_definition",
                  "form definition file")


def _database(ctx: Ctx) -> _Hits:
    discovery = ctx.discovery
    sql = [s for s in discovery.sql_files]
    sql_raws = [e for s in sql for e in s.as_dict()["evidence"]]
    files = _files(ctx, lambda a: a.cls in ("sql", "database"),
                   "database artefact file")
    return _join(_from_findings(list(discovery.database)),
                 (len(sql), sql_raws), files)


def _com(ctx: Ctx) -> _Hits:
    runtime = [r for r in ctx.discovery.runtime_dependencies
               if r.kind == "com-component"]
    return _join(_integrations(ctx, "com-ole", "dcom"),
                 _from_findings(runtime),
                 _files(ctx, lambda a: extension_of(a.path) == ".ocx",
                        "ActiveX control file"),
                 _unit_refs(ctx, _COM_UNITS))


def _reports(ctx: Ctx) -> _Hits:
    libs = [x for x in ctx.discovery.libraries if x.category == "reporting"]
    return _join(_integrations(ctx, "reporting"), _from_findings(libs),
                 _files(ctx, lambda a: extension_of(a.path) in _REPORT_EXT,
                        "report definition file"),
                 _unit_refs(ctx, _REPORT_UNITS))


def _services(ctx: Ctx) -> _Hits:
    runtime = [r for r in ctx.discovery.runtime_dependencies
               if r.kind == "service"]
    roots = [r for r in ctx.roots if r.shape == "service"]
    root_hits = (len(roots), [file_evidence(r.path, "service application")
                              for r in roots])
    return _join(_integrations(ctx, "windows-service"),
                 _from_findings(runtime), root_hits,
                 _unit_refs(ctx, _SERVICE_UNITS))


def _build_scripts(ctx: Ctx) -> _Hits:
    if ctx.discovery.build_scripts:
        return _from_findings(list(ctx.discovery.build_scripts))
    return _files(ctx, lambda a: a.cls == "build_script", "build script file")


def _documentation(ctx: Ctx) -> _Hits:
    return _files(ctx, lambda a: a.cls in ("documentation", "licence"),
                  "documentation file")


_DETECTORS: dict[str, Callable[[Ctx], _Hits]] = {
    "gui_application": _gui,
    "database": _database,
    "com_activex": _com,
    "reports": _reports,
    "scheduled_jobs": lambda ctx: _integrations(ctx, "scheduled-job"),
    "services": _services,
    "build_scripts": _build_scripts,
    "documentation": _documentation,
    "integrations": lambda ctx: _integrations(ctx),
}


def build_components(ctx: Ctx) -> list[dict[str, Any]]:
    """The nine ``components`` entries in their fixed order."""

    out = []
    for component_id, label in COMPONENTS:
        count, raws = _DETECTORS[component_id](ctx)
        evidence = evidence_list(raws, ctx, _COMPONENT_EVIDENCE)
        present = count > 0 and bool(evidence)
        out.append({
            "id": component_id,
            "label": label,
            "present": present,
            "count": count if present else 0,
            "evidence": evidence if present else [],
        })
    return out

