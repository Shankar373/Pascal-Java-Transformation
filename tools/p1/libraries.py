"""Stage 1 library detection: frameworks, RTL, database stacks and the known
third-party component families.

A library is reported from a real ``uses``/``requires`` clause (or an
``.lpi``/``.lpk`` required-package entry) - never from a comment, a string or
a bare identifier.  ``origin`` is decided against the input itself:

``bundled``     a unit of the library exists in the ingested input;
``external``    recognised third-party library that is absent;
``framework``   VCL / FMX / LCL (absent by design);
``rtl``         compiler-supplied runtime / data-access library;
``unresolved``  referenced, absent, and not recognised.

A project's own units (present in the input, not a known family) are never
libraries.  Recognition is by name only, so every finding is ``PARTIAL``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Iterable

from .dialects import classify_unit
from .evutil import (
    MAX_FINDINGS_PER_KIND,
    MAX_REFERENCES,
    bounded,
    first_unique,
    make_evidence,
    numbered_lines,
    sorted_files,
)
from .findings import Evidence, LibraryFinding
from .knowledge import PACKAGE_TABLE, match_family
from .model import AnalysedFile
from .projects import ProjectRoot

__all__ = ["detect_libraries"]

_POOL = 100
_MAX_UNITS = 200
_MAX_NAME = 128
_PASCAL_CLASSES = frozenset({
    "pascal_unit", "pascal_program", "pascal_include", "pascal_package",
})
_PACKAGE_NAME = re.compile(r"<PackageName\s+Value=\"([^\"]+)\"")
#: Plain unit names that exist in both VCL and LCL; context decides.
_AMBIGUOUS_GUI = frozenset({
    "forms", "controls", "graphics", "dialogs", "stdctrls", "extctrls",
    "comctrls", "menus", "buttons", "checklst", "grids", "mask", "imglist",
    "actnlist", "stdactns",
})
_LCL_FILES = (".lpi", ".lpr", ".lpk", ".lfm")
_VCL_FILES = (".dpr", ".dproj", ".dfm", ".dpk", ".bdsproj")
#: classify_unit category → (library, library category, origin)
_CLASSIFIED = {
    "vcl": ("VCL", "framework", "framework"),
    "lcl": ("LCL", "framework", "framework"),
    "fmx": ("FMX", "framework", "framework"),
    "delphi-rtl": ("Delphi RTL", "rtl", "rtl"),
    "cross-rtl": ("RTL", "rtl", "rtl"),
    "fpc-rtl": ("FPC RTL", "rtl", "rtl"),
    "windows-platform": ("Windows platform units", "rtl", "rtl"),
    "unix-platform": ("Unix platform units", "rtl", "rtl"),
    "database": ("Database (other)", "database", "external"),
}


@dataclass
class _Acc:
    name: str
    category: str
    vendor: str
    default_origin: str
    units: dict[str, None] = field(default_factory=dict)
    refs: set[str] = field(default_factory=set)
    evidence: list[Evidence] = field(default_factory=list)
    bundled: bool = False

    def add(self, unit: str, path: str, ev: Evidence, in_input: bool) -> None:
        if len(self.units) < _MAX_UNITS:
            self.units.setdefault(unit.lower(), None)
        self.refs.add(path)
        if len(self.evidence) < _POOL:
            self.evidence.append(ev)
        self.bundled = self.bundled or in_input


class _UnitIndex:
    """Which unit/package names exist in the ingested input."""

    def __init__(self, analysed: list[AnalysedFile]) -> None:
        self.names: set[str] = set()
        for item in analysed:
            stem = PurePosixPath(item.path).name.rsplit(".", 1)[0].lower()
            if item.cls in _PASCAL_CLASSES or item.path.lower().endswith(
                    (".bpl", ".dcp")):
                self.names.add(stem)
            if item.analysis is not None and item.analysis.declared_name:
                self.names.add(item.analysis.declared_name.lower())

    def has(self, name: str) -> bool:
        low = name.lower()
        return low in self.names or low.rsplit(".", 1)[-1] in self.names


def _gui_context(analysed: list[AnalysedFile]) -> str:
    """``lcl`` when the input is a Lazarus project, else ``vcl``."""

    lcl = vcl = False
    for item in analysed:
        lower = item.path.lower()
        lcl = lcl or lower.endswith(_LCL_FILES)
        vcl = vcl or lower.endswith(_VCL_FILES)
        if item.scan is None:
            continue
        for clause in item.scan.uses:
            for unit in clause.items:
                category, _ = classify_unit(unit.name)
                lcl = lcl or category == "lcl"
                vcl = vcl or unit.name.lower().startswith("vcl.")
    return "lcl" if lcl and not vcl else "vcl"


def _references(item: AnalysedFile, text_of: dict[str, str]
                ) -> Iterable[tuple[str, str, int, int]]:
    """``(name, kind, line, column)`` for every library reference in a file."""

    if item.scan is not None:
        for clause in item.scan.uses:
            for unit in clause.items:
                if unit.name and len(unit.name) <= _MAX_NAME:
                    yield unit.name, clause.kind, unit.line, unit.column
        return
    lower = item.path.lower()
    text = text_of.get(item.path)
    if text and lower.endswith((".lpi", ".lpk")):
        for number, line in numbered_lines(text):
            for match in _PACKAGE_NAME.finditer(line):
                name = match.group(1).strip()
                if name and len(name) <= _MAX_NAME:
                    yield name, "requires", number, match.start(1) + 1


def _package_entry(name: str) -> tuple[str, str, str] | None:
    low = name.lower()
    return PACKAGE_TABLE.get(low) or PACKAGE_TABLE.get(
        re.sub(r"\d+$", "", low))


class _Resolver:
    """Maps one reference to the accumulator it belongs to (or ``None``)."""

    def __init__(self, analysed: list[AnalysedFile],
                 unresolved_units: Iterable[str]) -> None:
        self.index = _UnitIndex(analysed)
        self.context = _gui_context(analysed)
        self.absent = {u.lower() for u in unresolved_units or ()}
        self.known: dict[str, _Acc] = {}
        self.unknown: dict[str, _Acc] = {}

    def _acc(self, store: dict[str, _Acc], name: str, category: str,
             vendor: str, origin: str) -> _Acc:
        key = name.lower()
        acc = store.get(key)
        if acc is None:
            acc = store[key] = _Acc(name, category, vendor, origin)
        return acc

    def target(self, name: str, kind: str, item: AnalysedFile
               ) -> tuple[_Acc | None, bool]:
        """``(accumulator, present_in_input)`` for a reference."""

        in_input = self.index.has(name) and name.lower() not in self.absent
        entry = _package_entry(name) if kind == "requires" else None
        if entry:
            lib, category, origin = entry
            return self._acc(self.known, lib, category, "", origin), in_input
        family = match_family(name)
        if family:
            return self._acc(self.known, family.name, family.category,
                             family.vendor, family.absent_origin), in_input
        classified = self._classified(name, item)
        if classified:
            lib, category, origin = classified
            return self._acc(self.known, lib, category, "", origin), in_input
        if in_input:
            return None, True  # the project's own unit
        return self._acc(self.unknown, name, "other", "",
                         "unresolved"), False

    def _classified(self, name: str, item: AnalysedFile
                    ) -> tuple[str, str, str] | None:
        category, matched = classify_unit(name)
        if category == "known-third-party":
            return (name, "other", "external")
        entry = _CLASSIFIED.get(category)
        if entry is None:
            return None
        lowered = name.lower()
        if entry[0] == "VCL" and lowered in _AMBIGUOUS_GUI:
            fpc = item.analysis is not None and item.analysis.dialect == "fpc"
            if fpc or self.context == "lcl":
                return _CLASSIFIED["lcl"]
        return entry


def _finalise(acc: _Acc) -> LibraryFinding | None:
    evidence = bounded(acc.evidence)
    if not evidence:
        return None
    origin = "bundled" if acc.bundled else acc.default_origin
    if origin == "unresolved":
        confidence = "low"
    elif acc.bundled or origin in ("framework", "rtl"):
        confidence = "high"
    else:
        confidence = "medium"
    return LibraryFinding(
        name=acc.name,
        category=acc.category,
        origin=origin,
        vendor=acc.vendor,
        units=tuple(sorted(acc.units)),
        referenced_by=first_unique(sorted(acc.refs), MAX_REFERENCES),
        resolved=acc.bundled,
        evidence=evidence,
        confidence=confidence,
        status="PARTIAL",
    )


def detect_libraries(
    analysed: list[AnalysedFile],
    roots: Iterable[ProjectRoot],
    unresolved_units: Iterable[str],
    *,
    text_of: dict[str, str] | None = None,
) -> list[LibraryFinding]:
    """Libraries referenced by the input, with origin and evidence.

    ``roots`` is accepted for signature symmetry with the other detectors and
    is not needed: package ``requires`` clauses are read from the scanned
    ``.dpk`` sources themselves.  ``text_of`` is only used for ``.lpi`` /
    ``.lpk`` required-package entries.  ``unresolved_units`` (graph output)
    can only *confirm* absence; it never hides a reference.

    Findings are sorted by name; unrecognised absent units are capped at
    500 (first by name) so a hostile input cannot grow the output.
    """

    resolver = _Resolver(analysed, unresolved_units)
    for item in sorted_files(analysed):
        for name, kind, line, column in _references(item, text_of or {}):
            acc, in_input = resolver.target(name, kind, item)
            if acc is None:
                continue
            acc.add(name, item.path, make_evidence(
                item.path, line, column,
                f"`{kind}` clause names unit {name}"
                if item.scan is not None
                else f"required package {name}"), in_input)

    findings = [f for f in map(_finalise, resolver.known.values()) if f]
    unknown = sorted(resolver.unknown.values(), key=lambda a: a.name.lower())
    findings.extend(
        f for f in map(_finalise, unknown[:MAX_FINDINGS_PER_KIND]) if f)
    return sorted(findings, key=lambda f: (f.name, f.origin))
