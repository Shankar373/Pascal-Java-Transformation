# P0 Parser Evaluation — tree-sitter-pascal vs DelphiAST

Two candidate parsers were evaluated over the **same** golden corpus, measuring
what the implementation prompt requires: *parsing, recovery, spans, supported
constructs, time and memory*.

Decision rationale is recorded separately as an ADR (`docs/decisions/0001`);
this file is the evidence that ADR rests on.

---

## 1. Candidates

| | tree-sitter-pascal | DelphiAST |
|---|---|---|
| Source | `github.com/Isopod/tree-sitter-pascal` | `github.com/Isopod/DelphiAST` |
| Revision evaluated | `042119e` | `3840253` |
| Licence (verified from `LICENSE` in clone) | **MIT** | **MPL-2.0** |
| Model | Incremental GLR error-recovering parser, generated C | Recursive-descent hand-written AST builder |
| Language of implementation | C grammar + `tree-sitter` runtime | Object Pascal |
| Runtime requirement | `tree-sitter` CLI 0.24.5 + gcc-built grammar | FPC-compiled harness (needed a patch, §4) |
| Output | full concrete syntax tree with byte/point ranges | AST node count, or first error `line:col` |

Neither was selected by popularity, stars or recency — both were selected because
they are the only two maintained open-source parsers that cover Object Pascal
at all, and both were *tested* before either was endorsed.

---

## 2. Method

- **Corpus:** the 24-fixture versioned golden corpus in `corpus/`
  (ISO 7185, Turbo, FPC `objfpc`, Delphi dialects, directives, multi-unit,
  project files). Fixture authoring defects were corrected first and are logged
  in `evidence/fixture-fixes.md`; no fixture was ever weakened to make a tool
  pass.
- **Identical inputs:** both parsers receive exactly the same 24 file paths.
- **Verdict rule (tree-sitter):** a fixture is `FAIL` if the parse output
  contains an `(ERROR` or `(MISSING` node; otherwise `PASS`.
- **Verdict rule (DelphiAST):** the harness emits `RESULT|<file>|OK|<nodes>` or
  `RESULT|<file>|ERROR|<line>:<col>|<message>`; `FAIL` = `ERROR`.
- **Isolation:** every parser run is a fresh process, so no state leaks between
  fixtures.

