"""Stage 1 orchestrator: ingest -> checkpoint -> inventory -> dependencies -> blueprint.

    request -> [1 Ingestion] -> [2 Checkpoint] -> [3 Scanning & Inventory]
            -> [4 Dependency Analysis] -> [5 Blueprint]

Two rules shape this module (docs/stage1/STAGE1_DESIGN.md §2-§3):

**Everything after step 1 reads the checkpoint.**  Untrusted bytes are
validated and staged by the existing ingestion code, frozen into an immutable
checkpoint, and from then on analysed *from the checkpoint's preserved tree*,
never from staging.  What is analysed is therefore exactly what is preserved.

**A refusal produces no blueprint.**  Any :class:`~p1.errors.IngestionError`
propagates after staging is removed; there is no partial output to mistake for
a result.  Wall-clock time lives only in ``run-record.json``; the blueprint
and every other artefact are deterministic.
"""

from __future__ import annotations

import json
import re
import tempfile
import time
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from . import __version__ as _tool_version
from .blueprint import build_blueprint, write_blueprint_outputs
from .checkpoint import CheckpointInfo, create_checkpoint
from .compilercfg import detect_compiler_configs
from .deps import build_graph
from .emit import Discovery, write_outputs
from .errors import DiagnosticSink, IngestionError, UnsupportedInputError
from .gitingest import _hardened_env, _rev_parse, ingest_git
from .inventory import (
    detect_build_scripts,
    list_directories,
    wants_text,
)
from .integrations import detect_integrations
from .libraries import detect_libraries
from .limits import DEFAULT_LIMITS, Limits
from .metadata import (
    build_requirements,
    detect_database,
    detect_native_libs,
    detect_os_dependencies,
    detect_sql_files,
)
from .model import IngestionResult, ingest_directory, rmtree_force
from .pipeline import (
    _as_diagnostic,
    _attach_staging,
    _decode,
    _origin_label,
    analyse_tree,
    build_roots,
)
from .remotegit import NetworkPolicy, ingest_remote_git
from .reports import write_derived_reports
from .runtimedeps import detect_runtime_dependencies
from .zipingest import ingest_zip

__all__ = [
    "STEP_IDS",
    "DiscoveryRequest",
    "DiscoveryResult",
    "Progress",
    "discover",
    "is_remote_git",
]

#: The five Stage 1 steps, in order (ids are part of the blueprint schema).
STEP_IDS: tuple[tuple[str, str], ...] = (
    ("ingestion", "Ingestion"),
    ("checkpoint", "Checkpoint"),
    ("scanning_inventory", "Scanning & Inventory"),
    ("dependency_analysis", "Dependency Analysis"),
    ("blueprint", "Application Blueprint"),
)

#: ``(step_id, status, message)`` with status in running|completed|warning|failed.
Progress = Callable[[str, str, str], None]

_KINDS = ("git", "zip", "directory")
_REMOTE_RE = re.compile(
    r"^(https?://|ssh://|git://|[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:)", re.I
)
_HEX40 = re.compile(r"^[0-9a-fA-F]{40}$")
_RUN_RECORD = "run-record.json"


@dataclass(frozen=True)
class DiscoveryRequest:
    """What to ingest.  ``network_policy`` is operator-set, never user input."""

    kind: str  # "git" | "zip" | "directory"
    source: str  # URL, archive path or directory path
    ref: str | None = None
    label: str | None = None
    allow_ssh: bool = False
    network_policy: NetworkPolicy = field(default_factory=NetworkPolicy)

    def __post_init__(self) -> None:
        if self.kind not in _KINDS:
            raise UnsupportedInputError(
                f"unknown input kind {self.kind!r}", code="UNKNOWN_INPUT_KIND"
            )


@dataclass
class DiscoveryResult:
    """Outcome of one :func:`discover` call."""

    checkpoint: CheckpointInfo
    outdir: Path
    blueprint: dict[str, Any]
    outputs: dict[str, str]
    reused: bool


def is_remote_git(source: str) -> bool:
    """True when *source* names a network Git remote rather than a local path."""

    return bool(_REMOTE_RE.match(source.strip()))


