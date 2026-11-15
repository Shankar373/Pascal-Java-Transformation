# P0 Final Review Report

**Scope:** feasibility + architecture freeze only. No P1 implementation has started.
**Review date:** 2026-11-13
**Git state:** `main` = `3bbba10`; `corpus/`, `docs/`, `tools/` are untracked. **0 tracked files modified.**
**Commit status:** not committed, not pushed — awaiting explicit approval.

---

## 1. File inventory — 66 files

| Area | Files | Contents |
|---|---:|---|
| `corpus/` | 29 | 28 fixtures across 9 categories + `README.md` |
| `docs/` | 27 | 8 P0 documents (incl. this report), 5 ADRs + ADR index, 13 evidence files |
| `tools/` | 10 | 8 sweep/probe scripts, 1 shared helper, 1 path-quoting test |
| **Total** | **66** | |

<details>
<summary>Full listing</summary>

**corpus/ (29)**
```
corpus/README.md
corpus/applications/console_multiunit/   miniapp.dpr · uMath.pas · uReport.pas
corpus/applications/lazarus_app/         lazarusapp.lpr · uMainForm.pas
corpus/applications/project_files/       delphi_style_app.dpr · delphi_style_app.dproj
                                         lazarusapp.lpi · legacy_pack.dpk
corpus/dbaccess/                         ado_style_connection.pas · bde_style_query.pas
                                         embedded_sql.pas
corpus/dialects/delphi/                  DelphiClasses.pas
corpus/dialects/fpc/                     mode_objfpc.pas
corpus/dialects/iso7185/                 hello_iso.pas
corpus/dialects/turbo/                   tp_point.pas
corpus/directives/                       directive_ifdef.pas · directive_include.pas
                                         directive_range_checks.pas · include_shared.inc
corpus/language/                         currency_math.pas · exception_flow.pas · file_io.pas
                                         NestedRoutines.pas · pointer_alloc.pas
                                         records_sets.pas · string_kinds.pas
                                         variant_record.pas
```

**docs/ (26)**
```
docs/p0/                DIALECT_COMPILER_MATRIX · FEASIBILITY_REPORT · LICENCE_REVIEW
                        P1_TASKS · PARSER_EVALUATION · SEMANTIC_IR_REQUIREMENTS
                        TOOLCHAIN_FEASIBILITY · P0_REVIEW_REPORT (this file)
docs/p0/evidence/       delphiast.txt · delphiast-fpc-helper-recursion.patch · fixture-fixes.md
                        fpc-docker.txt · fpc-host.txt · fpc-host-prefix.txt · fpc-run.txt
                        mode-claims.txt · parser-performance.txt · parser-recovery.txt
                        probes.txt · tool-versions.txt · treesitter.txt
docs/decisions/         README.md · 0001-parser-adapter-selection · 0002-licence-decisions
                        0003-target-java-version · 0004-database-policy
                        0005-no-llm-ci-gate
```

**tools/ (10)**
```
tools/p0/probes.ps1               semantic/language probe compiler sweep
tools/p0/sweep-fpc.ps1            host FPC 3.2.2 compile sweep
tools/p0/sweep-fpc-docker.sh      pinned-container compile sweep (oracle)
tools/p0/sweep-treesitter.ps1     tree-sitter parse sweep
tools/p0/sweep-delphiast.ps1      DelphiAST parse sweep
tools/p0/run-fpc.ps1              execute compiled programs, record behavior
tools/p0/probe-recovery.ps1       malformed-input recovery probes
tools/p0/measure-parsers.ps1      parser time/memory measurement
tools/p0/NativeArgument.ps1       shared MSVC-convention argument quoter   [NEW]
tools/p0/test-path-quoting.ps1    path/quoting test suite                  [NEW]
```
</details>

---

## 2. Changes made during this finalization review

Every change below was made to **P0's own artifacts** — no user work was touched, nothing deleted.

### 2.1 Corpus fixtures (2 content edits, 1 new evidence file)

