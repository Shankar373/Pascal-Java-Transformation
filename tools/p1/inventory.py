"""Stage 1 inventory: directories, build scripts and compiler configurations.

Pure functions of already-ingested data.  Nothing here executes a script,
follows a symlink or reads outside the supplied tree: the only filesystem
access is the directory *walk* in :func:`list_directories`, which needs the
real tree because an empty directory has no file to be inferred from.

``text_of`` contract (shared by every Stage 1 detector)
-------------------------------------------------------

``text_of`` maps the POSIX inventory path of a file to its **decoded text**
for every file for which :func:`wants_text` is true:

* classes ``build_script``, ``configuration``, ``sql``, ``ui_definition`` and
  ``pascal_project`` (``.dproj .lpi .dof .groupproj ...``), and
* ``.lpk`` Lazarus package files (class ``pascal_package``; their required
  packages are XML, not Pascal).

Pascal sources are *not* in ``text_of``: they are consumed through their
``AnalysedFile.scan`` token stream.  A file missing from ``text_of`` (too
large, unreadable, binary) is tolerated everywhere and reported as
``UNKNOWN`` with line-1 evidence rather than dropped.
"""

from __future__ import annotations

import os
import posixpath
import re
from collections import Counter
from pathlib import Path, PurePosixPath
from typing import Iterable

from .classify import extension_of, is_ci_config
from .compilercfg import detect_compiler_configs
from .evutil import (
    MAX_EVIDENCE,
    bounded,
    make_evidence,
    numbered_lines,
    sorted_files,
)
from .findings import BuildScriptFinding, DirectoryEntry
from .model import AnalysedFile, IngestedFile
from .projects import ProjectRoot

__all__ = [
    "TEXT_CLASSES",
    "wants_text",
    "list_directories",
    "detect_build_scripts",
    "detect_compiler_configs",
]

#: File classes whose decoded text the detectors need (see module docstring).
TEXT_CLASSES = frozenset(
    {"build_script", "configuration", "sql", "ui_definition", "pascal_project"}
)

#: Hard bound on directories listed (a hostile tree cannot grow the output).
_MAX_DIRECTORIES = 100_000
_VCS_DIRECTORY = ".git"


def wants_text(item: AnalysedFile) -> bool:
    """True when the detectors expect ``text_of[item.path]`` (see docstring)."""

    if item.cls in TEXT_CLASSES:
        return True
    return item.cls == "pascal_package" and item.path.lower().endswith(".lpk")


# --------------------------------------------------------------------------
# Directories
# --------------------------------------------------------------------------


def _size_of(item: object) -> int:
    """Size of an ``IngestedFile`` (or an ``AnalysedFile`` wrapping one)."""

    size = getattr(item, "size", None)
    if size is None:
        size = getattr(getattr(item, "inventory", None), "size", 0)
    return max(int(size or 0), 0)


def _ancestors(path: str) -> list[str]:
    parts = path.split("/")[:-1]
    return ["/".join(parts[:i]) for i in range(1, len(parts) + 1)]


def _is_junction(path: str) -> bool:
    probe = getattr(os.path, "isjunction", None)
    return bool(probe and probe(path))


def _walk_directories(root: Path) -> set[str]:
    """Relative POSIX directories under *root* (no symlinks, no ``.git``)."""

    found: set[str] = set()
    try:
        walker = os.walk(root, onerror=lambda _error: None)
        for dirpath, dirnames, _files in walker:
            dirnames[:] = sorted(
                d for d in dirnames
                if d.lower() != _VCS_DIRECTORY
                and not os.path.islink(os.path.join(dirpath, d))
                and not _is_junction(os.path.join(dirpath, d))
            )
            relative = Path(dirpath).relative_to(root).as_posix()
            if relative != ".":
                found.add(relative)
            if len(found) >= _MAX_DIRECTORIES:
                break
    except (OSError, ValueError):
        return found
    return found


def list_directories(
    root: Path, files: Iterable[IngestedFile]
) -> list[DirectoryEntry]:
    """Every directory of the tree - including empty ones - sorted by path.

    Directories implied by *files* are always listed; the walk of *root* adds
    the ones that hold no file at all.  A missing *root* degrades to the
    implied directories only.  ``.git`` is never walked (it is not inventoried
    either) and symlinked directories are not followed.
    """

    direct: Counter[str] = Counter()
    total_files: Counter[str] = Counter()
    total_bytes: Counter[str] = Counter()
    directories: set[str] = set()
    for item in files:
        path = item.path.replace("\\", "/")
        parents = _ancestors(path)
        if parents:
            direct[parents[-1]] += 1
        for parent in parents:
            directories.add(parent)
            total_files[parent] += 1
            total_bytes[parent] += _size_of(item)
    directories |= _walk_directories(Path(root))

    entries = [
        DirectoryEntry(
            path=path,
            depth=path.count("/") + 1,
            file_count=direct[path],
            total_file_count=total_files[path],
            total_bytes=total_bytes[path],
            empty=total_files[path] == 0,
        )
        for path in sorted(directories)[:_MAX_DIRECTORIES]
    ]
    return entries


