"""Stage 1 runtime-dependency detection.

What the *running* application needs that is not Pascal source: native
libraries and packages, configuration/data files opened by name, registry
keys, environment variables, hard-coded absolute paths, database client
libraries, Windows services and COM components.

Rules that keep this honest:

* Names come from real call sites (``TIniFile.Create('x.ini')``,
  ``GetEnvironmentVariable('X')``, ``CreateOleObject('A.B')``), from
  ``external`` clauses / ``requires`` clauses, or from literals that *are*
  paths, registry roots or ``%VARS%``.  Comments and bare identifiers never
  count (the scanner does not emit them as tokens).
* ``resolved_in_input`` is checked against the inventory, case-insensitively,
  by relative path or base name.  Absolute paths, registry keys and the like
  are never "resolved".
* OS-provided DLLs (``kernel32.dll`` ...) are not reported: they are never
  part of an application tree and would only add unresolvable noise.
* Secrets never reach a name or an excerpt: names are cut at ``;`` and pass
  through :func:`p1.evutil.redact_text`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable

from .evutil import (
    MAX_FINDINGS_PER_KIND,
    MAX_REFERENCES,
    Literal,
    bounded,
    first_unique,
    literals_of,
    make_evidence,
    numbered_lines,
    redact_text,
    sorted_files,
    unquote,
)
from .findings import Evidence, RuntimeDependencyFinding
from .knowledge import (
    DB_CLIENT_LIBRARIES,
    FIREDAC_DRIVER_CLIENT,
    PACKAGE_TABLE,
    SYSTEM_DLLS,
    TECH_CLIENT,
    match_family,
)
from .model import AnalysedFile
from .plex import Token

__all__ = ["detect_runtime_dependencies"]

_POOL = 100
_RANK = {"low": 0, "medium": 1, "high": 2}
_OPENSSL_NAME = "OpenSSL (libeay32.dll, ssleay32.dll)"
_INI_TRIGGERS = frozenset({
    "tinifile", "tmeminifile", "tcustominifile", "txmlinifile",
})
_FILE_TRIGGERS = frozenset({"loadfromfile", "readfromfile"})
_REGISTRY_TRIGGERS = frozenset({
    "openkey", "openkeyreadonly", "createkey", "keyexists", "deletekey",
    "regopenkeyex", "regcreatekeyex", "tregistryinifile",
})
_ENV_TRIGGERS = frozenset({
    "getenvironmentvariable", "getenvironmentvariableutf8",
    "setenvironmentvariable",
})
_SERVICE_BASES = frozenset({
    "tservice", "tdaemon", "tcustomdaemon", "tserviceapplication",
})
_CONFIG_EXTS = frozenset({
    ".ini", ".cfg", ".conf", ".config", ".xml", ".json", ".properties",
    ".yaml", ".yml", ".toml", ".env",
})
_DATA_EXTS = frozenset({
    ".dat", ".csv", ".txt", ".db", ".dbf", ".cds", ".xls", ".xlsx", ".mdb",
    ".tab", ".bin", ".lst", ".fr3", ".frf", ".rtm", ".rav", ".rpt", ".qrp",
    ".res", ".bmp", ".jpg", ".png", ".ico", ".wav", ".rtf", ".doc", ".pdf",
    ".sql", ".xsl", ".xsd",
})
_FILE_NAME = re.compile(r"[^\\/.\s][^\\/]*\.\w{1,6}$")
_PROGID = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+(?:\.\d+)*$")
_GUID = re.compile(r"^\{[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\}$")
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_ENV_REF = re.compile(r"%([A-Z_][A-Z0-9_]+)%")
_REGISTRY_ROOT = re.compile(
    r"(?i)\b(?:HKEY_(?:LOCAL_MACHINE|CURRENT_USER|CLASSES_ROOT|USERS|"
    r"CURRENT_CONFIG)|HK(?:LM|CU|CR|U))\\[^\"'<>|;\r\n]+"
)
_PATH_PATTERNS = (
    re.compile(r"(?<![\w])[A-Za-z]:[\\/][^\"'<>|;\r\n]+"),
    re.compile(r"(?<![\w\\])\\\\[A-Za-z0-9_.$-]+\\[A-Za-z0-9_.$-]+"
               r"(?:\\[^\"'<>|;\r\n]*)?"),
    re.compile(r"(?<![\w:/.\\])/(?:usr|etc|var|opt|home|tmp|srv|mnt|root|"
               r"dev|proc|lib|lib64|bin|sbin)(?:/[^\s\"'<>|;]*)?"),
)
_PATH_HINT = re.compile(r"[A-Za-z]:[\\/]|\\\\|/[a-z]")
_DRIVER_ID = re.compile(r"(?i)driverid\s*=\s*([A-Za-z0-9_]+)")
_DRIVER_ALIASES = {
    "oracle": "ora", "postgresql": "pg", "firebird": "fb", "interbase": "ib",
}
_SERVICE_COMMANDS = (
    re.compile(r"(?i)\bsc(?:\.exe)?\s+create\s+(\"[^\"]+\"|[\w.$-]+)"),
    re.compile(r"(?i)\bnssm(?:\.exe)?\s+install\s+(\"[^\"]+\"|[\w.$-]+)"),
    re.compile(r"(?i)\bnet\s+start\s+(\"[^\"]+\"|[\w.$-]+)"),
    re.compile(r"(?i)\bNew-Service\s+(?:-Name\s+)?(\"[^\"]+\"|[\w.$-]+)"),
)
_COMMENT_PREFIXES = ("rem ", "::", "#", ";")


# --------------------------------------------------------------------------
# Inventory and accumulator
# --------------------------------------------------------------------------


class _Inventory:
    """Case-insensitive lookup of paths, suffixes and base names."""

    def __init__(self, analysed: list[AnalysedFile]) -> None:
        self.suffixes: set[str] = set()
        self.by_name: dict[str, list[str]] = {}
        for item in analysed:
            parts = item.path.casefold().split("/")
            for i in range(len(parts)):
                self.suffixes.add("/".join(parts[i:]))
            self.by_name.setdefault(parts[-1], []).append(item.path)

    def has(self, name: str) -> bool:
        norm = name.replace("\\", "/").strip().casefold()
        while norm.startswith(("./", "../")):
            norm = norm.split("/", 1)[1]
        if not norm or ":" in norm or norm.startswith("/"):
            return False
        return norm in self.suffixes

    def first_path(self, base: str) -> str | None:
        paths = sorted(self.by_name.get(base.casefold(), []))
        return paths[0] if paths else None


@dataclass
class _Dep:
    name: str
    kind: str
    required_by: set[str] = field(default_factory=set)
    evidence: list[Evidence] = field(default_factory=list)
    resolved: bool = False
    rank: int = 0


class _Deps:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], _Dep] = {}

    def add(self, kind: str, name: str, ev: Evidence, *, resolved: bool,
            confidence: str, required_by: str | None = None) -> None:
        key = (kind, name.casefold().replace("\\", "/"))
        dep = self.items.setdefault(key, _Dep(name=name, kind=kind))
        dep.resolved = dep.resolved or resolved
        dep.rank = max(dep.rank, _RANK[confidence])
        if required_by:
            dep.required_by.add(required_by)
        if len(dep.evidence) < _POOL:
            dep.evidence.append(ev)

    def files_for(self, kind: str) -> set[str]:
        return {e.file for (k, _), d in self.items.items() if k == kind
                for e in d.evidence}


def _loc(item: AnalysedFile, tok: Token, text: str) -> Evidence:
    return make_evidence(item.path, tok.line, tok.column, text)


# --------------------------------------------------------------------------
# Native libraries and database clients
# --------------------------------------------------------------------------


def _db_client_label(base: str) -> str | None:
    for pattern, label in DB_CLIENT_LIBRARIES:
        if pattern.fullmatch(base):
            return label
    return None


def _native_kind(base: str) -> str:
    if _db_client_label(base):
        return "database-client"
    if base.endswith(".bpl"):
        return "bpl-package"
    if base.endswith(".ocx"):
        return "com-component"
    return "dll"


def _native_deps(analysed: list[AnalysedFile], native_libs: Iterable[Any],
                 inv: _Inventory, deps: _Deps) -> None:
    wanted = {str(lib.name).lower() for lib in native_libs or ()}
    locations: dict[str, list[tuple[str, Any]]] = {}
    for item in sorted_files(analysed):
        if item.scan is None:
            continue
        for ref in item.scan.native_refs:
            low = ref.name.lower()
            if ref.kind != "os-api" and low in wanted:
                bucket = locations.setdefault(low, [])
                if len(bucket) < _POOL:
                    bucket.append((item.path, ref))
    for name in sorted(wanted):
        base = PurePosixPath(name.replace("\\", "/")).name
        if base in SYSTEM_DLLS:
            continue
        kind = _native_kind(base)
        resolved = inv.has(name)
        refs = locations.get(name, [])
        for path, ref in refs:
            deps.add(kind, name, make_evidence(
                path, ref.line, ref.column,
                f"{ref.kind} reference {ref.name}"),
                resolved=resolved, confidence="high", required_by=path)
        shipped = inv.first_path(base)
        if not refs and shipped:
            deps.add(kind, name, make_evidence(
                shipped, 1, 1, "binary present in the ingested input"),
                resolved=True, confidence="high")


def _driver_client(driver: str) -> str | None:
    low = _DRIVER_ALIASES.get(driver.lower(), driver.lower())
    for prefix in sorted(FIREDAC_DRIVER_CLIENT, key=lambda p: (-len(p), p)):
        if low.startswith(prefix):
            return FIREDAC_DRIVER_CLIENT[prefix]
    return None


def _client_dep(deps: _Deps, inv: _Inventory, client: str, ev: Evidence
                ) -> None:
    deps.add("database-client", client, ev, resolved=inv.has(client),
             confidence="low", required_by=ev.file)


def _firedac_units(item: AnalysedFile, inv: _Inventory, deps: _Deps) -> None:
    for clause in item.scan.uses:  # type: ignore[union-attr]
        for unit in clause.items:
            low = unit.name.lower()
            if low.startswith("firedac.phys."):
                client = _driver_client(low[len("firedac.phys."):])
                if client:
                    _client_dep(deps, inv, client, make_evidence(
                        item.path, unit.line, unit.column,
                        f"unit {unit.name} implies client library {client}"))


def _db_client_deps(analysed: list[AnalysedFile], text_of: dict[str, str],
                    databases: Iterable[Any], inv: _Inventory,
                    deps: _Deps) -> None:
    for item in sorted_files(analysed):
        if item.scan is not None:
            _firedac_units(item, inv, deps)
        for lit in literals_of(item, text_of):
            match = _DRIVER_ID.search(lit.text) if "=" in lit.text else None
            client = _driver_client(match.group(1)) if match else None
            if client:
                _client_dep(deps, inv, client, make_evidence(
                    item.path, lit.line, lit.column,
                    f"connection parameter DriverID={match.group(1)} "
                    f"implies {client}"))
    by_base: dict[str, str] = {}
    for item in sorted_files(analysed):
        by_base.setdefault(PurePosixPath(item.path).name, item.path)
    for finding in databases or ():
        client = TECH_CLIENT.get(getattr(finding, "technology", ""))
        if not client:
            continue
        for entry in list(getattr(finding, "evidence", ()))[:_POOL]:
            path = by_base.get(str(entry.get("source", "")))
            if path:
                _client_dep(deps, inv, client, make_evidence(
                    path, int(entry.get("line", 1) or 1),
                    int(entry.get("column", 1) or 1),
                    f"{finding.technology} usage implies {client}"))


# --------------------------------------------------------------------------
# Call-site triggers (Pascal tokens)
# --------------------------------------------------------------------------


def _strings_after(tokens: list[Token], index: int, limit: int
                   ) -> list[Token]:
    out: list[Token] = []
    for tok in tokens[index + 1:index + 1 + limit]:
        if tok.text == ";":
            break
        if tok.kind == "string" and tok.text.startswith("'"):
            out.append(tok)
    return out


def _pick_file_literal(strings: list[Token], ini: bool) -> Token | None:
    named = [t for t in strings if _FILE_NAME.search(unquote(t.text).strip())]
    if named:
        return named[-1]
    if ini:
        real = [t for t in strings if len(unquote(t.text).strip()) > 1
                and not unquote(t.text).strip().startswith(".")
                and unquote(t.text).strip().strip("\\/")]
        return real[-1] if real else None
    return None


def _file_kind(name: str, ini: bool) -> str | None:
    ext = PurePosixPath(name.replace("\\", "/")).suffix.lower()
    if ini or ext in _CONFIG_EXTS:
        return "configuration-file"
    return "data-file" if ext in _DATA_EXTS else None


def _file_trigger(item: AnalysedFile, tokens: list[Token], i: int,
                  inv: _Inventory, deps: _Deps) -> None:
    ini = tokens[i].lower in _INI_TRIGGERS
    tok = _pick_file_literal(_strings_after(tokens, i, 16), ini)
    if tok is None:
        return
    name = unquote(tok.text).strip()
    kind = _file_kind(name, ini)
    if kind:
        deps.add(kind, name, _loc(item, tok, f"{tokens[i].text} names {name}"),
                 resolved=inv.has(name), confidence="high",
                 required_by=item.path)


def _registry_trigger(item: AnalysedFile, tokens: list[Token], i: int,
                      deps: _Deps) -> None:
    strings = _strings_after(tokens, i, 6)
    if not strings:
        return
    raw = unquote(strings[0].text).split(";", 1)[0].strip().lstrip("\\")
    name = redact_text(raw)
    if name:
        deps.add("registry-key", name, _loc(
            item, strings[0], f"{tokens[i].text} opens {name}"),
            resolved=False, confidence="medium", required_by=item.path)


def _env_trigger(item: AnalysedFile, tokens: list[Token], i: int,
                 deps: _Deps) -> None:
    strings = _strings_after(tokens, i, 6)
    name = unquote(strings[0].text).strip() if strings else ""
    if strings and _ENV_NAME.match(name):
        deps.add("environment-variable", name, _loc(
            item, strings[0], f"{tokens[i].text} reads {name}"),
            resolved=False, confidence="medium", required_by=item.path)


def _com_trigger(item: AnalysedFile, tokens: list[Token], i: int,
                 deps: _Deps) -> None:
    low = tokens[i].lower
    strings = _strings_after(tokens, i, 10)
    for tok in strings[:1] if low != "createcomobject" else strings:
        value = unquote(tok.text).strip()
        valid = _GUID.match(value) if low == "createcomobject" \
            else _PROGID.match(value)
        if valid:
            deps.add("com-component", value, _loc(
                item, tok, f"{tokens[i].text} creates {value}"),
                resolved=False, confidence="high", required_by=item.path)
            return


def _service_class(item: AnalysedFile, tokens: list[Token], i: int,
                   deps: _Deps) -> None:
    """``TFoo = class(TService)`` at *i* (the base-class ident)."""

    if i >= 4 and tokens[i - 1].text == "(" and \
            tokens[i - 2].lower == "class" and tokens[i - 3].text == "=" \
            and tokens[i - 4].kind == "ident":
        name = tokens[i - 4]
        deps.add("service", name.text, _loc(
            item, name, f"{name.text} derives from {tokens[i].text}"),
            resolved=False, confidence="high", required_by=item.path)


def _trigger_deps(item: AnalysedFile, inv: _Inventory, deps: _Deps) -> None:
    tokens = item.scan.tokens  # type: ignore[union-attr]
    for i, tok in enumerate(tokens):
        if tok.kind != "ident":
            continue
        low = tok.lower
        if low in _INI_TRIGGERS or low in _FILE_TRIGGERS:
            _file_trigger(item, tokens, i, inv, deps)
        elif low in _REGISTRY_TRIGGERS:
            _registry_trigger(item, tokens, i, deps)
        elif low in _ENV_TRIGGERS:
            _env_trigger(item, tokens, i, deps)
        elif low in ("createoleobject", "getactiveoleobject",
                     "createcomobject"):
            _com_trigger(item, tokens, i, deps)
        elif low in _SERVICE_BASES:
            _service_class(item, tokens, i, deps)


# --------------------------------------------------------------------------
# Literals: paths, registry roots, %VARS%
# --------------------------------------------------------------------------


def _clean_path(raw: str) -> str:
    return redact_text(raw.strip().rstrip(".,)").strip())[:200]


def _literal_deps(item: AnalysedFile, lit: Literal, deps: _Deps) -> None:
    text = lit.text
    for pattern in _PATH_PATTERNS if _PATH_HINT.search(text) else ():
        for match in pattern.finditer(text):
            name = _clean_path(match.group(0))
            if len(name) > 3:
                deps.add("hardcoded-path", name, make_evidence(
                    item.path, lit.line, lit.column,
                    f"hard-coded path {name}"),
                    resolved=False, confidence="medium",
                    required_by=item.path)
    for match in (_REGISTRY_ROOT.finditer(text) if "\\" in text else ()):
        name = _clean_path(match.group(0))
        deps.add("registry-key", name, make_evidence(
            item.path, lit.line, lit.column, f"registry key {name}"),
            resolved=False, confidence="medium", required_by=item.path)
    for match in (_ENV_REF.finditer(text) if "%" in text else ()):
        deps.add("environment-variable", match.group(1), make_evidence(
            item.path, lit.line, lit.column,
            f"environment reference %{match.group(1)}%"),
            resolved=False, confidence="medium", required_by=item.path)


def _is_compiler_config(item: AnalysedFile) -> bool:
    name = PurePosixPath(item.path).name.lower()
    return name.endswith(".cfg") or name.startswith(("dcc", "fpc"))


def _scan_literals(item: AnalysedFile, text_of: dict[str, str],
                   deps: _Deps) -> None:
    if item.cls == "configuration" and _is_compiler_config(item):
        return
    for lit in literals_of(item, text_of):
        if item.cls == "configuration" and lit.text.startswith((";", "#")):
            continue
        _literal_deps(item, lit, deps)


# --------------------------------------------------------------------------
# Scripts, integrations and libraries
# --------------------------------------------------------------------------


def _script_services(item: AnalysedFile, text: str, deps: _Deps) -> None:
    for number, line in numbered_lines(text):
        stripped = line.strip()
        if not stripped or stripped.lower().startswith(_COMMENT_PREFIXES):
            continue
        for pattern in _SERVICE_COMMANDS:
            match = pattern.search(stripped)
            if match:
                name = match.group(1).strip('"')
                deps.add("service", name, make_evidence(
                    item.path, number, 1, stripped),
                    resolved=False, confidence="medium",
                    required_by=item.path)


def _integration_services(integrations: Iterable[Any], deps: _Deps) -> None:
    covered = deps.files_for("service")
    for finding in integrations or ():
        if getattr(finding, "category", "") != "windows-service":
            continue
        for ev in finding.evidence:
            if ev.file not in covered:
                deps.add("service", finding.technology, ev, resolved=False,
                         confidence="low", required_by=ev.file)


def _library_runtime(libraries: Iterable[Any], inv: _Inventory,
                     deps: _Deps) -> None:
    for lib in libraries or ():
        units = " ".join(getattr(lib, "units", ()))
        evidence = list(getattr(lib, "evidence", ()))
        if not evidence:
            continue
        if "openssl" in units or lib.name == "OpenSSL":
            hit = next((e for e in evidence if "openssl" in e.text.lower()),
                       evidence[0])
            both = inv.has("libeay32.dll") and inv.has("ssleay32.dll")
            deps.add("runtime-library", _OPENSSL_NAME, hit, resolved=both,
                     confidence="low", required_by=hit.file)
        if lib.name == "SQLite":
            deps.add("database-client", "sqlite3.dll", evidence[0],
                     resolved=inv.has("sqlite3.dll"), confidence="low",
                     required_by=evidence[0].file)


def _compiler_package(name: str) -> bool:
    low = name.lower()
    if low in PACKAGE_TABLE or re.sub(r"\d+$", "", low) in PACKAGE_TABLE:
        return True
    family = match_family(name)
    return family is not None and family.absent_origin in ("rtl", "framework")


def _requires_deps(item: AnalysedFile, inv: _Inventory, deps: _Deps) -> None:
    for clause in item.scan.uses:  # type: ignore[union-attr]
        if clause.kind != "requires":
            continue
        for unit in clause.items:
            if _compiler_package(unit.name):
                continue  # compiler-supplied package, not a shipped BPL
            deps.add("bpl-package", unit.name, make_evidence(
                item.path, unit.line, unit.column,
                f"`requires` clause names package {unit.name}"),
                resolved=inv.has(unit.name + ".bpl")
                or inv.has(unit.name + ".dpk"),
                confidence="high", required_by=item.path)


def _finalise(dep: _Dep) -> RuntimeDependencyFinding | None:
    evidence = bounded(dep.evidence)
    if not evidence:
        return None
    confidence = {0: "low", 1: "medium", 2: "high"}[dep.rank]
    return RuntimeDependencyFinding(
        kind=dep.kind,
        name=dep.name,
        required_by=first_unique(sorted(dep.required_by), MAX_REFERENCES),
        resolved_in_input=dep.resolved,
        evidence=evidence,
        confidence=confidence,
        status="PARTIAL",
    )


def detect_runtime_dependencies(
    analysed: list[AnalysedFile],
    text_of: dict[str, str],
    native_libs: Iterable[Any],
    os_deps: Iterable[Any],
    databases: Iterable[Any],
    integrations: Iterable[Any],
    libraries: Iterable[Any],
) -> list[RuntimeDependencyFinding]:
    """Runtime dependencies of the application (see the module docstring).

    ``native_libs`` / ``databases`` / ``os_deps`` are the ``metadata``
    findings, ``integrations`` / ``libraries`` the Stage 1 findings.
    ``os_deps`` is accepted for contract symmetry; platform facts do not add
    a runtime dependency of their own.  At most 500 findings per kind are
    returned (first by name), each with at most 25 evidence entries.
    """

    text_of = text_of or {}
    inv = _Inventory(analysed)
    deps = _Deps()
    _native_deps(analysed, native_libs, inv, deps)
    _db_client_deps(analysed, text_of, databases, inv, deps)
    for item in sorted_files(analysed):
        if item.scan is not None:
            _trigger_deps(item, inv, deps)
            _requires_deps(item, inv, deps)
        _scan_literals(item, text_of, deps)
        text = text_of.get(item.path)
        if item.cls == "build_script" and text:
            _script_services(item, text, deps)
    _integration_services(integrations, deps)
    _library_runtime(libraries, inv, deps)

    ordered = sorted(deps.items.values(),
                     key=lambda d: (d.kind, d.name.casefold(), d.name))
    per_kind: dict[str, int] = {}
    findings: list[RuntimeDependencyFinding] = []
    for dep in ordered:
        per_kind[dep.kind] = per_kind.get(dep.kind, 0) + 1
        if per_kind[dep.kind] > MAX_FINDINGS_PER_KIND:
            continue
        finding = _finalise(dep)
        if finding:
            findings.append(finding)
    return findings
