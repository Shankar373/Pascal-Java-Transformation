"""Deterministic Pascal lexer for discovery (plan §5.3).

What it is
----------

A single-pass, position-tracking scanner that turns Pascal source into:

* **tokens** — identifiers, numbers, strings and symbols, each with a
  ``(line, column)`` span and the conditional-compilation context open at
  that point;
* **directives** — every ``{...}``/``(*...*)`` compiler directive, with its
  name, argument and the active conditional stack;
* **uses clauses** — ``uses`` / ``requires`` with the unit names, their
  spans and their section (``interface`` / ``implementation`` / ``program`` /
  ``package``);
* **includes** — ``{$I file}`` / ``{$INCLUDE file}`` references;
* **native references** — string literals that name a shared library, plus
  ``external`` clauses and dynamic-loading API calls;
* **diagnostics** — unbalanced directives and malformed ``uses`` clauses are
  *recorded*, never silently skipped (IR invariant I2).

What it is not
--------------

It is **not** a parser and produces no syntax tree: P0 established that
neither candidate parser has a symbol table, and ``P1_TASKS.md`` §F defers
symbol/type resolution to P2.  Discovery needs *spans and context*, which is
exactly what this scanner provides — and nothing more is claimed for it.

Determinism
-----------

The scanner is a pure function of the source text: no clock, no locale, no
regex backtracking over unbounded input, no environment access.  The same
bytes always produce the same tokens, directives and diagnostics.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .errors import DiagnosticSink
from .limits import DEFAULT_LIMITS, Limits

__all__ = [
    "Token",
    "Directive",
    "UsesItem",
    "UsesClause",
    "IncludeRef",
    "NativeRef",
    "ScanResult",
    "scan",
]

# Multi-character operators, longest first (greedy match).
_SYMBOLS = (
    ":=", "<=", ">=", "<>", "..", "+=", "-=", "*=", "/=", "**", "><",
)

#: Words that open a section; tracked so a ``uses`` clause can be attributed.
_SECTION_WORDS = {"program", "library", "package", "unit", "interface",
                  "implementation"}

#: Words that make a preceding ``uses``/``requires`` legal.  Requiring this
#: context stops a local variable *named* ``uses`` from being mistaken for a
#: clause — a false dependency edge would be worse than a missed one.
_USES_PRECEDERS = {";", "interface", "implementation"}

#: Guard against pathological input: a single clause cannot name 10k units.
_MAX_USES_ITEMS = 5000

#: Shared-library extensions recognised in string literals.
_DLL_SUFFIXES = (".dll", ".so", ".dylib", ".bpl", ".ocx", ".drv", ".sys")

#: Dynamic-loading APIs; their presence is evidence of a native dependency.
_OS_APIS = frozenset(
    {
        "loadlibrary",
        "getprocaddress",
        "freelibrary",
        "dlopen",
        "dlsym",
        "dlclose",
        "getmodulehandle",
    }
)


@dataclass(frozen=True)
class Token:
    """One lexical token with its source span and conditional context."""

    kind: str  # "ident" | "number" | "string" | "symbol"
    text: str
    line: int
    column: int
    #: Active conditional-compilation expressions (``MSWINDOWS``, ``!FPC``…).
    cond: tuple[str, ...] = ()

    @property
    def lower(self) -> str:
        return self.text.lower()


@dataclass(frozen=True)
class Directive:
    """A compiler directive with its argument and open conditionals."""

    name: str  # upper-case, without the leading '$'
    argument: str
    raw: str
    line: int
    column: int
    conditional: tuple[str, ...] = ()

    @property
    def upper_argument(self) -> str:
        return self.argument.upper()


@dataclass(frozen=True)
class UsesItem:
    """One unit named in a ``uses``/``requires`` clause."""

    name: str
    line: int
    column: int
    conditional: tuple[str, ...] = ()


@dataclass(frozen=True)
class UsesClause:
    """A complete ``uses``/``requires`` clause and the section it sits in."""

    kind: str  # "uses" | "requires"
    section: str  # "program" | "library" | "package" | "unit" |
    #               "interface" | "implementation" | "unknown"
    items: tuple[UsesItem, ...]
    line: int
    column: int


@dataclass(frozen=True)
class IncludeRef:
    """An ``{$I file}`` / ``{$INCLUDE file}`` reference."""

    filename: str
    line: int
    column: int
    directive: str  # "I" | "INCLUDE"
    conditional: tuple[str, ...] = ()


@dataclass(frozen=True)
class NativeRef:
    """A reference to a native/shared library or a dynamic-loading API."""

    name: str
    kind: str  # "external-clause" | "string-literal" | "os-api"
    line: int
    column: int


@dataclass
class ScanResult:
    """Everything one file's scan produced."""

    tokens: list[Token] = field(default_factory=list)
    directives: list[Directive] = field(default_factory=list)
    uses: list[UsesClause] = field(default_factory=list)
    includes: list[IncludeRef] = field(default_factory=list)
    native_refs: list[NativeRef] = field(default_factory=list)
    #: Populated from ``DiagnosticSink.to_list()``, so these are plain dicts
    #: (``code``/``severity``/``message``/``file``/``line``/``column``).
    diagnostics: list[dict[str, object]] = field(default_factory=list)
    #: True when the input exceeded ``max_source_bytes`` and was cut short.
    truncated: bool = False
    #: Characters actually scanned.
    scanned_chars: int = 0


