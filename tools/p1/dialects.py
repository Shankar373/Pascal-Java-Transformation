"""Dialect, compiler-mode and unit-visibility knowledge (tasks C1–C3).

Three separate things are modelled here and deliberately not conflated:

**dialect** — the source dialect the file is written in (``delphi``,
    ``fpc``, ``turbo-pascal``, ``iso-7185``, ``unknown``);
**mode** — the compiler mode it must be compiled with (``objfpc``,
    ``delphi``, ``fpc``, ``tp``, ``iso``, ...).  IR invariant I3 makes mode
    *context*, never a verdict: the same construct is legal in one mode and
    illegal in another;
**framework** — the UI/data framework implied by the units it uses (``vcl``,
    ``lcl``, ``fmx``, ``none``, ``unknown``).

Evidence
--------

Every table below cites the P0 evidence file that established it, because a
capability state without an evidence file is exactly what
``docs/p0/FEASIBILITY_REPORT.md`` forbids:

* ``probes.txt`` P01-P18 — per-mode identifier visibility and the ``-Miso``
  acceptance fact;
* ``mode-claims.txt`` — the header-claim/actual-mode cross-check;
* the ``ppu`` scan at the end of ``probes.txt`` — where
  ``AssignFile``/``CloseFile`` are actually declared.

Nothing here runs a compiler: P1 records what P0 proved.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .plex import ScanResult

__all__ = [
    "ModeInfo",
    "MODE_TABLE",
    "SourceAnalysis",
    "analyse_source",
    "classify_unit",
    "UNIT_CATEGORIES",
]

# --------------------------------------------------------------------------
# C1 — the mode table
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ModeInfo:
    """One compiler mode and what P0 proved about it."""

    name: str
    fpc_flag: str
    #: ``True``/``False`` proven by a probe, ``None`` when never probed.
    result_visible: bool | None
    bare_assignfile_visible: bool | None
    evidence: str
    #: True when FPC accepts the flag even though ``fpc -h`` does not list it.
    accepted_despite_missing_from_help: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            "accepted_despite_missing_from_help": (
                self.accepted_despite_missing_from_help
            ),
            "bare_assignfile_visible": self.bare_assignfile_visible,
            "evidence": self.evidence,
            "fpc_flag": self.fpc_flag,
            "mode": self.name,
            "result_visible": self.result_visible,
        }


#: Canonical mode table.  ``None`` means "not probed in P0" and is reported as
#: ``UNKNOWN`` rather than guessed — an invented capability is worse than an
#: absent one.
MODE_TABLE: dict[str, ModeInfo] = {
    "fpc": ModeInfo(
        name="fpc",
        fpc_flag="-Mfpc",
        result_visible=False,
        bare_assignfile_visible=False,
        evidence="probes.txt P01, P06",
    ),
    "objfpc": ModeInfo(
        name="objfpc",
        fpc_flag="-Mobjfpc",
        result_visible=True,
        bare_assignfile_visible=True,
        evidence="probes.txt P03, P07, P11",
    ),
    "delphi": ModeInfo(
        name="delphi",
        fpc_flag="-Mdelphi",
        result_visible=True,
        bare_assignfile_visible=True,
        evidence="probes.txt P04, P08",
    ),
    "tp": ModeInfo(
        name="tp",
        fpc_flag="-Mtp",
        result_visible=False,
        bare_assignfile_visible=None,  # P0 probed Result only, not AssignFile
        evidence="probes.txt P02; AssignFile visibility not probed in -Mtp",
    ),
    "iso": ModeInfo(
        name="iso",
        fpc_flag="-Miso",
        result_visible=None,
        bare_assignfile_visible=None,
        evidence="probes.txt P18 (fpc 3.2.2 accepts -Miso although absent "
                 "from -h); no visibility probes run in -Miso",
        accepted_despite_missing_from_help=True,
    ),
    "macpas": ModeInfo(
        name="macpas",
        fpc_flag="-Mmacpas",
        result_visible=None,
        bare_assignfile_visible=None,
        evidence="not probed in P0",
    ),
    "extendedsyntax": ModeInfo(
        name="extendedsyntax",
        fpc_flag="-Mex",
        result_visible=None,
        bare_assignfile_visible=None,
        evidence="not probed in P0",
    ),
    "objective-pascal": ModeInfo(
        name="objective-pascal",
        fpc_flag="-Mobjfpc",
        result_visible=True,
        bare_assignfile_visible=True,
        evidence="probes.txt P03, P07 (same -Mobjfpc family)",
    ),
}

#: FPC ``-M`` flag → canonical mode name, for reading a command line back.
#: Two modes can share one flag (``-Mobjfpc`` is both the ``objfpc`` mode and
#: the ``objective-pascal`` family), so the canonical mode name wins: the
#: mapping must be a function of the flag, not of declaration order.
FLAG_TO_MODE: dict[str, str] = {}
for _mode_name, _mode_info in MODE_TABLE.items():
    _flag = _mode_info.fpc_flag.lower()
    if _flag not in FLAG_TO_MODE or _mode_name == _flag[2:]:
        FLAG_TO_MODE[_flag] = _mode_name
del _mode_name, _mode_info, _flag

# --------------------------------------------------------------------------
# C3 — unit visibility knowledge
# --------------------------------------------------------------------------

#: Category values a unit can be assigned.  Anything not listed here is
#: ``unresolved`` and becomes an unresolved edge with a reason.
UNIT_CATEGORIES: tuple[str, ...] = (
    "delphi-rtl",
    "fpc-rtl",
    "cross-rtl",
    "windows-platform",
    "unix-platform",
    "vcl",
    "lcl",
    "fmx",
    "database",
    "known-third-party",
    "unresolved",
)

_UNITS: dict[str, str] = {}


def _add(category: str, *names: str) -> None:
    for name in names:
        _UNITS[name.lower()] = category


# --- RTL present in both dialects -----------------------------------------
_add(
    "cross-rtl",
    "system", "sysutils", "classes", "math", "strutils", "dateutils",
    "variants", "typinfo", "sysinit", "objpas", "rtlconsts", "types",
    "character", "inifiles", "contnrs", "fgl", "registry", "masks",
    "generics.collections", "generics.defaults", "zip", "zstream",
    "streams", "files", "fileutil", "lazutf8", "lazfileutils",
)

# --- Delphi-flavoured RTL --------------------------------------------------
_add(
    "delphi-rtl",
    "system.sysutils", "system.classes", "system.math", "system.strutils",
    "system.dateutils", "system.variants", "system.typinfo", "system.types",
    "system.ioutils", "system.regexpr", "system.netencoding",
    "system.hash", "system.character", "system.rtti", "system.uitypes",
    "winapi.windows", "winapi.messages", "winapi.shellapi",
)

# --- FPC-flavoured RTL -----------------------------------------------------
_add(
    "fpc-rtl",
    "crt", "dos", "unix", "baseunix", "sockets", "ssockets", "getch",
    "fgl", "custapp", "custchart", "lazutils", "lazlogger", "fileutil",
    "laz2_xmlread", "laz2_dom", "laz2_ftpput", "fpimage", "fpreadpng",
    "fpwritepng", "fpreadjpeg", "fpwritejpeg", "fpimgreader", "graphs",
    "matrix", "dos", "sockets",
)

# --- Windows-only ----------------------------------------------------------
_add(
    "windows-platform",
    "windows", "messages", "shellapi", "activex", "comobj", "comserv",
    "ole2", "oleauto", "shlobj", "tlbimp3", "winconst",
)

# --- Unix-only -------------------------------------------------------------
_add(
    "unix-platform",
    "baseunix", "unix", "unixtype", "unixutil", "sockets", "ssockets",
    "netdb", "process", "cthreads",
)

# --- VCL -------------------------------------------------------------------
_add(
    "vcl",
    "forms", "controls", "graphics", "dialogs", "stdctrls", "extctrls",
    "comctrls", "menus", "buttons", "checklst", "gridsex", "grids",
    "mask", "toolwin", "imglist", "actnlist", "stdactns", "appvcl",
    "vcl.forms", "vcl.controls", "vcl.graphics", "vcl.dialogs",
    "vcl.stdctrls", "vcl.extctrls", "vcl.comctrls", "vcl.menus",
    "vcl.buttons", "vcl.actnlist", "vcl.imglist", "vcl.filectrl",
    "vcl.touch", "vcl.themes", "vcl.styles",
)

# --- LCL -------------------------------------------------------------------
_add(
    "lcl",
    "interfaces", "lclintf", "lcltype", "lclproc", "lmessages", "lclasses",
    "lcontrols", "lforms", "lstdctrls", "lextdctrls", "lcomctrls",
    "lmenus", "lbuttons", "ldialogs", "lgraph", "lresources", "lazcontrols",
    "lcl", "lazdialogs", "lazregions", "lazxmlconfig",
)

# --- FireMonkey ------------------------------------------------------------
_add(
    "fmx",
    "fmx.forms", "fmx.controls", "fmx.graphics", "fmx.dialogs",
    "fmx.stdctrls", "fmx.extctrls", "fmx.comctrls", "fmx.menus",
    "fmx.types", "fmx.platform", "fmx.objects", "fmx.layouts",
    "fmx.actnlist", "fmx.essentials",
)

# --- Database --------------------------------------------------------------
_add(
    "database",
    "db", "dbtables", "dbctrls", "dbgrids", "dbclient", "provider",
    "midas", "sqlexpr", "dbx", "dbexpress", "ado", "adodb", "oledb",
    "datamodu", "dbxcommon", "dbxdynalink", "dbxmysql", "dbxoracle",
    "dbxsqlite", "dbxsybaseasa", "dbxmssql", "firebird", "ibdatabase",
    "ibsql", "ibase", "fbintf", "sqldb", "sqldbtypes", "memdataset",
    "bufdataset", "zconnection", "zdataset", "zeosdb", "unidac",
    "myaccess", "odac", "psql", "data.db", "data.sqlexpr", "data.dbxcommon",
    "data.adodb", "data.dbclient", "fireDAC.comp.client",
    "firedac.comp.client", "firedac.phys.sqlite", "firedac.phys.pg",
    "firedac.phys.mysql", "firedac.phys.mssql", "firedac.phys.oracle",
)

# --- Widely used third-party libraries (identified, not integrated) --------
_add(
    "known-third-party",
    "indy", "idglobal", "idhttp", "idssl", "idstack", "synapse",
    "openssl", "opensslsockets", "fphttpclient", "fpweb", "fpjson",
    "jsonparser", "xmlread", "xmlwrite", "xpath", "dom", "sax",
    "htmlparser", "fasthtmlparser", "virtualtreeview", "virtualstringtree",
    "rxdbutils", "rxctrls", "rxdates", "rxsplit",
)

#: Units that imply a platform regardless of any ``uses`` context.
PLATFORM_UNITS: dict[str, str] = {
    "windows": "windows",
    "messages": "windows",
    "winapi.windows": "windows",
    "winapi.messages": "windows",
    "shellapi": "windows",
    "activex": "windows",
    "comobj": "windows",
    "ole2": "windows",
    "baseunix": "unix",
    "unix": "unix",
    "unixtype": "unix",
    "unixutil": "unix",
    "ssockets": "unix",
    "cthreads": "unix",
    "crt": "cross",  # CRT exists on both, but is console-specific
}

#: Units that imply a UI framework.
FRAMEWORK_UNITS: dict[str, str] = {}
for _name in _UNITS:
    if _UNITS[_name] in ("vcl", "lcl", "fmx"):
        FRAMEWORK_UNITS[_name] = _UNITS[_name]


def classify_unit(name: str) -> tuple[str, str]:
    """Classify a unit name → ``(category, matched_name)``.

    Tries the fully-qualified name first, then the last dotted segment, so
    ``System.SysUtils`` and ``SysUtils`` land in the same place.  An
    unrecognised unit returns ``("unresolved", "")`` — it is *not* assumed to
    be third-party, because "not in our table" is not evidence of anything.
    """

    lowered = name.strip().lower()
    if not lowered:
        return "unresolved", ""
    if lowered in _UNITS:
        return _UNITS[lowered], lowered
    if "." in lowered:
        tail = lowered.rsplit(".", 1)[1]
        if tail in _UNITS:
            return _UNITS[tail], tail
        # Namespace-qualified framework names: Vcl.*, FMX.*, Winapi.*
        head = lowered.split(".", 1)[0]
        if head in ("vcl", "vclx", "vclactnband", "vcltee"):
            return "vcl", lowered
        if head == "fmx":
            return "fmx", lowered
        if head in ("winapi", "win32"):
            return "windows-platform", lowered
        if head in ("system", "data", "firedac"):
            return "delphi-rtl", lowered
        if head in ("lcl", "laz", "fpc"):
            return "lcl", lowered
    return "unresolved", ""


# --------------------------------------------------------------------------
# Per-source analysis
# --------------------------------------------------------------------------


@dataclass
class SourceAnalysis:
    """What one source file reveals about dialect, mode and framework."""

    path: str
    #: Declared unit/program name, when the file declares one.
    declared_name: str = ""
    #: ``unit`` | ``program`` | ``library`` | ``package`` | ``unknown``.
    source_kind: str = "unknown"
    dialect: str = "unknown"
    mode: str = "unknown"
    framework: str = "unknown"
    dialect_evidence: list[dict[str, object]] = field(default_factory=list)
    mode_evidence: list[dict[str, object]] = field(default_factory=list)
    framework_evidence: list[dict[str, object]] = field(default_factory=list)
    confidence: str = "low"
    #: Directives that carry profile state (R/Q/H/J/APPTYPE/MODE/DEFINE...).
    directives: dict[str, list[str]] = field(default_factory=dict)
    #: ``True`` when the declared name disagrees with the file name (P13).
    name_mismatch: bool = False
    diagnostics: list[dict[str, object]] = field(default_factory=list)


def _evidence(text: str, line: int | None = None, column: int | None = None,
              source: str = "source") -> dict[str, object]:
    out: dict[str, object] = {"evidence": text, "source": source}
    if line is not None:
        out["line"] = line
    if column is not None:
        out["column"] = column
    return out


def analyse_source(scan: ScanResult, path: str) -> SourceAnalysis:
    """Derive dialect/mode/framework for one scanned source file.

    Pure function of the scan result: no compiler, no network, no clock.
    """

    analysis = SourceAnalysis(path=path)
    lower_path = path.lower()

    # --- declared kind and name ------------------------------------------
    tokens = scan.tokens
    for index, token in enumerate(tokens):
        if token.kind != "ident":
            continue
        low = token.lower
        if low in ("unit", "program", "library", "package"):
            # The next identifier is the declared name (unless it is a
            # directive-supplied construct we do not model).
            if index + 1 < len(tokens):
                nxt = tokens[index + 1]
                if nxt.kind == "ident":
                    analysis.source_kind = low
                    analysis.declared_name = nxt.text
                    break

    # Unit name must equal the file name (probes.txt P13: mismatch rejected).
    if analysis.source_kind == "unit" and analysis.declared_name:
        stem = lower_path.rsplit("/", 1)[-1]
        stem = stem.rsplit(".", 1)[0] if "." in stem else stem
        if stem != analysis.declared_name.lower():
            analysis.name_mismatch = True
            analysis.diagnostics.append(
                {
                    "code": "UNIT_NAME_MISMATCH",
                    "message": (
                        f"declared unit {analysis.declared_name!r} does not "
                        f"match file name {stem!r}; FPC rejects this "
                        "(probes.txt P13)"
                    ),
                    "line": 1,
                    "column": 1,
                }
            )

    # --- directives ------------------------------------------------------
    for directive in scan.directives:
        analysis.directives.setdefault(directive.name, []).append(
            directive.argument
        )

    mode_directives = [
        d for d in scan.directives if d.name in ("MODE", "MODESWITCH")
    ]
    if mode_directives:
        first = mode_directives[0]
        raw = first.argument.strip().lower().split()[0] if first.argument else ""
        canonical = raw.replace("objective-pascal", "objective-pascal")
        if canonical in MODE_TABLE:
            analysis.mode = canonical
        elif canonical == "objfpc":
            analysis.mode = "objfpc"
        analysis.mode_evidence.append(
            _evidence(
                f"{{${first.name} {first.argument}}}",
                first.line,
                first.column,
            )
        )

    # --- dialect ---------------------------------------------------------
    dialect_hits: list[tuple[str, dict[str, object]]] = []

    if mode_directives:
        first = mode_directives[0]
        arg = first.argument.strip().lower()
        if arg.startswith("delphi"):
            dialect_hits.append(("delphi", _evidence(
                f"{{$MODE {first.argument}}}", first.line, first.column)))
        elif arg in ("objfpc", "objective-pascal", "extendedsyntax"):
            dialect_hits.append(("fpc", _evidence(
                f"{{$MODE {first.argument}}}", first.line, first.column)))
        elif arg == "tp":
            dialect_hits.append(("turbo-pascal", _evidence(
                f"{{$MODE {first.argument}}}", first.line, first.column)))
        elif arg == "iso":
            dialect_hits.append(("iso-7185", _evidence(
                f"{{$MODE {first.argument}}}", first.line, first.column)))

    extension_map = {
        ".dpr": "delphi",
        ".dproj": "delphi",
        ".dpk": "delphi",
        ".dfm": "delphi",
        ".pas": "",
        ".pp": "fpc",
        ".lpr": "fpc",
        ".lpi": "fpc",
        ".lpk": "fpc",
        ".lfm": "fpc",
        ".inc": "",
    }
    for suffix, dialect in extension_map.items():
        if lower_path.endswith(suffix) and dialect:
            dialect_hits.append((
                dialect,
                _evidence(f"file extension {suffix}", source="extension"),
            ))
            break

    # Unit-name evidence: a `unit X;` file is a unit in whichever dialect
    # the other signals point at; it adds no signal by itself.
    if dialect_hits:
        # Strongest signal wins: mode directive > extension.
        dialect_hits.sort(key=lambda pair: 0 if pair[1].get("line") else 1)
        analysis.dialect = dialect_hits[0][0]
        analysis.dialect_evidence.extend(h for _, h in dialect_hits)

    # --- framework -------------------------------------------------------
    framework_hits: dict[str, dict[str, object]] = {}
    for token in tokens:
        if token.kind != "ident":
            continue
        category, matched = classify_unit(token.text)
        if category in ("vcl", "lcl", "fmx") and matched:
            # Only a `uses`-position identifier counts; a mere mention in a
            # string or comment cannot happen (those are not ident tokens),
            # but a type reference can — which is still legitimate evidence.
            framework_hits.setdefault(category, _evidence(
                f"unit/framework reference {token.text!r}",
                token.line,
                token.column,
            ))
    if framework_hits:
        # Prefer the framework with the most distinct references.
        counts: dict[str, int] = {}
        for token in tokens:
            if token.kind == "ident":
                category, _ = classify_unit(token.text)
                if category in framework_hits:
                    counts[category] = counts.get(category, 0) + 1
        best = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        analysis.framework = best
        analysis.framework_evidence.append(framework_hits[best])
    else:
        analysis.framework = "none"

    # --- confidence ------------------------------------------------------
    if mode_directives or analysis.dialect != "unknown":
        analysis.confidence = "high"
    elif framework_hits or analysis.source_kind != "unknown":
        analysis.confidence = "medium"
    else:
        analysis.confidence = "low"

    return analysis


def visibility_for(mode: str) -> dict[str, object]:
    """C3: what a bare (unqualified) symbol resolves to in *mode*."""

    info = MODE_TABLE.get(mode)
    if info is None:
        return {
            "mode": mode,
            "result_visible": "UNKNOWN",
            "bare_assignfile_visible": "UNKNOWN",
            "evidence": "mode not present in the P0 mode table",
        }

    def tri(value: bool | None) -> str:
        if value is None:
            return "UNKNOWN"
        return "SUPPORTED" if value else "UNSUPPORTED"

    return {
        "mode": info.name,
        "fpc_flag": info.fpc_flag,
        "result_visible": tri(info.result_visible),
        "bare_assignfile_visible": tri(info.bare_assignfile_visible),
        "assignfile_declaring_unit": "ObjPas",
        "assignfile_evidence": (
            "probes.txt ppu scan: objpas.ppu declares AssignFile=True, "
            "system.ppu declares AssignFile=False; P09/P11 confirm"
        ),
        "evidence": info.evidence,
    }
