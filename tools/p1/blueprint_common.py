"""Shared plumbing for the Stage 1 blueprint section builders.

The blueprint (:mod:`p1.blueprint`) is assembled from several small section
builders.  Everything they share lives here:

* :class:`Ctx` - one immutable, pre-indexed view of a :class:`Discovery`
  (sorted files, ordered roots, flattened graph edges, per-project reach);
* evidence normalisation - the legacy detectors emit ``{"evidence", "source",
  "line", "column"}`` dictionaries whose ``source`` is only a *basename*,
  while the Stage 1 findings emit :class:`~p1.findings.Evidence`.  Both are
  turned into the one blueprint shape ``{file, line, column, text}`` here, so
  the evidence rule ("every item cites a located observation") is enforced in
  one place;
* credential redaction for every free-text value that reaches the output.

Nothing here reads the file system, the clock or the environment.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Iterable

from .emit import Discovery
from .findings import Evidence
from .graph import Edge
from .metadata import _redact
from .model import AnalysedFile
from .projects import ProjectRoot

__all__ = [
    "Ctx",
    "make_ctx",
    "clean_text",
    "locate",
    "evidence_list",
    "file_evidence",
    "canonical_sort",
    "file_group",
    "FILE_GROUPS",
    "MAX_EVIDENCE",
    "extension_of",
]

#: Maximum evidence entries kept per item (the findings stay bounded even when
#: a hostile tree references one component ten thousand times).
MAX_EVIDENCE = 25

#: ``(id, label)`` of the file-distribution groups, in output order.
FILE_GROUPS: tuple[tuple[str, str], ...] = (
    ("pascal_source", "Pascal Source (.pas, .pp)"),
    ("project_package", "Project/Package (.dpr, .dpk)"),
    ("form_ui", "Form/UI (.dfm, .xfm)"),
    ("config_build", "Config/Build Scripts"),
    ("other", "Other (Docs, Binaries, etc.)"),
)

_PASCAL_SOURCE_EXT = (".pas", ".pp", ".p", ".inc")
_FORM_EXT = (".dfm", ".lfm", ".fmx", ".xfm")
_PROJECT_CLASSES = frozenset(
    {"pascal_program", "pascal_package", "pascal_project"}
)
_CONFIG_CLASSES = frozenset(
    {"configuration", "build_script", "sql", "database"}
)
_USERINFO = re.compile(r"(?i)(\b[a-z][a-z0-9+.\-]*://)[^/@\s]+@")


def extension_of(path: str) -> str:
    """Lower-case extension of *path* (``""`` when it has none)."""

    return PurePosixPath(path).suffix.lower()


def clean_text(text: object) -> str:
    """Redact credentials (``key=value`` pairs and URL userinfo) from *text*."""

    return _USERINFO.sub(r"\1", _redact(str(text)))


def canonical_sort(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sort dictionaries by their canonical JSON - a total, stable order."""

    return sorted(
        items, key=lambda item: json.dumps(item, sort_keys=True,
                                           ensure_ascii=True)
    )


def file_group(item: AnalysedFile) -> str:
    """The file-distribution group id of *item* (design section 6)."""

    ext = extension_of(item.path)
    if ext in _PASCAL_SOURCE_EXT:
        return "pascal_source"
    if ext in _FORM_EXT:
        return "form_ui"
    if item.cls in ("pascal_unit", "pascal_include"):
        return "pascal_source"
    if item.cls in _PROJECT_CLASSES:
        return "project_package"
    if item.cls == "ui_definition":
        return "form_ui"
    if item.cls in _CONFIG_CLASSES:
        return "config_build"
    return "other"


# ---------------------------------------------------------------------------
# Context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ctx:
    """An immutable, pre-indexed view of one :class:`Discovery`."""

    discovery: Discovery
    analysed: tuple[AnalysedFile, ...]
    by_path: dict[str, AnalysedFile]
    #: lower-case basename -> every input path with that name (sorted).
    paths_by_name: dict[str, tuple[str, ...]]
    #: Primary project first, then by path.
    roots: tuple[ProjectRoot, ...]
    edges: tuple[Edge, ...]
    #: ``root.path`` -> sorted paths reachable through resolved edges.
    reach: dict[str, tuple[str, ...]]