# --------------------------------------------------------------------------
# The scanner
# --------------------------------------------------------------------------


def scan(
    text: str,
    *,
    path: str = "",
    limits: Limits = DEFAULT_LIMITS,
) -> ScanResult:
    """Scan *text*, recording spans, directives and clauses.

    Pure and deterministic.  *path* is only used to attach locations to
    diagnostics; it never influences what is produced.
    """

    sink = DiagnosticSink(limits.max_diagnostics)
    if len(text) > limits.max_source_bytes:
        text = text[: limits.max_source_bytes]
        sink.warn(
            "SOURCE_TRUNCATED",
            f"source exceeds max_source_bytes={limits.max_source_bytes}; "
            "only the leading portion was scanned (file still inventoried "
            "and hashed in full)",
            path=path,
        )

    result = ScanResult(truncated=len(text) >= limits.max_source_bytes)
    result.scanned_chars = len(text)

    n = len(text)
    i = 0
    line = 1
    column = 1

    # Conditional-compilation stack and the shared tuple handed to tokens.
    cond_stack: list[str] = []
    cond_now: tuple[str, ...] = ()

    # Section tracking for `uses` attribution.
    section = "unknown"
    prev_text: str | None = None

    # In-progress `uses` clause.
    pending_kind: str | None = None
    pending_items: list[UsesItem] = []
    pending_line = 0
    pending_column = 0
    pending_expect_name = False
    #: Delphi ``Unit in 'path.pas'``: 0 = none, 1 = saw ``in`` (a string must
    #: follow), 2 = the path string was consumed.
    pending_in = 0
    #: A '.' just followed a unit name: the next identifier extends it.
    pending_dot = False

    def advance_to(new_i: int) -> None:
        """Move *i* forward, updating line/column across the skipped span."""

        nonlocal line, column
        segment = text[i:new_i]
        newlines = segment.count("\n")
        if newlines:
            line += newlines
            column = len(segment) - segment.rfind("\n")
        else:
            column += len(segment)

    def fail_pending(reason: str, at_line: int, at_col: int) -> None:
        nonlocal pending_kind, pending_in, pending_dot
        if pending_kind is None:
            return
        sink.error(
            "USES_MALFORMED",
            f"{pending_kind} clause not well formed ({reason}); the clause "
            "was recorded as a diagnostic rather than dropped",
            path=path,
            line=at_line,
            column=at_col,
        )
        pending_kind = None
        pending_in = 0
        pending_dot = False
        pending_items.clear()

    def finish_pending() -> None:
        nonlocal pending_kind, pending_in, pending_dot
        if pending_kind is None:
            return
        result.uses.append(
            UsesClause(
                kind=pending_kind,
                section=section,
                items=tuple(pending_items),
                line=pending_line,
                column=pending_column,
            )
        )
        pending_kind = None
        pending_in = 0
        pending_dot = False
        pending_items.clear()

    while i < n:
        ch = text[i]

        # ---- whitespace -------------------------------------------------
        if ch == "\n":
            line += 1
            column = 1
            i += 1
            continue
        if ch.isspace():
            i += 1
            column += 1
            continue

        start_line, start_col = line, column

        # ---- comments and directives ------------------------------------
        if ch == "{":
            end = text.find("}", i + 1)
            if end == -1:
                sink.error(
                    "UNTERMINATED_COMMENT",
                    "unterminated '{' comment or directive",
                    path=path,
                    line=start_line,
                    column=start_col,
                )
                break
            body = text[i + 1 : end]
            advance_to(end + 1)
            i = end + 1
            if body.startswith("$"):
                _record_directive(
                    body, start_line, start_col, cond_now, result, sink, path
                )
                _update_conditions(
                    body, cond_stack, sink, path, start_line, start_col
                )
                cond_now = tuple(cond_stack)
            # else: plain comment — deliberately not a token.
            continue

        if text.startswith("(*", i):
            end = text.find("*)", i + 2)
            if end == -1:
                sink.error(
                    "UNTERMINATED_COMMENT",
                    "unterminated '(*' comment or directive",
                    path=path,
                    line=start_line,
                    column=start_col,
                )
                break
            body = text[i + 2 : end]
            advance_to(end + 2)
            i = end + 2
            if body.startswith("$"):
                _record_directive(
                    body, start_line, start_col, cond_now, result, sink, path
                )
                _update_conditions(
                    body, cond_stack, sink, path, start_line, start_col
                )
                cond_now = tuple(cond_stack)
            continue

        if text.startswith("//", i):
            end = text.find("\n", i + 2)
            if end == -1:
                advance_to(n)
                i = n
            else:
                advance_to(end)
                i = end
            continue

        # ---- string and character literals ------------------------------
        if ch == "'":
            j = i + 1
            while j < n:
                if text[j] == "'":
                    if j + 1 < n and text[j + 1] == "'":
                        j += 2  # escaped quote
                        continue
                    j += 1
                    break
                if text[j] == "\n":
                    break  # unterminated: stop at end of line (Pascal rule)
                j += 1
            else:
                j = n
            literal = text[i:j]
            if j <= i + 1 or not literal.endswith("'"):
                sink.error(
                    "UNTERMINATED_STRING",
                    "unterminated string literal",
                    path=path,
                    line=start_line,
                    column=start_col,
                )
            advance_to(j)
            _emit(result, "string", literal, start_line, start_col, cond_now)
            i = j
            prev_text = literal
            if pending_kind is not None:
                if pending_in == 1:
                    pending_in = 2  # `Unit in 'path'`: the path is not a unit
                else:
                    fail_pending(
                        "string literal inside clause", start_line, start_col
                    )
            continue

        if ch == "#":  # character code literal: #13, #$0A
            j = i + 1
            if j < n and text[j] == "$":
                j += 1
            while j < n and text[j] in "0123456789abcdefABCDEF":
                j += 1
            if j == i + 1:
                # A bare '#' is not a literal; treat it as a symbol.
                j = i + 1
                advance_to(j)
                _emit(result, "symbol", "#", start_line, start_col, cond_now)
                i = j
                prev_text = "#"
                continue
            literal = text[i:j]
            advance_to(j)
            _emit(result, "string", literal, start_line, start_col, cond_now)
            i = j
            prev_text = literal
            if pending_kind is not None:
                fail_pending("character code inside clause", start_line, start_col)
            continue

        # ---- identifiers -------------------------------------------------
        # `&` escapes a reserved word used as an identifier (&begin); it must
        # be followed by a letter, otherwise it is an octal literal (handled
        # by the number branch below).
        if ch.isalpha() or ch == "_" or (
            ch == "&"
            and i + 1 < n
            and (text[i + 1].isalpha() or text[i + 1] == "_")
        ):
            j = i + 1 if ch == "&" else i
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            word = text[i:j]
            advance_to(j)
            i = j
            _emit(result, "ident", word, start_line, start_col, cond_now)

            low = word.lower()

            # Section tracking.
            if low in _SECTION_WORDS:
                section = _next_section(section, low)

            # Clause start.
            if (
                pending_kind is None
                and low in ("uses", "requires")
                and (prev_text is None or prev_text in _USES_PRECEDERS)
            ):
                pending_kind = low
                pending_items = []
                pending_line, pending_column = start_line, start_col
                pending_expect_name = True
                prev_text = low
                continue

            # Clause body.
            if pending_kind is not None:
                if pending_expect_name:
                    if len(pending_items) >= _MAX_USES_ITEMS:
                        fail_pending(
                            f"more than {_MAX_USES_ITEMS} items",
                            start_line,
                            start_col,
                        )
                    else:
                        pending_items.append(
                            UsesItem(word, start_line, start_col, cond_now)
                        )
                        pending_expect_name = False
                elif pending_dot and pending_items:
                    last = pending_items[-1]
                    pending_items[-1] = UsesItem(
                        f"{last.name}.{word}", last.line, last.column,
                        last.conditional,
                    )
                    pending_dot = False
                elif low == "in" and pending_items and pending_in == 0:
                    pending_in = 1
                else:
                    fail_pending(
                        f"unexpected identifier {word!r} after unit name",
                        start_line,
                        start_col,
                    )
                prev_text = low
                continue

            prev_text = low
            continue

        # ---- numbers -----------------------------------------------------
        if ch.isdigit() or (
            ch == "$" and i + 1 < n and text[i + 1] in "0123456789abcdefABCDEF"
        ) or (ch == "%" and i + 1 < n and text[i + 1] in "01") or (
            ch == "&" and i + 1 < n and text[i + 1] in "01234567"
        ):
            j = i
            if ch in "$%&":
                j += 1
            while j < n and (text[j].isalnum() or text[j] == "."):
                # Stop before a range operator: `1..5` is 1, .., 5.
                if text[j] == "." and text[j : j + 2] == "..":
                    break
                if text[j] == "." and not text[j + 1 : j + 2].isdigit():
                    break
                j += 1
            # Exponent.
            if j < n and text[j] in "eE":
                k = j + 1
                if k < n and text[k] in "+-":
                    k += 1
                if k < n and text[k].isdigit():
                    j = k
                    while j < n and text[j].isdigit():
                        j += 1
            word = text[i:j]
            advance_to(j)
            i = j
            _emit(result, "number", word, start_line, start_col, cond_now)
            prev_text = word
            if pending_kind is not None:
                fail_pending("number inside clause", start_line, start_col)
            continue

        # ---- symbols -----------------------------------------------------
        matched = ""
        for symbol in _SYMBOLS:
            if text.startswith(symbol, i):
                matched = symbol
                break
        if not matched:
            matched = ch
        advance_to(i + len(matched))
        i += len(matched)
        _emit(result, "symbol", matched, start_line, start_col, cond_now)

        if pending_kind is not None:
            if matched == "." and pending_items and not pending_expect_name                     and pending_in == 0 and not pending_dot:
                pending_dot = True
            elif matched == ",":
                pending_expect_name = True
                pending_in = 0
                pending_dot = False
            elif matched == ";" and pending_dot:
                fail_pending("dangling '.' after unit name", start_line,
                             start_col)
            elif matched == ";":
                finish_pending()
            else:
                fail_pending(
                    f"unexpected symbol {matched!r}", start_line, start_col
                )
        prev_text = matched

    # ---- end of input ---------------------------------------------------
    if pending_kind is not None:
        sink.error(
            "USES_UNTERMINATED",
            f"{pending_kind} clause reaches end of file without ';'",
            path=path,
            line=pending_line,
            column=pending_column,
        )
        finish_pending()

    if cond_stack:
        sink.warn(
            "DIRECTIVE_UNTERMINATED",
            f"conditional compilation still open at end of file: "
            f"{', '.join(cond_stack)}",
            path=path,
        )

    _post_process(result, sink, path)

    result.diagnostics = sink.to_list()
    return result


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _emit(
    result: ScanResult,
    kind: str,
    text: str,
    line: int,
    column: int,
    cond: tuple[str, ...],
) -> None:
    result.tokens.append(Token(kind, text, line, column, cond))


