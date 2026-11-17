"""File classification: extension table first, content sniff second (plan §5.1).

Design rules
------------

* **Unknown is a first-class outcome.**  A file that cannot be classified is
  emitted as ``unknown`` with ``preserved=True`` and ``discovery_only=True``.
  Dropping it would violate IR invariant I2 and task D4.
* **Evidence is recorded, not implied.**  ``class_evidence`` names what
  actually decided the class (``extension``, ``magic``, ``content-keyword``),
  so a reader can tell a confident classification from a fallback.
* **Sniffing is bounded.**  Only the first ``max_sniff_bytes`` are examined;
  a multi-gigabyte binary is hashed but never read into memory for sniffing.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath

from .limits import DEFAULT_LIMITS, Limits

__all__ = [
    "Classification",
    "classify",
    "extension_of",
    "is_ci_config",
    "CLASS_VOCABULARY",
    "PASCAL_SOURCE_CLASSES",
]

# --------------------------------------------------------------------------
# Class vocabulary
# --------------------------------------------------------------------------

#: Closed set of file classes P1 can emit.  Adding a class is a schema change.
CLASS_VOCABULARY: tuple[str, ...] = (
    "pascal_program",
    "pascal_unit",
    "pascal_include",
    "pascal_package",
    "pascal_project",
    "ui_definition",
    "resource",
    "configuration",
    "database",
    "sql",
    "build_script",
    "documentation",
    "licence",
    "version_control",
    "binary",
    "unknown",
)

#: Classes whose contents are tokenised for discovery.
PASCAL_SOURCE_CLASSES = frozenset(
    {"pascal_program", "pascal_unit", "pascal_include", "pascal_package"}
)

#: Classes that are inventoried but never parsed for Pascal semantics.
INVENTORY_ONLY_CLASSES = frozenset(
    {
        "ui_definition",
        "resource",
        "configuration",
        "database",
        "sql",
        "build_script",
        "documentation",
        "licence",
        "version_control",
        "binary",
        "unknown",
    }
)

# --------------------------------------------------------------------------
# Extension table
# --------------------------------------------------------------------------

_EXT_TABLE: dict[str, str] = {
    # Pascal source
    ".pas": "pascal_unit",
    ".pp": "pascal_unit",
    ".p": "pascal_unit",
    ".inc": "pascal_include",
    ".dpr": "pascal_program",
    ".lpr": "pascal_program",
    ".dpk": "pascal_package",
    ".lpk": "pascal_package",
    # Project / IDE metadata
    ".dproj": "pascal_project",
    ".lpi": "pascal_project",
    ".bdsproj": "pascal_project",
    ".groupproj": "pascal_project",
    ".dsk": "pascal_project",
    ".skincfg": "pascal_project",
    ".dof": "pascal_project",
    ".cfg": "configuration",  # Delphi/FPC CLI config; still configuration
    # UI definitions
    ".dfm": "ui_definition",
    ".lfm": "ui_definition",
    ".xfm": "ui_definition",
    ".fmx": "ui_definition",
    # Resources
    ".res": "resource",
    ".rc": "resource",
    ".rcc": "resource",
    ".ico": "resource",
    ".cur": "resource",
    ".ani": "resource",
    ".bmp": "resource",
    ".png": "resource",
    ".jpg": "resource",
    ".jpeg": "resource",
    ".gif": "resource",
    ".svg": "resource",
    # Data / database
    ".sql": "sql",
    ".db": "database",
    ".sqlite": "database",
    ".sqlite3": "database",
    ".mdb": "database",
    ".accdb": "database",
    ".fdb": "database",
    ".gdb": "database",
    ".ib": "database",
    ".paradox": "database",
    ".dbf": "database",
    # Configuration
    ".ini": "configuration",
    ".conf": "configuration",
    ".xml": "configuration",
    ".json": "configuration",
    ".yaml": "configuration",
    ".yml": "configuration",
    ".toml": "configuration",
    ".properties": "configuration",
    ".env": "configuration",
    ".config": "configuration",
    # Build scripts
    ".bat": "build_script",
    ".cmd": "build_script",
    ".sh": "build_script",
    ".ps1": "build_script",
    ".mak": "build_script",
    ".mk": "build_script",
    ".gradle": "build_script",
    # Installer scripts (Inno Setup, NSIS)
    ".iss": "build_script",
    ".nsi": "build_script",
    ".nsh": "build_script",
    # Documentation
    ".md": "documentation",
    ".rst": "documentation",
    ".txt": "documentation",
    ".htm": "documentation",
    ".html": "documentation",
    ".adoc": "documentation",
    # Binaries (never executed, never decompiled)
    ".exe": "binary",
    ".dll": "binary",
    ".so": "binary",
    ".dylib": "binary",
    ".ocx": "binary",
    ".bpl": "binary",
    ".dcu": "binary",
    ".ppu": "binary",
    ".o": "binary",
    ".obj": "binary",
    ".a": "binary",
    ".lib": "binary",
    ".or": "binary",
    ".compiled": "binary",
    ".jar": "binary",
    ".class": "binary",
    ".zip": "binary",
    ".7z": "binary",
    ".rar": "binary",
    ".gz": "binary",
    ".tgz": "binary",
    ".pdf": "binary",
    ".ttf": "binary",
    ".woff": "binary",
}

#: Exact file names (no extension) matched case-insensitively.
_NAME_TABLE: dict[str, str] = {
    "makefile": "build_script",
    "gnumakefile": "build_script",
    "dockerfile": "build_script",
    # CI pipeline definitions with a fixed file name
    "jenkinsfile": "build_script",
    ".gitlab-ci.yml": "build_script",
    "azure-pipelines.yml": "build_script",
    "azure-pipelines.yaml": "build_script",
    "appveyor.yml": "build_script",
    ".appveyor.yml": "build_script",
    "bitbucket-pipelines.yml": "build_script",
    ".travis.yml": "build_script",
    "license": "licence",
    "licence": "licence",
    "copying": "licence",
    "notice": "licence",
    "authors": "documentation",
    "readme": "documentation",
    "changelog": "documentation",
    "history": "documentation",
    "todo": "documentation",
    ".gitignore": "version_control",
    ".gitattributes": "version_control",
    ".gitmodules": "version_control",
    ".gitkeep": "version_control",
    ".hgignore": "version_control",
    ".editorconfig": "configuration",
}

#: Fixed file names that are CI pipeline definitions.
_CI_NAMES = frozenset({
    "jenkinsfile", ".gitlab-ci.yml", "azure-pipelines.yml",
    "azure-pipelines.yaml", "appveyor.yml", ".appveyor.yml",
    "bitbucket-pipelines.yml", ".travis.yml",
})

#: Magic prefixes → class.  Checked before text heuristics.
_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"PK\x03\x04", "binary"),
    (b"PK\x05\x06", "binary"),
    (b"MZ", "binary"),
    (b"\x7fELF", "binary"),
    (b"\x89PNG\r\n\x1a\n", "resource"),
    (b"GIF87a", "resource"),
    (b"GIF89a", "resource"),
    (b"%PDF-", "binary"),
    (b"\x1f\x8b", "binary"),
    (b"\xca\xfe\xba\xbe", "binary"),
    (b"\xfe\xed\xfa\xce", "binary"),
    (b"\xfe\xed\xfa\xcf", "binary"),
    (b"\xce\xfa\xed\xfe", "binary"),
    (b"\xcf\xfa\xed\xfe", "binary"),
    (b"\x00\x00\x01\x00", "resource"),  # Windows .ico
    (b"\x00\x01\x00\x00\x00", "resource"),  # Windows .fon/ttf-ish
)

#: Content keywords → class, applied to the first token of a text file.
_TEXT_KEYWORDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("select", "insert", "update", "delete", "create", "alter", "drop",
      "with", "exec"), "sql"),
    (("program", "unit", "library", "package"), "pascal_unit"),
)


@dataclass(frozen=True)
class Classification:
    """Outcome of :func:`classify`."""

    cls: str
    evidence: tuple[str, ...]
    confidence: str  # "high" | "medium" | "low"
    discovery_only: bool
    #: Why analysis stopped, when it did: ``""``, ``"too-large"``, ``"binary"``.
    analysis_blocker: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "analysis": self.analysis_blocker,
            "class": self.cls,
            "class_evidence": list(self.evidence),
            "confidence": self.confidence,
            "discovery_only": self.discovery_only,
        }


def is_ci_config(path: str) -> bool:
    """True for a CI pipeline definition (by file name or well-known folder).

    Covers ``.github/workflows/*.yml|yaml``, ``.circleci/config.yml`` and the
    fixed names in the name table (``Jenkinsfile``, ``.gitlab-ci.yml``,
    ``azure-pipelines.yml``, ``appveyor.yml`` ...).  Pure function of the
    path; never reads the file.
    """

    norm = path.replace("\\", "/")
    parts = [p.lower() for p in PurePosixPath(norm).parts]
    if not parts:
        return False
    name = parts[-1]
    if name in _CI_NAMES:
        return True
    ext = extension_of(norm)
    if ext in (".yml", ".yaml"):
        folders = parts[:-1]
        for index, folder in enumerate(folders[:-1]):
            if folder == ".github" and folders[index + 1] == "workflows":
                return True
        if folders and folders[-1] == ".circleci" and name.startswith("config"):
            return True
    return False


def extension_of(path: str) -> str:
    """Lower-cased extension including the dot; ``""`` when there is none.

    Dot-files such as ``.gitignore`` have no extension in this sense (their
    whole name is the signal), while ``.hidden.pas`` does.
    """

    name = PurePosixPath(path.replace("\\", "/")).name
    idx = name.rfind(".")
    if idx <= 0:  # no dot, or the only dot leads a dot-file
        return ""
    return name[idx:].lower()


def classify(
    path: str,
    head: bytes = b"",
    *,
    size: int = 0,
    limits: Limits = DEFAULT_LIMITS,
) -> Classification:
    """Classify one file from its name and the first bytes of its content.

    *path* is the POSIX-relative ingested path.  *head* is a bounded prefix of
    the file (at most ``limits.max_sniff_bytes``); callers pass ``b""`` when
    they deliberately do not read the content.

    The result is deterministic: the same inputs always produce the same
    :class:`Classification`.
    """

    norm = path.replace("\\", "/")
    name = PurePosixPath(norm).name.lower()
    ext = extension_of(norm)

    # Version-control metadata anywhere in the tree (including ".git/").
    parts = PurePosixPath(norm).parts
    if any(p.lower() == ".git" for p in parts):
        return Classification(
            "version_control", ("path-segment",), "high", True
        )

    # 0. CI pipeline folders (.github/workflows/*.yml): file name alone is
    #    not enough, so this is decided on the path before the tables.
    if is_ci_config(norm):
        return Classification("build_script", ("ci-config",), "high", True)

    # 1. Exact file name wins (Makefile, LICENSE, .gitignore).
    if name in _NAME_TABLE:
        return Classification(_NAME_TABLE[name], ("file-name",), "high", True)

    # 2. Extension table.
    if ext in _EXT_TABLE:
        cls = _EXT_TABLE[ext]
        evidence = ("extension",)
        confidence = "high"
        if cls == "pascal_unit" and ext in (".p",):
            # ".p" is ambiguous (Pascal, Perl, Pascal-script); sniff to decide.
            sniffed = _sniff_text(head, limits)
            if sniffed and sniffed[0] != "pascal_unit":
                return Classification(
                    sniffed[0], ("extension", "content-keyword"), "medium", True
                )
        # An extensionless-content mismatch is caught below by magic bytes for
        # known-binary extensions; for source extensions we trust the table.
        magic = _sniff_magic(head)
        if magic and _binary_magic_conflicts(ext, magic):
            return Classification(magic, ("magic", "extension-override"), "high", True)
        return Classification(cls, evidence, confidence, True)

    # 3. Content sniff for everything else (unknown or missing extension).
    magic = _sniff_magic(head)
    if magic:
        return Classification(magic, ("magic",), "high", True)

    text = _sniff_text(head, limits)
    if text:
        cls, keyword = text
        # A `program`/`library` header on a source file is a program, not a unit.
        if cls == "pascal_unit" and _starts_with_keyword(head, ("program", "library")):
            return Classification(
                "pascal_program", ("content-keyword",), "medium", False
            )
        if cls == "pascal_unit":
            return Classification(
                "pascal_unit", ("content-keyword",), "medium", False
            )
        return Classification(cls, (f"content-keyword:{keyword}",), "medium", True)

    # 4. Nothing matched.
    if not head:
        # No content supplied: we can only say what the name does not say.
        return Classification("unknown", ("no-extension", "no-content"), "low", True)
    if _looks_binary(head):
        return Classification("binary", ("nul-byte",), "medium", True)
    return Classification(
        "unknown", ("no-extension", "content-unrecognised"), "low", True
    )


def _binary_magic_conflicts(ext: str, magic: str) -> bool:
    """True when magic bytes contradict a source-looking extension.

    ``evil.pas`` that is really a PE executable must be reported as the
    executable it is — reporting it as Pascal source would be a silent lie.
    """

    source_exts = {".pas", ".pp", ".p", ".inc", ".dpr", ".lpr", ".dpk", ".lpk"}
    return ext in source_exts and magic == "binary"


def _sniff_magic(head: bytes) -> str | None:
    if not head:
        return None
    for prefix, cls in _MAGIC:
        if head.startswith(prefix):
            return cls
    return None


def _looks_binary(head: bytes) -> bool:
    if not head:
        return False
    if b"\x00" in head:
        return True
    # High proportion of non-text bytes ⇒ binary.
    sample = head[:4096]
    textish = sum(
        1 for b in sample if b in (9, 10, 13) or 32 <= b < 127 or b >= 0xC0
    )
    return textish < len(sample) * 0.75


def _sniff_text(head: bytes, limits: Limits) -> tuple[str, str] | None:
    """Detect Pascal or SQL from the leading text, if any."""

    if not head or _looks_binary(head):
        return None
    window = head[: min(len(head), limits.max_sniff_bytes)]
    try:
        text = window.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = window.decode("cp1252")
        except UnicodeDecodeError:  # pragma: no cover - latin-1 always works
            text = window.decode("latin-1")

    # Strip a BOM and leading comments/whitespace to reach the first token.
    text = text.lstrip("\ufeff")
    # XML declarations are configuration-ish, not Pascal.  Checked before the
    # tokeniser because "<?xml" begins with a non-identifier character, so
    # _first_token would return "" and the branch would be unreachable.
    if text.lstrip().startswith("<?xml"):
        return "configuration", "<?xml"
    first = _first_token(text)
    if not first:
        return None
    for keywords, cls in _TEXT_KEYWORDS:
        if first in keywords:
            return cls, first
    return None


def _first_token(text: str) -> str:
    """First Pascal-significant token, skipping comments and whitespace."""

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        if ch == "{":
            end = text.find("}", i + 1)
            if end == -1:
                return ""
            i = end + 1
            continue
        if text.startswith("(*", i):
            end = text.find("*)", i + 2)
            if end == -1:
                return ""
            i = end + 2
            continue
        if text.startswith("//", i):
            end = text.find("\n", i + 2)
            if end == -1:
                return ""
            i = end + 1
            continue
        break
    if i >= n:
        return ""
    j = i
    while j < n and (text[j].isalpha() or text[j] == "_"):
        j += 1
    return text[i:j].lower()


def _starts_with_keyword(head: bytes, keywords: tuple[str, ...]) -> bool:
    """True when the first significant token of *head* is one of *keywords*."""

    if not head:
        return False
    try:
        text = head.decode("utf-8")
    except UnicodeDecodeError:
        try:
            text = head.decode("cp1252")
        except UnicodeDecodeError:  # pragma: no cover
            text = head.decode("latin-1")
    return _first_token(text) in keywords
