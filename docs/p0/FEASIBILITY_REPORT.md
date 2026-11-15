# P0 Feasibility Report — Repository and Toolchain Feasibility

- **Phase:** P0 of the Pascal-to-Java Enterprise Modernization roadmap
- **Date:** 2026-11-13
- **Repo baseline:** `main` @ `3bbba10`
- **Verdict:** **FEASIBLE**, with one hard blocker (Delphi) and five recorded
  constraints

---

## 1. Scope — what P0 did and did not do

**Did:** establish whether the toolchain can support this platform at all, and
freeze the initial architecture on evidence.

**Did not:** generate any Java, implement any IR, or prove any conversion. No
result below establishes behavioural equivalence. Per the capability-state
rules, everything here is **`NOT_VERIFIED`** with respect to conversion
correctness; it is verified only as *toolchain and parser acceptance*.

---

## 2. Acceptance criteria — checkable status

| # | Criterion | Status | Where |
|---|---|---|---|
| 1 | Parser candidates tested on representative fixtures | **Met** | `PARSER_EVALUATION.md`; both 24/24 over the same corpus |
| 2 | Compiler availability verified | **Met** | `DIALECT_COMPILER_MATRIX.md` §1 — FPC 3.2.2 on Windows **and** pinned Linux container |
| 3 | Delphi licensing/execution requirements documented | **Met** | `TOOLCHAIN_FEASIBILITY.md` §4 |
| 4 | Dialect gaps/blockers identified | **Met** | `DIALECT_COMPILER_MATRIX.md` §2, §6; `SEMANTIC_IR_REQUIREMENTS.md` §2 |
| 5 | OSS licence decisions documented | **Met** | `LICENCE_REVIEW.md`; ADR `0002` |
| 6 | Initial conversion parsers selected/rejected | **Met** | ADR `0001` (both adopted, roles separated) |
| 7 | Reproducible feasibility report | **Met** | this file + `evidence/` + `tool-versions.txt` |
| 8 | P1 tasks defined | **Met** | `P1_TASKS.md` |

---

## 3. Baseline and repo health

| Item | State |
|---|---|
| Branch | `main` @ `3bbba10` |
| Pre-existing automated tests / build | **none** — repository contained only `README.md` |
| Baseline established before editing | **yes** — `README.md` committed first; P0 work then layered as untracked `corpus/`, `docs/`, `tools/` |
| Working-tree state | P0 deliverables **uncommitted**, pending review (no commit/push until validation is reviewed) |

There were no pre-existing failures to separate from regressions, because
there was no pre-existing test suite. P0 therefore *created* the baseline:
a versioned corpus plus sweeps that can be re-run at any time.

---

## 4. Corpus

24 synthetic fixtures under `corpus/`, covering ISO 7185, Turbo, FPC
`objfpc`/`delphi` modes, Delphi constructs, directives and conditional
compilation, includes, range checks, records/variant records, short strings,
sets/enums, currency, exceptions, file I/O, nested routines, pointers,
multi-unit console projects, and project/package files.

- Expectation contract: `corpus/README.md` — `PASS` / `FAIL-DEPENDENCY` /
  `DISCOVERY-ONLY`.
- **Six genuine authoring defects** were corrected after the first sweep; every
  fix is logged with its exact pre-fix error line and root cause in
  `evidence/fixture-fixes.md`. No fixture was ever weakened to make a tool pass.
- **Three fixtures are intended failures** (`Forms` ×2, `DBTables`) and still
  fail exactly as declared.

---

## 5. Results (all evidence-backed)

### 5.1 Compiler

| Run | Evidence | Result |
|---|---|---|
| Pre-fix baseline (host) | `fpc-host-prefix.txt` | 15 PASS / 9 FAIL |
| Post-fix host FPC 3.2.2 Win32 | `fpc-host.txt` | **21 PASS / 3 FAIL** (3 = declared dependencies) |
| Pinned Linux container | `fpc-docker.txt` | **20 PASS / 4 FAIL**, `MATCH=24`, `MISMATCH=0` |
| Execution of produced programs | `fpc-run.txt` | **16 RUN / 8 SKIP / 0 TIMEOUT**, exit codes real |

`exception_flow.pas` exits **2** — its own asserted behaviour — proving run
evidence captures semantics, not just "it started". This closes
`corpus/README.md`'s "compiles **and runs** where a program" claim.

**Cross-OS differential:** host 21/3 vs container 20/4. The delta is exactly
`ado_style_connection.pas` → `Can't find unit ComObj`, precisely what its header
now documents. Platform-dependent capability is real and is modelled as such
(ADR `0004`, IR invariant I4).

### 5.2 Dialect probes

`probes.txt` — **18 probes, all `OK`, 0 `UNEXPECTED`, 0 `UNKNOWN`.**

