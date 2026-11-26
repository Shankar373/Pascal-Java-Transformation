"""Compiler-configuration discovery (``dcc32.cfg``, ``fpc.cfg``, ``.dof``,
``.dproj``, ``.lpi``): switches, conditional defines and search paths.

Detection reads text only - the compiler is never invoked, so every value is
what the file *states*, not what a build would resolve.  A project file that
cannot be parsed (malformed XML, an entity-declaring DTD, empty) yields an
``UNKNOWN`` finding with a located note instead of being dropped.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from .evutil import (
    MAX_TEXT_CHARS,
    bounded,
    make_evidence,
    numbered_lines,
    redact_text,
    sorted_files,
)
from .findings import CompilerConfigFinding, Evidence
from .model import AnalysedFile
from .projects import parse_project_file

__all__ = ["detect_compiler_configs", "CONFIG_EXTENSIONS"]

CONFIG_EXTENSIONS = (".cfg", ".dof", ".dproj", ".bdsproj", ".lpi")

#: Distinct ``(switch, value)`` pairs kept per file.
_MAX_SWITCHES = 200
#: Evidence candidates gathered before the per-finding cap is applied.
_MAX_EVIDENCE_POOL = 400
#: Largest project file handed to the XML parser.
_MAX_XML_CHARS = 4_000_000

_DCC_TWO_LETTER = (
    "LE", "LN", "LU", "NS", "NU", "NB", "NH", "NO", "GD", "GP", "GS",
)
_DCC_SEARCH = frozenset({"-U", "-I", "-R", "-O"})
_FPC_SEARCH = frozenset({"-Fu", "-Fi", "-Fl", "-Fo"})
_FPC_TWO_LETTER_HEADS = "FCSXWT"
_FPC_CONDITIONAL = re.compile(r"(?i)^#\s*(?:IFDEF|IFNDEF|IF|ELSE|ENDIF|"
                              r"ELSEIF|INCLUDE|WRITE|SECTION)\b")
_FPC_DEFINE = re.compile(r"(?i)^#\s*DEFINE\s+([A-Za-z_]\w*)")
_MACRO_ONLY = re.compile(r"^\$\(DCC_\w+\)$")
_DCC_ELEMENT = re.compile(r"<(DCC_\w+)>([^<]*)</\1>")
_LPI_ELEMENT = re.compile(
    r"<(SyntaxMode|OtherUnitFiles|IncludeFiles|ObjectPath|CustomOptions|"
    r"UnitOutputDirectory|TargetFileExt|SrcPath|LibraryPath)\s+"
    r"Value=\"([^\"]*)\""
)
_INI_SECTION = re.compile(r"^\s*\[([^\]]+)\]\s*$")
_INI_KEY = re.compile(r"^\s*([^=;#\s][^=]*?)\s*=\s*(.*)$")
_DOF_SECTIONS = ("compiler", "linker", "directories", "parameters")


class _Parsed:
    """Mutable accumulator for one file (never escapes this module)."""

    def __init__(self) -> None:
        self.switches: dict[tuple[str, str], int] = {}
        self.defines: dict[str, None] = {}
        self.paths: dict[str, None] = {}
        self.evidence: list[Evidence] = []

    def switch(self, name: str, value: str, line: int, path: str) -> None:
        if len(self.switches) < _MAX_SWITCHES:
            self.switches.setdefault((name, value), line)
        if len(self.evidence) < _MAX_EVIDENCE_POOL:
            self.evidence.append(make_evidence(path, line, 1, f"{name}{value}"))

    def define(self, name: str) -> None:
        if name and not name.startswith("$("):
            self.defines.setdefault(name, None)

    def search(self, raw: str) -> None:
        for part in raw.split(";"):
            part = part.strip()
            if part and not _MACRO_ONLY.match(part):
                self.paths.setdefault(part, None)

    def result(self, path: str, kind: str, scope: str, text: str,
               parsed: bool) -> CompilerConfigFinding:
        evidence = bounded(self.evidence)
        if not evidence:
            evidence = (make_evidence(path, 1, 1, _first_line(text)),)
        return CompilerConfigFinding(
            path=path,
            kind=kind,
            scope=scope,
            switches=tuple(self.switches),
            defines=tuple(sorted(self.defines)),
            search_paths=tuple(sorted(self.paths)),
            evidence=evidence,
            confidence="medium" if parsed else "low",
            status="PARTIAL" if parsed else "UNKNOWN",
        )


def _first_line(text: str) -> str:
    for line in text[:4000].split("\n"):
        if line.strip():
            return line.strip()
    return "configuration file present"


_TOKEN = re.compile(r'(?:[^\s"]|"[^"]*(?:"|$))+')


def _tokens(line: str) -> list[str]:
    """Split on whitespace outside double quotes (an open quote runs on)."""

    return _TOKEN.findall(line)


def _split_switch(body: str, flavour: str) -> tuple[str, str]:
    """``U"x"`` → ``("-U", "x")`` honouring each compiler's switch grammar."""

    if flavour == "dcc":
        if body.startswith("$"):
            name, value = "-$" + body[1:2], body[2:]
        elif body[:2] in _DCC_TWO_LETTER:
            name, value = "-" + body[:2], body[2:]
        elif body[:1] == "N" and body[1:2].isdigit():
            name, value = "-" + body[:2], body[2:]
        else:
            name, value = "-" + body[:1], body[1:]
    else:
        if body[:1] in _FPC_TWO_LETTER_HEADS and body[1:2].isalpha():
            name, value = "-" + body[:2], body[2:]
        else:
            name, value = "-" + body[:1], body[1:]
    return name, value.strip().strip('"')