| # | File | Change | Why it is legitimate |
|---|---|---|---|
| 1 | `corpus/applications/project_files/delphi_style_app.dproj` | `..\dialects\delphi\DelphiClasses.pas` → `..\..\dialects\delphi\DelphiClasses.pas` | Reference resolved to `corpus/applications/dialects/…`, which does not exist. Invisible to every sweep because `.dproj` is `DISCOVERY-ONLY` — no tool ever resolved the path. The `.dpk` in the same directory was already correct, which is what made the discrepancy detectable. |
| 2 | `corpus/directives/directive_range_checks.pas` | Corrected the boundary comment | The comment asserted `32000+767` overflows `SmallInt`. It equals **32767**, exactly `SmallInt` max — in range, hence `exit=0`. The fixture behavior was already correct; only the comment lied. |
| 3 | `docs/p0/evidence/mode-claims.txt` | **New** — `SUMMARY\|tested=6\|pass=6\|fail=0` | `hello_iso.pas` and `tp_point.pas` claimed `{$MODE}` / `{$H+}` behavior in their headers. Each claim was compiled under all applicable compiler modes and now has recorded evidence instead of an unverified assertion. |

No fixture was ever edited to make a tool pass; all fixture edits are logged in `docs/p0/evidence/fixture-fixes.md`.

### 2.2 Tool fixes

| # | File | Change |
|---|---|---|
| 4 | `tools/p0/NativeArgument.ps1` | **New.** `ConvertTo-NativeArgument` implements the MSVC / `CommandLineToArgvW` quoting convention (N backslashes before a quote → 2N + `\"`; trailing backslashes doubled; every argument always quoted). Dot-sourced by both consumers so the logic cannot drift. |
| 5 | `tools/p0/measure-parsers.ps1` | Replaced hand-rolled `'"' + $arg + '"'` with the shared quoter. **This was a real defect** (the one named in the review instructions). |
| 6 | `tools/p0/run-fpc.ps1` | Same fix at line 119. **This was the second real instance** — not `probe-recovery.ps1`. |
| 7 | `tools/p0/test-path-quoting.ps1` | **New** — 16-test suite (§3.1). |
| 8 | 8 scripts: `measure-parsers`, `run-fpc`, `sweep-fpc`, `sweep-treesitter`, `sweep-delphiast`, `probe-recovery`, `probes`, `test-path-quoting` | `Resolve-Path`, `Get-ChildItem` and `Test-Path` switched to `-LiteralPath`. **New defect found by writing the path test** — see §4.2. |

### 2.3 Documentation

| # | File | Change |
|---|---|---|
| 9 | `docs/p0/evidence/fixture-fixes.md` | Added a note that this fix log quotes **pre-fix paths by design** (4 occurrences that deliberately no longer resolve), and recorded the `.dproj` depth defect as §8b with a before/after existence table. |

---

## 3. Test results

### 3.1 Path / quoting test — **16 / 16 PASS**

```
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\test-path-quoting.ps1
```

