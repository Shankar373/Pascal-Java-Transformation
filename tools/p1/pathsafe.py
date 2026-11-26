"""Path hardening for ingested entry names (plan §4.2).

Defence in depth, in this order:

1. **Lexical rules** — reject names that are structurally unsafe before any
   filesystem call (traversal, absolute, drive/UNC, ADS, reserved devices,
   control/bidi characters, trailing dot/space, depth/length).
2. **Normalisation** — both ``/`` and ``\\`` are separators (the staging
   filesystem is Windows, where ``\\`` is a separator and ``/`` is accepted),
   then ``.`` components are dropped and ``..`` re-checked.
3. **Containment** — the joined path is resolved and must remain inside the
   staging root, which is also resolved.  This catches anything lexical
   analysis missed (junctions, symlinks already present in staging).

Every rejection raises :class:`~p1.errors.UnsafePathError` with a stable code,
so the adversarial suite asserts on codes instead of message wording.
"""

from __future__ import annotations

import os
import re
import unicodedata
from pathlib import Path, PurePosixPath

from .errors import UnsafePathError
from .limits import DEFAULT_LIMITS, Limits

__all__ = [
    "clean_entry_name",
    "is_reserved_device_name",
    "resolve_within",
    "SEPARATORS",
]

#: Both characters act as separators on the Windows staging filesystem.
SEPARATORS = "/\\"

#: C0 controls, DEL and C1 controls.  NUL is included.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")

#: Bidi overrides/enclosures used for display spoofing (e.g. U+202E RLO).
_BIDI_RE = re.compile(
    "[\u202a-\u202e\u2066-\u2069\u2028\u2029\u200e\u200f]"
)

#: Windows reserved device names, matched against the first path component
#: with or without an extension (``CON.txt`` is still reserved).
_RESERVED_DEVICES = frozenset(
    {"CON", "PRN", "AUX", "NUL"}
    | {f"COM{i}" for i in range(1, 10)}
    | {f"LPT{i}" for i in range(1, 10)}
)

#: Drive-letter pattern at the start of a component (``C:``, ``c:\``).
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def is_reserved_device_name(component: str) -> bool:
    """True when *component* names a Windows device (case-insensitive)."""

    stem = component.split(".", 1)[0]
    return stem.upper() in _RESERVED_DEVICES


def _reject(name: str, reason: str) -> "UnsafePathError":
    return UnsafePathError(
        f"entry name rejected: {reason}",
        code="UNSAFE_PATH",
        path=name,
    )


def clean_entry_name(raw: str, limits: Limits = DEFAULT_LIMITS) -> str:
    """Validate and normalise one entry name; return the relative POSIX path.

    The returned value is always relative, uses ``/``, contains no ``..`` and
    no empty component.  Anything that cannot satisfy that raises
    :class:`UnsafePathError`.

    Note that this function does **not** touch the filesystem: it is pure, so
    it is exhaustively unit-testable and has no side effects on rejection.
    """

    if not isinstance(raw, str):  # pragma: no cover - defensive
        raise _reject(repr(raw), "not a string")
    if raw == "":
        raise _reject(raw, "empty name")

    # 1. Characters that are never legal in an entry name.
    if "\x00" in raw:
        raise _reject(_display(raw), "contains NUL")
    if _CONTROL_RE.search(raw):
        bad = _CONTROL_RE.search(raw)
        assert bad is not None
        raise _reject(
            _display(raw),
            f"contains control character U+{ord(bad.group()):04X}",
        )
    if _BIDI_RE.search(raw):
        raise _reject(_display(raw), "contains bidirectional override character")

    # 2. Normalise unicode so two spellings cannot produce one file twice
    #    (NFC is what Windows' and macOS' default normalisers produce).
    if unicodedata.normalize("NFC", raw) != raw:
        raise _reject(_display(raw), "is not NFC-normalised (ambiguous name)")

    # 3. Length of the whole path and of each component.
    if len(raw) > limits.max_path_length:
        raise _reject(
            _display(raw[:80]) + "...",
            f"path exceeds {limits.max_path_length} characters",
        )
    for component in re.split(r"[/\\]", raw):
        if len(component) > limits.max_name_length:
            raise _reject(
                _display(component[:80]) + "...",
                f"path component exceeds {limits.max_name_length} characters",
            )

    # 4. Absolute / drive / UNC / device-prefixed forms.
    if raw[0] in SEPARATORS:
        raise _reject(_display(raw), "is absolute")
    if _DRIVE_RE.match(raw):
        raise _reject(_display(raw), "is drive-qualified")
    if raw.startswith("//") or raw.startswith("\\\\"):
        raise _reject(_display(raw), "is a UNC path")
    if raw.startswith("//?/") or raw.startswith("\\\\?\\"):
        raise _reject(_display(raw), "uses the extended-length device prefix")

    # 5. Alternate data streams / any colon.  On Windows a colon in a name is
    #    either a drive separator or an ADS stream; both are unsafe here.
    if ":" in raw:
        raise _reject(_display(raw), "contains ':' (drive or NTFS stream)")

    # 6. Separator normalisation, then traversal re-check.
    parts = [p for p in re.split(r"[/\\]", raw) if p != ""]
    if not parts:
        raise _reject(_display(raw), "contains no path components")
    for part in parts:
        if part == "..":
            raise _reject(_display(raw), "contains a '..' component")
        if part == ".":
            continue
        if is_reserved_device_name(part):
            raise _reject(_display(raw), f"uses reserved device name {part!r}")
        if part != part.rstrip(" ."):
            raise _reject(
                _display(raw),
                f"component {part!r} ends with a space or dot "
                "(the filesystem would silently strip it)",
            )

    cleaned = [p for p in parts if p != "."]
    if not cleaned:  # pragma: no cover - guarded above
        raise _reject(_display(raw), "contains no path components")

    # 7. Depth.
    if len(cleaned) > limits.max_path_depth:
        raise _reject(
            _display(raw),
            f"path depth {len(cleaned)} exceeds {limits.max_path_depth}",
        )

    return PurePosixPath(*cleaned).as_posix()


def _display(name: str) -> str:
    """Render a name safely for a message (control characters made visible)."""

    return "".join(
        ch if 0x20 <= ord(ch) < 0x7F else f"\\u{ord(ch):04x}" for ch in name[:120]
    )


def resolve_within(root: Path, relative: str) -> Path:
    """Join *relative* onto *root* and prove the result stays inside *root*.

    ``root`` must already exist.  The check resolves symlinks on both sides,
    so a pre-existing link inside the staging tree cannot redirect a write.

    Raises :class:`UnsafePathError` on any escape.
    """

    root_resolved = root.resolve()
    target = root_resolved / Path(relative.replace("/", os.sep))

    # resolve(strict=False) collapses symlinks and ".." without requiring the
    # leaf to exist, which is what we want before creating anything.
    resolved = target.resolve()

    try:
        resolved.relative_to(root_resolved)
    except ValueError:
        raise _reject(relative, "resolves outside the staging root") from None

    # Belt and braces: the string form must also start with the root string
    # (protects against a root such as /tmp/stage vs /tmp/stage-evil).
    root_str = str(root_resolved)
    res_str = str(resolved)
    if not (res_str == root_str or res_str.startswith(root_str + os.sep)):
        raise _reject(relative, "resolves outside the staging root")

    return target
