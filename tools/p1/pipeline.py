"""End-to-end P1 discovery pipeline.

    ingest  ->  classify  ->  analyse  ->  roots/profiles/shapes
            ->  metadata  ->  graph  ->  emit

Two rules shape this module:

**Staging is disposable and never observable.**  A temporary directory is
created for ZIP/Git inputs, removed on *both* success and failure, and its
path is scrubbed from every artefact.  A failure therefore cannot leave a
partial tree behind, and a success cannot leak where it worked.

**Analysis being impossible never removes a file.**  A file above
``max_source_bytes``, a binary, or an undecodable blob is still hashed,
classified and listed in the manifest with an explicit ``analysis_blocker``.
Dropping it would make the inventory lie (task D4).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .classify import PASCAL_SOURCE_CLASSES, classify
from .deps import build_graph
from .dialects import analyse_source
from .emit import Discovery, write_outputs
from .errors import (
    Diagnostic,
    DiagnosticSink,
    IngestionError,
    UnsupportedInputError,
)
from .gitingest import ingest_git, resolve_git_source
from .hashing import detect_encoding
from .limits import DEFAULT_LIMITS, Limits
from .metadata import (
    build_requirements,
    detect_database,
    detect_native_libs,
    detect_os_dependencies,
    detect_sql_files,
)
from .model import AnalysedFile, ingest_directory, rmtree_force
from .plex import scan as scan_source
from .projects import (
    Profile,
    ProjectRoot,
    apply_source_profile,
    detect_shape,
    find_project_roots,
    parse_project_file,
)
from .zipingest import ingest_zip

__all__ = ["PipelineResult", "run", "analyse_tree"]

#: Extensions treated as ZIP archives when the kind is not given.
_ARCHIVE_SUFFIXES = (".zip", ".jar", ".ear", ".war", ".epub", ".docx", ".xlsx")


@dataclass
class PipelineResult:
    """Outcome of one :func:`run` invocation."""

    discovery: Discovery
    outputs: dict[str, str]
    outdir: Path
    #: Set when the input was staged in a temporary directory and removed.
    staged: bool = False
    diagnostics: list[dict[str, object]] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Input classification
# ---------------------------------------------------------------------------


def resolve_kind(source: str, explicit: str | None) -> str:
    """Decide whether *source* is a ``zip``, ``git`` or ``directory`` input.

    Refuses anything ambiguous rather than guessing: a wrong choice here would
    route untrusted bytes down the wrong security model.
    """

    if explicit:
        if explicit not in ("zip", "git", "directory"):
            raise UnsupportedInputError(
                f"unknown input kind {explicit!r}",
                code="UNKNOWN_INPUT_KIND",
                path=str(source),
            )
        return explicit

    text = str(source)
    if text.startswith(("http://", "https://", "ssh://", "git://")):
        # Network remotes are refused later, with a clearer message, but the
        # kind is unambiguous: it is a git source.
        return "git"
    if text.startswith("file://"):
        return "git"

    path = Path(text)
    lowered = path.name.lower()
    if lowered.endswith(_ARCHIVE_SUFFIXES):
        return "zip"
    if path.is_dir():
        return "git" if (path / ".git").exists() else "directory"
    if path.is_file():
        with path.open("rb") as handle:
            magic = handle.read(4)
        if magic[:2] == b"PK":
            return "zip"
        raise UnsupportedInputError(
            "input is neither a directory nor a recognised archive; "
            "pass --kind to state the input type explicitly",
            code="UNSUPPORTED_INPUT",
            path=path.name,
        )
    raise UnsupportedInputError(
        f"input not found: {path.name}",
        code="INPUT_NOT_FOUND",
        path=path.name,
    )


def _origin_label(source: str, kind: str) -> str:
    """A short, path-free label for ``source.origin`` (never an absolute path)."""

    text = str(source)
    if text.startswith("file://"):
        text = text[7:]
    if text.endswith("/"):
        text = text[:-1]
    name = text.rstrip("/\\").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    if kind == "git" and text.endswith(".git"):
        name = name[:-4]
    return name or kind


# ---------------------------------------------------------------------------
# Ingestion
# ---------------------------------------------------------------------------


def _ingest(
    source: str,
    kind: str,
    staging: Path | None,
    limits: Limits,
    commit: str | None,
    sink: DiagnosticSink,
):
    """Run the right ingestion path and return its :class:`IngestionResult`."""

    if kind == "zip":
        if staging is None:  # pragma: no cover - guarded by run()
            raise IngestionError("zip ingestion requires a staging directory",
                                 code="STAGING_INVALID")
        return ingest_zip(
            Path(source), staging, origin=_origin_label(source, kind),
            limits=limits, sink=sink,
        )
    if kind == "git":
        if staging is None:  # pragma: no cover - guarded by run()
            raise IngestionError("git ingestion requires a staging directory",
                                 code="STAGING_INVALID")
        return ingest_git(
            source, staging, commit=commit, limits=limits, sink=sink,
        )
    # Plain directory: inventoried in place.  Nothing is extracted, so there
    # is nothing to stage and nothing to clean up.
    root = Path(source).resolve()
    if not root.is_dir():
        raise UnsupportedInputError(
            f"not a directory: {root.name}",
            code="INPUT_NOT_FOUND",
            path=root.name,
        )
    return ingest_directory(
        root, origin=_origin_label(source, kind), kind="directory",
        skip=(".git",), skip_reason="version-control metadata",
        sink=sink, limits=limits,
    )


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------


def _read_head(absolute: Path, limit: int) -> bytes:
    with absolute.open("rb") as handle:
        return handle.read(limit)


def _decode(data: bytes, encoding: str) -> str:
    """Decode *data*, falling back through a fixed, ordered codec list.

    ``latin-1`` is last and cannot fail, so this always returns text — a
    source file we cannot decode is still scanned rather than skipped, with
    whatever mojibake it contains.
    """

    for codec in (encoding, "utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = data.decode(codec)
        except (LookupError, UnicodeDecodeError):
            continue
        if text.startswith("﻿"):
            text = text[1:]
        return text
    return data.decode("latin-1")  # pragma: no cover - latin-1 cannot fail


def analyse_tree(
    ingestion: Any,
    limits: Limits,
    sink: DiagnosticSink,
) -> list[AnalysedFile]:
    """Classify, decode and scan every inventoried file.

    Files that cannot be analysed are kept with an ``analysis_blocker``; the
    only thing analysis can do is *add* information, never remove a file.
    """

    analysed: list[AnalysedFile] = []
    for ingested in ingestion.files:
        absolute = ingestion.staging_root / ingested.path
        try:
            head = _read_head(absolute, limits.max_sniff_bytes)
        except OSError as exc:  # pragma: no cover - races are not testable
            sink.error(
                "FILE_UNREADABLE",
                f"could not read staged file: {exc}",
                path=ingested.path,
            )
            analysed.append(AnalysedFile(
                inventory=ingested,
                cls="unknown",
                class_evidence=("unreadable",),
                encoding="unknown",
                encoding_confidence="low",
                analysis_blocker="unreadable",
            ))
            continue

        result = classify(ingested.path, head, size=ingested.size,
                          limits=limits)
        cls = result.cls

        if cls == "binary":
            encoding, confidence, bom = "binary", "low", False
        else:
            guess = detect_encoding(head)
            encoding, confidence, bom = (
                guess.name, guess.confidence, guess.bom
            )

        item = AnalysedFile(
            inventory=ingested,
            cls=cls,
            class_evidence=result.evidence,
            encoding=encoding,
            encoding_confidence=confidence,
            bom=bom,
            discovery_only=result.discovery_only,
            analysis_blocker=result.analysis_blocker,
        )

        if cls in PASCAL_SOURCE_CLASSES and not result.analysis_blocker:
            if ingested.size > limits.max_source_bytes:
                item.analysis_blocker = "too-large"
            else:
                try:
                    text = _decode(absolute.read_bytes(), encoding)
                except OSError as exc:  # pragma: no cover - races
                    sink.error(
                        "FILE_UNREADABLE",
                        f"could not read staged file: {exc}",
                        path=ingested.path,
                    )
                    item.analysis_blocker = "unreadable"
                else:
                    item.scan = scan_source(
                        text, path=ingested.path, limits=limits
                    )
                    item.analysis = analyse_source(item.scan, ingested.path)
                    item.discovery_only = False

        analysed.append(item)

    return analysed


# ---------------------------------------------------------------------------
# Roots, profiles and shapes
# ---------------------------------------------------------------------------


def _merge_profile(target: Profile, incoming: Profile) -> None:
    """Overlay *incoming* onto *target*, keeping whichever states a value."""

    if target.mode == "not-specified" and incoming.mode != "not-specified":
        target.mode = incoming.mode
    for define in incoming.defines:
        if define not in target.defines:
            target.defines.append(define)
    if target.platform == "not-specified" and incoming.platform != "not-specified":
        target.platform = incoming.platform
    for path in incoming.unit_search_paths:
        if path not in target.unit_search_paths:
            target.unit_search_paths.append(path)
    for field_name in ("range_check", "overflow_check", "string_model",
                       "app_type", "output_kind"):
        current = getattr(target, field_name)
        value = getattr(incoming, field_name)
        if current == "not-specified" and value != "not-specified":
            setattr(target, field_name, value)
    target.evidence.extend(incoming.evidence)
    target.sources.extend(incoming.sources)


def build_roots(
    analysed: list[AnalysedFile],
    sink: DiagnosticSink,
) -> tuple[list[ProjectRoot], dict[str, Profile], list[dict[str, object]]]:
    """Detect roots, parse their project files and shape them.

    Every root's profile starts from its project file (``.dproj``/``.lpi``)
    and is then overlaid with the directives found in the entry-point source,
    so the reported profile reflects what would actually be passed to the
    compiler for that file.
    """

    paths = [item.path for item in analysed]
    roots, diagnostics = find_project_roots(paths)
    for payload in diagnostics:
        sink.add(_as_diagnostic(payload))

    by_path = {item.path: item for item in analysed}
    profiles: dict[str, Profile] = {}

    for root in roots:
        profile = Profile()
        for meta in sorted(root.meta_files):
            item = by_path.get(meta)
            if item is None:  # pragma: no cover - meta comes from the same list
                continue
            absolute = _absolute(item)
            if absolute is None:
                text = ""
            else:
                try:
                    text = absolute.read_text(encoding="utf-8",
                                              errors="replace")
                except OSError:  # pragma: no cover - races
                    text = ""
            parsed, parse_diagnostics = parse_project_file(meta, text)
            _merge_profile(profile, parsed)
            for payload in parse_diagnostics:
                sink.add(_as_diagnostic(payload))

        item = by_path.get(root.path)
        if item is not None:
            apply_source_profile(profile, item.scan, item.analysis, root.path)
            detect_shape(root, item.scan, item.analysis, profile)
        else:
            detect_shape(root, None, None, profile)

        root.profile = profile
        profiles[root.path] = profile
        for payload in root.diagnostics:
            sink.add(_as_diagnostic(payload))

    return roots, profiles, diagnostics


def _absolute(item: AnalysedFile) -> Path | None:
    """Absolute path of an inventoried file, when it is still reachable.

    ``AnalysedFile`` carries only POSIX-relative metadata, so the run's
    ingestion root is attached to each item by :func:`_attach_staging`.
    """

    staging = getattr(item, "staging_root", None)
    if staging is None:  # pragma: no cover - run() always attaches
        return None
    return Path(staging) / item.path


def _attach_staging(analysed: list[AnalysedFile], staging: Path) -> None:
    """Record where each analysed file physically lives (relative paths stay)."""

    for item in analysed:
        item.staging_root = staging


# ---------------------------------------------------------------------------
# Diagnostics helper
# ---------------------------------------------------------------------------


def _as_diagnostic(payload: dict[str, object]) -> Diagnostic:
    """Convert a plain diagnostic dict into a typed :class:`Diagnostic`."""

    code = str(payload.get("code", "DISCOVERY_DIAGNOSTIC"))
    message = str(payload.get("message", ""))
    kwargs: dict[str, object] = {}
    if payload.get("file") is not None:
        kwargs["path"] = payload["file"]
    if payload.get("line") is not None:
        kwargs["line"] = payload["line"]
    if payload.get("column") is not None:
        kwargs["column"] = payload["column"]
    return Diagnostic.make(code, message, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------


def run(
    source: str,
    outdir: Path | str,
    *,
    kind: str | None = None,
    commit: str | None = None,
    limits: Limits = DEFAULT_LIMITS,
    origin_label: str | None = None,
) -> PipelineResult:
    """Ingest *source*, discover the application, write the three artefacts.

    Raises :class:`~p1.errors.IngestionError` on any refusal.  The staging
    directory is removed before the exception propagates.
    """

    outdir = Path(outdir)
    resolved_kind = resolve_kind(source, kind)

    if resolved_kind == "git":
        # Fail fast on network remotes with the dedicated diagnostic.
        resolve_git_source(str(source))

    sink = DiagnosticSink(limits.max_diagnostics)
    staging: Path | None = None
    staged = False

    if resolved_kind in ("zip", "git"):
        staging = Path(tempfile.mkdtemp(prefix="p1-stage-"))
        staged = True

    try:
        ingestion = _ingest(source, resolved_kind, staging, limits, commit, sink)

        analysed = analyse_tree(ingestion, limits, sink)
        # Always attach the physical root: project files must be readable for
        # directory inputs too, where nothing was extracted.
        _attach_staging(analysed, ingestion.staging_root)

        roots, profiles, _ = build_roots(analysed, sink)

        graph_build = build_graph(analysed, roots, sink=sink)
        for payload in graph_build.diagnostics:
            sink.add(_as_diagnostic(payload))

        database = detect_database(analysed)
        sql_files = detect_sql_files(
            analysed, _text_index(analysed, ingestion, limits)
        )
        native_libs = detect_native_libs(analysed)
        os_dependencies = detect_os_dependencies(analysed)
        requirements = build_requirements(
            analysed,
            roots,
            profiles,
            graph_build.unresolved_units,
            has_project_files=any(r.meta_files for r in roots),
            sink=sink,
        )

        discovery = Discovery(
            ingestion=ingestion,
            analysed=analysed,
            roots=roots,
            graph=graph_build.graph,
            database=database,
            sql_files=sql_files,
            native_libs=native_libs,
            os_dependencies=os_dependencies,
            build_requirements=requirements,
            diagnostics=sink.to_list(),
            origin_label=origin_label or _origin_label(source, resolved_kind),
            limits=limits,
        )

        staging_roots: tuple[str, ...] = ()
        if staged and staging is not None:
            # Both the temp root and the resolved staging root: a resolve()
            # can change case or shorten a path on Windows, and neither form
            # may appear in an artefact.
            staging_roots = (str(staging), str(ingestion.staging_root))
        outputs = write_outputs(
            discovery, outdir, staging_roots=staging_roots
        )

        return PipelineResult(
            discovery=discovery,
            outputs=outputs,
            outdir=outdir,
            staged=staged,
            diagnostics=sink.to_list(),
        )
    finally:
        # Never leave a partial tree behind (plan §4.1): a refused input or a
        # failed extraction must not persist its staging directory, and a
        # successful run must not keep one either.  Read-only git objects
        # would defeat a plain rmtree, so cleanup is forced.
        if staging is not None:
            rmtree_force(staging)


def _text_index(
    analysed: list[AnalysedFile], ingestion: Any, limits: Limits
) -> dict[str, str]:
    """Read inventory-only text files so their content is analysable.

    Bounded by ``max_source_bytes``: an oversized file yields no text and is
    therefore reported as ``UNKNOWN`` rather than silently assumed to be
    something it might not be.
    """

    out: dict[str, str] = {}
    for item in analysed:
        if item.cls not in ("sql", "configuration", "database"):
            continue
        if item.inventory.size > limits.max_source_bytes:
            continue
        absolute = Path(ingestion.staging_root) / item.path
        try:
            data = absolute.read_bytes()
        except OSError:  # pragma: no cover - races
            continue
        out[item.path] = _decode(data, item.encoding)
    return out