class _Steps:
    """Progress reporting plus the wall-clock run record (never in artefacts)."""

    def __init__(self, progress: Progress | None) -> None:
        self._progress = progress
        self.records: dict[str, dict[str, Any]] = {}
        self._started: dict[str, float] = {}
        #: The step most recently started and not yet finished.
        self.current = ""

    def emit(self, step: str, status: str, message: str = "") -> None:
        now = time.monotonic()
        if status == "running":
            self.current = step
            self._started[step] = now
            self.records[step] = {
                "id": step, "status": status, "message": message,
                "started_at": _utc_now(), "duration_ms": 0,
            }
        else:
            if self.current == step:
                self.current = ""
            record = self.records.setdefault(step, {
                "id": step, "started_at": _utc_now(), "duration_ms": 0,
            })
            record["status"] = status
            record["message"] = message
            started = self._started.get(step, now)
            record["duration_ms"] = int((now - started) * 1000)
        if self._progress is not None:
            try:
                self._progress(step, status, message)
            except Exception:  # noqa: BLE001 - a callback must not break a run
                pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Step 1: ingestion
# ---------------------------------------------------------------------------


def _resolve_local_ref(repo: str, ref: str, staging: Path) -> str:
    """Resolve a local branch/tag/SHA to a full 40-hex commit id."""

    if ref.startswith("-") or any(c.isspace() or ord(c) < 32 for c in ref):
        raise UnsupportedInputError(
            f"invalid git ref {ref!r}", code="INVALID_REF", path=ref
        )
    env = _hardened_env(staging)
    path = repo[7:] if repo.lower().startswith("file://") else repo
    return _rev_parse(Path(path), env, f"{ref}^{{commit}}", ref)


def _ingest(
    request: DiscoveryRequest, staging: Path, limits: Limits,
    sink: DiagnosticSink,
) -> tuple[IngestionResult, Path | None]:
    """Run the matching ingestion path; return it and any original archive."""

    label = request.label or _origin_label(request.source, request.kind)
    if request.kind == "zip":
        archive = Path(request.source)
        result = ingest_zip(archive, staging, origin=label, limits=limits,
                            sink=sink)
        return result, archive
    if request.kind == "git":
        if is_remote_git(request.source):
            return ingest_remote_git(
                request.source, staging, ref=request.ref,
                allow_ssh=request.allow_ssh, policy=request.network_policy,
                limits=limits, sink=sink,
            ), None
        commit = None
        if request.ref:
            commit = (request.ref if _HEX40.match(request.ref)
                      else _resolve_local_ref(request.source, request.ref,
                                              staging))
        result = ingest_git(request.source, staging, commit=commit,
                            limits=limits, sink=sink)
        result.ref = request.ref or ""
        return result, None
    root = Path(request.source).resolve()
    if not root.is_dir():
        raise UnsupportedInputError(
            f"not a directory: {root.name}", code="INPUT_NOT_FOUND",
            path=root.name,
        )
    return ingest_directory(
        root, origin=label, kind="directory", skip=(".git",),
        skip_reason="version-control metadata", sink=sink, limits=limits,
    ), None


def _origin_for_checkpoint(request: DiscoveryRequest,
                           ingestion: IngestionResult) -> str:
    """A credential-free, path-free origin string for the checkpoint."""

    if ingestion.remote:
        return ingestion.remote
    return request.label or _origin_label(request.source, request.kind)


# ---------------------------------------------------------------------------
# Steps 3-4: analysis over the checkpoint
# ---------------------------------------------------------------------------

_TEXT_EXTRA = frozenset({"database"})


def _text_of(analysed: list, source_root: Path, limits: Limits) -> dict[str, str]:
    """Decoded text for every file the detectors read (bounded, never raises)."""

    out: dict[str, str] = {}
    for item in analysed:
        if not (wants_text(item) or item.cls in _TEXT_EXTRA):
            continue
        if item.inventory.size > limits.max_source_bytes:
            continue
        try:
            data = (source_root / item.path).read_bytes()
        except OSError:
            continue
        out[item.path] = _decode(data, item.encoding)
    return out