Findings that directly constrain the IR:

- `Result` exists only under `objfpc`/`delphi`; `fpc`/`tp` need function-name
  assignment (`P01`–`P05`).
- `AssignFile`/`CloseFile` are declared in **`ObjPas`**, not `System`
  (`system.ppu` scan: `AssignFile=False`; `objpas.ppu`: `AssignFile=True`), so
  `System.AssignFile` fails in *every* mode (`P06`–`P11`).
- A unit's name must equal its file name; a program's need not (`P12`–`P14`).
- Nested `{$…}` in `{…}` comments: warning under `fpc`/`objfpc`, **fatal** under
  `delphi` (`P16`/`P17`).
- `string[31]` is valid in a variant record; `ShortString[31]` is not (`P15`).
- `-Miso` is accepted though absent from `-h` (`P18`).

### 5.3 Parsers

| | tree-sitter-pascal `042119e` | DelphiAST `3840253` |
|---|---|---|
| Corpus acceptance | **24/24** | **24/24** |
| Recovery (`parser-recovery.txt`) | 3 error nodes, **keeps parsing past them** | **first error only** |
| Spans | full ranges on every node | first error `line:col` |
| Licence | MIT | MPL-2.0 |
| Builds under FPC as-is | yes | **no — needs patch** |
| Batch time / peak memory (single run) | 219 ms / 12.57 MB | 84 ms / 7.75 MB |

**DelphiAST finding:** under FPC its encoding helper recursed
(`Bytes := BytesOf(DataString)` resolving back into itself), causing
`EStackOverflow` on every input. Root-caused and patched —
`evidence/delphiast-fpc-helper-recursion.patch`. The patch changes only how
bytes are read, so post-patch results remain attributable to DelphiAST.

**Honest measurement limits:** single-run timings with ~2× run-to-run variance
(an earlier run measured the tree-sitter batch at 448 ms vs 219 ms); per-file
figures include process start-up; the two parsers' output volumes (2060 vs 24
lines) are not comparable. Full caveats in `PARSER_EVALUATION.md` §6.

**Evidence gap, stated not hidden:** the *pre-fix* parser baselines were
overwritten rather than archived. Only the host-FPC pre-fix baseline survives.
Recorded as `fixture-fixes.md` footnote 1 and closed by `P1_TASKS.md` A4.

### 5.4 Toolchain and reproducibility

`tool-versions.txt`: Node 22.23.4 · npm 10.9.9 · Python 3.11.9 ·
Java (Temurin) 21.0.12.1 · Maven 3.9.16 · FPC 3.2.2 · Docker 29.8.2 ·
tree-sitter 0.24.5 (`1a983b7e…`) · gcc 16.2.0.

Container pinned **by digest**:
`freepascal/fpc:3.2.2-bookworm-full@sha256:6c951541…ed3872`, mounted `:ro`,
compiler output to `/tmp`, fresh `-FE`/`-FU` per fixture (a stale `.ppu` once
produced a false pass — fresh dirs are now mandatory). All evidence normalised
to UTF-8 no-BOM so review and diff tools can read it.

---

## 6. Blockers

### B1 — Delphi compiler UNAVAILABLE (hard blocker)

Verified absent: no Embarcadero/Borland/CodeGear directories, no
`dcc32`/`dcc64`/`bds`/`rsvars`, no matching uninstall registry entries.

- Capability `UNAVAILABLE`, workflow `ORACLE_UNAVAILABLE`.
- `corpus/dialects/delphi/*` validated by **FPC `-Mdelphi`**, a **proxy** that
  must never be reported as Delphi equivalence.
- **Licensing** (verified from vendor sources, not invented): proprietary
  commercial; Professional/Enterprise/Architect; Community Edition is
  non-commercial (revenue < US$5,000/yr, teams ≤ 5, one-year term) and **not
  offered for RAD Studio**; Named User node-locked or Network Named/Concurrent
  via a customer-run AppWave License Server; indicative list prices from
  Delphi Pro $1,583.01 to RAD Studio Architect $6,533.01.
- **Execution:** requires a licensed **Windows** worker; node-locked licensing
  is a poor fit for an unattended CI oracle, so network/concurrent licensing is
  the relevant route; the licence is customer-supplied and cannot be
  redistributed; per-seat cost makes Delphi verification an opt-in paid
  certification path, never a default.
- **Resolution path:** interface + test double specified for P3. The missing
  work is never claimed to have passed.

### Evidence gaps (not blockers, but recorded)