def _paths_by_basename(paths: Iterable[str]) -> dict[str, tuple[str, ...]]:
    seen: dict[str, list[str]] = {}
    for path in sorted(paths):
        seen.setdefault(PurePosixPath(path).name.lower(), []).append(path)
    return {name: tuple(hits) for name, hits in seen.items()}


def _reach(roots: Iterable[ProjectRoot],
           edges: Iterable[Edge]) -> dict[str, tuple[str, ...]]:
    adjacency: dict[str, list[str]] = {}
    for edge in edges:
        if (edge.resolution == "resolved" and edge.src.startswith("file:")
                and edge.dst.startswith("file:")
                and edge.relation in ("uses", "requires", "include")):
            adjacency.setdefault(edge.src[5:], []).append(edge.dst[5:])
    out: dict[str, tuple[str, ...]] = {}
    for root in roots:
        seen: set[str] = {root.path}
        stack = [root.path]
        while stack:
            for nxt in adjacency.get(stack.pop(), []):
                if nxt not in seen:
                    seen.add(nxt)
                    stack.append(nxt)
        out[root.path] = tuple(sorted(seen))
    return out


def make_ctx(discovery: Discovery) -> Ctx:
    """Index *discovery* once; every section builder reads this."""

    analysed = tuple(sorted(discovery.analysed, key=lambda a: a.path))
    roots = tuple(sorted(discovery.roots,
                         key=lambda r: (not r.primary, r.path)))
    edges = tuple(discovery.graph.edges())
    return Ctx(
        discovery=discovery,
        analysed=analysed,
        by_path={a.path: a for a in analysed},
        paths_by_name=_paths_by_basename(a.path for a in analysed),
        roots=roots,
        edges=edges,
        reach=_reach(roots, edges),
    )


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------


def _as_int(value: object) -> int:
    try:
        return max(int(value), 0)  # type: ignore[call-overload]
    except (TypeError, ValueError):
        return 0


def locate(raw: object, ctx: Ctx) -> dict[str, object] | None:
    """Normalise one piece of evidence to ``{file, line, column, text}``.

    Accepts a :class:`~p1.findings.Evidence`, a legacy detector dictionary or
    a bare string.  The returned ``file`` is always an input path: a legacy
    ``source`` that is only a basename is resolved to the input file with that
    name - when several share it, the lexicographically first one (the choice
    is deterministic and the legacy detectors now state full paths, so this
    is only a fallback).  Returns ``None`` when the file is not part of the
    input - such an observation is not located.
    """

    if isinstance(raw, Evidence):
        raw = raw.as_dict()
    if not isinstance(raw, dict):
        return None
    file = str(raw.get("file") or raw.get("source") or "")
    if not file:
        return None
    if file not in ctx.by_path:
        hits = ctx.paths_by_name.get(PurePosixPath(file).name.lower(), ())
        if not hits:
            return None
        file = hits[0]
    text = raw.get("text") or raw.get("evidence") or ""
    return {
        "column": _as_int(raw.get("column")),
        "file": file,
        "line": _as_int(raw.get("line")),
        "text": clean_text(text)[:120],
    }


def evidence_list(raws: Iterable[object], ctx: Ctx,
                  limit: int = MAX_EVIDENCE) -> list[dict[str, object]]:
    """Located, de-duplicated, sorted and capped evidence."""

    seen: dict[tuple[object, ...], dict[str, object]] = {}
    for raw in raws:
        item = locate(raw, ctx)
        if item is not None:
            key = (item["file"], item["line"], item["column"], item["text"])
            seen.setdefault(key, item)
    return [seen[key] for key in sorted(seen)][:limit]


def file_evidence(path: str, text: str) -> dict[str, object]:
    """Evidence that *path* exists in the input (located at its first byte)."""

    return {"column": 1, "file": path, "line": 1, "text": clean_text(text)[:120]}