**Reproduce:**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\sweep-treesitter.ps1  -GrammarDir <clone> -MingwBin <mingw64\bin>
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\sweep-delphiast.ps1   -Harness <delphiast_eval.exe>
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\measure-parsers.ps1   -TreeSitterExe <exe> -GrammarDir <clone> -MingwBin <mingw64\bin> -DelphiASTHarness <harness>
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\probe-recovery.ps1    -TreeSitterExe <exe> -GrammarDir <clone> -MingwBin <mingw64\bin> -DelphiASTHarness <harness>
```

---

## 3. Parsing correctness

| Sweep | Evidence | Result |
|---|---|---|
| tree-sitter over 24 fixtures | `evidence/treesitter.txt` | **24/24 PASS** |
| DelphiAST over 24 fixtures | `evidence/delphiast.txt` | **24/24 PASS** |
| Free Pascal (compiler oracle) over 24 fixtures | `evidence/fpc-host.txt` | 21 PASS / 3 FAIL (3 = declared missing-unit dependencies) |

Both parsers accept every fixture the compiler accepts, **plus** the three
fixtures the compiler rejects for absent platform units (`Forms` ×2,
`DBTables`) — parsers do not resolve external units, which is exactly the
expected division of labour: **parsing ≠ resolution**.

> **Honesty note.** The *pre-fix* parser baselines were not archived as files
> (the parser sweeps were re-run after fixture corrections and their earlier
> output was overwritten). This gap is recorded as such in
> `evidence/fixture-fixes.md` rather than reconstructed. Only the host-FPC
> pre-fix baseline (`fpc-host-prefix.txt`, 15 PASS / 9 FAIL) survives intact.

---

## 4. Finding: DelphiAST does not build under FPC without a patch

**Symptom.** Every input — including the valid control — died with
`EStackOverflow` when the DelphiAST harness was built with FPC 3.2.2.

**Root cause (established by reading the source, not by guessing).** In
`Source/SimpleParser/SimpleParser.pas` the encoding helper did:

```pascal
Bytes := BytesOf(DataString);   // DataString is a class-helper getter
```

Under FPC, class-helper member precedence resolves `DataString`'s getter back
into *that same helper method*, producing infinite recursion. Delphi's own
resolution order does not reproduce it, which is why upstream never sees it.

**Fix applied for evaluation only** —
`evidence/delphiast-fpc-helper-recursion.patch` (also applied to the working
clone at `3840253`):

```pascal
OldPos := Position;
Position := 0;
Count := Size;
SetLength(Bytes, Count);
if Count > 0 then ReadBuffer(Bytes[0], Count);
Position := OldPos;
```

i.e. read the stream buffer directly instead of round-tripping through the
recursing getter.

**Consequences recorded, not glossed over:**

- DelphiAST is **not usable as-is** under FPC; it needs a maintained patch.
  The patch is a *candidate-specific* liability and belongs in the ADR.
- The patch does **not** change DelphiAST's parsing behaviour — it only changes
  how bytes are read from the stream. Post-patch results are therefore
  attributable to DelphiAST itself.
- Upstream has not been notified/patched as of this evaluation; that is a P1
  follow-up item (`P1_TASKS.md`), not a P0 claim of "fixed upstream".

---

## 5. Recovery and spans

Measured by `tools/p0/probe-recovery.ps1` on three inputs generated at run
time — the golden corpus stays valid-only by design, so malformed inputs are
created in a temp dir instead. Evidence: `evidence/parser-recovery.txt`.

| Input | tree-sitter | DelphiAST |
|---|---|---|
| `rec_two_errors.pas` — two stray `)` statements + trailing `writeln` | **3 `(ERROR` nodes**, `nodes_after_error=yes`, first span `[2, 2] - [2, 3]` | **first error only** — `3:3` `'End' expected found ')'`, `result_lines=1` |
| `rec_missing_end.pas` — body with no `end.` | **2 `(ERROR` nodes**, span `[0, 0] - [3, 0]` (EOF recovery), `nodes_after_error=yes` | `1:4` `'End' expected found 'end of file'` |
| `rec_valid_control.pas` — valid program | **0 errors**, accepted | **`OK`**, `nodes=22` |

**Findings.**

1. **Both accept valid input** — the control rules out a harness artifact.
2. **tree-sitter recovers**: it reports *multiple* error nodes and keeps
   building the tree past them (`nodes_after_error=yes`), so a file with a local
   defect still yields a usable tree for everything else in it.
3. **DelphiAST fails closed at the first error**: one `ERROR` result, no
   partial AST. This matches its documented single-unit, fail-fast design.
4. **Spans differ in shape**: tree-sitter emits inclusive byte/point ranges
   `[row, col] - [row, col]` (0-based) for *every* node, including error nodes;
   DelphiAST reports a single 1-based `line:col` for the first error only.

**Implication for the platform.** Tree-sitter's recovery is the stronger basis
for *discovery over unknown/legacy input* (P1: never lose a file because one
line is odd). DelphiAST's fail-closed behaviour is the stronger basis for
*exact acceptance* of a construct it claims to support. These are different
jobs, and the ADR must not pretend one parser does both.

---

## 6. Time and memory

Measured by `tools/p0/measure-parsers.ps1`; evidence
`evidence/parser-performance.txt`. Both parsers are launched as their **real
native executable** (not an npm/cmd shim, which would measure the launcher), and
memory is sampled from the live process handle every 5 ms.

**Batch — one process parses all 24 fixtures:**

| Parser | elapsed | peak working set | exit | output lines |
|---|---|---|---|---|
| tree-sitter `0.24.5` | **219 ms** | **12.57 MB** | 0 | 2060 |
| DelphiAST `3840253`+patch | **84 ms** | **7.75 MB** | 0 | 24 |

**Per-file — one process per fixture (24 processes each):**

| Parser | total | mean per file | max peak working set |
|---|---|---|---|
| tree-sitter | 1821 ms | 75.9 ms | 12.52 MB |
| DelphiAST | 2084 ms | 86.8 ms | 7.24 MB |

**Validity signals** (so the numbers cannot be measuring an aborted run):
`exit=0` for both batches, `out_lines` non-zero for every single measurement
(`badOutLines=0`).

### Measurement caveats (stated, not hidden)

- **Single run, no repetition, background load uncontrolled.** An earlier run
  of the same script measured the tree-sitter batch at **448 ms** versus 219 ms
  here — i.e. roughly 2× run-to-run variance at these durations. Treat these as
  **order-of-magnitude**, not as a precise ranking.
- **Per-file figures include process start-up**, which dominates for 24 tiny
  files. That is why per-file means (75.9 / 86.8 ms) are far above the batch
  figure divided by 24 (9.1 / 3.5 ms). Batch is the honest
  "can this process a corpus?" number; per-file is the honest
  "cost of one invocation" number. They are not interchangeable.
- **Output volumes are not comparable**: tree-sitter prints a full S-expression
  tree (2060 lines), DelphiAST prints one line per file (24 lines). Faster wall
  time is *not* evidence of less work; DelphiAST simply emits far less.
- Both parsers ran against the same inputs on the same machine within the same
  session, so the *relative* comparison is fair even though absolute numbers
  carry variance.

**Conclusion on performance:** neither candidate is disqualified on time or
memory. Both are comfortably within feasibility for P0-scale corpora; the real
differentiators are recovery behaviour (§5), licence (§1) and the FPC patch
requirement (§4).

---

## 7. Supported constructs — what this evaluation does and does not establish

**Established:**

- Both parsers accept every fixture in a corpus covering ISO 7185, Turbo,
  FPC `objfpc`/`delphi` modes, compiler directives and conditional compilation,
  includes, records/variant records, short strings, sets/enums, currency,
  exceptions, file I/O, nested routines, pointers, multi-unit projects and
  project/package files.
- Both reject genuinely malformed syntax, and behave differently when doing so
  (§5).
- Both are **syntax** tools: neither resolves `uses` edges, neither knows that
  `Forms`/`DBTables`/`ComObj` are absent, neither has a symbol table.

**Not established (explicitly out of scope for P0):**

- Semantic equivalence of any construct — no Java was generated, so per the
  capability-state rules nothing here can be `VERIFIED`. Every result in this
  file is **`NOT_VERIFIED`** with respect to conversion correctness; it is
  verified only as *parser acceptance*.
- Behaviour on real customer code — the corpus is synthetic by design.
- Delphi's own parser behaviour — the Delphi compiler is unavailable
  (`TOOLCHAIN_FEASIBILITY.md` §Delphi), so `{$mode delphi}` fixtures are
  checked by **FPC `-Mdelphi`**, a proxy that must never be reported as Delphi
  equivalence.
- Long-file / pathological-input robustness — no adversarial or oversized input
  was tested in P0 (P1 task).

---

## 8. Summary table

| Criterion | tree-sitter-pascal | DelphiAST |
|---|---|---|
| Corpus acceptance | 24/24 | 24/24 |
| Error recovery | multiple errors, keeps tree | stops at first error |
| Spans | full ranges on every node | first error `line:col` only |
| Symbol resolution | none | none |
| Builds under FPC as-is | yes (C grammar) | **no — needs patch (§4)** |
| Licence | MIT | MPL-2.0 (file-level copyleft) |
| Batch time / memory (single run) | 219 ms / 12.57 MB | 84 ms / 7.75 MB |
| Documented unit-at-a-time use | whole file at once | yes, one unit, no symbol table |

Neither candidate is rejected. The selection decision, including the licence and
patch trade-offs, is `docs/decisions/0001`.