| Gap | Handling |
|---|---|
| Pre-fix parser baselines not archived | Stated in `fixture-fixes.md` fn.1; closed by `P1_TASKS.md` A4 |
| `tp`/`iso` have probe coverage but no fixture sweep | `DIALECT_COMPILER_MATRIX.md` §7; `P1_TASKS.md` A3 |
| Repository has no `LICENSE` file | `LICENCE_REVIEW.md` §4; **not invented** — owner decision, `P1_TASKS.md` A1 |
| DelphiAST patch not reported upstream | `P1_TASKS.md` A2 |
| Parser perf measured once, no repetition | Caveats in `PARSER_EVALUATION.md` §6 |

---

## 7. Architecture changes made in P0

| Change | Reason | Impact |
|---|---|---|
| DelphiAST adopted **with a local patch**, not as-is | Upstream FPC class-helper recursion bug makes it unbuildable otherwise | Permanent fork liability; upstream notification tracked (A2) |
| Both parsers adopted with **separate roles** instead of one winner | Recovery suits discovery; fail-closed suits semantic work; neither has a symbol table | Two adapters to maintain; mitigated by one shared `PascalParserAdapter` contract |
| FPC fixed as **external process only** | Compiler is GPL; process invocation avoids creating a combined work | Permanent design constraint — linking FPC requires a new ADR |
| Capability states made **platform-scoped** | `ComObj` passes on Windows, fails on Linux for identical source | Every capability is a `(construct, mode, platform)` triple |
| Container pinned **by digest** | Reproducibility requirement | Re-pinning is an explicit, reviewed action |

---

## 8. Feasibility verdict

**Feasible — proceed to P1.**

**Established:** a reproducible, cross-OS compiler oracle at FPC 3.2.2; two
parser candidates that each accept 24/24 fixtures with measurably different
recovery/span behaviour; licence boundaries understood from primary sources;
dialect gaps enumerated with probe evidence; 16 programs executed with real
exit codes.

**Not established (and not claimed):** any conversion, any IR, any Delphi
equivalence, any `VERIFIED` capability state. P0 proved the *tools* work, not
that the *transformation* works.

**Proceed to P1** (`P1_TASKS.md`) subject to the validation review of this
working tree. No commit or push has been made.

---

## 9. Reproduce everything

```powershell
# dialect probes -> docs/p0/evidence/probes.txt
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\probes.ps1

# compiler sweeps -> fpc-host.txt / treesitter.txt / delphiast.txt
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\sweep-fpc.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\sweep-treesitter.ps1 -GrammarDir <clone> -MingwBin <mingw64\bin>
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\sweep-delphiast.ps1  -Harness <delphiast_eval.exe>

# pinned container -> fpc-docker.txt
docker run --rm -v <repo>:/repo:ro freepascal/fpc:3.2.2-bookworm-full `
  bash /repo/tools/p0/sweep-fpc-docker.sh

# execution -> fpc-run.txt
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\run-fpc.ps1

# parser time/memory -> parser-performance.txt
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\measure-parsers.ps1 `
  -TreeSitterExe <tree-sitter.exe> -GrammarDir <clone> -MingwBin <mingw64\bin> -DelphiASTHarness <harness>

# parser recovery/spans -> parser-recovery.txt
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\probe-recovery.ps1 `
  -TreeSitterExe <tree-sitter.exe> -GrammarDir <clone> -MingwBin <mingw64\bin> -DelphiASTHarness <harness>
```

**Note:** use the real `node_modules\tree-sitter-cli\tree-sitter.exe`, not the
`.cmd` shim (the shim runs `node cli.js` and pollutes memory measurement). Run
sweeps with `powershell.exe` (Windows PowerShell 5.1) — `pwsh` is not installed.

---

## 10. Deliverables

**`docs/p0/`** — `FEASIBILITY_REPORT.md` (this file) ·
`DIALECT_COMPILER_MATRIX.md` · `PARSER_EVALUATION.md` ·
`TOOLCHAIN_FEASIBILITY.md` · `LICENCE_REVIEW.md` ·
`SEMANTIC_IR_REQUIREMENTS.md` · `P1_TASKS.md`

**`docs/p0/evidence/`** — `probes.txt` · `fpc-host.txt` ·
`fpc-host-prefix.txt` · `fpc-docker.txt` · `fpc-run.txt` ·
`treesitter.txt` · `delphiast.txt` · `parser-performance.txt` ·
`parser-recovery.txt` · `tool-versions.txt` · `fixture-fixes.md` ·
`delphiast-fpc-helper-recursion.patch` — all UTF-8 no-BOM.

**`docs/decisions/`** — index + ADRs `0001`–`0005` (parser selection, licence
decisions, target Java version, database policy, no-LLM CI gate).

**`tools/p0/`** — `probes.ps1` · `sweep-fpc.ps1` · `sweep-treesitter.ps1` ·
`sweep-delphiast.ps1` · `sweep-fpc-docker.sh` · `run-fpc.ps1` ·
`measure-parsers.ps1` · `probe-recovery.ps1`.

**`corpus/`** — 24 fixtures + `README.md` expectation contract.