def _guess_flavour(lines: list[str]) -> str:
    """``fpc`` / ``dcc`` / ``""`` from the switches a ``.cfg`` uses."""

    fpc = dcc = 0
    for line in lines:
        for tok in _tokens(line.strip()):
            if re.match(r"^-(?:F[a-zA-Z]|M|d[A-Za-z_]|C[a-z]|S[a-z0-9])", tok):
                fpc += 1
            elif re.match(r"^-(?:\$|D[A-Za-z_]|U|R|I|E|N|LE|LN|LU)", tok):
                dcc += 1
        if line.lstrip().startswith("#") and _FPC_CONDITIONAL.match(
                line.lstrip()):
            fpc += 1
    if fpc > dcc:
        return "fpc"
    return "dcc" if dcc else ""


def _parse_cfg(text: str, flavour: str, path: str, out: _Parsed) -> None:
    for number, raw in numbered_lines(text):
        line = redact_text(raw).strip()
        if not line or line.startswith((";", "//", "@")):
            continue
        if line.startswith("#"):
            match = _FPC_DEFINE.match(line)
            if match:
                out.define(match.group(1))
                out.evidence.append(make_evidence(path, number, 1, line))
            continue
        for token in _tokens(line):
            if token[:1] not in ("-", "/") or len(token) < 2:
                continue
            name, value = _split_switch(token[1:], flavour or "dcc")
            _apply_switch(name, value, flavour or "dcc", number, path, out)


def _apply_switch(name: str, value: str, flavour: str, number: int,
                  path: str, out: _Parsed) -> None:
    out.switch(name, value, number, path)
    if flavour == "dcc":
        if name == "-D":
            for define in re.split(r"[;,]", value):
                out.define(define.strip())
        if name in _DCC_SEARCH:
            out.search(value)
    else:
        if name == "-d":
            out.define(value.strip())
        if name in _FPC_SEARCH:
            out.search(value)


def _cfg_finding(item: AnalysedFile, text: str) -> CompilerConfigFinding:
    name = PurePosixPath(item.path).name.lower()
    lines = text[:MAX_TEXT_CHARS].split("\n")
    flavour = _guess_flavour(lines)
    if name.startswith("fpc"):
        flavour = "fpc"
    elif name.startswith("dcc"):
        flavour = "dcc"
    out = _Parsed()
    _parse_cfg(text, flavour, item.path, out)
    known = bool(out.switches) or bool(out.defines)
    if not known or not flavour:
        kind = "other-cfg"
    else:
        kind = "fpc-cfg" if flavour == "fpc" else "dcc-cfg"
    scope = "global" if name.startswith(("fpc", "dcc")) else "project"
    return out.result(item.path, kind, scope, text,
                      parsed=known and kind != "other-cfg")


