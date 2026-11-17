"""Shared ingestion results and the plain-directory ingest path.

``ingest_directory`` is the common tail of every other path: ZIP ingestion
validates then extracts into a staging root, Git clones then verifies, and
both finish by walking the staged tree, hashing every file and recording it
with a source-derived timestamp.  Sharing that tail guarantees the manifest
cannot differ between input kinds for identical bytes.
"""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from .errors import Diagnostic, DiagnosticSink, IngestionError
from .hashing import sha256_file
from .limits import DEFAULT_LIMITS, Limits

if TYPE_CHECKING:  # pragma: no cover - import cycle avoidance only
    from .dialects import SourceAnalysis
    from .plex import ScanResult

__all__ = [
    "IngestedFile",
    "IngestionResult",
    "AnalysedFile",
    "walk_files",
    "ingest_directory",
    "rmtree_force",
]


def rmtree_force(path: Path) -> None:
    """Delete *path* even when its files are read-only.

    ``shutil.rmtree(..., ignore_errors=True)`` **silently leaves read-only
    files behind**.  Git stores pack files as ``0o444``, so a plain rmtree on
    Windows would leave ``.git/objects`` inside the staged tree and the
    inventory would hash VCS metadata as if it were source.  This helper
    clears the write bit bottom-up first, then removes; failures after that
    are still ignored because cleanup is best-effort by contract (the caller
    is discarding the tree, never inspecting it).
    """

    if not path.exists():
        return

    def _on_walk_error(_error: OSError) -> None:
        return None

    for root, _dirs, files in os.walk(path, topdown=False,
                                      onerror=_on_walk_error):
        for name in files:
            target = Path(root) / name
            try:
                target.chmod(0o666)
            except OSError:
                pass
        for name in _dirs:
            target = Path(root) / name
            try:
                target.chmod(0o777)
            except OSError:
                pass
    try:
        path.chmod(0o777)
    except OSError:
        pass
    shutil.rmtree(path, ignore_errors=True)


@dataclass(frozen=True)
class IngestedFile:
    """One staged file, with everything the manifest needs."""

    path: str  # POSIX, relative to the staging root
    sha256: str
    size: int
    #: Source-derived timestamp, never wall-clock: ZIP DOS time or the Git
    #: commit time.  ``""`` when the source carries none.
    source_timestamp: str = ""
    #: True when the path is excluded from the Pascal analysis (e.g. VCS metadata).
    excluded: bool = False
    exclusion_reason: str = ""

    def as_dict(self) -> dict[str, object]:
        out: dict[str, object] = {
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
        }
        if self.source_timestamp:
            out["source_timestamp"] = self.source_timestamp
        if self.excluded:
            out["excluded"] = self.exclusion_reason
        return out


@dataclass
class IngestionResult:
    """Everything an ingestion run produced, before any Pascal analysis."""

    kind: str  # "zip" | "git" | "directory"
    origin: str
    staging_root: Path
    files: list[IngestedFile] = field(default_factory=list)
    commit: str | None = None
    #: Git commit time of the pinned commit; never wall-clock.
    commit_timestamp: str = ""
    entry_count: int = 0
    total_bytes: int = 0
    diagnostics: list[Diagnostic] = field(default_factory=list)
    limits: Limits = DEFAULT_LIMITS

    @property
    def source_timestamp(self) -> str:
        """Deterministic source timestamp for the run.

        The pinned commit time when there is one, otherwise the earliest
        source-carried timestamp.  Never the current clock.
        """

        if self.commit_timestamp:
            return self.commit_timestamp
        times = sorted(f.source_timestamp for f in self.files if f.source_timestamp)
        return times[0] if times else ""

    def paths(self) -> list[str]:
        return [f.path for f in self.files]

    def get(self, path: str) -> IngestedFile | None:
        for f in self.files:
            if f.path == path:
                return f
        return None


