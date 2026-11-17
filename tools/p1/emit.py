"""Emit the three P1 output documents (task D1, plan §6).

`application-manifest.json`
    Everything discovered about the ingested application, with evidence.

`dependency-graph.json`
    Nodes, edges, unresolved projection and statistics.

`discovery-report.md`
    A human rendering of the same data — no information exists only in the
    prose, and nothing in the prose exists only in the prose.

Determinism (IR invariant I6)
-----------------------------

Every document is produced by pure functions of the discovery result:

* ``json.dumps(..., sort_keys=True, indent=2)`` plus exactly one trailing
  newline;
* every collection sorted by a stable key (paths use ``/``);
* **no wall-clock time**, no absolute or staging paths, no randomness;
* source-derived timestamps only (ZIP DOS time, Git commit time).

The staging directory is scrubbed from every string on the way out, so a
temp path can never leak into an artefact.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from .dialects import MODE_TABLE, SourceAnalysis, visibility_for
from .findings import (
    BuildScriptFinding,
    CompilerConfigFinding,
    DirectoryEntry,
    IntegrationFinding,
    LibraryFinding,
    RuntimeDependencyFinding,
)
from .graph import DependencyGraph
from .limits import Limits
from .metadata import (
    DatabaseFinding,
    NativeLibraryFinding,
    OsDependencyFinding,
    SqlFileFinding,
)
from .model import AnalysedFile, IngestionResult
from .projects import ProjectRoot, entry_point
from .statuses import CapabilityState, validate_states

__all__ = [
    "MANIFEST_SCHEMA",
    "GRAPH_SCHEMA",
    "Discovery",
    "build_manifest",
    "build_graph_document",
    "render_report",
    "write_outputs",
    "capability_states",
]

MANIFEST_SCHEMA = "p1.application-manifest/1.0"
GRAPH_SCHEMA = "p1.dependency-graph/1.0"

#: Paths referenced by capability states as evidence.  Referenced by name so a
#: reader (and a test) can check the citations resolve without re-deriving them.
_E = "docs/p0/evidence/"

# ---------------------------------------------------------------------------
# The discovery bundle
# ---------------------------------------------------------------------------


@dataclass
class Discovery:
    """Everything one pipeline run produced, ready to be serialised."""

    ingestion: IngestionResult
    analysed: list[AnalysedFile]
    roots: list[ProjectRoot]
    graph: DependencyGraph
    database: list[DatabaseFinding] = field(default_factory=list)
    sql_files: list[SqlFileFinding] = field(default_factory=list)
    native_libs: list[NativeLibraryFinding] = field(default_factory=list)
    os_dependencies: list[OsDependencyFinding] = field(default_factory=list)
    build_requirements: dict[str, Any] = field(default_factory=dict)
    #: Diagnostics collected outside the ingestion sink (analysis, roots,
    #: project files, graph construction).  Merged, de-duplicated and sorted
    #: by :func:`build_manifest`.
    diagnostics: list[dict[str, object]] = field(default_factory=list)
    #: Label recorded as ``source.origin`` — a name, never a path.
    origin_label: str = ""
    limits: Limits | None = None
    # --- Stage 1 additions (consumed by ``p1.blueprint``; the P1 manifest is
    #     deliberately unchanged so its schema and tests stay stable). -------
    directories: list[DirectoryEntry] = field(default_factory=list)
    build_scripts: list[BuildScriptFinding] = field(default_factory=list)
    compiler_configs: list[CompilerConfigFinding] = field(default_factory=list)
    integrations: list[IntegrationFinding] = field(default_factory=list)
    libraries: list[LibraryFinding] = field(default_factory=list)
    runtime_dependencies: list[RuntimeDependencyFinding] = field(
        default_factory=list
    )
    #: Provenance of the pinned source (see docs/stage1/STAGE1_DESIGN.md §3):
    #: ``{"ref": str, "commit": str, "remote": str, "tree_id": str}`` — values
    #: are redacted; empty for ZIP and directory inputs.
    source_provenance: dict[str, str] = field(default_factory=dict)
    #: ``CheckpointInfo.as_dict()`` of the immutable checkpoint, when one was
    #: created for this run; ``{}`` for the legacy ``ingest`` command.
    checkpoint: dict[str, Any] = field(default_factory=dict)

    def analysis_of(self, path: str) -> tuple[object | None, SourceAnalysis | None]:
        """Return ``(scan, analysis)`` for *path*, or ``(None, None)``."""

        for item in self.analysed:
            if item.path == path:
                return item.scan, item.analysis
        return None, None


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------


def _file_entry(item: AnalysedFile) -> dict[str, object]:
    inventory = item.inventory
    cls = item.cls
    if cls == "unknown":
        status = "UNKNOWN"
    elif cls in ("pascal_unit", "pascal_program", "pascal_package",
                 "pascal_include") and item.scan is None:
        status = "PARTIAL"
    else:
        status = "SUPPORTED"
    entry: dict[str, object] = {
        "bom": item.bom,
        "capability_status": status,
        "class": cls,
        "class_evidence": list(item.class_evidence),
        "encoding": item.encoding,
        "encoding_confidence": item.encoding_confidence,
        "extension": PurePosixPath(item.path).suffix.lower(),
        "path": item.path,
        # P1 never rewrites or relocates an input file (master prompt).
        "preserved": True,
        "sha256": inventory.sha256,
        "size": inventory.size,
    }
    if item.analysis_blocker:
        entry["analysis_blocker"] = item.analysis_blocker
    if inventory.source_timestamp:
        entry["source_timestamp"] = inventory.source_timestamp
    if inventory.excluded:
        entry["excluded"] = inventory.exclusion_reason
    return entry


def _dialect_entry(item: AnalysedFile) -> dict[str, object] | None:
    if item.analysis is None:
        return None
    analysis = item.analysis
    return {
        "confidence": analysis.confidence,
        "dialect": analysis.dialect,
        "evidence": list(analysis.dialect_evidence),
        "file": item.path,
        "framework": analysis.framework,
        "mode": analysis.mode,
        "mode_evidence": list(analysis.mode_evidence),
        "name_mismatch": analysis.name_mismatch,
        "source_kind": analysis.source_kind,
    }


def _merge_diagnostics(discovery: Discovery) -> list[dict[str, object]]:
    """Merge every diagnostic source into one sorted, de-duplicated list."""

    raw: list[dict[str, object]] = []
    for diagnostic in discovery.ingestion.diagnostics:
        raw.append(diagnostic if isinstance(diagnostic, dict)
                   else diagnostic.as_dict())  # type: ignore[union-attr]
    raw.extend(discovery.diagnostics)

    # Per-file lexer/analysis diagnostics carry their own path, so they are
    # folded in here rather than lost (IR invariant I2).
    for item in discovery.analysed:
        if item.scan is not None:
            for diagnostic in item.scan.diagnostics:
                # plex fills this from DiagnosticSink.to_list(), so the entries
                # are plain dicts; accept a Diagnostic too so the two shapes
                # cannot be confused again.
                payload = diagnostic if isinstance(diagnostic, dict) \
                    else diagnostic.as_dict()  # type: ignore[union-attr]
                payload = dict(payload)
                payload.setdefault("file", item.path)
                raw.append(payload)
        if item.analysis is not None:
            for extra in item.analysis.diagnostics:
                payload = dict(extra)
                payload.setdefault("file", item.path)
                raw.append(payload)

    seen: dict[tuple[object, ...], dict[str, object]] = {}
    for payload in raw:
        key = (
            payload.get("code", ""),
            payload.get("file", ""),
            payload.get("line", 0),
            payload.get("column", 0),
            payload.get("message", ""),
        )
        if key not in seen:
            seen[key] = payload

    ordered = [
        seen[k]
        for k in sorted(
            seen,
            key=lambda key: (str(key[0]), str(key[1]), int(key[2] or 0),
                             int(key[3] or 0), str(key[4])),
        )
    ]
    return ordered


def capability_states(discovery: Discovery) -> list[dict[str, str]]:
    """Build the ``(construct, mode, platform)`` capability table (task C2).

    Two kinds of row are produced:

    * **P0-proven facts** — copied from ``docs/p0/evidence/`` so the discovery
      report never re-states something without its citation;
    * **P1 implementation states** — each naming the test that exercises it.

    ``VERIFIED`` is never produced; :func:`p1.statuses.validate_status`
    rejects it, so a regression here fails loudly rather than quietly.
    """

    states: list[CapabilityState] = []

    def add(construct: str, mode: str, platform: str, status: str,
            evidence: str) -> None:
        states.append(CapabilityState(construct, mode, platform, status, evidence))

    # --- P0-proven compiler facts ----------------------------------------
    add("identifier `Result` usable in a function body", "fpc", "win32",
        "UNSUPPORTED", _E + "probes.txt P01")
    add("identifier `Result` usable in a function body", "tp", "win32",
        "UNSUPPORTED", _E + "probes.txt P02")
    add("identifier `Result` usable in a function body", "objfpc", "win32",
        "SUPPORTED", _E + "probes.txt P03")
    add("identifier `Result` usable in a function body", "delphi", "win32",
        "SUPPORTED", _E + "probes.txt P04")
    add("bare `AssignFile`/`CloseFile` without `uses ObjPas`", "fpc", "win32",
        "UNSUPPORTED", _E + "probes.txt P06, ppu scan")
    add("bare `AssignFile`/`CloseFile` without `uses ObjPas`", "objfpc",
        "win32", "SUPPORTED", _E + "probes.txt P07, P11")
    add("bare `AssignFile`/`CloseFile` without `uses ObjPas`", "delphi",
        "win32", "SUPPORTED", _E + "probes.txt P08")
    add("compiler mode flag `-Miso` accepted by fpc 3.2.2", "iso", "win32",
        "SUPPORTED", _E + "probes.txt P18")
    add("unit name differing from the file name compiles", "delphi", "win32",
        "UNSUPPORTED", _E + "probes.txt P13")
    add("compiler directive nested inside a brace comment", "fpc", "win32",
        "SUPPORTED", _E + "probes.txt P16")
    add("compiler directive nested inside a brace comment", "delphi", "win32",
        "UNSUPPORTED", _E + "probes.txt P17")
    add("fixture set compiles identically under fpc 3.2.2", "any", "linux",
        "SUPPORTED", _E + "fpc-docker.txt (24 fixtures, MISMATCH=0)")

    # --- P1 ingestion -----------------------------------------------------
    add("archive entry path-traversal rejection", "any", "any",
        "SUPPORTED", "tests/security/test_adversarial_archives.py")
    add("archive symlink and special-file rejection", "any", "any",
        "SUPPORTED", "tests/security/test_adversarial_archives.py")
    add("archive expansion limits (ratio, entry, total, count)", "any", "any",
        "SUPPORTED", "tests/security/test_adversarial_archives.py")
    add("ingestion of a local git repository", "any", "any",
        "SUPPORTED", "tests/security/test_git_ingestion.py")
    add("ingestion of a network git remote", "any", "any",
        "UNSUPPORTED", "tools/p1/gitingest.py raises REMOTE_INPUT_UNSUPPORTED")

    # --- P1 discovery -----------------------------------------------------
    add("Pascal source classification", "any", "any",
        "SUPPORTED", "tests/unit/test_classify.py")
    add("encoding and byte-order-mark detection", "any", "any",
        "SUPPORTED", "tests/unit/test_hashing.py")
    add("compiler mode table for fpc/objfpc/delphi/tp/iso", "any", "any",
        "SUPPORTED", _E + "probes.txt P01-P18; tests/unit/test_dialects.py")
    add("project root and entry-point discovery", "any", "any",
        "PARTIAL", "tests/unit/test_projects.py")
    add("application shape detection (console/GUI/library/package)", "any",
        "any", "PARTIAL", "tests/unit/test_projects.py")
    add("dialect and framework detection from source", "any", "any",
        "PARTIAL", "tests/unit/test_dialects.py")
    add("compiler profile extraction (defines, paths, checks)", "any", "any",
        "PARTIAL", "tests/unit/test_projects.py")
    add("unit dependency graph construction", "any", "any",
        "PARTIAL", "tests/unit/test_deps.py")
    add("include (`{$I}`) resolution", "any", "any",
        "PARTIAL", "tests/unit/test_deps.py")
    add("database technology detection", "any", "any",
        "PARTIAL", "tests/integration/test_pipeline.py")
    add("SQL dialect detection", "any", "any",
        "PARTIAL", "tests/integration/test_pipeline.py")
    add("native library reference detection", "any", "any",
        "PARTIAL", "tests/integration/test_pipeline.py")
    add("OS dependency detection", "any", "any",
        "PARTIAL", "tests/integration/test_pipeline.py")
    add("byte-identical repeatable output", "any", "any",
        "SUPPORTED", "tests/integration/test_determinism.py")
    add("no-LLM dependency gate", "any", "any",
        "SUPPORTED", "tests/security/test_no_llm_guard.py")

    # --- Deliberately out of scope ---------------------------------------
    add("symbol and type resolution across units", "any", "any",
        "UNSUPPORTED", "docs/p0/P1_TASKS.md §F (deferred to P2)")
    add("semantic intermediate representation", "any", "any",
        "UNSUPPORTED", "docs/p0/P1_TASKS.md §F (deferred to P2)")
    add("Java source generation", "any", "any",
        "UNSUPPORTED", "docs/p1/P1_IMPLEMENTATION_PLAN.md §1 (P1 scope)")
    add("original-vs-Java differential equivalence", "any", "any",
        "UNSUPPORTED", "docs/p0/P1_TASKS.md §F (reachable only in P3)")
    add("execution of a Delphi compiler", "any", "win32",
        "UNAVAILABLE", "no Delphi installation or licence in this environment")
    add("compiler invocation during discovery", "any", "any",
        "UNSUPPORTED", "discovery is syntactic by design (plan §1)")
    add("project LICENSE file", "any", "any",
        "UNAVAILABLE", "owner decision required (P1 blocker A1)")

    # --- Anything this run actually found ---------------------------------
    if discovery.build_requirements.get("compiler") == "unknown":
        add("compiler identification from the ingested tree", "any", "any",
            "UNKNOWN", "")
    else:
        add("compiler identification from the ingested tree", "any", "any",
            "PARTIAL", "derived from extensions and directives; "
                       "tests/integration/test_pipeline.py")

    validated = validate_states(states)
    return [state.as_dict() for state in validated]


def build_manifest(discovery: Discovery) -> dict[str, Any]:
    """Assemble ``application-manifest.json`` (plan §6.1)."""

    analysed = sorted(discovery.analysed, key=lambda a: a.path)
    ingestion = discovery.ingestion

    counts: dict[str, int] = {}
    for item in analysed:
        counts[item.cls] = counts.get(item.cls, 0) + 1

    roots = sorted(discovery.roots, key=lambda r: r.path)
    root_dicts: list[dict[str, object]] = []
    profile_dicts: list[dict[str, object]] = []
    shape_dicts: list[dict[str, object]] = []
    for root in roots:
        scan, analysis = discovery.analysis_of(root.path)
        entry = entry_point(root, scan, analysis)  # type: ignore[arg-type]
        root_dicts.append({
            "entry_points": [entry],
            "evidence": root.evidence,
            "kind": root.kind,
            "path": root.path,
            "primary": root.primary,
            "status": root.status,
        })
        profile_payload = root.profile.as_dict()
        profile_payload["root"] = root.path
        profile_dicts.append(profile_payload)
        shape_dicts.append({
            "confidence": root.shape_confidence,
            "evidence": root.shape_evidence,
            "root": root.path,
            "shape": root.shape,
            "status": root.shape_status,
        })

    dialects = [
        payload for payload in (_dialect_entry(item) for item in analysed)
        if payload is not None
    ]

    states = capability_states(discovery)

    manifest: dict[str, Any] = {
        "build_requirements": dict(discovery.build_requirements),
        "capability_states": states,
        "classification": {key: counts[key] for key in sorted(counts)},
        "database": [f.as_dict() for f in discovery.database],
        "dependency_summary": discovery.graph.stats(),
        "diagnostics": _merge_diagnostics(discovery),
        "dialects": dialects,
        "files": [_file_entry(item) for item in analysed],
        "generator": {
            "llm_assisted": False,
            "phase": "P1",
            "tool": "tools/p1",
        },
        "limits": (discovery.limits or ingestion.limits).as_dict(),
        "mode_visibility": [visibility_for(name) for name in sorted(MODE_TABLE)],
        "native_libs": [f.as_dict() for f in discovery.native_libs],
        "os_dependencies": [f.as_dict() for f in discovery.os_dependencies],
        "profiles": profile_dicts,
        "project_roots": root_dicts,
        "schema_version": MANIFEST_SCHEMA,
        "shapes": shape_dicts,
        "source": {
            "commit": ingestion.commit or "",
            "entry_count": ingestion.entry_count,
            "kind": ingestion.kind,
            "origin": discovery.origin_label,
            "source_timestamp": ingestion.source_timestamp,
            "total_bytes": ingestion.total_bytes,
        },
        "sql_files": [f.as_dict() for f in discovery.sql_files],
    }
    return manifest


# ---------------------------------------------------------------------------
# Dependency graph document
# ---------------------------------------------------------------------------


def build_graph_document(graph: DependencyGraph) -> dict[str, Any]:
    """Assemble ``dependency-graph.json`` (plan §6.2, IR invariant I6)."""

    payload = graph.to_dict()
    payload["schema_version"] = GRAPH_SCHEMA
    return payload


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["_(none)_", ""]
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join("---" for _ in headers) + "|"]
    for row in rows:
        out.append("| " + " | ".join(row) + " |")
    out.append("")
    return out


def _cell(value: object) -> str:
    """Render a value as a single Markdown table cell."""

    text = str(value)
    return text.replace("|", "\\|").replace("\n", " ").strip()


def render_report(manifest: dict[str, Any], graph: dict[str, Any]) -> str:
    """Render ``discovery-report.md`` from the two JSON documents.

    Pure function of its inputs: running it twice on the same manifest yields
    byte-identical Markdown.
    """

    lines: list[str] = []
    add = lines.append
    source = manifest["source"]
    stats = graph["stats"]

    add("# Pascal application discovery report")
    add("")
    add(f"Schema: `{manifest['schema_version']}` / "
        f"`{graph['schema_version']}`  ")
    add(f"Generator: `{manifest['generator']['tool']}` "
        f"phase `{manifest['generator']['phase']}` — "
        "no machine-assisted analysis was used.")
    add("")

    add("## 1. Scope")
    add("")
    add(f"- **Input kind:** `{source['kind']}`")
    add(f"- **Origin label:** `{source['origin']}`")
    add(f"- **Pinned commit:** `{source['commit'] or 'n/a'}`")
    add(f"- **Source timestamp:** `{source['source_timestamp'] or 'n/a'}`")
    add(f"- **Files inventoried:** {source['entry_count']}")
    add(f"- **Total bytes:** {source['total_bytes']}")
    add("")
    add("Discovery is syntactic: no compiler, interpreter, model or network "
        "call is made while producing this report.")
    add("")

    add("## 2. File inventory")
    add("")
    counts = manifest["classification"]
    rows = [[_cell(cls), str(counts[cls])] for cls in sorted(counts)]
    add("### 2.1 Classification")
    add("")
    lines.extend(_table(["Class", "Files"], rows))

    add("### 2.2 Files")
    add("")
    file_rows = [
        [
            _cell(f["path"]),
            _cell(f["class"]),
            str(f["size"]),
            _cell(f["sha256"][:16]),
            _cell(f["encoding"]),
            _cell(f["capability_status"]),
        ]
        for f in manifest["files"]
    ]
    lines.extend(_table(
        ["Path", "Class", "Bytes", "SHA-256 (16)", "Encoding", "Status"],
        file_rows,
    ))

    add("## 3. Project roots and entry points")
    add("")
    root_rows = []
    for root in manifest["project_roots"]:
        entry = root["entry_points"][0]
        root_rows.append([
            _cell(root["path"]),
            _cell(root["kind"]),
            _cell(entry.get("declared_name") or "—"),
            _cell(entry.get("location") or "—"),
            _cell(root["status"]),
            "yes" if root["primary"] else "no",
        ])
    lines.extend(_table(
        ["Path", "Kind", "Declared name", "Location", "Status", "Primary"],
        root_rows,
    ))

    add("## 4. Dialect, mode and framework")
    add("")
    dialect_rows = []
    for item in manifest["dialects"]:
        dialect_rows.append([
            _cell(item["file"]),
            _cell(item["dialect"]),
            _cell(item["mode"]),
            _cell(item["framework"]),
            _cell(item["confidence"]),
        ])
    lines.extend(_table(
        ["File", "Dialect", "Mode", "Framework", "Confidence"], dialect_rows,
    ))

    add("### 4.1 Per-mode identifier visibility (P0 evidence)")
    add("")
    visibility_rows = []
    for entry in manifest["mode_visibility"]:
        visibility_rows.append([
            _cell(entry["mode"]),
            _cell(entry.get("fpc_flag", "")),
            _cell(entry["result_visible"]),
            _cell(entry["bare_assignfile_visible"]),
            _cell(entry["evidence"]),
        ])
    lines.extend(_table(
        ["Mode", "Flag", "`Result`", "Bare `AssignFile`", "Evidence"],
        visibility_rows,
    ))
    add("`UNKNOWN` means P0 did not probe that mode — it is not a "
        "recommendation and it is never guessed.")
    add("")

    add("## 5. Compiler profiles")
    add("")
    profile_rows = []
    for profile in manifest["profiles"]:
        profile_rows.append([
            _cell(profile["root"]),
            _cell(profile["mode"]),
            _cell(", ".join(profile["defines"]) or "—"),
            _cell(profile["platform"]),
            _cell(", ".join(profile["unit_search_paths"]) or "—"),
            _cell(profile["range_check"]),
            _cell(profile["overflow_check"]),
            _cell(profile["string_model"]),
            _cell(profile["output_kind"]),
        ])
    lines.extend(_table(
        ["Root", "Mode", "Defines", "Platform", "Unit paths", "R", "Q",
         "String", "Output"],
        profile_rows,
    ))

    add("## 6. Application shapes")
    add("")
    shape_rows = [
        [_cell(s["root"]), _cell(s["shape"]), _cell(s["confidence"]),
         _cell(s["status"])]
        for s in manifest["shapes"]
    ]
    lines.extend(_table(["Root", "Shape", "Confidence", "Status"], shape_rows))

    add("## 7. Data, native libraries and OS dependencies")
    add("")
    add("### 7.1 Database technologies")
    add("")
    db_rows = [
        [_cell(d["technology"]), _cell(d["confidence"]), _cell(d["status"]),
         _cell(len(d["evidence"]))]
        for d in manifest["database"]
    ]
    lines.extend(_table(
        ["Technology", "Confidence", "Status", "Evidence items"], db_rows,
    ))
    add("> Detection only. Listing a technology is **not** a claim that a "
        "driver or adapter for it is available here.")
    add("")

    add("### 7.2 SQL files")
    add("")
    sql_rows = [
        [_cell(s["path"]), _cell(s["dialect"]), _cell(s["confidence"]),
         _cell(s["status"])]
        for s in manifest["sql_files"]
    ]
    lines.extend(_table(["Path", "Dialect", "Confidence", "Status"], sql_rows))

    add("### 7.3 Native libraries")
    add("")
    native_rows = [
        [_cell(n["name"]), _cell(n["kind"]), _cell(n["status"]),
         _cell(len(n["evidence"]))]
        for n in manifest["native_libs"]
    ]
    lines.extend(_table(
        ["Library", "Kind", "Status", "Evidence items"], native_rows,
    ))

    add("### 7.4 OS dependencies")
    add("")
    os_rows = [
        [_cell(o["platform"]), _cell(o["confidence"]), _cell(o["status"]),
         _cell(len(o["evidence"]))]
        for o in manifest["os_dependencies"]
    ]
    lines.extend(_table(
        ["Platform", "Confidence", "Status", "Evidence items"], os_rows,
    ))

    add("## 8. Build and runtime requirements")
    add("")
    build = manifest["build_requirements"]
    add(f"- **Compiler (inferred):** `{build['compiler']}` "
        f"— {build['status']}")
    add(f"- **Modes:** {', '.join('`' + m + '`' for m in build['modes']) or '—'}")
    add(f"- **Flags:** {', '.join('`' + f + '`' for f in build['flags']) or '—'}")
    add("")
    blockers = build["blockers"]
    if blockers:
        add("**Blockers**")
        add("")
        lines.extend(_table(
            ["Code", "Detail"],
            [[_cell(b["code"]), _cell(b["detail"])] for b in blockers],
        ))
    else:
        add("**Blockers:** none")
        add("")

    add("## 9. Dependency graph")
    add("")
    add(f"- **Nodes:** {stats['nodes']}")
    add(f"- **Edges:** {stats['edges']}")
    add(f"- **Resolved:** {stats['resolved']}")
    add(f"- **Unresolved:** {stats['unresolved']}")
    add(f"- **Duplicate edges ignored:** {stats['duplicate_edges_ignored']}")
    add("")
    add("### 9.1 Unresolved dependencies")
    add("")
    unresolved_rows = [
        [
            _cell(e["from"]),
            _cell(e["to"]),
            _cell(e["relation"]),
            _cell(e["reason"]),
            _cell(f"{e['file']}:{e['line']}:{e['column']}"),
        ]
        for e in graph["unresolved"]
    ]
    lines.extend(_table(
        ["From", "To", "Relation", "Reason", "Location"], unresolved_rows,
    ))
    add("Every unresolved edge above is also present in `edges`; the "
        "`unresolved` array is a projection, not a second source of truth.")
    add("")

    add("## 10. Capability states")
    add("")
    cap_rows = [
        [_cell(c["construct"]), _cell(c["mode"]), _cell(c["platform"]),
         _cell(c["status"]), _cell(c["evidence"] or "—")]
        for c in manifest["capability_states"]
    ]
    lines.extend(_table(
        ["Construct", "Mode", "Platform", "Status", "Evidence"], cap_rows,
    ))

    add("## 11. Diagnostics")
    add("")
    diagnostics = manifest["diagnostics"]
    if diagnostics:
        diag_rows = [
            [_cell(d.get("severity", "")), _cell(d.get("code", "")),
             _cell(d.get("file", "—")), _cell(d.get("line", "")),
             _cell(d.get("message", ""))]
            for d in diagnostics
        ]
        lines.extend(_table(
            ["Severity", "Code", "File", "Line", "Message"], diag_rows,
        ))
    else:
        add("_No diagnostics._")
        add("")

    add("## 12. Limitations of this report")
    add("")
    add("- Discovery is **syntactic**: no symbol table and no cross-unit "
        "type resolution (deferred to P2).")
    add("- No compiler is invoked; every compile-related statement cites "
        "evidence captured in `docs/p0/evidence/`.")
    add("- GUI shapes are detected and reported, not converted: GUI "
        "translation is out of scope for the first release.")
    add("- Database and native-library entries are an inventory, not a "
        "driver or adapter capability claim.")
    add("- Network git remotes are refused; only local paths and `file://` "
        "URLs are accepted.")
    add("- `VERIFIED` is unreachable before P3 and is never emitted.")
    add("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _scrub(text: str, needles: list[str]) -> str:
    """Remove staging/temporary paths from serialised output."""

    for needle in needles:
        if needle:
            text = text.replace(needle, "<staging>")
    return text


def _serialise(payload: dict[str, Any], needles: list[str]) -> str:
    text = json.dumps(payload, sort_keys=True, indent=2, ensure_ascii=True)
    return _scrub(text, needles) + "\n"


def write_outputs(
    discovery: Discovery,
    outdir: Path,
    *,
    staging_roots: tuple[str, ...] = (),
) -> dict[str, str]:
    """Write the three artefacts into *outdir*; return their paths.

    The report is rendered from the *serialised* documents, so the prose can
    never disagree with the JSON that ships alongside it.
    """

    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    needles = [str(root) for root in staging_roots if root]
    # Also scrub the Windows and POSIX forms of each staging root.
    extra: list[str] = []
    for needle in list(needles):
        extra.append(needle.replace("/", "\\"))
        extra.append(needle.replace("\\", "/"))
    needles.extend(extra)

    manifest_text = _serialise(build_manifest(discovery), needles)
    graph_text = _serialise(build_graph_document(discovery.graph), needles)
    report_text = _scrub(
        render_report(json.loads(manifest_text), json.loads(graph_text)),
        needles,
    )

    paths = {
        "manifest": outdir / "application-manifest.json",
        "graph": outdir / "dependency-graph.json",
        "report": outdir / "discovery-report.md",
    }
    paths["manifest"].write_text(manifest_text, encoding="utf-8", newline="\n")
    paths["graph"].write_text(graph_text, encoding="utf-8", newline="\n")
    paths["report"].write_text(report_text, encoding="utf-8", newline="\n")

    return {key: value.as_posix() for key, value in paths.items()}