def _analyse(ingestion: IngestionResult, source_root: Path, limits: Limits,
             sink: DiagnosticSink, steps: _Steps) -> dict[str, Any]:
    """Steps 3 and 4 over the checkpoint's preserved tree."""

    steps.emit("scanning_inventory", "running")
    view = replace(ingestion, staging_root=source_root)
    analysed = analyse_tree(view, limits, sink)
    _attach_staging(analysed, source_root)
    roots, profiles, _ = build_roots(analysed, sink)
    text_of = _text_of(analysed, source_root, limits)
    directories = list_directories(source_root, ingestion.files)
    scripts = detect_build_scripts(analysed, text_of, roots)
    configs = detect_compiler_configs(analysed, text_of)
    steps.emit("scanning_inventory", "completed",
               f"{len(analysed)} files, {len(directories)} directories")

    steps.emit("dependency_analysis", "running")
    graph_build = build_graph(analysed, roots, sink=sink)
    for payload in graph_build.diagnostics:
        sink.add(_as_diagnostic(payload))
    databases = detect_database(analysed)
    native_libs = detect_native_libs(analysed)
    os_deps = detect_os_dependencies(analysed)
    integrations = detect_integrations(analysed, text_of)
    libraries = detect_libraries(analysed, roots, graph_build.unresolved_units,
                                 text_of=text_of)
    runtime = detect_runtime_dependencies(
        analysed, text_of, native_libs, os_deps, databases, integrations,
        libraries,
    )
    requirements = build_requirements(
        analysed, roots, profiles, graph_build.unresolved_units,
        has_project_files=any(r.meta_files for r in roots), sink=sink,
    )
    steps.emit("dependency_analysis", "completed",
               f"{graph_build.graph.stats()['edges']} dependency edges")
    return {
        "analysed": analysed, "roots": roots, "graph": graph_build.graph,
        "database": databases,
        "sql_files": detect_sql_files(analysed, text_of),
        "native_libs": native_libs, "os_dependencies": os_deps,
        "build_requirements": requirements, "directories": directories,
        "build_scripts": scripts, "compiler_configs": configs,
        "integrations": integrations, "libraries": libraries,
        "runtime_dependencies": runtime,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def _write_run_record(outdir: Path, info: CheckpointInfo,
                      steps: _Steps) -> str:
    record = {
        "checkpoint_id": info.checkpoint_id,
        "ingested_at": _utc_now(),
        "steps": [steps.records[sid] for sid, _ in STEP_IDS
                  if sid in steps.records],
        "tool_versions": {"p1": _tool_version},
    }
    path = outdir / _RUN_RECORD
    path.write_text(json.dumps(record, sort_keys=True, indent=2) + "\n",
                    encoding="utf-8", newline="\n")
    return path.as_posix()


def _validate_request(request: DiscoveryRequest, store: Path) -> None:
    """Refuse requests that are inconsistent or would corrupt the input."""

    if request.ref and request.kind != "git":
        raise UnsupportedInputError(
            f"--ref applies to git inputs only, not {request.kind!r}",
            code="REF_NOT_APPLICABLE", path=request.ref,
        )
    if request.kind == "directory":
        root = Path(request.source).resolve()
        target = store.resolve()
        if target == root or root in target.parents:
            raise UnsupportedInputError(
                "the store must not lie inside the input directory",
                code="STORE_INSIDE_INPUT",
            )


def _build_discovery(request: DiscoveryRequest, ingestion: IngestionResult,
                     info: CheckpointInfo, found: dict[str, Any],
                     limits: Limits, sink: DiagnosticSink) -> Discovery:
    return Discovery(
        ingestion=ingestion, diagnostics=sink.to_list(),
        origin_label=_origin_for_checkpoint(request, ingestion),
        limits=limits, checkpoint=info.as_dict(),
        source_provenance={
            "ref": ingestion.ref or (request.ref or ""),
            "commit": ingestion.commit or "",
            "remote": ingestion.remote,
            "tree_id": ingestion.tree_id,
        },
        **found,
    )


def _publish(discovery: Discovery, info: CheckpointInfo, store: Path,
             scrub: tuple[str, ...]) -> tuple[Path, dict[str, Any],
                                              dict[str, str]]:
    """Write every deterministic artefact; return (outdir, blueprint, outputs)."""

    outdir = store / "discoveries" / info.checkpoint_id
    outdir.mkdir(parents=True, exist_ok=True)
    blueprint = build_blueprint(discovery, scrub_roots=scrub)
    outputs = write_outputs(discovery, outdir, staging_roots=scrub)
    outputs.update(write_blueprint_outputs(
        discovery, outdir, staging_roots=scrub, blueprint=blueprint))
    outputs.update(write_derived_reports(
        blueprint, _checkpoint_document(info), outdir, staging_roots=scrub))
    return outdir, blueprint, outputs


def _checkpoint_document(info: CheckpointInfo) -> dict[str, Any]:
    """The sealed ``checkpoint.json`` of *info*, or a refusal.

    The manifest must describe the checkpoint that was actually verified and
    read; if its metadata cannot be loaded the run fails closed rather than
    publishing a discovery without a source identity.
    """

    try:
        document = json.loads(
            (info.path / "checkpoint.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise IngestionError(
            "the checkpoint metadata could not be read",
            code="CHECKPOINT_INVALID",
        ) from exc
    if not isinstance(document, dict):
        raise IngestionError(
            "the checkpoint metadata is not a JSON object",
            code="CHECKPOINT_INVALID",
        )
    return document


def _cleanup(staging: Path) -> None:
    """Remove staging without letting a cleanup error mask the real outcome."""

    try:
        rmtree_force(staging)
    except OSError:  # pragma: no cover - rmtree_force is already best-effort
        pass


def discover(
    request: DiscoveryRequest,
    store: Path | str,
    *,
    progress: Progress | None = None,
    limits: Limits = DEFAULT_LIMITS,
) -> DiscoveryResult:
    """Run the whole Stage 1 workflow and return the blueprint.

    Raises :class:`~p1.errors.IngestionError` on any refusal; staging is always
    removed first and no blueprint is written for a refused input.  Any other
    exception also reports its step as ``failed`` before propagating.
    """

    store = Path(store)
    _validate_request(request, store)
    store.mkdir(parents=True, exist_ok=True)
    steps = _Steps(progress)
    sink = DiagnosticSink(limits.max_diagnostics)
    staging = Path(tempfile.mkdtemp(prefix="p1-stage-", dir=store))
    try:
        steps.emit("ingestion", "running")
        ingestion, archive = _ingest(request, staging, limits, sink)
        steps.emit("ingestion", "completed",
                   f"{ingestion.entry_count} files from {ingestion.kind}")

        steps.emit("checkpoint", "running")
        info = create_checkpoint(
            ingestion, store,
            origin_label=_origin_for_checkpoint(request, ingestion),
            ref=ingestion.ref or (request.ref or ""),
            tree_id=ingestion.tree_id, original_archive=archive,
        )
        steps.emit("checkpoint", "completed",
                   f"{info.checkpoint_id}{' (reused)' if info.reused else ''}")

        found = _analyse(ingestion, info.source_root, limits, sink, steps)

        steps.emit("blueprint", "running")
        discovery = _build_discovery(request, ingestion, info, found, limits,
                                     sink)
        scrub = (str(info.source_root), str(staging),
                 str(ingestion.staging_root), str(store))
        outdir, blueprint, outputs = _publish(discovery, info, store, scrub)
        steps.emit("blueprint", "completed", blueprint["stage"]["status"])
        outputs["run_record"] = _write_run_record(outdir, info, steps)
        return DiscoveryResult(info, outdir, blueprint, outputs, info.reused)
    except IngestionError as exc:
        steps.emit(steps.current or "ingestion", "failed", exc.code)
        raise
    except Exception:
        steps.emit(steps.current or "ingestion", "failed", "INTERNAL_ERROR")
        raise
    finally:
        _cleanup(staging)