def _dof_finding(item: AnalysedFile, text: str) -> CompilerConfigFinding:
    out = _Parsed()
    section = ""
    for number, raw in numbered_lines(text):
        line = redact_text(raw)
        head = _INI_SECTION.match(line)
        if head:
            section = head.group(1).strip().lower()
            continue
        pair = _INI_KEY.match(line)
        if not pair or section not in _DOF_SECTIONS:
            continue
        key, value = pair.group(1).strip(), pair.group(2).strip()
        out.switch(f"{section.capitalize()}.{key}", value, number, item.path)
        if section == "directories" and key.lower() == "searchpath":
            out.search(value)
        if section == "directories" and key.lower() == "conditionals":
            for define in re.split(r"[;,]", value):
                out.define(define.strip())
    return out.result(item.path, "delphi-options", "project", text,
                      parsed=bool(out.switches))


def _xml_parseable(text: str) -> bool:
    """Refuse empty, oversized or entity-declaring XML (expansion attacks).

    Entity declarations are the only DTD feature that can amplify input, so a
    plain ``<!DOCTYPE>`` is still parsed.
    """

    if not text.strip() or len(text) > _MAX_XML_CHARS:
        return False
    return "<!ENTITY" not in text and "<!DOCTYPE" not in text.upper()[:4096] \
        or "<!ENTITY" not in text


def _project_finding(item: AnalysedFile, text: str) -> CompilerConfigFinding:
    kind = "lazarus-project" if item.path.lower().endswith(".lpi") \
        else "delphi-project"
    out = _Parsed()
    ok = _xml_parseable(text)
    if ok:
        profile, problems = parse_project_file(item.path, text)
        ok = not problems
        for define in profile.defines:
            out.define(define)
        for entry in profile.unit_search_paths:
            out.search(entry)
    if ok:
        _project_switches(text, item.path, out)
    return out.result(item.path, kind, "project", text, parsed=ok)


def _project_switches(text: str, path: str, out: _Parsed) -> None:
    for number, raw in numbered_lines(text):
        line = redact_text(raw)
        for match in _DCC_ELEMENT.finditer(line):
            out.switch(match.group(1), match.group(2).strip(), number, path)
        for match in _LPI_ELEMENT.finditer(line):
            value = match.group(2)
            out.switch(match.group(1), value, number, path)
            if match.group(1) == "CustomOptions":
                for token in _tokens(value):
                    if token.startswith("-d") and len(token) > 2:
                        out.define(token[2:])


def detect_compiler_configs(
    analysed: list[AnalysedFile], text_of: dict[str, str]
) -> list[CompilerConfigFinding]:
    """Compiler configuration files and the switches they state.

    ``text_of`` maps path → decoded text; a file without text still yields an
    ``UNKNOWN`` finding (located at line 1) so the config is never dropped.
    """

    findings: list[CompilerConfigFinding] = []
    for item in sorted_files(analysed):
        lower = item.path.lower()
        if not lower.endswith(CONFIG_EXTENSIONS):
            continue
        text = (text_of or {}).get(item.path)
        if not text or not text.strip():
            findings.append(_empty_finding(item))
        elif lower.endswith(".cfg"):
            findings.append(_cfg_finding(item, text))
        elif lower.endswith(".dof"):
            findings.append(_dof_finding(item, text))
        else:
            findings.append(_project_finding(item, text))
    return findings


_KINDS_BY_EXTENSION = {
    ".cfg": "other-cfg", ".dof": "delphi-options", ".dproj": "delphi-project",
    ".bdsproj": "delphi-project", ".lpi": "lazarus-project",
}


def _empty_finding(item: AnalysedFile) -> CompilerConfigFinding:
    ext = PurePosixPath(item.path).suffix.lower()
    name = PurePosixPath(item.path).name.lower()
    kind = _KINDS_BY_EXTENSION.get(ext, "other-cfg")
    if ext == ".cfg" and name.startswith("fpc"):
        kind = "fpc-cfg"
    elif ext == ".cfg" and name.startswith("dcc"):
        kind = "dcc-cfg"
    return CompilerConfigFinding(
        path=item.path,
        kind=kind,
        scope="global" if name.startswith(("fpc", "dcc")) else "project",
        evidence=(make_evidence(
            item.path, 1, 1, "configuration file present; content not read"
        ),),
        confidence="low",
        status="UNKNOWN",
    )

