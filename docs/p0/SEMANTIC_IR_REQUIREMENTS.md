# P0 Semantic IR Requirements

What the Semantic IR must represent, and **why each requirement exists** —
every requirement below is traced to a P0 observation rather than to
speculation. The authoritative coverage list is the master prompt's
*Required Semantic IR coverage*; this file records the P0 evidence that makes
each item concrete, plus the items P0 newly proved necessary.

**Status:** requirements only. No IR is implemented in P0.

---

## 1. Why this document exists

P0 was a feasibility exercise, but it produced observations that *constrain*
IR design. If these are not captured now, later phases will rediscover them as
bugs. Each section states: the requirement, the P0 evidence, and the failure it
prevents.

---

## 2. Requirements proven necessary by P0 probes

### 2.1 The IR must record the active compiler mode with every resolved symbol

**Requirement.** Symbol resolution is a function of mode; the IR must carry the
active mode as first-class context, not as a global.

**P0 evidence** (`evidence/probes.txt`, `fpc-host.txt`):

| Probe | Mode | `Result := 1` | Verdict |
|---|---|---|---|
| `P01` | `-Mfpc` | `Identifier not found "Result"` | FAIL |
| `P02` | `-Mtp` | `Identifier not found "Result"` | FAIL |
| `P03` | `-Mobjfpc` | compiles | PASS |
| `P04` | `-Mdelphi` | compiles | PASS |
| `P05` | `-Mfpc` (function-name form) | compiles | PASS (control) |

**Failure prevented.** A converter that emits `Result := …` because "that is
modern Pascal" silently breaks every `fpc`/`tp`-mode function. The IR must know
the mode before it can choose the assignment form.

### 2.2 Identifier visibility must be modelled per unit-of-origin, not per keyword list

**Requirement.** The IR must resolve identifiers against *which unit declares
them*, and must model auto-included units as a function of mode.

**P0 evidence:**

```
system.ppu | AssignFile=False | CloseFile=False | Rewrite=True  | Reset=True
objpas.ppu | AssignFile=True  | CloseFile=True  | Rewrite=False | Reset=True
```

plus probes `P06`–`P11`: bare `AssignFile` fails in `-Mfpc`, passes in
`-Mobjfpc`/`-Mdelphi`; `uses ObjPas` restores it in `-Mfpc`; `System.AssignFile`
fails in **every** mode.

**Failure prevented.** The obvious "fix" — qualify as `System.AssignFile` — is
*wrong in all four modes*. A keyword-level model would have produced exactly
that bug. The IR must know that `AssignFile` originates in `ObjPas` and that
`ObjPas` is auto-included only under `objfpc`/`delphi`.

### 2.3 Unit identity comes from the file name; program identity need not

**Requirement.** Discovery must derive unit identity from the **file name** and
report any mismatch as a blocker rather than guessing.

**P0 evidence:** `P12` `unit ProbeUnit` in `ProbeUnit.pas` → PASS; `P13` same
unit in `ProbeUnit.pas` named `OtherName` → `Illegal unit name: OtherName`;
`P14` `program WrongName` in `probe_prog.pas` → PASS.

**Failure prevented.** Two corpus fixtures failed on exactly this
(`delphi_classes.pas`, `nested_routines.pas`). Renaming the *unit* to match the
file would have broken the idiomatic `uses DelphiClasses` clause; renaming the
*file* preserved both. The IR must not silently rewrite either side.

### 2.4 Comments are not opaque — nested directives are mode-dependent

**Requirement.** The IR must parse directives *inside* comments and must record
the mode in force, because comment termination differs by mode.

**P0 evidence:** `P16` `{ outer {$mode objfpc} inner }` in `-Mfpc` → PASS with
`Warning: Comment level 2 found`; the identical construct in `-Mdelphi`
(`P17`) → `Fatal: Syntax error, "BEGIN" expected but "identifier INNER" found`.

**Failure prevented.** Any "strip comments, then preprocess" pipeline is
unsound under `-Mdelphi`. This is also why two fixtures had to be reworded —
their headers contained the defect.

### 2.5 Type facts must be exact, including length-suffixed strings in variant records

**Requirement.** IR type facts must carry signedness, width, bounds, string
kind and encoding, and must model variant-record field layout.

**P0 evidence:** `P15` `string[31]` inside a variant record compiles under
`-Mfpc`; `ShortString[31]` is invalid (`Error in type definition`).

**Failure prevented.** `ShortString` and `string[N]` are different types with
different layout; conflating them corrupts the ABI/binary-serialization facts
the IR is required to carry.