@dataclass
class AnalysedFile:
    """One inventoried file joined with whatever analysis was possible.

    ``scan``/``analysis`` are ``None`` for every file that is not Pascal
    source, for files above ``max_source_bytes`` and for binaries — which is
    exactly why the file is still present: analysis being impossible is not a
    reason to drop a file (task D4).
    """

    inventory: IngestedFile
    cls: str
    class_evidence: tuple[str, ...] = ()
    encoding: str = "ascii"
    encoding_confidence: str = "high"
    bom: bool = False
    discovery_only: bool = True
    #: ``""`` when analysis ran; otherwise why it did not.
    analysis_blocker: str = ""
    #: Where this file physically lives.  Relative metadata is authoritative;
    #: this is only used to re-open the file for project-file parsing, and is
    #: never written to an artefact.
    staging_root: Path | None = None
    scan: "ScanResult | None" = None
    analysis: "SourceAnalysis | None" = None

    @property
    def path(self) -> str:
        return self.inventory.path


def walk_files(root: Path, *, skip: tuple[str, ...] = ()) -> list[tuple[str, Path]]:
    """Return ``(posix_relative_path, absolute_path)`` for every file under *root*.

    Deterministic: sorted by relative path.  ``skip`` holds path prefixes
    (POSIX, directory names such as ``".git"``) that are not inventoried —
    callers must record why, so the exclusion is explicit rather than silent.
    """

    skip_set = {s.lower() for s in skip}
    out: list[tuple[str, Path]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skipped directories in-place so os.walk does not descend.
        dirnames[:] = sorted(d for d in dirnames if d.lower() not in skip_set)
        current = Path(dirpath)
        for filename in sorted(filenames):
            absolute = current / filename
            if not absolute.is_file():
                continue  # sockets/fifos/etc. are never inventoried
            rel = absolute.relative_to(root).as_posix()
            out.append((rel, absolute))
    out.sort(key=lambda pair: pair[0])
    return out


def ingest_directory(
    root: Path,
    *,
    origin: str,
    kind: str = "directory",
    skip: tuple[str, ...] = (),
    skip_reason: str = "",
    sink: DiagnosticSink | None = None,
    limits: Limits = DEFAULT_LIMITS,
) -> IngestionResult:
    """Hash and inventory an already-staged directory tree.

    Excluded prefixes are reported through *sink* as an ``INFO`` diagnostic so
    the omission appears in the manifest instead of vanishing.
    """

    root = root.resolve()
    if not root.is_dir():
        raise IngestionError(
            f"staging root is not a directory: {root}", code="STAGING_INVALID"
        )

    result = IngestionResult(
        kind=kind, origin=origin, staging_root=root, limits=limits
    )
    sink = sink or DiagnosticSink(limits.max_diagnostics)

    files = walk_files(root, skip=skip)
    # Only report an exclusion that actually occurred: announcing that `.git`
    # was skipped when the tree has no `.git` would put a phantom entry in
    # every manifest (and make two identical inputs differ).
    actually_skipped = sorted(
        prefix for prefix in skip if (root / prefix).exists()
    )
    if actually_skipped and sink is not None:
        sink.info(
            "PATH_EXCLUDED_FROM_INVENTORY",
            f"prefix(es) {', '.join(actually_skipped)} not inventoried"
            + (f": {skip_reason}" if skip_reason else ""),
        )

    total = 0
    for rel, absolute in files:
        size = absolute.stat().st_size
        total += size
        if total > limits.max_total_bytes:
            raise IngestionError(
                f"staged tree exceeds max_total_bytes="
                f"{limits.max_total_bytes} ({total} bytes observed)",
                code="LIMIT_EXCEEDED",
                path=rel,
            )
        result.files.append(
            IngestedFile(
                path=rel,
                sha256=sha256_file(absolute),
                size=size,
            )
        )

    result.entry_count = len(result.files)
    result.total_bytes = total
    result.diagnostics = sink.to_list()
    return result
