"""Versioned machine-readable reports derived from the serialised discovery.

Stage 1 publishes three *derived* documents alongside the blueprint.  They
contain no analysis of their own: every field is projected from data that is
already computed and written elsewhere, so they can never disagree with the
blueprint, the checkpoint or the dependency graph:

``checkpoint-manifest.json``
    the frozen source identity and the complete per-file SHA-256 list of the
    checkpoint the analysis read, plus the integrity seal that protects it.

``project-inventory.json``
    the catalogue of discovered projects, applications, entry points, dialect
    and compiler profile.

``architecture-report.json``
    the application architecture view: shapes, build and runtime requirements,
    configuration inventory, databases, integrations, libraries, diagnostics,
    unresolved dependencies and modernization blockers.

All three are deterministic projections: same blueprint, same bytes.  Wall
clock, absolute paths and tenant identifiers never appear (staging roots are
scrubbed exactly as in the blueprint).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .errors import IngestionError

__all__ = [
    "CHECKPOINT_MANIFEST_SCHEMA",
    "PROJECT_INVENTORY_SCHEMA",
    "ARCHITECTURE_REPORT_SCHEMA",
    "build_checkpoint_manifest",
    "build_project_inventory",
    "build_architecture_report",
    "write_derived_reports",
]

CHECKPOINT_MANIFEST_SCHEMA = "stage1.checkpoint-manifest/1.0"
PROJECT_INVENTORY_SCHEMA = "stage1.project-inventory/1.0"
ARCHITECTURE_REPORT_SCHEMA = "stage1.architecture-report/1.0"

_FILES = "checkpoint.json"
_REQUIRED = ("checkpoint_id", "source", "source_digest", "file_count",
             "directory_count", "total_bytes", "files")


# ---------------------------------------------------------------------------
# checkpoint-manifest.json
# ---------------------------------------------------------------------------


def build_checkpoint_manifest(document: dict[str, Any]) -> dict[str, Any]:
    """Project the sealed ``checkpoint.json`` document into the manifest.

    Raises :class:`~p1.errors.IngestionError` when a required field is
    missing: a checkpoint we cannot fully describe is not published as one.
    """

    missing = [key for key in _REQUIRED if key not in document]
    if missing:
        raise IngestionError(
            "the checkpoint metadata is incomplete; refusing to publish a "
            "checkpoint manifest",
            code="CHECKPOINT_INVALID",
        )
    if not isinstance(document["files"], list) or not isinstance(
            document.get("directories"), list):
        raise IngestionError(
            "the checkpoint file list is malformed", code="CHECKPOINT_INVALID")
    return {
        "schema_version": CHECKPOINT_MANIFEST_SCHEMA,
        "checkpoint_id": document["checkpoint_id"],
        "source": document["source"],
        "source_digest": document["source_digest"],
        "file_count": document["file_count"],
        "directory_count": document["directory_count"],
        "total_bytes": document["total_bytes"],
        "read_only": True,
        "integrity": {
            "content_algorithm": "sha256",
            "seal_kind": document.get("seal_kind", ""),
            "sealed": bool(document.get("seal")),
            "files": [{"path": f["path"], "sha256": f["sha256"],
                       "size": f["size"]}
                      for f in sorted(document["files"],
                                      key=lambda f: str(f.get("path", "")))],
        },
        "directories": sorted(document["directories"]),
        "seal": document.get("seal"),
    }


# ---------------------------------------------------------------------------
# project-inventory.json
# ---------------------------------------------------------------------------


def build_project_inventory(blueprint: dict[str, Any]) -> dict[str, Any]:
    """The project / application catalogue of *blueprint*."""

    projects = blueprint.get("projects") or []
    summary = blueprint.get("summary") or {}
    return {
        "schema_version": PROJECT_INVENTORY_SCHEMA,
        "project": blueprint.get("project", {}),
        "stage": {
            "id": (blueprint.get("stage") or {}).get("id"),
            "name": (blueprint.get("stage") or {}).get("name"),
            "status": (blueprint.get("stage") or {}).get("status"),
        },
        "dialect": blueprint.get("dialect", {}),
        "projects": projects,
        "entry_points": [
            {
                "project": p.get("path"),
                "primary": bool(p.get("primary")),
                "kind": p.get("kind"),
                "shape": p.get("shape"),
                "entry_point": p.get("entry_point"),
            }
            for p in projects
        ],
        "file_distribution": blueprint.get("file_distribution", {}),
        "counts": {
            "projects": summary.get("projects"),
            "pascal_sources": summary.get("pascal_sources"),
            "packages": summary.get("packages"),
            "forms": summary.get("forms"),
            "total_files": summary.get("total_files"),
            "directories": summary.get("directories"),
        },
    }


# ---------------------------------------------------------------------------
# architecture-report.json
# ---------------------------------------------------------------------------


def _counts(items: Any) -> dict[str, int]:
    out: dict[str, int] = {}
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict):
                key = str(item.get("status") or item.get("kind") or "unknown")
                out[key] = out.get(key, 0) + 1
    return dict(sorted(out.items()))


def _present_components(blueprint: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {"id": c.get("id"), "label": c.get("label"), "count": c.get("count"),
         "evidence": c.get("evidence", [])}
        for c in (blueprint.get("components") or [])
        if c.get("present")
    ]


def _diagnostic_index(diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    by_severity: dict[str, int] = {}
    by_code: dict[str, int] = {}
    for item in diagnostics:
        severity = str(item.get("severity", "unknown"))
        code = str(item.get("code", "UNKNOWN"))
        by_severity[severity] = by_severity.get(severity, 0) + 1
        by_code[code] = by_code.get(code, 0) + 1
    return {
        "by_severity": dict(sorted(by_severity.items())),
        "by_code": dict(sorted(by_code.items())),
        "items": diagnostics,
    }


def _unresolved_index(unresolved: list[dict[str, Any]]) -> dict[str, Any]:
    by_severity: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for item in unresolved:
        severity = str(item.get("severity", "unknown"))
        kind = str(item.get("kind", "unknown"))
        by_severity[severity] = by_severity.get(severity, 0) + 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {
        "count": len(unresolved),
        "by_severity": dict(sorted(by_severity.items())),
        "by_kind": dict(sorted(by_kind.items())),
        "items": unresolved,
    }


def build_architecture_report(blueprint: dict[str, Any]) -> dict[str, Any]:
    """The architecture view of *blueprint* (a projection, not new analysis)."""

    dependencies = blueprint.get("dependencies") or {}
    build = dependencies.get("build") or {}
    summary = blueprint.get("summary") or {}
    stage = blueprint.get("stage") or {}
    return {
        "schema_version": ARCHITECTURE_REPORT_SCHEMA,
        "project": blueprint.get("project", {}),
        "stage": {"id": stage.get("id"), "name": stage.get("name"),
                  "status": stage.get("status"),
                  "steps": stage.get("steps", [])},
        "dialect_and_compiler": blueprint.get("dialect", {}),
        "application": {
            "components": _present_components(blueprint),
            "projects": [
                {"path": p.get("path"), "kind": p.get("kind"),
                 "shape": p.get("shape"), "primary": p.get("primary"),
                 "status": p.get("status"),
                 "entry_point": p.get("entry_point")}
                for p in (blueprint.get("projects") or [])
            ],
        },
        "build_requirements": {
            "requirements": build.get("requirements", []),
            "scripts": build.get("scripts", []),
            "compiler_configs": [
                {key: cfg.get(key)
                 for key in ("path", "kind", "scope", "status", "confidence")}
                for cfg in (build.get("compiler_configs") or [])
            ],
        },
        "runtime_requirements": {
            "count": len(dependencies.get("runtime") or []),
            "by_status": _counts(dependencies.get("runtime")),
            "items": dependencies.get("runtime", []),
        },
        "configuration_and_environment": {
            "runtime_dependency_kinds": sorted({
                str(item.get("kind", "")) for item in
                (dependencies.get("runtime") or []) if isinstance(item, dict)}),
            "compiler_config_paths": [
                cfg.get("path") for cfg in (build.get("compiler_configs") or [])
            ],
            "build_script_paths": [
                s.get("path") if isinstance(s, dict) else s
                for s in (build.get("scripts") or [])
            ],
        },
        "databases": dependencies.get("databases", []),
        "sql_files": dependencies.get("sql_files", []),
        "integrations": dependencies.get("integrations", []),
        "libraries": dependencies.get("libraries", []),
        "native_libraries": dependencies.get("native_libraries", []),
        "file_classes": (blueprint.get("file_distribution") or {}).get(
            "by_class", {}),
        "security_diagnostics": _diagnostic_index(
            blueprint.get("diagnostics") or []),
        "missing_source_and_unresolved": _unresolved_index(
            blueprint.get("unresolved") or []),
        "modernization_blockers": blueprint.get("blockers", []),
        "capability_states": blueprint.get("capability_states", []),
        "summary": {
            key: summary.get(key)
            for key in ("total_files", "directories", "pascal_sources",
                        "projects", "packages", "forms",
                        "external_dependencies", "unresolved_dependencies",
                        "database_artifacts", "blockers")
        },
        "limitations": list(blueprint.get("limitations") or []),
    }


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------


#: Roots shorter than this are ignored so a trivial path cannot corrupt unrelated text.
_MIN_NEEDLE = 8


def _needles(*roots: str) -> list[str]:
    out: list[str] = []
    for root in roots:
        if len(root.strip("/\\")) < _MIN_NEEDLE:
            continue
        forms = (root, root.replace("/", "\\"), root.replace("\\", "/"),
                 root.replace("\\", "\\\\"),
                 root.replace("/", "\\").replace("\\", "\\\\"))
        out.extend(form for form in forms if form not in out)
    return sorted(out, key=lambda s: (-len(s), s))


def _write(outdir: Path, name: str, payload: dict[str, Any],
           needles: list[str]) -> Path:
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True)
    for needle in needles:
        if needle:
            text = text.replace(needle, "<staging>")
    path = outdir / name
    path.write_text(text + "\n", encoding="utf-8", newline="\n")
    return path


def write_derived_reports(
    blueprint: dict[str, Any],
    checkpoint_document: dict[str, Any],
    outdir: Path,
    *,
    staging_roots: tuple[str, ...] = (),
) -> dict[str, str]:
    """Write the three derived reports into *outdir*; return POSIX paths.

    *checkpoint_document* is the parsed ``checkpoint.json`` of the checkpoint
    the analysis read.  A checkpoint we cannot describe fails the run instead
    of publishing a partial manifest.
    """

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    needles = _needles(*staging_roots)
    paths = {
        "checkpoint_manifest": _write(
            outdir, "checkpoint-manifest.json",
            build_checkpoint_manifest(checkpoint_document), needles),
        "project_inventory": _write(
            outdir, "project-inventory.json",
            build_project_inventory(blueprint), needles),
        "architecture_report": _write(
            outdir, "architecture-report.json",
            build_architecture_report(blueprint), needles),
    }
    return {key: path.as_posix() for key, path in paths.items()}
