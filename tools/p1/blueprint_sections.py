"""Blueprint sections that describe *the project itself*.

``stage``, ``project``, ``summary``, ``file_distribution``, ``dialect``,
``projects`` and ``inventory`` (design section 6).  The dependency sections
live in :mod:`p1.blueprint_deps`, the tree and component sections in
:mod:`p1.blueprint_structure`.

Every builder is a pure function of a :class:`~p1.blueprint_common.Ctx`.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import PurePosixPath
from typing import Any

from .blueprint_common import (
    FILE_GROUPS,
    Ctx,
    clean_text,
    evidence_list,
    extension_of,
    file_group,
)
from .findings import DirectoryEntry
from .projects import ProjectRoot, entry_point

__all__ = [
    "build_stage",
    "build_project_info",
    "build_summary",
    "build_file_distribution",
    "build_dialect",
    "build_projects",
    "build_inventory",
    "percentages",
    "dialect_label",
]

STAGE_STEPS = (
    ("ingestion", "Ingestion"),
    ("checkpoint", "Checkpoint"),
    ("scanning_inventory", "Scanning & Inventory"),
    ("dependency_analysis", "Dependency Analysis"),
    ("blueprint", "Application Blueprint"),
)

_DIALECT_LABELS = {
    "delphi": "Delphi / Object Pascal",
    "fpc": "Free Pascal / Lazarus",
    "turbo-pascal": "Turbo Pascal",
    "iso-7185": "ISO 7185 Pascal",
    "unknown": "Unknown",
}
_COMPILER_NAMES = {
    "delphi": "Embarcadero Delphi",
    "fpc": "Free Pascal Compiler (FPC)",
    "unknown": "Unknown",
}
#: Extensions that corroborate a dialect although they are never scanned.
_DIALECT_EXTENSIONS = {
    "delphi": (".dproj", ".dfm", ".bdsproj", ".groupproj"),
    "fpc": (".lpi", ".lfm", ".lpk"),
}
_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}
_SHA_RE = re.compile(r"[0-9a-f]{40}")
#: How many extension-corroboration entries are kept per extension.
_EXTENSION_EVIDENCE_PER_EXT = 3
_DIALECT_EVIDENCE_LIMIT = 12


def dialect_label(dialect: str) -> str:
    """Human label of a dialect id (``Unknown`` for anything unrecognised)."""

    return _DIALECT_LABELS.get(dialect, _DIALECT_LABELS["unknown"])


# ---------------------------------------------------------------------------
# stage / project
# ---------------------------------------------------------------------------


def build_stage(ctx: Ctx, *, blockers: int, actionable_unresolved: int,
                ) -> dict[str, Any]:
    """The ``stage`` block: overall and per-step status (never a failure)."""

    discovery = ctx.discovery
    ingestion_noise = any(
        getattr(d, "severity", None) in ("warning", "error")
        or (isinstance(d, dict) and d.get("severity") in ("warning", "error"))
        for d in discovery.ingestion.diagnostics
    )
    warnings = {
        "ingestion": ingestion_noise,
        "checkpoint": not discovery.checkpoint,
        "scanning_inventory": any(a.analysis_blocker for a in ctx.analysed),
        "dependency_analysis": actionable_unresolved > 0,
        "blueprint": blockers > 0,
    }
    steps = [
        {"id": step_id, "name": name,
         "status": ("COMPLETED_WITH_WARNINGS" if warnings[step_id]
                    else "COMPLETED")}
        for step_id, name in STAGE_STEPS
    ]
    with_blockers = blockers > 0  # includes UNRESOLVED_DEPENDENCIES
    return {
        "id": 1,
        "name": "Ingestion and Discovery",
        "status": "COMPLETED_WITH_BLOCKERS" if with_blockers else "COMPLETED",
        "steps": steps,
    }


def _pick(*values: object) -> str:
    for value in values:
        if value:
            return str(value)
    return ""


def build_project_info(ctx: Ctx) -> dict[str, Any]:
    """The ``project`` block: name, ingestion source and checkpoint."""

    discovery = ctx.discovery
    ingestion = discovery.ingestion
    checkpoint = discovery.checkpoint or {}
    cp_source = checkpoint.get("source") or {}
    prov = discovery.source_provenance or {}
    commit = _pick(cp_source.get("commit"), prov.get("commit"),
                   ingestion.commit)
    name = _pick(discovery.origin_label, ingestion.origin)
    if not name and ctx.roots:
        name = PurePosixPath(ctx.roots[0].path).stem
    return {
        "name": clean_text(name or "unnamed"),
        "ingestion_source": {
            "kind": _pick(cp_source.get("kind"), ingestion.kind),
            "origin": clean_text(_pick(prov.get("remote"),
                                       cp_source.get("origin"), name)),
            "ref": clean_text(_pick(cp_source.get("ref"), prov.get("ref"))),
            "commit": commit if _SHA_RE.fullmatch(commit) else "",
            "commit_timestamp": _pick(cp_source.get("commit_timestamp"),
                                      ingestion.commit_timestamp),
        },
        "checkpoint": {
            "id": _pick(checkpoint.get("checkpoint_id")),
            "source_digest": _pick(checkpoint.get("source_digest")),
            "tree_id": _pick(cp_source.get("tree_id"), prov.get("tree_id")),
            "file_count": int(checkpoint.get("file_count",
                                             len(ctx.analysed))),
            "directory_count": int(checkpoint.get("directory_count", 0)),
        },
    }


# ---------------------------------------------------------------------------
# summary / distribution
# ---------------------------------------------------------------------------


def build_summary(ctx: Ctx, *, directories: int, diagnostics: list[dict],
                  unresolved_actionable: int, blockers: int,
                  external: int) -> dict[str, Any]:
    """The ``summary`` tiles (all integers)."""

    discovery = ctx.discovery
    classes = Counter(a.cls for a in ctx.analysed)
    groups = Counter(file_group(a) for a in ctx.analysed)
    severities = Counter(str(d.get("severity", "")) for d in diagnostics)
    database_files = classes["sql"] + classes["database"]
    return {
        "total_files": len(ctx.analysed),
        "directories": directories,
        "total_bytes": sum(a.inventory.size for a in ctx.analysed),
        "pascal_sources": groups["pascal_source"],
        "forms": classes["ui_definition"],
        "projects": len(ctx.roots),
        "packages": classes["pascal_package"],
        "database_artifacts": database_files + len(discovery.database),
        "external_dependencies": external,
        "unresolved_dependencies": unresolved_actionable,
        "diagnostics": {
            "error": severities["error"],
            "warning": severities["warning"],
            "info": severities["info"],
        },
        "blockers": blockers,
    }


def percentages(counts: list[int], total: int) -> list[float]:
    """Percent per count, 1 dp, summing to exactly 100.0 (largest remainder).

    Integer arithmetic only, so the result is identical on every platform.
    ``total == 0`` yields all zeros and never divides.
    """

    if total <= 0:
        return [0.0 for _ in counts]
    tenths = [c * 1000 // total for c in counts]
    order = sorted(range(len(counts)),
                   key=lambda i: (-(counts[i] * 1000 % total), i))
    for index in order[: 1000 - sum(tenths)]:
        tenths[index] += 1
    return [t / 10 for t in tenths]


def build_file_distribution(ctx: Ctx) -> dict[str, Any]:
    """The ``file_distribution`` block (design section 6)."""

    total = len(ctx.analysed)
    counts = Counter(file_group(a) for a in ctx.analysed)
    ordered = [counts[group_id] for group_id, _ in FILE_GROUPS]
    percent = percentages(ordered, total)
    by_extension = Counter(extension_of(a.path) or "(none)"
                           for a in ctx.analysed)
    return {
        "total": total,
        "groups": [
            {"id": group_id, "label": label, "count": ordered[i],
             "percent": percent[i]}
            for i, (group_id, label) in enumerate(FILE_GROUPS)
        ],
        "by_class": {k: v for k, v in sorted(
            Counter(a.cls for a in ctx.analysed).items())},
        "by_extension": {k: v for k, v in sorted(by_extension.items())},
    }


# ---------------------------------------------------------------------------
# dialect
# ---------------------------------------------------------------------------


def _parse_compiler_signal(signal: str) -> dict[str, object] | None:
    """Turn ``path``, ``path (note)`` or ``path:line (note)`` into evidence."""

    text = "file extension or project metadata"
    path = signal
    match = re.fullmatch(r"(.*?) \((.*)\)", signal)
    if match:
        path, text = match.group(1), match.group(2)
    line = 0
    located = re.fullmatch(r"(.*):(\d+)", path)
    if located:
        path, line = located.group(1), int(located.group(2))
    if not path:
        return None
    return {"file": path, "line": line, "column": 0,
            "text": f"compiler signal: {text}"}


def _dialect_evidence(ctx: Ctx, primary: str) -> list[dict[str, object]]:
    lined: list[dict[str, object]] = []
    plain: list[dict[str, object]] = []
    for item in ctx.analysed:
        analysis = item.analysis
        if analysis is None or analysis.dialect != primary:
            continue
        for raw in analysis.dialect_evidence:
            entry = dict(raw)
            entry["file"] = item.path
            (lined if raw.get("line") else plain).append(entry)
    for ext in _DIALECT_EXTENSIONS.get(primary, ()):
        hits = [a.path for a in ctx.analysed if extension_of(a.path) == ext]
        for path in hits[:_EXTENSION_EVIDENCE_PER_EXT]:
            plain.append({"file": path, "line": 1, "column": 1,
                          "text": f"{ext} file typical of "
                                  f"{dialect_label(primary)}"})
    first = evidence_list(lined, ctx, _DIALECT_EVIDENCE_LIMIT)
    rest = evidence_list(plain, ctx, _DIALECT_EVIDENCE_LIMIT)
    return (first + rest)[:_DIALECT_EVIDENCE_LIMIT]


def _compiler_block(ctx: Ctx) -> dict[str, Any]:
    reqs = ctx.discovery.build_requirements
    compiler = str(reqs.get("compiler") or "unknown")
    if compiler not in _COMPILER_NAMES:
        compiler = "unknown"
    signals = (reqs.get("compiler_evidence") or {}).get(compiler, [])
    raws = [_parse_compiler_signal(str(s)) for s in signals]
    return {
        "name": _COMPILER_NAMES[compiler],
        "status": "UNKNOWN" if compiler == "unknown" else "PARTIAL",
        "evidence": evidence_list([r for r in raws if r], ctx, 10),
        "_id": compiler,
    }


def _project_versions(ctx: Ctx) -> list[tuple[str, str]]:
    """``(value, source-file)`` pairs for every stated ``ProjectVersion``."""

    found: set[tuple[str, str]] = set()
    for root in ctx.roots:
        for entry in root.profile.evidence:
            text = str(entry.get("evidence", ""))
            if text.startswith("project_version="):
                name = str(entry.get("source", ""))
                source = next((m for m in root.meta_files
                               if PurePosixPath(m).name == name), name)
                found.add((text.split("=", 1)[1], source))
    for config in ctx.discovery.compiler_configs:
        for key, value in config.switches:
            if key.lower() in ("projectversion", "project_version") and value:
                found.add((value, config.path))
    return sorted(found)


def _version_block(ctx: Ctx) -> dict[str, str]:
    found = _project_versions(ctx)
    if not found:
        return {"value": "unknown", "status": "UNKNOWN",
                "source": "not stated by any project file in the input"}
    values = sorted({v for v, _ in found})
    # The release name is deliberately not inferred: a ProjectVersion-to-
    # release table cannot be cited from the input, so the raw value is
    # reported and the mapping is left to the reader.
    return {
        "value": ", ".join(f"ProjectVersion {v}" for v in values),
        "status": "PARTIAL",
        "source": "; ".join(f"{src} (ProjectVersion={v})" for v, src in found),
    }


def _primary_dialect(ctx: Ctx, by_dialect: Counter, compiler: str) -> str:
    known = sorted(((-n, d) for d, n in by_dialect.items()
                    if d != "unknown"))
    if known:
        return known[0][1]
    return compiler if compiler in ("delphi", "fpc") else "unknown"


def build_dialect(ctx: Ctx) -> dict[str, Any]:
    """The ``dialect`` block, with the evidence of the detected dialect."""

    by_dialect = Counter(a.analysis.dialect for a in ctx.analysed
                         if a.analysis is not None)
    compiler = _compiler_block(ctx)
    compiler_id = compiler.pop("_id")
    primary = _primary_dialect(ctx, by_dialect, compiler_id)
    evidence = _dialect_evidence(ctx, primary) if primary != "unknown" else []
    if primary != "unknown" and not evidence:
        evidence = compiler["evidence"]
    rank = max((_CONFIDENCE_RANK.get(a.analysis.confidence, 0)
                for a in ctx.analysed
                if a.analysis is not None and a.analysis.dialect == primary),
               default=1)
    confidence = {3: "high", 2: "medium"}.get(rank, "low")
    return {
        "primary": primary,
        "label": dialect_label(primary),
        "confidence": confidence if primary != "unknown" else "low",
        "status": "UNKNOWN" if primary == "unknown" else "PARTIAL",
        "evidence": evidence,
        "compiler": compiler,
        "version": _version_block(ctx),
        "by_dialect": {k: v for k, v in sorted(by_dialect.items())},
    }


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------


def _stem_key(path: str) -> tuple[str, str]:
    pure = PurePosixPath(path)
    return pure.parent.as_posix().lower(), pure.stem.lower()


def _root_evidence(ctx: Ctx, root: ProjectRoot, entry: dict) -> list[dict]:
    local = {PurePosixPath(p).name: p for p in [root.path, *root.meta_files]}
    raws: list[dict[str, object]] = []
    for group in (root.evidence, root.shape_evidence, root.profile.evidence):
        for raw in group:
            item = dict(raw)
            item["file"] = local.get(str(raw.get("source", "")),
                                     str(raw.get("source", "")))
            raws.append(item)
    location = str(entry.get("location") or "")
    if location:
        path, line, column = location.rsplit(":", 2)
        raws.append({"file": path, "line": int(line), "column": int(column),
                     "text": f"declares `{entry['kind']} "
                             f"{entry['declared_name']}`"})
    return evidence_list(raws, ctx)


def _project_counts(ctx: Ctx, root: ProjectRoot) -> tuple[int, int, int]:
    """``(unit_count, form_count, package_count)`` of one project.

    ``unit_count`` is the number of ``pascal_unit`` files reachable from the
    project (include files and the program file are not units).  A unit or
    form shared by two projects is counted for each project that reaches it;
    the ``structure`` tree lists it once, under its owner.  A form belongs to
    a project when the unit with the same directory and stem is reachable.
    """

    reached = [ctx.by_path[p] for p in ctx.reach.get(root.path, ())
               if p in ctx.by_path]
    units = [a for a in reached if a.cls == "pascal_unit"]
    unit_keys = {_stem_key(a.path) for a in units}
    forms = sum(1 for a in ctx.analysed
                if a.cls == "ui_definition" and _stem_key(a.path) in unit_keys)
    packages = len({e.dst for e in ctx.edges
                    if e.src == f"file:{root.path}"
                    and e.relation == "requires"})
    return len(units), forms, packages


def _profile_block(root: ProjectRoot) -> dict[str, Any]:
    full = root.profile.as_dict()
    full.pop("evidence", None)
    return full


def build_projects(ctx: Ctx) -> list[dict[str, Any]]:
    """The ``projects`` list, primary first."""

    out: list[dict[str, Any]] = []
    for root in ctx.roots:
        item = ctx.by_path.get(root.path)
        entry = entry_point(root, item.scan if item else None,
                            item.analysis if item else None)
        location = str(entry.get("location") or "")
        line = column = 0
        if location:
            _, line_text, column_text = location.rsplit(":", 2)
            line, column = int(line_text), int(column_text)
        units, forms, packages = _project_counts(ctx, root)
        out.append({
            "path": root.path,
            "kind": root.kind,
            "primary": root.primary,
            "shape": root.shape,
            "status": root.status,
            "entry_point": {"file": root.path, "line": line,
                            "column": column},
            "profile": _profile_block(root),
            "meta_files": sorted(root.meta_files),
            "unit_count": units,
            "form_count": forms,
            "package_count": packages,
            "evidence": _root_evidence(ctx, root, entry),
        })
    return out


# ---------------------------------------------------------------------------
# inventory
# ---------------------------------------------------------------------------


def derive_directories(ctx: Ctx) -> list[DirectoryEntry]:
    """Directory entries derived from file paths (no empty directories)."""

    direct: Counter = Counter()
    total: Counter = Counter()
    size: Counter = Counter()
    for item in ctx.analysed:
        parts = item.path.split("/")[:-1]
        for depth in range(1, len(parts) + 1):
            name = "/".join(parts[:depth])
            total[name] += 1
            size[name] += item.inventory.size
        if parts:
            direct["/".join(parts)] += 1
    return [
        DirectoryEntry(path=name, depth=name.count("/") + 1,
                       file_count=direct[name], total_file_count=total[name],
                       total_bytes=size[name], empty=False)
        for name in sorted(total)
    ]


def directory_entries(ctx: Ctx) -> list[dict[str, object]]:
    """Every directory entry, sorted by path."""

    entries = ctx.discovery.directories or derive_directories(ctx)
    return sorted((d.as_dict() for d in entries),
                  key=lambda d: str(d["path"]))


def build_inventory(ctx: Ctx) -> dict[str, Any]:
    """The ``inventory`` block (the full file list is ``inventory.csv``)."""

    return {
        "directories": directory_entries(ctx),
        "file_count": len(ctx.analysed),
        "files_ref": "inventory.csv",
    }