### 2.6 The legal mode set cannot be derived from `-h` output

**Requirement.** The profile resolver's mode table must be explicit and tested.

**P0 evidence:** `P18` `-Miso` is accepted by fpc 3.2.2 although it does not
appear in `-h`'s mode list.

**Failure prevented.** A resolver that scrapes `-h` would reject a valid mode
and mark an ISO profile `UNSUPPORTED` without cause.

### 2.7 Capability state must be scoped to a target platform

**Requirement.** `SUPPORTED`/`PARTIAL`/`UNSUPPORTED` must be recorded **per
target platform**, not per dialect alone.

**P0 evidence:** `ado_style_connection.pas` → PASS on Windows host,
`FAIL — Can't find unit ComObj` on the pinned Linux container. Same source,
same mode, different verdict; `fpc-docker.txt` records `MATCH=24|MISMATCH=0`
against expectations that themselves differ by OS.

**Failure prevented.** A platform-agnostic capability matrix would declare this
fixture either wrongly supported or wrongly unsupported on one of the two
targets.

---

## 3. Coverage the master prompt requires (carried forward unchanged)

The IR must represent at minimum:

1. **Source identity, file hash, source spans, active build variant.**
   - *P0 note:* both parser candidates supply spans, but in different shapes —
     tree-sitter emits `[row,col]-[row,col]` ranges for every node, DelphiAST
     only a first-error `line:col` (`PARSER_EVALUATION.md` §5). The IR's span
     type must be parser-agnostic.
2. **Symbols, scopes, visibility, overloads, generics, nested procedures,
   units/packages, calls.** — *P0 note:* neither candidate has a symbol table;
   this is P2 work, and P0 established that parsing alone cannot provide it.
3. **Exact type facts:** signedness, width, bounds, precision, scale, string
   kind/encoding, array and ordinal layout. — see §2.5.
4. **Records/variant records:** field order, packing/alignment, ABI, binary
   serialization facts.
5. **Expressions, statements, evaluation order, control flow, exceptions.**
6. **Compiler modes/directives, defines, range/overflow checking, calling
   conventions, target platform.** — see §2.1, §2.4, §2.6, §2.7.
7. **Side effects:** database reads/writes, file operations,
   environment/time/random, native calls, network, messaging.
   - *P0 note:* `embedded_sql.pas` proves SQL exists as inert string literals
     requiring *extraction*, not execution; `ado_style_connection.pas` proves
     native/COM dependency discovery; `fpc-run.txt` records real observable
     behavior (exit codes, stdout) for 16 programs — the seed of the runtime
     side-effect oracle.
8. **Diagnostic state, capability state, blockers, traceability to generated
   target elements.** — see §2.7.

Explicitly handled or blocked rather than approximated: fixed-point currency,
BigDecimal mapping/rounding, integer overflow, `ShortString`/`AnsiString`/
`UnicodeString` differences, code pages, declared array bounds, packed sets,
enum ordinals, record alignment and calling conventions.

---

## 4. Invariants these requirements impose

| # | Invariant | Derived from |
|---|---|---|
| I1 | **Fail closed.** Unknown syntax/directive/type is a recorded blocker, never silently dropped or approximated. | master prompt rule 5; §2.2, §2.5 |
| I2 | **No silent acceptance.** An unrecognised construct produces a diagnostic with file/line/col, not a best-effort tree. | `P13`, `P17` |
| I3 | **Mode is context, not a flag.** Every resolution records the mode in force. | §2.1, §2.4 |
| I4 | **Platform is context, not a footnote.** Capability states are `(construct, mode, platform)` triples. | §2.7 |
| I5 | **Traceability.** Every IR element and every generated Java element resolves back to a source span and a fixture/probe. | master prompt §Required Semantic IR coverage |
| I6 | **Deterministic.** Same input + same tool versions ⇒ byte-identical IR. No probabilistic step anywhere. | no-LLM gate, `docs/decisions/0005` |
| I7 | **Preserve compiler metadata.** Mode, defines, range/overflow state and target survive into the IR; they are never normalised away. | §2.1, §2.6 |

---

## 5. Explicit non-claims

- **No IR exists yet.** P0 produced requirements, not an implementation.
- **Nothing here is `VERIFIED`.** Capability state for every item above is
  `NOT_VERIFIED` — a parser accepting input does not establish conversion
  correctness. `VERIFIED` requires original-vs-Java differential tests (P3+).
- **Delphi semantics are proxy-only.** `{$mode delphi}` fixtures were checked
  by FPC `-Mdelphi`; the Delphi compiler is unavailable, so no Delphi-specific
  IR claim is established.