| Section | Tests | Covers |
|---|---:|---|
| `UNIT` | 11 | Exact quoter output, incl. cases impossible as Windows filenames (embedded `"`, trailing `\`, `\` before `"`, empty argument, tab, `%`, `^`, `#`, `[draft]`) |
| `ROUND` | 3 | Real child (`fpc.exe`) receives the exact path from a corpus under `p0 quote test (v2) & [draft] #1\`; trailing-separator output dir; `CommandLineToArgvW` control |
| `SCRIPT` | 2 | `run-fpc.ps1` and `measure-parsers.ps1` executed against a corpus copied under that same bracketed path |

`SUMMARY|tested=16|pass=16|fail=0|skip=0`

**The control is what proves the fix matters:** under `CommandLineToArgvW`, the old encoding of a trailing-backslash path yields **9 garbled arguments** (`-FE` value split across 7 pieces, `-FU` destroyed); the new encoding yields **exactly the 4 correct arguments**.

> **FPC caveat:** fpc's own argv parser is lenient (backslash-literal), so it tolerated the old encoding. That is why `CommandLineToArgvW` — the rule `tree-sitter.exe` and MSVC-built binaries follow — is used as the oracle for the control, not fpc.

### 3.2 Reproducibility — all six sweeps reproduce

Each rerun output was normalized (timing fields, CRLF) and compared line-by-line against the recorded evidence.

| # | Sweep | Result |
|---|---|---|
| 1 | `probes.ps1` | **MATCH** — 22 / 22 lines |
| 2 | `sweep-fpc.ps1` | **MATCH** — 24 / 24 lines |
| 3 | `sweep-treesitter.ps1` | **MATCH** — 24 / 24 lines |
| 4 | `sweep-delphiast.ps1` | **MATCH** — 24 / 24 lines |
| 5 | `run-fpc.ps1` | **MATCH** — 24 / 24 lines |
| 6 | `sweep-fpc-docker.sh` | **IDENTICAL** — 51 / 51 script lines |

**Docker provenance re-verified live:**

| Field | Recorded | Actual |
|---|---|---|
| `DOCKER\|` | 29.8.2 | `Docker version 29.8.2, build 7fc2dff` ✓ |
| `DIGEST\|` | `sha256:6c951541…3872` | `freepascal/fpc@sha256:6c951541…3872` ✓ |
| `SUMMARY\|` | `fixtures=24\|PASS=20\|FAIL=4\|MATCH=24\|MISMATCH=0` | identical ✓ |

The 6-line provenance header (`IMAGE`/`DIGEST`/`DOCKER`/`MOUNT`/`SCRIPT`/blank) is part of the recorded evidence file but is not emitted by the raw `docker run` — that accounts for the 56-vs-51 line difference. With it stripped, the two are byte-identical and **0 rerun lines are absent from the evidence**.

Additionally, the two tools whose scripts changed in this review were re-run:

| Tool | Result |
|---|---|
| `probe-recovery.ps1` | **IDENTICAL** — 15 / 15 lines, 0 differing |
| `measure-parsers.ps1` | **Structurally identical** — 54 / 54 lines after normalizing timings |

### 3.3 Security / prohibited-dependency verification

| Check | Result |
|---|---|
| Secret-shaped literals (passwords, API keys, tokens, private-key headers) | **0** |
| Credential-shaped literals | **1** — synthetic `ado_style_connection.pas` fixture: `Provider=SQLOLEDB;Data Source=legacy;Initial Catalog=sales;` — no user, no password |
| Dependency manifests added (`package.json`, `pom.xml`, `requirements.txt`, …) | **0** — P0 added none |
| Model-weight / binary blobs (`.pt`, `.gguf`, `.onnx`, `.safetensors`, …) | **0** |
| LLM / inference integration in executable files | **0** |
| No-LLM policy prose | 8 hits — these are the guardrail describing itself (`README.md`, ADR `0005-no-llm-ci-gate`) |
| Build artifacts leaked into repo (`.ppu`, `.o`, `.exe`, …) | **0** |
| Stray temp directories in repo | **0**; leftover `%TEMP%` test dirs also **0** |
| Evidence files UTF-8 without BOM | 13 / 13 ✓ |

### 3.4 Structural integrity

| Check | Result |
|---|---|
| Cross-references in Markdown (docs/corpus/tools paths) | 30 checked, **5 intentional non-resolving** (all inside `fixture-fixes.md`, which is a fix log and by design quotes pre-rename names and the recorded broken path), **0 unexpected missing** |
| PowerShell parse check, all 9 `.ps1` | **0 errors** |
| Tracked files modified | **0** |

---

## 4. Findings that differ from the review instructions

### 4.1 `probe-recovery.ps1` has no argument-quoting defect

The instruction named `measure-parsers.ps1` and `probe-recovery.ps1` as the two defect sites. Inspection showed:

- `measure-parsers.ps1` — **confirmed defect**, built `ProcessStartInfo.Arguments` as `'"' + $arg + '"'`. Fixed.
- `probe-recovery.ps1` — **no such code.** It invokes children through PowerShell's call operator (`& $TreeSitterExe parse $file`), never building an argument string. Only the `-LiteralPath` conversion (§4.2) applied to it.
- `run-fpc.ps1:119` — **the actual second instance**, same pattern. Fixed.

The fix was therefore applied to the two sites where the defect exists, rather than to the two sites named.

### 4.2 A second, previously unknown defect: wildcard path expansion

Writing the path test exposed a defect class no sweep could have caught:

Every P0 script resolved paths with the **wildcard** parameter sets — `Resolve-Path $Corpus`, `Get-ChildItem -Path $Corpus`, `Test-Path $Path`. On a corpus directory containing `[draft]`, these behave as character-class globs:

| Call | Result on `…\p0 quote test (v2) & [draft] #1\corpus` |
|---|---|
| `Get-ChildItem -Path` | **0 files** — sweep would silently report no fixtures |
| `Resolve-Path -Path` | **empty** — script entry point would throw under `$ErrorActionPreference = 'Stop'` |
| `Test-Path -Path` | **False** — even for a directory that exists |
| `Get-ChildItem -LiteralPath` | 1 file ✓ |

All 8 scripts were converted to `-LiteralPath` for user-supplied paths. After the fix, both script-level tests in §3.1 pass with the corpus living under a bracketed path.

### 4.3 Two PowerShell traps recorded for P1

Both were hit while writing the test and are now documented in-code:

1. **`,` binds tighter than `+`.** `@('-FE' + $a, '-FU' + $b)` parses as `'-FE' + @($a,'-FU',$b)` — the array is stringified with `$OFS` (a single space) and the whole thing collapses to **one string**. Every concatenation inside an array literal must be parenthesized: `@(('-FE' + $a), ('-FU' + $b))`.
2. **`return ,$arr` yields a nested array** whose `.Count` is 1 regardless of the real element count, silently corrupting downstream comparisons.

Both are now caught: the test was corrected, and a repo-wide scan confirms no other script exhibits either pattern.

---

## 5. Remaining limitations

### Blocking for later phases (not blocking P0)

| # | Limitation | Impact |
|---|---|---|
| L1 | **Delphi is not installed.** `ORACLE_UNAVAILABLE`. | Delphi-specific behavior (VCL units, `{$MODE DELPHI}` edge cases, Delphi 10.x language features) has no second oracle. Recorded as a P1 carry-over assumption. |
| L2 | **A parse pass is `NOT_VERIFIED`, never `VERIFIED`.** | Parser/tool feasibility is fully evidenced; **actual Pascal-to-Java behavioral equivalence is not**, and cannot be until P3's original-vs-Java oracle exists. This distinction is stated throughout the P0 deliverables and must not be collapsed in later phases. |
| L3 | **Expected-FAIL fixtures have no Java equivalence target yet:** `lazarusapp.lpr` / `uMainForm.pas` (`Forms`), `bde_style_query.pas` (`DBTables`), `ado_style_connection.pas` (Windows-only: PASS on host, FAIL in the Linux container). | P3 must decide translate-against-stub vs. legitimately out of scope. |

### Reproducibility caveats (environment changed since the first sweeps)

| # | Caveat | Detail |
|---|---|---|
| L4 | **gcc / cc / clang are no longer present on this machine.** Verified: `where.exe gcc` fails; no compiler found on any checked path. | The tree-sitter grammar is already built and cached at `%LOCALAPPDATA%\tree-sitter\lib\pascal.dll`, so `tree-sitter parse` works (verified exit 0). **However**, the recorded reproduction command `-MingwBin <mingw64\bin>` now points at a directory that does not exist. The rerun used `-MingwBin <repo>\tools\p0` — a valid existing directory whose only effect is a no-op `PATH` prepend. **If the cache were deleted, rebuilding the grammar would require a C compiler.** |
| L5 | **Pre-fix parser baseline gap.** The parser performance figure was recorded *before* the `.dproj` / comment / mode-claim corrections. | Timing is unaffected (corpus is byte-identical for the compiled fixtures), but no "before" number exists to diff against. |
| L6 | **Single-run timings vary ~2×.** Per-file figures include process start-up; tree-sitter batch output (2060 lines) is not volumetrically comparable to DelphiAST's (24). | Do not treat the timing columns as precise benchmarks. |

### Policy / process

| # | Item | Detail |
|---|---|---|
| L7 | **No `LICENSE` file exists.** | Deliberately not invented — all third-party licence obligations are recorded in `LICENCE_REVIEW.md` and ADR `0002`. Adding a project licence is a decision for the project owner, not for P0. |
| L8 | **`tp` / `iso` sweep coverage gap (P1 task A3) only partially closed.** | `mode-claims.txt` verifies 6 mode assertions, which addresses part of A3; full dialect-matrix sweep coverage remains open and is carried in `P1_TASKS.md`. |
| L9 | **`security-reviewer` subagent was unavailable** (free-usage limit). | The security review in §3.3 was performed inline instead. Re-invoke only if usage resets. |

---

## 6. Carry-over tasks into P1

`docs/p0/P1_TASKS.md` remains authoritative. A1–A5 are carried forward; **A3 is partially addressed** by `mode-claims.txt`.

---

## 7. Gate status

| Gate | Status |
|---|---|
| All untracked files reviewed individually | ✅ 66 files |
| Corpus fixture quality / expected outcomes / reproducibility verified | ✅ §3 |
| Argument-quoting defect fixed with safe argument passing | ✅ `NativeArgument.ps1` |
| Tests for paths with spaces + special characters | ✅ 16 / 16 |
| Six P0 sweeps rerun + security checks | ✅ all reproduce, security clean |
| No secrets / prohibited deps / model weights / LLM integrations | ✅ §3.3 |
| Final P0 review report produced | ✅ this document |
| No unrelated user work modified, deleted or pushed | ✅ 0 tracked modifications |
| **Committed** | ⛔ **NOT COMMITTED — awaiting explicit approval** |
| **P1 started** | ⛔ **NOT STARTED — gated on approval of this review** |
