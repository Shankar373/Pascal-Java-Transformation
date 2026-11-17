"""Stage 1 external-integration detection (HTTP, SOAP, FTP, mail, COM, ...).

Unit names are accepted only from real ``uses``/``requires`` clauses and from
component class tokens or form-definition ``object X: TClass`` lines - never
from a bare identifier, a comment or a string - mirroring ``metadata.py``.
String literals feed *endpoints only* (URLs, hosts, ports, COM ProgIDs, queue
names) and are credential-redacted, query-stripped and capped.

Detection is ``PARTIAL`` evidence that the application talks to a technology.
It says nothing about whether the platform can drive it.

This module is also the public home of the other two Stage 1 dependency
detectors, :func:`detect_libraries` and :func:`detect_runtime_dependencies`
(implemented in ``libraries.py`` and ``runtimedeps.py`` to keep each file
small).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterator

from .evutil import (
    MAX_ENDPOINTS,
    Literal,
    bounded,
    first_unique,
    literals_of,
    make_evidence,
    numbered_lines,
    sorted_files,
    unquote,
)
from .findings import Evidence, IntegrationFinding
from .knowledge import (
    CLASS_RULES,
    IDENT_RULES,
    INTEGRATION_RULES,
    IntegrationRule,
    ignored_url_host,
)
from .libraries import detect_libraries
from .model import AnalysedFile
from .plex import Token
from .runtimedeps import detect_runtime_dependencies

__all__ = [
    "detect_integrations",
    "detect_libraries",
    "detect_runtime_dependencies",
]

_EVIDENCE_POOL = 100
_ENDPOINT_POOL = 400
_NETWORK = frozenset({
    "http-client", "ftp", "email", "socket", "messaging", "ldap",
    "soap-webservice", "rpc",
})
_HOST_PROPS = frozenset({
    "host", "hostname", "server", "servername", "remotehost", "smtphost",
    "pophost", "address", "remoteaddress",
})
_ADDRESS_NEEDS_TYPE = frozenset({"address", "remoteaddress"})
_CLASS_RE_RULES = tuple(r for r in INTEGRATION_RULES if r.class_re)
Key = tuple[str, str]

_SCHEMES = {
    "http": "http-client", "https": "http-client", "ws": "socket",
    "wss": "socket", "ftp": "ftp", "ftps": "ftp", "sftp": "ftp",
    "ldap": "ldap", "ldaps": "ldap", "amqp": "messaging",
    "amqps": "messaging", "mqtt": "messaging", "mqtts": "messaging",
    "stomp": "messaging", "smtp": "email", "smtps": "email",
    "pop3": "email", "imap": "email", "imaps": "email",
}
_URL = re.compile(r"(?i)\b([a-z][a-z0-9+.-]{1,15})://([^\s'\"<>)\]\\]+)")
_HOST = re.compile(
    r"^(?:\d{1,3}(?:\.\d{1,3}){3}|[A-Za-z0-9](?:[A-Za-z0-9._-]{0,251}"
    r"[A-Za-z0-9])?)(?::\d{1,5})?$"
)
_SOAPISH = re.compile(r"(?i)\.asmx|\.svc\b|wsdl|/soap")
_QUEUE = re.compile(
    r"(?i)^(?:\.|[\w.-]+)\\private\$\\[\w.-]+$|^FormatName:\S+$")
_COM_PORT = re.compile(r"(?i)^(?:\\\\\.\\)?COM\d{1,3}$")
_UNC_SHARE = re.compile(r"^(\\\\[A-Za-z0-9_.$-]+\\[A-Za-z0-9_.$-]+)")
_SCHTASKS = re.compile(r"(?i)\bschtasks(?:\.exe)?\b")
_SQL_SCHEDULER = re.compile(
    r"(?i)\bDBMS_SCHEDULER\b|\bDBMS_JOB\b|\bsp_add_job\b|\bON\s+SCHEDULE\b")
_PROGID = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+(?:\.\d+)*$")
_DFM_OBJECT = re.compile(
    r"^\s*(?:object|inherited|inline)\s+(\w+)\s*:\s*(\w+)", re.I)
_DFM_ITEM = re.compile(r"^\s*item\s*$", re.I)
_DFM_END = re.compile(r"^\s*end\b", re.I)
_DFM_PROP = re.compile(r"^\s*(\w+)\s*=\s*(.*)$")
_DFM_STRING = re.compile(r"'((?:[^']|'')*)'")
_TEMPLATE_FILES = {
    ".fr3": ("reporting", "FastReport", "high"),
    ".frf": ("reporting", "FastReport", "high"),
    ".lrf": ("reporting", "LazReport", "high"),
    ".rtm": ("reporting", "ReportBuilder", "high"),
    ".rav": ("reporting", "Rave", "high"),
    ".qrp": ("reporting", "QuickReport", "high"),
    ".rpt": ("reporting", "Crystal Reports", "low"),
}
_PROGID_RULES: tuple[tuple[re.Pattern[str], Key], ...] = tuple(
    (re.compile(p, re.I), key) for p, key in (
        (r"^(?:msxml2?\.|microsoft\.xmlhttp)", ("http-client", "MSXML")),
        (r"^winhttp\.", ("http-client", "WinHTTP")),
        (r"^mssoap\.", ("soap-webservice", "MS SOAP Toolkit")),
        (r"^outlook\.", ("email", "Outlook (COM)")),
        (r"^cdo\.", ("email", "CDO (COM)")),
        (r"^msmq\.", ("messaging", "MSMQ")),
        (r"^schedule\.", ("scheduled-job", "Task Scheduler")),
    )
)


@dataclass
class _Acc:
    """Mutable per-key accumulator (never escapes this module)."""

    unit: bool = False
    code: bool = False
    literal: bool = False
    evidence: list[Evidence] = field(default_factory=list)
    endpoints: list[tuple[str, int, int, str]] = field(default_factory=list)

    def note(self, ev: Evidence) -> None:
        if len(self.evidence) < _EVIDENCE_POOL:
            self.evidence.append(ev)

    def endpoint(self, ev: Evidence, value: str) -> None:
        if len(self.endpoints) < _ENDPOINT_POOL:
            self.endpoints.append((ev.file, ev.line, ev.column, value))
        self.note(ev)


class _Hits:
    """Per-file hits keyed by ``(category, technology)``."""

    def __init__(self) -> None:
        self.by_key: dict[Key, _Acc] = {}

    def acc(self, key: Key) -> _Acc:
        return self.by_key.setdefault(key, _Acc())

    def add(self, key: Key, kind: str, ev: Evidence) -> None:
        acc = self.acc(key)
        setattr(acc, kind, True)
        acc.note(ev)

    def keys_in(self, categories: frozenset[str] | set[str]) -> list[Key]:
        return sorted(k for k in self.by_key if k[0] in categories)


def _key(rule: IntegrationRule) -> Key:
    return (rule.category, rule.technology)


@lru_cache(maxsize=20_000)
def _rules_for_unit(low: str) -> tuple[IntegrationRule, ...]:
    return tuple(r for r in INTEGRATION_RULES if r.match_unit(low))


@lru_cache(maxsize=50_000)
def _rules_for_ident(low: str) -> tuple[IntegrationRule, ...]:
    found: list[IntegrationRule] = list(CLASS_RULES.get(low, ()))
    found.extend(IDENT_RULES.get(low, ()))
    if low.startswith("t"):
        found.extend(r for r in _CLASS_RE_RULES if r.match_class(low))
    return tuple(dict.fromkeys(found))


# --------------------------------------------------------------------------
# URLs and hosts
# --------------------------------------------------------------------------


def _clean_url(scheme: str, rest: str) -> tuple[str, str] | None:
    """``(category, endpoint)`` for a URL literal, or ``None`` to ignore it."""

    category = _SCHEMES.get(scheme.lower())
    if category is None:
        return None
    authority, sep, tail = rest.partition("/")
    for cut in "?#":
        authority = authority.split(cut, 1)[0]
    path = tail.split("?", 1)[0].split("#", 1)[0] if sep else ""
    host = authority.rsplit("@", 1)[-1]
    if not _HOST.match(host) or ignored_url_host(host):
        return None
    path = path.rstrip(".,;:'\")")
    endpoint = f"{scheme.lower()}://{host}" + (f"/{path}" if path else "")
    if category == "http-client" and _SOAPISH.search(rest):
        category = "soap-webservice"
    return category, endpoint[:200]


def _urls_in(text: str) -> Iterator[tuple[str, str]]:
    if "://" not in text:
        return
    for match in _URL.finditer(text):
        cleaned = _clean_url(match.group(1), match.group(2))
        if cleaned:
            yield cleaned


def _valid_host(value: str) -> bool:
    return bool(value) and bool(_HOST.match(value)) and not value.isdigit()


# --------------------------------------------------------------------------
# Pascal sources
# --------------------------------------------------------------------------


def _variable_classes(tokens: list[Token]) -> dict[str, str]:
    """``var X: TCls`` / ``X := TCls.Create`` → ``{x: tcls}`` (lower-case)."""

    out: dict[str, str] = {}
    for i in range(2, len(tokens)):
        tok = tokens[i]
        if tok.kind != "ident" or not _rules_for_ident(tok.lower):
            continue
        before = tokens[i - 1].text
        if before == ":" and tokens[i - 2].kind == "ident":
            j = i - 2
            while j >= 0 and tokens[j].kind == "ident":
                out[tokens[j].lower] = tok.lower
                if j >= 1 and tokens[j - 1].text == ",":
                    j -= 2
                else:
                    break
        elif before == ":=" and tokens[i - 2].kind == "ident":
            out[tokens[i - 2].lower] = tok.lower
    return out


def _scan_units(item: AnalysedFile, hits: _Hits) -> None:
    for clause in item.scan.uses:  # type: ignore[union-attr]
        for unit in clause.items:
            for rule in _rules_for_unit(unit.name.lower()):
                hits.add(_key(rule), "unit", make_evidence(
                    item.path, unit.line, unit.column,
                    f"`{clause.kind}` clause names unit {unit.name}"))


def _scan_idents(item: AnalysedFile, hits: _Hits) -> None:
    seen: set[str] = set()
    for tok in item.scan.tokens:  # type: ignore[union-attr]
        if tok.kind != "ident" or tok.lower in seen:
            continue
        seen.add(tok.lower)
        for rule in _rules_for_ident(tok.lower):
            hits.add(_key(rule), "code", make_evidence(
                item.path, tok.line, tok.column, f"reference to {tok.text}"))


def _string_after(tokens: list[Token], index: int, limit: int = 10
                  ) -> Token | None:
    """First string literal after *index* within one statement."""

    for tok in tokens[index + 1:index + 1 + limit]:
        if tok.text == ";":
            return None
        if tok.kind == "string" and tok.text.startswith("'"):
            return tok
    return None


def _number_after_assign(tokens: list[Token], index: int) -> int | None:
    """``Port := 587`` → 587 for the ``Port`` ident at *index*."""

    if index + 2 < len(tokens) and tokens[index + 1].text == ":=":
        nxt = tokens[index + 2]
        if nxt.kind == "number" and nxt.text.isdigit() and \
                int(nxt.text) <= 65535:
            return int(nxt.text)
    return None


def _paired_port(tokens: list[Token], start: int, receiver: str
                 ) -> int | None:
    for j in range(start + 1, min(start + 30, len(tokens) - 2)):
        tok = tokens[j]
        if tok.kind == "ident" and tok.lower == "port" and \
                tokens[j - 1].text == "." and j >= 2 and \
                tokens[j - 2].lower == receiver:
            return _number_after_assign(tokens, j)
    return None


def _host_targets(rules: tuple[IntegrationRule, ...], host: str,
                  hits: _Hits) -> list[Key]:
    keys = [_key(r) for r in rules if r.category in _NETWORK]
    if keys:
        return keys
    low = host.lower()
    if low.startswith("ftp"):
        return hits.keys_in({"ftp"})
    if low.startswith(("smtp", "mail", "pop", "imap", "mx")):
        return hits.keys_in({"email"})
    return hits.keys_in(_NETWORK)


def _scan_host_assignments(item: AnalysedFile, var_class: dict[str, str],
                           hits: _Hits) -> None:
    tokens = item.scan.tokens  # type: ignore[union-attr]
    for i in range(2, len(tokens) - 2):
        tok = tokens[i]
        if tok.kind != "ident" or tokens[i - 1].text != "." or \
                tokens[i + 1].text != ":=":
            continue
        receiver = tokens[i - 2].lower
        rules = _rules_for_ident(var_class.get(receiver, ""))
        if tok.lower in _HOST_PROPS:
            value = tokens[i + 2]
            if value.kind != "string" or not value.text.startswith("'"):
                continue
            if tok.lower in _ADDRESS_NEEDS_TYPE and not rules:
                continue
            host = unquote(value.text).strip()
            if not _valid_host(host):
                continue
            port = _paired_port(tokens, i + 2, receiver)
            endpoint = f"{host}:{port}" if port and ":" not in host else host
            ev = make_evidence(item.path, value.line, value.column,
                               f"{tok.text} assigned {endpoint}")
            for key in _host_targets(rules, host, hits):
                hits.acc(key).endpoint(ev, endpoint)
        elif tok.lower == "port":
            port = _number_after_assign(tokens, i)
            if port and any(r.listener for r in rules):
                ev = make_evidence(item.path, tok.line, tok.column,
                                   f"Port assigned {port}")
                for rule in rules:
                    if rule.listener:
                        hits.acc(_key(rule)).endpoint(ev, f"port:{port}")


def _progid_key(progid: str) -> Key:
    for pattern, key in _PROGID_RULES:
        if pattern.match(progid):
            return key
    return ("com-ole", "COM/OLE")


def _scan_com_calls(item: AnalysedFile, hits: _Hits) -> None:
    tokens = item.scan.tokens  # type: ignore[union-attr]
    for i, tok in enumerate(tokens):
        if tok.kind != "ident":
            continue
        if tok.lower in ("createoleobject", "getactiveoleobject"):
            lit = _string_after(tokens, i)
            progid = unquote(lit.text).strip() if lit else ""
            if lit and _PROGID.match(progid):
                ev = make_evidence(item.path, lit.line, lit.column,
                                   f"{tok.text}('{progid}')")
                hits.acc(_progid_key(progid)).endpoint(ev, progid)
                hits.acc(_progid_key(progid)).literal = True
        elif tok.lower == "createremotecomobject":
            lit = _string_after(tokens, i)
            machine = unquote(lit.text).strip() if lit else ""
            if lit and _valid_host(machine):
                ev = make_evidence(item.path, lit.line, lit.column,
                                   f"{tok.text} on {machine}")
                hits.acc(("dcom", "DCOM")).endpoint(ev, machine)


def _scan_pascal(item: AnalysedFile, hits: _Hits) -> None:
    _scan_units(item, hits)
    _scan_idents(item, hits)
    _scan_host_assignments(
        item, _variable_classes(item.scan.tokens), hits)  # type: ignore
    _scan_com_calls(item, hits)


# --------------------------------------------------------------------------
# Form definitions, scripts and file names
# --------------------------------------------------------------------------


@dataclass
class _Frame:
    name: str
    cls: str
    host: tuple[str, int, int] | None = None
    port: int | None = None


def _flush_frame(path: str, frame: _Frame, hits: _Hits) -> None:
    rules = _rules_for_ident(frame.cls.lower())
    if frame.host:
        host, line, column = frame.host
        endpoint = f"{host}:{frame.port}" if frame.port else host
        ev = make_evidence(path, line, column,
                           f"{frame.name}.Host = {endpoint}")
        for key in _host_targets(rules, host, hits):
            hits.acc(key).endpoint(ev, endpoint)
    elif frame.port and any(r.listener for r in rules):
        ev = make_evidence(path, 1, 1, f"{frame.name}.Port = {frame.port}")
        for rule in rules:
            if rule.listener:
                hits.acc(_key(rule)).endpoint(ev, f"port:{frame.port}")


def _scan_dfm(item: AnalysedFile, text: str, hits: _Hits) -> None:
    stack: list[_Frame] = []
    for number, line in numbered_lines(text):
        obj = _DFM_OBJECT.match(line)
        if obj:
            frame = _Frame(obj.group(1), obj.group(2))
            stack.append(frame)
            for rule in _rules_for_ident(frame.cls.lower()):
                hits.add(_key(rule), "code", make_evidence(
                    item.path, number, line.index(obj.group(0).strip()[0]) + 1,
                    f"component {frame.cls} declared as {frame.name}"))
            continue
        if _DFM_ITEM.match(line):
            stack.append(_Frame("", ""))
        elif _DFM_END.match(line):
            if stack:
                _flush_frame(item.path, stack.pop(), hits)
        elif stack:
            _dfm_property(stack[-1], number, line)
    while stack:
        _flush_frame(item.path, stack.pop(), hits)


def _dfm_property(frame: _Frame, number: int, line: str) -> None:
    prop = _DFM_PROP.match(line)
    if not prop or not frame.cls:
        return
    name, value = prop.group(1).lower(), prop.group(2).strip()
    if name in _HOST_PROPS:
        string = _DFM_STRING.search(value)
        if string and _valid_host(string.group(1).strip()):
            frame.host = (string.group(1).strip(), number,
                          prop.start(2) + 1)
    elif name == "port" and value.isdigit() and int(value) <= 65535:
        frame.port = int(value)


def _scan_script_lines(item: AnalysedFile, text: str, hits: _Hits) -> None:
    for number, line in numbered_lines(text):
        stripped = line.strip()
        if not stripped:
            continue
        if item.cls == "build_script" and _SCHTASKS.search(stripped):
            hits.add(("scheduled-job", "schtasks"), "literal",
                     make_evidence(item.path, number, 1, stripped))
        elif item.cls == "sql" and _SQL_SCHEDULER.search(stripped):
            hits.add(("scheduled-job", "SQL scheduler"), "literal",
                     make_evidence(item.path, number, 1, stripped))


def _scan_file_names(item: AnalysedFile, hits: _Hits) -> None:
    lower = item.path.lower()
    name = lower.rsplit("/", 1)[-1]
    ext = name[name.rfind("."):] if "." in name else ""
    if ext in _TEMPLATE_FILES:
        category, tech, _ = _TEMPLATE_FILES[ext]
        hits.add((category, tech), "literal", make_evidence(
            item.path, 1, 1, f"report template file ({ext})"))
    if name == "crontab" or ext == ".cron":
        hits.add(("scheduled-job", "cron"), "literal", make_evidence(
            item.path, 1, 1, "cron schedule file present"))
    if ext == ".ocx":
        hits.add(("com-ole", "COM/OLE"), "literal", make_evidence(
            item.path, 1, 1, "ActiveX control file present"))


def _attach_url(item: AnalysedFile, lit: Literal, category: str,
                endpoint: str, hits: _Hits) -> None:
    ev = make_evidence(item.path, lit.line, lit.column,
                       f"URL literal {endpoint}")
    keys = hits.keys_in({category})
    if not keys:
        keys = [(category, "URL literal")]
        hits.acc(keys[0]).literal = True
    for key in keys:
        hits.acc(key).endpoint(ev, endpoint)


def _special_literal(item: AnalysedFile, lit: Literal, hits: _Hits) -> None:
    """Queue names, COM port names and UNC shares (whole-literal matches)."""

    text = lit.text.strip()
    for pattern, key in ((_QUEUE, ("messaging", "MSMQ")),
                         (_COM_PORT, ("serial-port", "Serial port literal"))):
        if pattern.match(text):
            ev = make_evidence(item.path, lit.line, lit.column,
                               f"literal {text}")
            acc = hits.acc(key)
            acc.literal = True
            acc.endpoint(ev, text)
    share = _UNC_SHARE.match(text)
    if share:
        ev = make_evidence(item.path, lit.line, lit.column,
                           f"UNC share {share.group(1)}")
        acc = hits.acc(("file-exchange", "UNC share"))
        acc.literal = True
        acc.endpoint(ev, share.group(1))


def _scan_literals(item: AnalysedFile, text_of: dict[str, str],
                   hits: _Hits) -> None:
    # Resolve URLs after every technology hit of the file exists, so a URL
    # attaches to Indy/SOAP/... rather than inventing a generic finding.
    for lit in literals_of(item, text_of):
        for category, endpoint in _urls_in(lit.text):
            _attach_url(item, lit, category, endpoint, hits)
        if item.scan is not None:
            _special_literal(item, lit, hits)
        if item.scan is not None and _SCHTASKS.search(lit.text):
            hits.add(("scheduled-job", "schtasks"), "literal",
                     make_evidence(item.path, lit.line, lit.column,
                                   lit.text))


def _scan_item(item: AnalysedFile, text_of: dict[str, str]) -> _Hits:
    hits = _Hits()
    text = text_of.get(item.path)
    if item.scan is not None:
        _scan_pascal(item, hits)
    elif item.cls == "ui_definition" and text:
        _scan_dfm(item, text, hits)
    elif item.cls in ("build_script", "sql") and text:
        _scan_script_lines(item, text, hits)
    _scan_file_names(item, hits)
    _scan_literals(item, text_of, hits)
    return hits


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def _confidence(acc: _Acc) -> str:
    if acc.unit and (acc.code or acc.endpoints):
        return "high"
    return "medium" if acc.unit else "low"


def detect_integrations(
    analysed: list[AnalysedFile], text_of: dict[str, str]
) -> list[IntegrationFinding]:
    """External integrations, with endpoints (credentials redacted, capped).

    Findings are keyed by ``(category, technology)`` across the whole input
    and sorted by that key; evidence is capped at 25 entries and endpoints at
    20, keeping the first by ``(file, line)``.
    """

    merged: dict[Key, _Acc] = {}
    for item in sorted_files(analysed):
        for key, acc in _scan_item(item, text_of or {}).by_key.items():
            target = merged.setdefault(key, _Acc())
            target.unit |= acc.unit
            target.code |= acc.code
            target.literal |= acc.literal
            target.evidence.extend(acc.evidence)
            target.endpoints.extend(acc.endpoints)
    findings: list[IntegrationFinding] = []
    for key in sorted(merged):
        acc = merged[key]
        evidence = bounded(acc.evidence)
        if not evidence:  # pragma: no cover - every hit records evidence
            continue
        endpoints = first_unique(
            (e for *_, e in sorted(acc.endpoints)), MAX_ENDPOINTS)
        findings.append(IntegrationFinding(
            category=key[0],
            technology=key[1],
            endpoints=endpoints,
            evidence=evidence,
            confidence=_confidence(acc),
            status="PARTIAL",
        ))
    return findings
