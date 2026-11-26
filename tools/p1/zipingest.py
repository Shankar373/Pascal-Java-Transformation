"""Secure ZIP ingestion (task B1, plan §4.1–4.3).

The extraction strategy is **validate everything first, then extract**.  A
hostile archive is rejected before a single byte is written, so a failure
cannot leave a partially-materialised tree behind for a later step to trip
over.  Every bound is enforced twice where it matters: declared sizes are
checked from the central directory, and bytes actually written are counted
while streaming, because a zip-bomb attacker controls the declaration.

Nothing here executes, imports or interprets archive content.
"""

from __future__ import annotations

import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .errors import (
    DiagnosticSink,
    IngestionError,
    LimitExceededError,
    UnsupportedInputError,
)
from .hashing import sha256_file
from .limits import DEFAULT_LIMITS, Limits
from .model import IngestedFile, IngestionResult
from .pathsafe import clean_entry_name, resolve_within

__all__ = ["ingest_zip"]


@dataclass(frozen=True)
class _Entry:
    """A validated central-directory entry, ready for extraction."""

    info: zipfile.ZipInfo
    relpath: str
    is_dir: bool


def _mode_of(info: zipfile.ZipInfo) -> int:
    """Unix permission bits stored in the high half of ``external_attr``."""

    return (info.external_attr >> 16) & 0xFFFF


#: Unix file-type mask (``S_IFMT``) and the type values we must refuse.
_IFMT = 0o170000
_IFLNK = 0o120000
_IFIFO = 0o010000
_IFCHR = 0o020000
_IFDIR = 0o040000
_IFBLK = 0o060000
_IFREG = 0o100000
_IFSOCK = 0o140000

_SPECIAL_TYPES = {
    _IFLNK: "symlink",
    _IFIFO: "FIFO",
    _IFCHR: "character device",
    _IFBLK: "block device",
    _IFSOCK: "socket",
}


def _check_special_file(info: zipfile.ZipInfo) -> None:
    """Reject symlinks, fifos, sockets and device nodes (plan §4.3).

    Only an **explicit** special type is refused.  Some archivers store DOS
    attribute bits (``0x20`` archive flag) in the same high word; those produce
    a type field of ``0`` or an unrecognised value and must not be mistaken for
    a symlink — a false rejection here would make ordinary enterprise archives
    uningestable, which is its own availability bug.
    """

    mode = _mode_of(info)
    file_type = mode & _IFMT
    if file_type == 0:
        return  # no unix type information stored
    if file_type in _SPECIAL_TYPES:
        raise IngestionError(
            f"{_SPECIAL_TYPES[file_type]} entry refused: {info.filename!r}",
            code="SYMLINK_ENTRY" if file_type == _IFLNK else "SPECIAL_FILE_ENTRY",
            path=info.filename,
        )
    # Regular file and directory are the only remaining expected types.
    if file_type not in (_IFREG, _IFDIR):
        # Unrecognised type bits: not one of the refusable specials above, so
        # treat as a regular file rather than rejecting a valid archive.
        return


def _check_ratio(info: zipfile.ZipInfo, limits: Limits) -> None:
    """Reject declared expansion beyond the compression-ratio bound."""

    if info.compress_size >= limits.min_bytes_for_ratio and info.file_size > 0:
        ratio = info.file_size / max(1, info.compress_size)
        if ratio > limits.max_compression_ratio:
            raise LimitExceededError(
                f"compression ratio {ratio:.1f} exceeds "
                f"{limits.max_compression_ratio} for {info.filename!r}",
                code="ZIP_BOMB_RATIO",
                path=info.filename,
            )


def _dos_timestamp(info: zipfile.ZipInfo) -> str:
    """Source-derived (DOS) modification time — never the current clock."""

    try:
        year, month, day, hour, minute, second = info.date_time
    except (TypeError, ValueError):  # pragma: no cover - malformed tuple
        return ""
    if year < 1980 or month < 1 or day < 1:
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}T{hour:02d}:{minute:02d}:{second:02d}"


