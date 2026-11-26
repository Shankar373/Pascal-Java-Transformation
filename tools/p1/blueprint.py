"""Stage 1 Application Blueprint (``stage1.application-blueprint/1.0``).

:func:`build_blueprint` turns one :class:`~p1.emit.Discovery` into the
evidence-backed, machine-readable blueprint described in
``docs/stage1/STAGE1_DESIGN.md`` section 6; :func:`write_blueprint_outputs`
writes it together with its auxiliary reports.

Guarantees
----------

* **Pure and deterministic.**  No clock, no environment, no file-system
  access; every list is sorted by a stable key, so two runs - and two runs
  over differently ordered inputs - serialise to identical bytes.
* **No absolute paths.**  Staging roots are scrubbed from every string.
* **Credential-free.**  Free text is passed through the same redaction the
  detectors use; URL userinfo is stripped.
* **Evidence-backed.**  Every item of ``dependencies.*``, ``projects``,
  ``components`` (when present) and ``dialect`` (when detected) carries at
  least one located ``{file, line, column, text}`` observation.
* **Nothing pruned.**  ``unresolved`` is a superset of the unresolved edges
  of the dependency graph.

The section builders live in :mod:`p1.blueprint_sections`,
:mod:`p1.blueprint_deps` and :mod:`p1.blueprint_structure`.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

from .blueprint_common import Ctx, clean_text, extension_of, make_ctx
from .blueprint_deps import (
    actionable,
    build_dependencies,
    build_graphs,
    build_unresolved,
    external_dependency_count,
)
from .blueprint_sections import (
    build_dialect,
    build_file_distribution,
    build_inventory,
    build_project_info,
    build_projects,
    build_stage,
    build_summary,
)
from .blueprint_structure import build_components, build_structure
from .emit import Discovery, _merge_diagnostics, _serialise, capability_states

__all__ = [
    "BLUEPRINT_SCHEMA",
    "UNRESOLVED_SCHEMA",
    "DIAGNOSTICS_SCHEMA",
    "LIMITATIONS",
    "build_blueprint",
    "write_blueprint_outputs",
    "render_inventory_csv",
]

BLUEPRINT_SCHEMA = "stage1.application-blueprint/1.0"
UNRESOLVED_SCHEMA = "stage1.unresolved/1.0"
DIAGNOSTICS_SCHEMA = "stage1.diagnostics/1.0"

#: What Stage 1 deliberately does not determine (design section 10).
LIMITATIONS: tuple[str, ...] = (
    "Discovery is syntactic: no symbol table and no cross-unit type "
    "resolution (Stage 2).",
    "No semantic intermediate representation is built (Stage 2).",
    "Binary files (.exe, .dll, .bpl, .dcu, .ocx ...) are inventoried and "
    "hashed but never decompiled or executed.",
    "No compiler is invoked and no build is attempted; the compiler named "
    "is inferred from file extensions, directives and project metadata.",
    "Databases are never connected to; database technologies and SQL "
    "dialects are detected from source and SQL files only.",
    "Dependency resolution is limited to the ingested input: a unit or "
    "library that is absent is reported as unresolved, not searched for.",
    "Library, integration and runtime-dependency detection is "
    "heuristic (PARTIAL); a finding is evidence of a reference, not proof "
    "that the dependency is exercised at run time.",
    "Evidence lists are capped at 25 entries per item and the structure "
    "tree at 50 files per group; the full file list is in inventory.csv.",
    "Delphi ProjectVersion values are reported as stated; they are not "
    "mapped to a product release name.",
    "GUI forms are detected and counted, not converted; GUI conversion is "
    "out of scope for the first release.",
    "Nothing in this blueprint is VERIFIED: equivalence with a Java "
    "translation is only measurable from Stage 5.",
)

_MIN_NEEDLE = 4


# ---------------------------------------------------------------------------
# assembly
# ---------------------------------------------------------------------------


def _diagnostics(discovery: Discovery) -> list[dict[str, Any]]:
    """Merged diagnostics; a missing severity defaults to ``warning``."""

    out = []
    for raw in _merge_diagnostics(discovery):
        item = dict(raw)
        item.setdefault("severity", "warning")
        item["message"] = clean_text(item.get("message", ""))
        out.append(item)
    return out


def _blockers(discovery: Discovery,
              todo: list[dict[str, Any]]) -> list[dict[str, str]]:
    found = {
        (clean_text(b.get("code", "")), clean_text(b.get("detail", "")))
        for b in discovery.build_requirements.get("blockers", [])
    }
    if todo:
        errors = sum(1 for u in todo if u["severity"] == "error")
        found.add((
            "UNRESOLVED_DEPENDENCIES",
            f"{len(todo)} unresolved dependenc"
            f"{'y' if len(todo) == 1 else 'ies'} need attention "
            f"({errors} error, {len(todo) - errors} warning)",
        ))
    return [{"code": c, "detail": d} for c, d in sorted(found)]


def _needles(discovery: Discovery, extra: tuple[str, ...] = ()) -> list[str]:
    """Staging paths to scrub, in every separator form."""

    raw = [str(discovery.ingestion.staging_root), *extra]
    out: list[str] = []
    for root in raw:
        if len(root.strip("/\\")) < _MIN_NEEDLE:
            continue
        forms = (root, root.replace("/", "\\"), root.replace("\\", "/"),
                 root.replace("\\", "\\\\"),
                 root.replace("/", "\\").replace("\\", "\\\\"))
        for form in forms:
            if form not in out:
                out.append(form)
    return sorted(out, key=lambda s: (-len(s), s))


def _roots(roots: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(r) for r in roots if r)


def _scrub(value: Any, needles: list[str]) -> Any:
    if isinstance(value, str):
        for needle in needles:
            value = value.replace(needle, "<staging>")
        return value
    if isinstance(value, list):
        return [_scrub(v, needles) for v in value]
    if isinstance(value, dict):
        return {k: _scrub(v, needles) for k, v in value.items()}
    return value


def _sections(ctx: Ctx, diagnostics: list[dict[str, Any]],
              unresolved: list[dict[str, Any]],
              blockers: list[dict[str, str]]) -> dict[str, Any]:
    todo = actionable(unresolved)
    inventory = build_inventory(ctx)
    project = build_project_info(ctx)
    return {
        "schema_version": BLUEPRINT_SCHEMA,
        "generator": {"llm_assisted": False, "stage": 1, "tool": "tools/p1"},
        "stage": build_stage(ctx, blockers=len(blockers),
                             actionable_unresolved=len(todo)),
        "project": project,
        "summary": build_summary(
            ctx, directories=len(inventory["directories"]),
            diagnostics=diagnostics, unresolved_actionable=len(todo),
            blockers=len(blockers),
            external=external_dependency_count(ctx)),
        "file_distribution": build_file_distribution(ctx),
        "dialect": build_dialect(ctx),
        "projects": build_projects(ctx),
        "structure": build_structure(ctx, project["name"]),
        "dependencies": build_dependencies(ctx),
        "unresolved": unresolved,
        "graphs": build_graphs(ctx, unresolved),
        "components": build_components(ctx),
        "inventory": inventory,
        "diagnostics": diagnostics,
        "blockers": blockers,
        "capability_states": capability_states(ctx.discovery),
        "limitations": list(LIMITATIONS),
    }


def build_blueprint(discovery: Discovery, *,
                    scrub_roots: tuple[str, ...] = ()) -> dict[str, Any]:
    """Build the Application Blueprint for *discovery* (pure, deterministic).

    The ingestion staging root and every path in *scrub_roots* are replaced
    by ``<staging>`` in every string, exactly as the written files are.
    """

    ctx = make_ctx(discovery)
    unresolved = build_unresolved(ctx)
    blockers = _blockers(discovery, actionable(unresolved))
    document = _sections(ctx, _diagnostics(discovery), unresolved, blockers)
    return _scrub(document, _needles(discovery, _roots(scrub_roots)))


# ---------------------------------------------------------------------------
# inventory.csv
# ---------------------------------------------------------------------------

_CSV_COLUMNS = ("path", "class", "extension", "size", "sha256", "encoding",
                "analysis_blocker")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _safe_cell(value: object) -> object:
    """Neutralise spreadsheet formula injection (OWASP CSV-injection rule)."""

    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def render_inventory_csv(discovery: Discovery) -> str:
    """``inventory.csv``: LF line endings, sorted by path, injection-safe.

    Every text cell, the ``path`` cell included, that starts with a formula
    character (``= + - @``, tab, CR) is prefixed with ``'``.  CSV quoting
    cannot stop a spreadsheet from evaluating such a cell, so the path cannot
    be both verbatim and injection-safe; safety wins.  The real path is
    recovered by removing exactly one leading apostrophe from a path that
    starts with ``'`` followed by a formula character.
    """

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(_CSV_COLUMNS)
    for item in sorted(discovery.analysed, key=lambda a: a.path):
        writer.writerow([_safe_cell(v) for v in (
            item.path, item.cls, extension_of(item.path), item.inventory.size,
            item.inventory.sha256, item.encoding, item.analysis_blocker)])
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------


def write_blueprint_outputs(
    discovery: Discovery,
    outdir: Path,
    *,
    staging_roots: tuple[str, ...] = (),
    blueprint: dict[str, Any] | None = None,
) -> dict[str, str]:
    """Write the blueprint and its auxiliary reports into *outdir*.

    Writes ``application-blueprint.json``, ``unresolved-dependencies.json``,
    ``diagnostics.json`` and ``inventory.csv``; returns their POSIX paths
    keyed ``blueprint``, ``unresolved``, ``diagnostics`` and ``inventory``.
    ``run-record.json`` and the three P1 outputs are not touched.  A
    *blueprint* built earlier (``build_blueprint(discovery, scrub_roots=...)``)
    is written as given - it is not built a second time - and is scrubbed
    again with *staging_roots*, which is idempotent.
    """

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    needles = _needles(discovery, _roots(staging_roots))
    if blueprint is None:
        blueprint = build_blueprint(discovery)

    severities = blueprint["summary"]["diagnostics"]
    documents = {
        "blueprint": ("application-blueprint.json", blueprint),
        "unresolved": ("unresolved-dependencies.json", {
            "schema_version": UNRESOLVED_SCHEMA,
            "count": len(blueprint["unresolved"]),
            "items": blueprint["unresolved"],
        }),
        "diagnostics": ("diagnostics.json", {
            "schema_version": DIAGNOSTICS_SCHEMA,
            "counts": dict(severities),
            "items": blueprint["diagnostics"],
        }),
    }
    paths: dict[str, Path] = {}
    for key, (name, payload) in documents.items():
        paths[key] = outdir / name
        # Scrub the data, not the serialised text: JSON escapes backslashes,
        # so a Windows path would no longer match its needle after dumps().
        paths[key].write_text(_serialise(_scrub(payload, needles), []),
                              encoding="utf-8", newline="\n")
    csv_text = _scrub(render_inventory_csv(discovery), needles)
    paths["inventory"] = outdir / "inventory.csv"
    paths["inventory"].write_bytes(
        csv_text.encode("utf-8", errors="backslashreplace"))
    return {key: value.as_posix() for key, value in paths.items()}