# --------------------------------------------------------------------------
# Build scripts
# --------------------------------------------------------------------------

_PROJECT_EXTS = "dproj|dpr|dpk|lpi|lpr|lpk|groupproj|bdsproj"
_QUOTED_PROJECT = re.compile(
    rf"[\"']([^\"'\r\n]+?\.(?:{_PROJECT_EXTS}))[\"']", re.I
)
_BARE_PROJECT = re.compile(
    rf"(?<![\w.$%-])([\w$%(){{}}.\\/:-]*?[\w$%(){{}}-]\.(?:{_PROJECT_EXTS}))"
    r"(?![\w.])",
    re.I,
)
_PROJECT_HINT = re.compile(rf"\.(?:{_PROJECT_EXTS})", re.I)
_MACRO_PREFIX = re.compile(r"^(?:\$\([^)]*\)|%[^%]*%|\$\{[^}]*\})[\\/]?")

_TOOL_END = r"(?![\w.\\/-])"
_TOOLS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("dcc", re.compile(
        r"(?<![\w.-])(dcc(?:32|64|osx64|osx|linux64|ios32|iosarm64|"
        r"iossimarm64|android64|android|arm)?)(?:\.exe)?" + _TOOL_END, re.I)),
    ("msbuild", re.compile(
        r"(?<![\w.-])msbuild(?:\.exe)?" + _TOOL_END, re.I)),
    ("rsvars", re.compile(r"(?<![\w.-])rsvars(?:\.bat)?" + _TOOL_END, re.I)),
    ("lazbuild", re.compile(
        r"(?<![\w.-])lazbuild(?:\.exe)?" + _TOOL_END, re.I)),
    ("fpc", re.compile(r"(?<![\w.%$-])fpc(?:\.exe)?" + _TOOL_END, re.I)),
    ("inno", re.compile(
        r"(?<![\w.-])(?:iscc|compil32)(?:\.exe)?" + _TOOL_END, re.I)),
    ("nsis", re.compile(
        r"(?<![\w.-])makensis(?:\.exe)?" + _TOOL_END, re.I)),
)
_SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|]")
_COMMAND_PREFIX = re.compile(
    r"^(?:[-@]\s*|call\s+|run:\s*|script:\s*|then\s+|do\s+|sudo\s+|exec\s+)*",
    re.I,
)
_MAKE_COMMAND = re.compile(
    r"^(?:\$\(MAKE\)|\$\{MAKE\}|g?make|mingw32-make|nmake)(?:\.exe)?(?:\s|$)",
    re.I,
)
_COMMENT_PREFIXES = {
    "batch": ("rem ", "rem\t", "::", "@rem "),
    "powershell": ("#",),
    "shell": ("#",),
    "makefile": ("#",),
    "ci-config": ("#",),
    "installer": (";", "#"),
    "msbuild": (),
}
_SCRIPT_EXTENSIONS = {
    ".bat": "batch", ".cmd": "batch", ".ps1": "powershell", ".sh": "shell",
    ".bash": "shell", ".mk": "makefile", ".mak": "makefile",
    ".iss": "installer", ".nsi": "installer", ".nsh": "installer",
    ".groupproj": "msbuild",
}
_DPROJ_MARKERS = re.compile(
    r"<Target\b|<PreBuildEvent\b|<PostBuildEvent\b|<Exec\b", re.I)
_MAX_RESOLVED = 20


class _ProjectIndex:
    """Project files of the input, for resolving names a script mentions."""

    def __init__(self, analysed: list[AnalysedFile],
                 roots: Iterable[ProjectRoot]) -> None:
        paths = {
            item.path for item in analysed
            if re.search(rf"\.(?:{_PROJECT_EXTS})$", item.path, re.I)
        }
        for root in roots or ():
            paths.add(root.path)
            paths.update(root.meta_files)
        self.by_path = {p.casefold(): p for p in paths}
        self.by_name: dict[str, list[str]] = {}
        for path in sorted(paths):
            self.by_name.setdefault(
                PurePosixPath(path).name.casefold(), []).append(path)

    def resolve(self, token: str, script_path: str) -> list[str]:
        norm = _MACRO_PREFIX.sub("", token.replace("\\", "/").strip())
        if not norm:
            return []
        here = posixpath.normpath(
            posixpath.join(posixpath.dirname(script_path), norm))
        if here.casefold() in self.by_path:
            return [self.by_path[here.casefold()]]
        rooted = posixpath.normpath(norm).lstrip("./")
        while rooted.startswith("../"):
            rooted = rooted[3:]
        if rooted.casefold() in self.by_path:
            return [self.by_path[rooted.casefold()]]
        name = posixpath.basename(norm).casefold()
        return self.by_name.get(name, [])[:_MAX_RESOLVED]