def ingest_zip(
    archive: Path,
    staging: Path,
    *,
    origin: str | None = None,
    limits: Limits = DEFAULT_LIMITS,
    sink: DiagnosticSink | None = None,
) -> IngestionResult:
    """Extract *archive* into *staging* under the full security model.

    *staging* must be a directory the caller owns and can discard.

    **Phase 1** validates the entire central directory — names, types,
    duplicates, declared sizes, compression ratios — before a single byte is
    written, so no policy refusal can ever leave a partial tree behind.
    **Phase 2** then materialises and re-counts bytes, because declared sizes
    are untrusted.  A phase-2 failure (truncated or corrupt data, I/O error)
    raises and leaves an incomplete tree, which the caller discards:
    ``pipeline.py`` removes the staging directory on any failure.

    Raises :class:`~p1.errors.IngestionError` (and subclasses) on any refusal.
    """

    archive = Path(archive)
    staging = Path(staging)
    sink = sink or DiagnosticSink(limits.max_diagnostics)

    if not archive.is_file():
        raise UnsupportedInputError(
            f"archive not found: {archive}", code="INPUT_NOT_FOUND"
        )

    # --- Phase 1: open and validate the central directory. -----------------
    try:
        zf = zipfile.ZipFile(archive, "r")
    except zipfile.BadZipFile as exc:
        raise UnsupportedInputError(
            f"not a readable ZIP archive: {exc}", code="NOT_A_ZIP"
        ) from None
    except OSError as exc:
        raise UnsupportedInputError(
            f"archive could not be opened: {exc}", code="INPUT_UNREADABLE"
        ) from None

    with zf:
        infos = zf.infolist()
        if len(infos) > limits.max_entries:
            raise LimitExceededError(
                f"{len(infos)} entries exceed max_entries={limits.max_entries}",
                code="TOO_MANY_ENTRIES",
            )

        declared_total = 0
        seen: dict[str, str] = {}  # casefolded relpath -> original name
        entries: list[_Entry] = []

        for info in infos:
            raw_name = info.filename
            if not raw_name:
                raise IngestionError(
                    "entry with empty name", code="UNSAFE_PATH", path="<empty>"
                )

            _check_special_file(info)

            relpath = clean_entry_name(raw_name, limits)

            # Duplicate detection.  Windows staging is case-insensitive, so
            # "A.pas" and "a.pas" are the same file: refuse rather than let
            # one silently overwrite the other.
            key = relpath.casefold()
            if key in seen:
                raise IngestionError(
                    f"duplicate entry name {relpath!r} collides with "
                    f"{seen[key]!r} (case-insensitive filesystem)",
                    code="DUPLICATE_ENTRY",
                    path=relpath,
                )
            seen[key] = raw_name

            is_dir = info.is_dir() or raw_name.endswith(("/", "\\"))
            if is_dir:
                entries.append(_Entry(info, relpath, True))
                continue

            if info.file_size > limits.max_entry_bytes:
                raise LimitExceededError(
                    f"declared size {info.file_size} exceeds max_entry_bytes="
                    f"{limits.max_entry_bytes}",
                    code="ENTRY_TOO_LARGE",
                    path=relpath,
                )
            declared_total += info.file_size
            if declared_total > limits.max_total_bytes:
                raise LimitExceededError(
                    f"declared total {declared_total} exceeds max_total_bytes="
                    f"{limits.max_total_bytes}",
                    code="TOTAL_TOO_LARGE",
                    path=relpath,
                )
            _check_ratio(info, limits)
            entries.append(_Entry(info, relpath, False))

        # --- Phase 2: materialise. ----------------------------------------
        written_total = 0
        produced: list[IngestedFile] = []

        for entry in entries:
            target = resolve_within(staging, entry.relpath)
            if entry.is_dir:
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.is_dir():
                raise IngestionError(
                    f"path is both a file and a directory: {entry.relpath!r}",
                    code="DUPLICATE_ENTRY",
                    path=entry.relpath,
                )

            expected = entry.info.file_size
            written = 0
            with zf.open(entry.info, "r") as src, target.open("wb") as dst:
                while True:
                    chunk = src.read(1024 * 1024)
                    if not chunk:
                        break
                    written += len(chunk)
                    written_total += len(chunk)
                    # Counted bounds: the declaration is untrusted.
                    if written > limits.max_entry_bytes:
                        raise LimitExceededError(
                            f"entry grew past max_entry_bytes="
                            f"{limits.max_entry_bytes} while extracting",
                            code="ENTRY_TOO_LARGE",
                            path=entry.relpath,
                        )
                    if written_total > limits.max_total_bytes:
                        raise LimitExceededError(
                            f"extraction grew past max_total_bytes="
                            f"{limits.max_total_bytes}",
                            code="TOTAL_TOO_LARGE",
                            path=entry.relpath,
                        )
                    dst.write(chunk)

            if written != expected:
                raise IngestionError(
                    f"declared {expected} bytes but extracted {written}",
                    code="SIZE_MISMATCH",
                    path=entry.relpath,
                )

            produced.append(
                IngestedFile(
                    path=entry.relpath,
                    sha256=sha256_file(target),
                    size=written,
                    source_timestamp=_dos_timestamp(entry.info),
                )
            )

        # Directories are recorded only as structure; the manifest lists files.
        produced.sort(key=lambda f: f.path)

        result = IngestionResult(
            kind="zip",
            origin=origin if origin is not None else str(archive),
            staging_root=staging.resolve(),
            files=produced,
            entry_count=len(infos),
            total_bytes=written_total,
            limits=limits,
        )
        sink.info(
            "ZIP_INGESTED",
            f"{len(produced)} file(s), {written_total} byte(s) extracted "
            f"from {len(infos)} entr{'y' if len(infos) == 1 else 'ies'}",
        )
        result.diagnostics = sink.to_list()
        return result
