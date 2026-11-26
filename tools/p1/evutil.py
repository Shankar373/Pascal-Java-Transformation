"""Shared helpers for the Stage 1 detectors: bounded, redacted evidence.

Every Stage 1 detector (inventory, integrations, libraries, runtime
dependencies) obeys the same output rules, so the rules live here once:

* **Bounded.**  A finding carries at most :data:`MAX_EVIDENCE` evidence
  entries, endpoints are capped at :data:`MAX_ENDPOINTS`, and a detector
  never reads more than :data:`MAX_TEXT_CHARS` characters of one file or
  :data:`MAX_LINE_CHARS` of one line.  When a cap bites, the *first* entries
  by ``(file, line, column)`` are kept - never an arbitrary subset.
* **Redacted.**  Every excerpt passes through :func:`redact_text`, which
  extends ``metadata._redact`` with URL user-info, secret-shaped assignments
  and query strings, so a password literal can never reach an artefact.
* **Deterministic.**  Nothing here depends on dictionary order, clocks or
  absolute paths.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Iterator, Sequence

from .findings import Evidence
from .metadata import _redact
from .model import AnalysedFile

__all__ = [
    "MAX_EVIDENCE",
    "MAX_ENDPOINTS",
    "MAX_REFERENCES",
    "MAX_FINDINGS_PER_KIND",
    "MAX_TEXT_CHARS",
    "MAX_LINE_CHARS",
    "Literal",
    "redact_text",
    "make_evidence",
    "bounded",
    "first_unique",
    "numbered_lines",
    "unquote",
    "pascal_literals",
    "dfm_literals",
    "text_literals",
    "literals_of",
    "line_of",
    "sorted_files",
]

MAX_EVIDENCE = 25
MAX_ENDPOINTS = 20
MAX_REFERENCES = 50
MAX_FINDINGS_PER_KIND = 500
MAX_TEXT_CHARS = 2_000_000
MAX_LINE_CHARS = 2000
MAX_LINES = 100_000
MAX_LITERALS = 50_000
EVIDENCE_TEXT_CHARS = 120

_URL_USERINFO = re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s'\"@]+@")
_SECRET_WORDS = (
    r"password|passwd|pwd|passphrase|secret|token|apikey|api_key|api-key|"
    r"accesskey|access_key|private[_-]?key|credential"
)
_SECRET_ASSIGN = re.compile(
    rf"(?i)(\b[\w.-]*(?:{_SECRET_WORDS})[\w.-]*\s*(?::=|=|:)\s*)"
    r"(?:\"[^\"]*\"|'[^']*'|[^\s;,\"']+)"
)
_SECRET_INDEXED = re.compile(
    rf"(?i)(['\"][\w .-]*(?:{_SECRET_WORDS})[\w .-]*['\"]\s*\]?\s*"
    r"(?::=|=)\s*)'[^']*'"
)
_USER_ASSIGN = re.compile(
    r"(?i)(\b(?:user[_ ]?name|user[_ ]?id|uid|login)\s*=\s*)[^;,\s\"']+"
)
#: Substring probes (linear, C speed) that gate the heavier patterns above.
_SECRET_PROBES = (
    "password", "passwd", "pwd", "passphrase", "secret", "token", "apikey",
    "api_key", "api-key", "accesskey", "access_key", "private", "credential",
)
_REDACT_PROBES = _SECRET_PROBES + ("user", "uid", "api key", "api  key")


def _mentions(text: str, probes: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(probe in low for probe in probes)
_SPACE_RUN = re.compile(r"\s+")


def redact_text(text: str) -> str:
    """Strip credentials from *text* (superset of ``metadata._redact``)."""

    out = text
    if "=" in out and _mentions(out, _REDACT_PROBES):
        out = _redact(out)  # 12 compiled-on-demand patterns: gate it
    if "://" in out:
        out = _URL_USERINFO.sub(r"\1<redacted>@", out)
    if _mentions(out, _SECRET_PROBES):
        # The quadratic-prone patterns only run on lines that can matter.
        out = _SECRET_INDEXED.sub(r"\1'<redacted>'", out)
        out = _SECRET_ASSIGN.sub(r"\1<redacted>", out)
    if "=" in out:
        out = _USER_ASSIGN.sub(r"\1<redacted>", out)
    return out


def make_evidence(file: str, line: int, column: int, text: str) -> Evidence:
    """A located, redacted, length-bounded evidence entry."""

    excerpt = _SPACE_RUN.sub(" ", redact_text(text[:MAX_LINE_CHARS])).strip()
    return Evidence(
        file=file,
        line=max(int(line), 0),
        column=max(int(column), 0),
        text=excerpt[:EVIDENCE_TEXT_CHARS],
    )


def bounded(
    evidence: Iterable[Evidence], cap: int = MAX_EVIDENCE
) -> tuple[Evidence, ...]:
    """De-duplicate, sort by location and keep the first *cap* entries."""

    unique = {(e.file, e.line, e.column, e.text): e for e in evidence}
    ordered = sorted(unique.items(), key=lambda pair: pair[0])
    return tuple(e for _, e in ordered[:cap])


def first_unique(values: Iterable[str], cap: int) -> tuple[str, ...]:
    """The first *cap* distinct values, in encounter order."""

    seen: dict[str, None] = {}
    for value in values:
        if value not in seen:
            seen[value] = None
            if len(seen) >= cap:
                break
    return tuple(seen)


def numbered_lines(text: str) -> Iterator[tuple[int, str]]:
    """``(line_number, line)`` pairs, bounded in lines and line length.

    Only ``\\n`` separates lines (so numbers agree with editors), and a lone
    ``\\r`` is stripped from the end.
    """

    if len(text) > MAX_TEXT_CHARS:
        text = text[:MAX_TEXT_CHARS]
    for number, line in enumerate(text.split("\n"), 1):
        if number > MAX_LINES:
            return
        yield number, line.rstrip("\r")[:MAX_LINE_CHARS]


def line_of(text: str, needle: str) -> int:
    """1-based line of the first occurrence of *needle* (1 when absent)."""

    index = text.find(needle, 0, MAX_TEXT_CHARS)
    return text.count("\n", 0, index) + 1 if index >= 0 else 1


# --------------------------------------------------------------------------
# String literals
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Literal:
    """One string literal (or config line) with its location."""

    file: str
    line: int
    column: int
    text: str


def unquote(token_text: str) -> str:
    """Pascal string token → its value (``'a''b'`` → ``a'b``)."""

    body = token_text[1:] if token_text.startswith("'") else token_text
    if body.endswith("'") and len(token_text) > 1:
        body = body[:-1]
    return body.replace("''", "'")


def pascal_literals(item: AnalysedFile) -> Iterator[Literal]:
    """String literals of a scanned Pascal source (char codes excluded)."""

    if item.scan is None:
        return
    count = 0
    for token in item.scan.tokens:
        if token.kind != "string" or not token.text.startswith("'"):
            continue
        count += 1
        if count > MAX_LITERALS:
            return
        yield Literal(
            item.path, token.line, token.column,
            unquote(token.text)[:MAX_LINE_CHARS],
        )


_DFM_VALUE = re.compile(r"'((?:[^']|'')*)'")
_DFM_PROP = re.compile(r"^\s*([\w.]+)\s*=\s*(.*)$")


def dfm_literals(path: str, text: str) -> Iterator[Literal]:
    """Quoted property values of a text form definition."""

    count = 0
    for number, line in numbered_lines(text):
        match = _DFM_PROP.match(line)
        if not match or "'" not in match.group(2):
            continue
        for value in _DFM_VALUE.finditer(match.group(2)):
            count += 1
            if count > MAX_LITERALS:
                return
            yield Literal(path, number, match.start(2) + value.start() + 1,
                          value.group(1).replace("''", "'"))


def text_literals(path: str, text: str) -> Iterator[Literal]:
    """Every non-empty line of a configuration file as one literal."""

    for number, line in numbered_lines(text):
        stripped = line.strip()
        if stripped:
            yield Literal(path, number, line.index(stripped[0]) + 1, stripped)


def literals_of(
    item: AnalysedFile, text_of: dict[str, str] | None
) -> Iterator[Literal]:
    """Literals of one file, whatever its class (empty when unreadable)."""

    if item.scan is not None:
        yield from pascal_literals(item)
        return
    text = (text_of or {}).get(item.path)
    if not text:
        return
    if item.cls == "ui_definition":
        yield from dfm_literals(item.path, text)
    elif item.cls == "configuration":
        yield from text_literals(item.path, text)


def sorted_files(analysed: Sequence[AnalysedFile]) -> list[AnalysedFile]:
    """Input order must never influence output: always iterate sorted."""

    return sorted(analysed, key=lambda item: item.path)
