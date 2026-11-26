"""Database, native-library, OS and build/runtime requirement discovery (req. 5).

Everything here is *detection with evidence*, never an integration claim: a
connection component found in a ``uses`` clause says the application talks to
that technology, not that this platform can drive it.  The report therefore
records these as inventory findings with ``PARTIAL``/``UNKNOWN`` capability
states — an inventory list is explicitly not a driver claim (README
*Current limitations*).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

from .dialects import classify_unit
from .errors import DiagnosticSink
from .model import AnalysedFile
from .projects import Profile, ProjectRoot

__all__ = [
    "DatabaseFinding",
    "detect_database",
    "detect_sql_files",
    "detect_native_libs",
    "detect_os_dependencies",
    "build_requirements",
]

# --------------------------------------------------------------------------
# Database technology detection
# --------------------------------------------------------------------------

#: Component/class name (lower-case) → database technology.
_DB_COMPONENTS: dict[str, str] = {
    "tadoconnection": "ADO",
    "tadoquery": "ADO",
    "tadodataset": "ADO",
    "tadotable": "ADO",
    "tadostoredproc": "ADO",
    "tquery": "BDE",
    "ttable": "BDE",
    "tupdatesql": "BDE",
    "tstoredproc": "BDE",
    "tsession": "BDE",
    "tsqlconnection": "dbExpress",
    "tsqlquery": "dbExpress",
    "tsqlstoredproc": "dbExpress",
    "tsqltable": "dbExpress",
    "tibdatabase": "InterBase/Firebird",
    "tibquery": "InterBase/Firebird",
    "tibtransaction": "InterBase/Firebird",
    "tibsql": "InterBase/Firebird",
    "tfdconnection": "FireDAC",
    "tfdquery": "FireDAC",
    "tfdtable": "FireDAC",
    "tuniconnection": "UniDAC",
    "tuniquery": "UniDAC",
    "tmyconnection": "MyDAC (MySQL)",
    "tzconnection": "Zeos DBO",
    "tzquery": "Zeos DBO",
    "tsqlite3connection": "SQLite (SQLdb)",
    "tsqlite3query": "SQLite (SQLdb)",
    "tpqconnection": "PostgreSQL (SQLdb)",
    "tpgconnection": "PostgreSQL (SQLdb)",
    "tpqquery": "PostgreSQL (SQLdb)",
    "toracleconnection": "Oracle (SQLdb)",
    "toraclequery": "Oracle (SQLdb)",
    "tclientdataset": "MIDAS/DataSnap",
    "tdataset": "generic (TDataSet)",
    "tdatasource": "generic (TDataSource)",
}

#: Unit name (lower-case) → database technology.  Used when the unit is in a
#: ``uses`` clause but no component class appears.
_DB_UNITS: dict[str, str] = {
    "dbtables": "BDE",
    "db": "generic (TDataSet)",
    "dbctrls": "generic (TDataSet)",
    "dbgrids": "generic (TDataSet)",
    "ado": "ADO",
    "adodb": "ADO",
    "sqlexpr": "dbExpress",
    "data.sqlexpr": "dbExpress",
    "dbxcommon": "dbExpress",
    "ibdatabase": "InterBase/Firebird",
    "ibase": "InterBase/Firebird",
    "ibsql": "InterBase/Firebird",
    "fbintf": "InterBase/Firebird",
    "firebird": "InterBase/Firebird",
    "firedac.comp.client": "FireDAC",
    "firedac.phys.sqlite": "FireDAC",
    "firedac.phys.pg": "FireDAC",
    "firedac.phys.mysql": "FireDAC",
    "sqldb": "SQLdb (FPC)",
    "sqldbtypes": "SQLdb (FPC)",
    "zconnection": "Zeos DBO",
    "zeosdb": "Zeos DBO",
    "dbclient": "MIDAS/DataSnap",
    "provider": "MIDAS/DataSnap",
    "dsnap": "MIDAS/DataSnap",
}

#: Connection-string parameter → technology, for literal connection strings.
_CONN_PARAM_TECH: dict[str, str] = {
    "sqloledb": "ADO",
    "microsoft.jet.oledb": "ADO (Access)",
    "microsoft.ace.oledb": "ADO (Access)",
    "sqloledb.1": "ADO",
}

#: Connection-string parameters worth recording (never their *values*, which
#: may contain credentials — see :func:`_redact`).
_CONN_PARAMS = (
    "provider", "driverid", "drivername", "server", "data source",
    "initial catalog", "database", "datasource", "host", "port",
    "integrated security", "persist security info",
)

_CREDENTIAL_KEYS = (
    "password", "passwd", "pwd", "user id", "uid", "user", "username",
    "credential", "secret", "token", "api key", "apikey",
)


def _redact(text: str) -> str:
    """Strip credential-shaped key/value pairs from a captured string."""

    out = text
    for key in _CREDENTIAL_KEYS:
        out = re.sub(
            rf"(?i)(\b{re.escape(key)}\s*=\s*)([^;,\s\"]+)",
            r"\1<redacted>",
            out,
        )
    return out


@dataclass
class DatabaseFinding:
    """One database technology detected, with its evidence."""

    technology: str
    evidence: list[dict[str, object]] = field(default_factory=list)
    confidence: str = "low"
    #: Detection only — never a driver/adapter capability claim.
    status: str = "PARTIAL"

    def as_dict(self) -> dict[str, object]:
        return {
            "confidence": self.confidence,
            "evidence": self.evidence,
            "status": self.status,
            "technology": self.technology,
        }


def detect_database(analysed: list[AnalysedFile]) -> list[DatabaseFinding]:
    """Find database technologies referenced by the ingested sources."""

    found: dict[str, DatabaseFinding] = {}

    def add(tech: str, evidence: dict[str, object], weight: int) -> None:
        finding = found.setdefault(
            tech, DatabaseFinding(technology=tech, evidence=[])
        )
        finding.evidence.append(evidence)
        if weight >= 2 and finding.confidence == "low":
            finding.confidence = "medium"
        elif weight >= 3 and finding.confidence == "medium":
            finding.confidence = "high"

    for item in analysed:
        if item.scan is None:
            continue
        source = item.path

        # (a) Component classes — distinctive names, safe as plain idents.
        for token in item.scan.tokens:
            if token.kind != "ident":
                continue
            tech = _DB_COMPONENTS.get(token.text.lower())
            if tech:
                add(tech, {
                    "evidence": f"reference to {token.text}",
                    "line": token.line,
                    "column": token.column,
                    "source": source,
                }, weight=1)

        # (b) Units — only from an actual `uses`/`requires` clause.  A bare
        #     identifier such as `DB` is far too common to treat as a unit
        #     reference; guessing here would invent a database technology.
        for clause in item.scan.uses:
            for unit in clause.items:
                tech = _DB_UNITS.get(unit.name.lower())
                if tech is None:
                    category, matched = classify_unit(unit.name)
                    if category == "database" and matched:
                        tech = _DB_UNITS.get(matched)
                if tech:
                    add(tech, {
                        "evidence": (
                            f"`{clause.kind}` clause names unit {unit.name}"
                        ),
                        "line": unit.line,
                        "column": unit.column,
                        "source": source,
                    }, weight=2)

        # Connection strings and component properties live in literals.
        for token in item.scan.tokens:
            if token.kind != "string":
                continue
            literal = token.text.strip("'")
            lowered = literal.lower()
            for needle, tech in _CONN_PARAM_TECH.items():
                if needle in lowered:
                    add(tech, {
                        "evidence": f"connection string mentions {needle}",
                        "line": token.line,
                        "column": token.column,
                        "source": source,
                    }, weight=3)
            if "driverid=" in lowered or "drivername=" in lowered:
                match = re.search(
                    r"(?:driverid|drivername)=([A-Za-z0-9_]+)", literal, re.I
                )
                if match:
                    add(f"driver {match.group(1)}", {
                        "evidence": (
                            "connection parameter "
                            + _redact(literal)[:120]
                        ),
                        "line": token.line,
                        "column": token.column,
                        "source": source,
                    }, weight=2)

    return [found[key] for key in sorted(found)]


# --------------------------------------------------------------------------
# SQL files
# --------------------------------------------------------------------------

#: Ordered dialect probes: first match wins, so a more specific marker must
#: come before a generic one.
_SQL_DIALECTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("sqlite", re.compile(
        r"\bPRAGMA\b|\bAUTOINCREMENT\b|INTEGER\s+PRIMARY\s+KEY", re.I)),
    ("postgresql", re.compile(
        r"\bSERIAL\b|\bBIGSERIAL\b|\bILIKE\b|::\s*text\b|\bRETURNING\b"
        r"|\bpg_[a-z_]+\s*\(", re.I)),
    ("mysql/mariadb", re.compile(
        r"\bAUTO_INCREMENT\b|ENGINE\s*=\s*InnoDB|\bSET\s+NAMES\b"
        r"|\bTINYINT\b", re.I)),
    ("oracle", re.compile(
        r"\bFROM\s+DUAL\b|\bNVL\s*\(|\bSEQUENCE\b|\bNUMBER\s*\(", re.I)),
    ("sql-server", re.compile(
        r"\bNVARCHAR\b|\bISNULL\s*\(|\bGETDATE\s*\(|\bIDENTITY\s*\(",
        re.I)),
    ("firebird/interbase", re.compile(
        r"\bEXECUTE\s+PROCEDURE\b|\bCREATE\s+DOMAIN\b|\bGEN_ID\s*\("
        r"|\bRDB\$", re.I)),
)


@dataclass
class SqlFileFinding:
    """One SQL file with the dialect markers found in it."""

    path: str
    dialect: str
    markers: list[str] = field(default_factory=list)
    line: int = 1
    confidence: str = "low"
    status: str = "PARTIAL"

    def as_dict(self) -> dict[str, object]:
        return {
            "confidence": self.confidence,
            "dialect": self.dialect,
            "evidence": [
                {
                    "evidence": f"SQL dialect marker {m!r}",
                    "line": self.line,
                    "source": self.path,
                }
                for m in self.markers
            ],
            "path": self.path,
            "status": self.status,
        }


def detect_sql_files(
    analysed: list[AnalysedFile], text_of: "dict[str, str]"  # noqa: F821
) -> list[SqlFileFinding]:
    """Classify each ``.sql`` file by dialect markers, with line evidence."""

    findings: list[SqlFileFinding] = []
    for item in sorted(analysed, key=lambda a: a.path):
        if item.cls != "sql":
            continue
        text = text_of.get(item.path, "")
        if not text:
            findings.append(SqlFileFinding(
                path=item.path, dialect="unknown", markers=[],
                confidence="low", status="UNKNOWN",
            ))
            continue
        dialect = "unknown"
        markers: list[str] = []
        line = 1
        for name, pattern in _SQL_DIALECTS:
            match = pattern.search(text)
            if match:
                dialect = name
                line = text.count("\n", 0, match.start()) + 1
                markers.append(match.group(0).strip())
                # A second, independent marker raises confidence.
                second = pattern.search(text, match.end())
                if second:
                    markers.append(second.group(0).strip())
                break
        findings.append(SqlFileFinding(
            path=item.path,
            dialect=dialect,
            markers=markers,
            line=line,
            confidence="medium" if markers else "low",
            status="PARTIAL" if markers else "UNKNOWN",
        ))
    return findings


# --------------------------------------------------------------------------
# Native libraries and OS dependencies
# --------------------------------------------------------------------------


@dataclass
class NativeLibraryFinding:
    name: str
    evidence: list[dict[str, object]] = field(default_factory=list)
    #: ``dll`` / ``so`` / ``dylib`` / ``unknown``
    kind: str = "unknown"
    status: str = "PARTIAL"

    def as_dict(self) -> dict[str, object]:
        return {
            "evidence": self.evidence,
            "kind": self.kind,
            "name": self.name,
            "status": self.status,
        }


def _lib_kind(name: str) -> str:
    lowered = name.lower()
    if lowered.endswith(".dll") or lowered.endswith(".ocx"):
        return "dll"
    if lowered.endswith(".dylib"):
        return "dylib"
    if lowered.endswith(".so"):
        return "so"
    if lowered.endswith(".bpl"):
        return "bpl"
    if lowered.endswith((".a", ".lib", ".o")):
        return "static"
    return "unknown"


def detect_native_libs(analysed: list[AnalysedFile]) -> list[NativeLibraryFinding]:
    """Aggregate shared-library references and in-tree binary components."""

    found: dict[str, NativeLibraryFinding] = {}

    for item in analysed:
        source = item.path
        if item.scan is not None:
            for ref in item.scan.native_refs:
                if ref.kind == "os-api":
                    continue  # recorded as an OS dependency instead
                key = ref.name.lower()
                entry = found.setdefault(
                    key, NativeLibraryFinding(name=key, kind=_lib_kind(key))
                )
                entry.evidence.append({
                    "evidence": f"{ref.kind} reference {ref.name}",
                    "line": ref.line,
                    "column": ref.column,
                    "source": source,
                })
        # A binary shipped inside the input is itself a native dependency.
        if item.cls == "binary" and _lib_kind(item.path) in (
            "dll", "so", "dylib", "bpl"
        ):
            key = PurePosixPath(item.path).name.lower()
            entry = found.setdefault(
                key, NativeLibraryFinding(name=key, kind=_lib_kind(key))
            )
            entry.evidence.append({
                "evidence": "binary present in the ingested input",
                "sha256": item.inventory.sha256,
                "source": item.path,
            })

    return [found[key] for key in sorted(found)]


#: Conditional-compilation symbols that imply a platform.
_PLATFORM_CONDITIONALS: dict[str, str] = {
    "mswindows": "windows",
    "win32": "windows",
    "win64": "windows",
    "windows": "windows",
    "msdos": "windows",
    "unix": "unix",
    "linux": "linux",
    "darwin": "macos",
    "macos": "macos",
    "posix": "unix",
    "cpu386": "x86",
    "cpux86_64": "x86-64",
    "cpuarm": "arm",
    "cpu64": "64-bit",
}


@dataclass
class OsDependencyFinding:
    platform: str
    evidence: list[dict[str, object]] = field(default_factory=list)
    confidence: str = "medium"
    status: str = "PARTIAL"

    def as_dict(self) -> dict[str, object]:
        return {
            "confidence": self.confidence,
            "evidence": self.evidence,
            "platform": self.platform,
            "status": self.status,
        }


def detect_os_dependencies(
    analysed: list[AnalysedFile],
) -> list[OsDependencyFinding]:
    """Platforms implied by unit references and conditional compilation."""

    found: dict[str, OsDependencyFinding] = {}

    def add(platform: str, evidence: dict[str, object]) -> None:
        entry = found.setdefault(
            platform, OsDependencyFinding(platform=platform, evidence=[])
        )
        entry.evidence.append(evidence)

    for item in analysed:
        source = item.path
        if item.scan is None:
            continue
        # Platform units are only trusted from a real `uses` clause: `Windows`
        # or `Unix` as a bare identifier is far too common to mean anything.
        for clause in item.scan.uses:
            for unit in clause.items:
                lowered = unit.name.lower()
                platform = None
                if lowered in ("windows", "messages", "shellapi", "activex",
                               "comobj", "ole2", "winapi.windows"):
                    platform = "windows"
                elif lowered in ("baseunix", "unix", "unixtype", "unixutil",
                                 "cthreads", "ssockets"):
                    platform = "unix"
                if platform:
                    add(platform, {
                        "evidence": (
                            f"`{clause.kind}` clause names platform unit "
                            f"{unit.name}"
                        ),
                        "line": unit.line,
                        "column": unit.column,
                        "source": source,
                    })
        for directive in item.scan.directives:
            head = directive.argument.strip().split()
            if directive.name in ("IFDEF", "IFNDEF") and head:
                symbol = head[0].upper()
                platform = _PLATFORM_CONDITIONALS.get(symbol.lower())
                if platform:
                    add(platform, {
                        "evidence": f"{{$ {directive.name} {head[0]}}}",
                        "line": directive.line,
                        "column": directive.column,
                        "source": source,
                    })
        for ref in item.scan.native_refs:
            if ref.kind == "os-api":
                add("windows" if ref.name.lower() in (
                    "loadlibrary", "getprocaddress", "freelibrary",
                    "getmodulehandle",
                ) else "unix", {
                    "evidence": f"dynamic-loading API {ref.name}",
                    "line": ref.line,
                    "column": ref.column,
                    "source": source,
                })

    return [found[key] for key in sorted(found)]


# --------------------------------------------------------------------------
# Build / runtime requirements
# --------------------------------------------------------------------------


def build_requirements(
    analysed: list[AnalysedFile],
    roots: list[ProjectRoot],
    profiles: dict[str, Profile],
    unresolved_units: list[str],
    has_project_files: bool,
    sink: DiagnosticSink | None = None,
) -> dict[str, object]:
    """Derive compiler, flags and blockers from what was actually found.

    The compiler is *inferred*, never executed.  Two independent signal sets
    are counted — one per toolchain — and when both are present the conflict
    is reported rather than hidden behind whichever happened to score higher:
    a project that looks like both is a real ambiguity, not a tie to break
    silently.
    """

    #: Directives only FPC accepts; their presence is one-sided evidence.
    fpc_only_directives = {"MODE", "MODESWITCH", "PACKAGES", "IFDECLARED"}
    fpc_evidence: list[str] = []
    delphi_evidence: list[str] = []

    for item in analysed:
        lower = item.path.lower()
        if lower.endswith((".lpr", ".lpi", ".lpk", ".lfm", ".pp")):
            fpc_evidence.append(item.path)
        elif lower.endswith((".dpr", ".dproj", ".dpk", ".dfm", ".bdsproj")):
            delphi_evidence.append(item.path)

        if item.analysis is not None:
            if item.analysis.dialect == "delphi":
                delphi_evidence.append(f"{item.path} (dialect)")
            elif item.analysis.dialect in ("fpc", "iso-7185"):
                fpc_evidence.append(f"{item.path} (dialect)")

        if item.scan is None:
            continue
        for directive in item.scan.directives:
            if directive.name in fpc_only_directives:
                fpc_evidence.append(
                    f"{item.path}:{directive.line} ({{${directive.name}}})"
                )
            elif directive.name in ("IFDEF", "IFNDEF"):
                head = directive.argument.split()
                if head and head[0].upper() == "FPC":
                    fpc_evidence.append(
                        f"{item.path}:{directive.line} ({{$IFDEF FPC}})"
                    )

    if fpc_evidence and not delphi_evidence:
        compiler = "fpc"
    elif delphi_evidence and not fpc_evidence:
        compiler = "delphi"
    elif fpc_evidence and delphi_evidence:
        # Both toolchains have claimed this tree: report the winner by count
        # but record the conflict so the inference is never mistaken for a
        # fact.
        compiler = "fpc" if len(fpc_evidence) >= len(delphi_evidence) else "delphi"
        if sink is not None:
            sink.warn(
                "COMPILER_SIGNAL_CONFLICT",
                "both FPC and Delphi signals present "
                f"(fpc={len(fpc_evidence)}, delphi={len(delphi_evidence)}); "
                f"inferred {compiler}, but the tree is ambiguous",
            )
    else:
        compiler = "unknown"

    modes = sorted({
        p.mode for p in profiles.values()
        if p.mode and p.mode != "not-specified"
    })
    defines = sorted({d for p in profiles.values() for d in p.defines})
    unit_paths = sorted({p for p in profiles.values()
                         for p in p.unit_search_paths})

    flags: list[str] = []
    for mode in modes:
        # FPC's mode switch is a capital `-M`; the define and unit-path
        # switches are `-d` and `-Fu`.
        flags.append(f"-M{mode}")
    for define in defines:
        flags.append(f"-d{define}")
    for path in unit_paths:
        flags.append(f"-Fu{path}")
    flags = sorted(set(flags))

    blockers: list[dict[str, str]] = []
    if not roots:
        blockers.append({
            "code": "NO_PROJECT_ROOT",
            "detail": "no .dpr/.lpr/.dpk/.lpk entry-point file was found",
        })
    for root in roots:
        if root.status == "UNKNOWN":
            blockers.append({
                "code": "AMBIGUOUS_PROJECT_ROOT",
                "detail": f"{root.path} is not an unambiguous project root",
            })
        if root.kind == "unknown":
            blockers.append({
                "code": "ENTRY_POINT_MISSING",
                "detail": f"{root.path} has no entry-point source file",
            })
        if root.shape in ("gui_vcl", "gui_lcl", "gui_fmx"):
            blockers.append({
                "code": "GUI_SHAPE_DETECTED",
                "detail": (
                    f"{root.path} is a {root.shape} application; GUI "
                    "conversion is out of scope for the first release"
                ),
            })
    if unresolved_units:
        blockers.append({
            "code": "UNRESOLVED_UNITS",
            "detail": (
                f"{len(unresolved_units)} unit reference(s) could not be "
                "resolved inside the ingested input"
            ),
        })
    if compiler == "unknown":
        blockers.append({
            "code": "COMPILER_UNKNOWN",
            "detail": "no signal distinguishes FPC from Delphi",
        })
    if not has_project_files:
        blockers.append({
            "code": "NO_PROJECT_FILE",
            "detail": (
                "no .dproj/.lpi found: unit search paths and defines are "
                "source-directive only"
            ),
        })

    return {
        "blockers": blockers,
        "compiler": compiler,
        "compiler_evidence": {
            "delphi": sorted(set(delphi_evidence)),
            "fpc": sorted(set(fpc_evidence)),
            "note": (
                "derived from file extensions, dialects and directives; no "
                "compiler was invoked during discovery"
            ),
        },
        "defines": defines,
        "flags": flags,
        "modes": modes,
        # Heuristic by construction: naming a compiler from text is a
        # PARTIAL result, never a verified one.
        "status": "PARTIAL" if compiler != "unknown" else "UNKNOWN",
        "unit_search_paths": unit_paths,
    }