def _next_section(current: str, word: str) -> str:
    """Advance the section state machine on a reserved word."""

    if word == "unit":
        return "unit"
    if word in ("program", "library", "package"):
        return word
    if word == "interface":
        return "interface"
    if word == "implementation":
        return "implementation"
    return current


def _record_directive(
    body: str,
    line: int,
    column: int,
    cond: tuple[str, ...],
    result: ScanResult,
    sink: DiagnosticSink,
    path: str,
) -> None:
    """Parse ``$NAME argument`` out of a directive body (``body[0] == '$'``)."""

    inner = body[1:]
    j = 0
    while j < len(inner) and (inner[j].isalnum() or inner[j] == "_"):
        j += 1
    name = inner[:j].upper()
    argument = inner[j:].strip()
    if not name:
        sink.warn(
            "EMPTY_DIRECTIVE",
            "directive has no name",
            path=path,
            line=line,
            column=column,
        )
        return
    result.directives.append(
        Directive(name, argument, "$" + inner.strip(), line, column, cond)
    )


def _update_conditions(
    body: str,
    stack: list[str],
    sink: DiagnosticSink,
    path: str,
    line: int,
    column: int,
) -> None:
    """Maintain the conditional stack from a directive body.

    The stack records *what* is open, not whether it is taken: discovery needs
    the context a construct sits in, not a preprocessor's evaluation of it.
    ``!`` marks a negated arm so ``{$IFDEF X}`` and ``{$IFNDEF X}`` stay
    distinguishable in the evidence.

    A stray ``{$ENDIF}`` is recorded as a diagnostic rather than ignored — an
    unbalanced directive is an ambiguity in the input, and IR invariant I2
    forbids letting it pass silently.
    """

    inner = body[1:]
    j = 0
    while j < len(inner) and (inner[j].isalnum() or inner[j] == "_"):
        j += 1
    name = inner[:j].upper()
    argument = inner[j:].strip()

    if name in ("IFDEF", "IFNDEF"):
        head = argument.split()[0] if argument else "?"
        stack.append("!" + head if name == "IFNDEF" else head)
    elif name in ("IF", "IFOPT", "IFDECLARED"):
        stack.append(argument or "?")
    elif name == "ELSE":
        if stack:
            top = stack[-1]
            stack[-1] = top[1:] if top.startswith("!") else "!" + top
        else:
            sink.warn(
                "DIRECTIVE_UNBALANCED",
                "{$ELSE} with no open conditional",
                path=path,
                line=line,
                column=column,
            )
    elif name in ("ELSEIF", "ELSEIFDEF", "ELSEIFNDEF"):
        if stack:
            stack[-1] = argument or "?"
        else:
            sink.warn(
                "DIRECTIVE_UNBALANCED",
                f"{{${name}}} with no open conditional",
                path=path,
                line=line,
                column=column,
            )
    elif name in ("ENDIF", "IFEND"):
        if stack:
            stack.pop()
        else:
            sink.warn(
                "DIRECTIVE_UNBALANCED",
                f"{{${name}}} with no open conditional",
                path=path,
                line=line,
                column=column,
            )