def _script_kind(item: AnalysedFile, text: str | None) -> str | None:
    if is_ci_config(item.path):
        return "ci-config"
    name = PurePosixPath(item.path).name.lower()
    if name in ("makefile", "gnumakefile"):
        return "makefile"
    ext = extension_of(item.path)
    if ext in _SCRIPT_EXTENSIONS:
        return _SCRIPT_EXTENSIONS[ext]
    if ext == ".dproj" and text and _DPROJ_MARKERS.search(text):
        return "msbuild"
    return None


def _is_comment(line: str, kind: str) -> bool:
    return line.lower().startswith(_COMMENT_PREFIXES.get(kind, ()))


def _tools_in_line(line: str) -> set[str]:
    tools: set[str] = set()
    for canonical, pattern in _TOOLS:
        for match in pattern.finditer(line):
            tools.add(match.group(1).lower() if canonical == "dcc"
                      else canonical)
    for segment in _SEGMENT_SPLIT.split(line):
        command = _COMMAND_PREFIX.sub("", segment.strip())
        if _MAKE_COMMAND.match(command):
            tools.add("make")
    return tools


def _project_tokens(line: str) -> list[str]:
    if not _PROJECT_HINT.search(line):
        return []  # cheap linear pre-filter before the backtracking regexes
    tokens = [m.group(1) for m in _QUOTED_PROJECT.finditer(line)]
    remainder = _QUOTED_PROJECT.sub(" ", line)
    tokens.extend(m.group(1) for m in _BARE_PROJECT.finditer(remainder))
    return tokens


def _default_tools(item: AnalysedFile, kind: str) -> set[str]:
    ext = extension_of(item.path)
    if kind == "installer":
        return {"inno"} if ext == ".iss" else {"nsis"}
    if kind == "msbuild":
        return {"msbuild"}
    return set()


def _analyse_script(
    item: AnalysedFile, kind: str, text: str | None, index: _ProjectIndex
) -> BuildScriptFinding:
    if not text or not text.strip():
        return BuildScriptFinding(
            path=item.path,
            kind=kind,
            tools=tuple(sorted(_default_tools(item, kind))),
            evidence=(make_evidence(
                item.path, 1, 1, "build script present; content not read"),),
            confidence="low",
            status="UNKNOWN",
        )
    tools = _default_tools(item, kind)
    projects: set[str] = set()
    evidence = []
    scoped = kind == "msbuild" and item.path.lower().endswith(".dproj")
    for number, raw in numbered_lines(text):
        line = raw.strip()
        if not line or _is_comment(line, kind):
            continue
        if scoped and not _DPROJ_MARKERS.search(line):
            continue
        found = _tools_in_line(line)
        refs = [r for t in _project_tokens(line)
                for r in index.resolve(t, item.path)]
        if found or refs:
            tools |= found
            projects.update(refs)
            if len(evidence) < 4 * MAX_EVIDENCE:
                evidence.append(make_evidence(item.path, number, 1, line))
    if not evidence:
        first = next((ln.strip() for _, ln in numbered_lines(text)
                      if ln.strip()), "")
        evidence.append(make_evidence(item.path, 1, 1, first))
    return BuildScriptFinding(
        path=item.path,
        kind=kind,
        tools=tuple(sorted(tools)),
        referenced_projects=tuple(sorted(projects)),
        evidence=bounded(evidence),
        confidence="high" if tools else "medium",
        status="PARTIAL",
    )


def detect_build_scripts(
    analysed: list[AnalysedFile],
    text_of: dict[str, str],
    roots: Iterable[ProjectRoot] = (),
) -> list[BuildScriptFinding]:
    """Build, packaging and CI scripts, the tools they invoke and the project
    files they name (resolved against the input).

    Covered: ``.bat .cmd .ps1 .sh Makefile *.mk *.mak *.iss *.nsi``,
    ``.groupproj``, ``.dproj`` files that declare targets or build events,
    and CI definitions (``.github/workflows``, ``.gitlab-ci.yml``,
    ``azure-pipelines.yml``, ``Jenkinsfile``, ``appveyor.yml`` ...).
    Comment lines never count as tool invocations.  ``Dockerfile`` and
    ``.gradle`` have no kind in the closed vocabulary and are not reported.
    """

    index = _ProjectIndex(analysed, roots)
    findings: list[BuildScriptFinding] = []
    for item in sorted_files(analysed):
        text = (text_of or {}).get(item.path)
        kind = _script_kind(item, text)
        if kind is None:
            continue
        findings.append(_analyse_script(item, kind, text, index))
    return findings