def _post_process(
    result: ScanResult, sink: DiagnosticSink, path: str
) -> None:
    """Derive includes, native references and directive-balance diagnostics."""

    tokens = result.tokens

    # --- includes -------------------------------------------------------
    for directive in result.directives:
        if directive.name in ("I", "INCLUDE"):
            filename = directive.argument.strip().strip("'\"").strip()
            if filename and not filename.upper().startswith("ONCE"):
                result.includes.append(
                    IncludeRef(
                        filename=filename,
                        line=directive.line,
                        column=directive.column,
                        directive=directive.name,
                        conditional=directive.conditional,
                    )
                )
        elif directive.name == "LINKLIB":
            lib = directive.argument.strip().strip("'\"").strip()
            if lib:
                result.native_refs.append(
                    NativeRef(
                        name=lib,
                        kind="external-clause",
                        line=directive.line,
                        column=directive.column,
                    )
                )

    # --- external clauses and string literals ---------------------------
    for index, token in enumerate(tokens):
        if token.kind == "string":
            lowered = token.text.strip("'").lower()
            if lowered.endswith(_DLL_SUFFIXES):
                result.native_refs.append(
                    NativeRef(lowered, "string-literal", token.line, token.column)
                )
        elif token.kind == "ident":
            low = token.lower
            if low == "external":
                # `external 'lib.dll'` / `external name 'x'`
                for lookahead in tokens[index + 1 : index + 4]:
                    if lookahead.kind == "string":
                        name = lookahead.text.strip("'")
                        if name:
                            result.native_refs.append(
                                NativeRef(
                                    name,
                                    "external-clause",
                                    token.line,
                                    token.column,
                                )
                            )
                        break
                    if lookahead.kind == "ident" and lookahead.lower == "name":
                        continue
                    break
            elif low in _OS_APIS:
                result.native_refs.append(
                    NativeRef(low, "os-api", token.line, token.column)
                )

    # --- native reference de-duplication -------------------------------
    # `external 'foo.dll'` yields both an `external-clause` reference at the
    # keyword and a `string-literal` reference at the literal on the same
    # line.  Both are true, but emitting two edges for one declaration would
    # inflate the graph; the clause form is the more informative, so it wins.
    seen_refs: set[tuple[str, int]] = set()
    deduped: list[NativeRef] = []
    for ref in result.native_refs:
        key = (ref.name.lower(), ref.line)
        if key in seen_refs:
            continue
        seen_refs.add(key)
        deduped.append(ref)
    result.native_refs = deduped

    # --- directive balance ---------------------------------------------
    # Count openings and closings per directive name; a mismatch is a real
    # ambiguity in the input and must surface as evidence, not disappear.
    opens = sum(
        1
        for d in result.directives
        if d.name in ("IFDEF", "IFNDEF", "IF", "IFOPT", "IFDECLARED")
    )
    closes = sum(
        1 for d in result.directives if d.name in ("ENDIF", "IFEND")
    )
    elses = sum(1 for d in result.directives if d.name == "ELSE")
    if opens != closes:
        sink.warn(
            "DIRECTIVE_UNBALANCED",
            f"{opens} conditional opener(s) vs {closes} ENDIF(s) "
            f"({elses} ELSE)",
            path=path,
        )
