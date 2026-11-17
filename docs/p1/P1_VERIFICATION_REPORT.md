# P1 Verification Report — Secure Ingestion and Deterministic Discovery

**Phase:** P1 of the roadmap (see `README.md` §Roadmap)
**Contract:** `docs/p0/P1_TASKS.md` (A1–A5, B1–B5, C1–C3, D1–D4, E1–E5; F explicitly deferred)
**Design:** `docs/p1/P1_IMPLEMENTATION_PLAN.md`
**Date:** 16 November 2026
**Git state:** P0 committed as `fbf59d2`; **P1 is not committed and not pushed** — this report is produced for review before any commit.

---

## 1. Verdict

**P1 is complete against its contract, with two owner blockers carried forward.**

| | |
|---|---|
| Tests | **612 passed, 0 failed** (`python -m pytest tests -q`) — 438 unit, 32 integration, 142 security |
| No-LLM guard | **PASS**, 0 findings (`python tools/p1/cli.py guard --root .`, exit 0) |
| Host corpus sweep | **24/24 MATCH**, 0 MISMATCH, exit 0 (`fpc.exe:3.2.2`) |
| Container corpus sweep | **24/24 MATCH**, 0 MISMATCH, exit 0 (`fpc:3.2.2`, digest-pinned image) |
| Gate failure path | **proven**, not assumed — a deliberately wrong expectation produced `MISMATCH=1` and exit 1 |
| Unverified | the GitHub Actions workflow (written, never executed — nothing is pushed) |
| Blocked | **A1** (project licence) and **A2** (DelphiAST upstream notification) need owner decisions |

No `VERIFIED` capability state is claimed anywhere; the Delphi lane remains `ORACLE_UNAVAILABLE`.

---

## 2. What was delivered, against the contract

### A — P0 carry-over

| ID | Status | Evidence |
|---|---|---|
| A1 project licence + notices | **BLOCKED — owner decision** | no `LICENSE` exists and none can be invented; `docs/p0/LICENCE_REVIEW.md` stands as the third-party record |
| A2 notify DelphiAST upstream | **BLOCKED — owner decision** | no upstream link can be raised from here; the recorded default is in-repo patch maintenance (`docs/p0/PARSER_EVALUATION.md`, `docs/p0/fixture-fixes.md`) pending a named owner |
| A3 `tp` / `iso` fixtures swept on host **and** container | **DONE** | `corpus/dialects/turbo/tp_point.pas`, `corpus/dialects/iso7185/hello_iso.pas` → `PASS` in both `docs/p1/evidence/fpc-host-p1.txt` and `fpc-container-p1.txt` |
| A4 `-Baseline` archive mode | **DONE** | `tools/p0/sweep-fpc.ps1 -Baseline <file>`, `tools/p0/sweep-fpc-docker.sh --baseline <file>`, `tools/p1/sweep.py --out <file>`; all refuse to overwrite an existing archive (tested) |
| A5 README updated | **DONE** | status, capability, dialect matrix, architecture, workflow, stack, structure, prerequisites, commands, testing, security, limitations, roadmap and references all re-stated against evidence |

### B — Ingestion and secure input

| ID | Status | Evidence |
|---|---|---|
| B1 secure ZIP ingestion | **DONE** | `tools/p1/zipingest.py`, `pathsafe.py`, `limits.py`; `tests/security/test_adversarial_archives.py` |
| B2 secure Git input | **DONE** | `tools/p1/gitingest.py`; `tests/security/test_git_ingestion.py`; commit-pinned re-ingestion is byte-identical |
| B3 hashing + classification | **DONE** | `tools/p1/hashing.py`, `classify.py`; SHA-256 over original bytes, encoding detection, unknown types preserved |
| B4 project root detection | **DONE** | `tools/p1/projects.py`; roots carry the evidence that justified them; ambiguity → `AMBIGUOUS_PROJECT_ROOT` / `MULTIPLE_PROJECT_ROOTS`, never a guess |
| B5 app-shape detection | **DONE** | shapes `console`, `gui_vcl`, `gui_lcl`, `gui_fmx`, `service`, `library`, `package`, `unknown`, each with evidence, confidence (`high`/`medium`/`low`) and status (`SUPPORTED`/`PARTIAL`/`UNKNOWN`) |

### C — Profiles

| ID | Status | Evidence |
|---|---|---|
| C1 build/compiler profile model | **DONE** | mode, defines, platform, unit paths, range/overflow checks, app type, output kind and sources are first-class fields; flags are derived deterministically (`-Mobjfpc -d… -Fu…`) |
| C2 per-platform capability scoping | **DONE** | `tools/p1/statuses.py` makes every state a `(construct, mode, platform)` triple; the Windows/Linux `ComObj` delta appears as `dbaccess/ado_style_connection.pas` `PASS` on Windows, `FAIL-DEPENDENCY` on Linux |
| C3 mode-dependent symbol visibility | **DONE** | `tools/p1/dialects.py` carries a per-mode `bare_assignfile_visible` table sourced from `probes.txt`, with `None` (→ `UNKNOWN`) wherever P0 did not probe — no invented facts |

### D — Discovery outputs

| ID | Status | Evidence |
|---|---|---|
| D1 `application-manifest.json` | **DONE** | versioned `p1.application-manifest/1.0`, 20 top-level keys, every field traces to a file hash or probe |
| D2 `dependency-graph.json` | **DONE** | versioned `p1.dependency-graph/1.0`; unresolved edges preserved with a reason (`missing-unit`, platform-absent, external) — never pruned |
| D3 human-readable report | **DONE** | `tools/p1/emit.py::render_report` renders the *serialised* JSON, so report and manifest cannot disagree |
| D4 unknown file types preserved | **DONE** | `Classification.preserved` and `discovery_only` (`classify.py`); non-Pascal assets are inventoried and carried through |

### E — Tests and gates

| ID | Status | Evidence |
|---|---|---|
| E1 archive adversarial tests | **DONE** | traversal, absolute paths, backslash escape, symlink, special files, submodules, duplicates, entry/total size, compression ratio, zero-byte, encoding bomb, non-ZIP |
| E2 deterministic discovery | **DONE** | `tests/integration/test_determinism.py` — same input ⇒ byte-identical manifest and graph |
| E3 no-LLM guard | **DONE** | `tools/p1/guard.py` + `tests/security/test_no_llm_guard.py`; scans `tools/`, `tests/`, `scripts/`, `.github/`; CI step present |
| E4 no-silent-drop | **DONE** | `tests/security/test_no_silent_drop.py` — unknown syntax and exclusions always become located diagnostics |
| E5 fixture-corpus regression gate | **DONE (locally)** | `corpus/expectations.txt` + `tools/p1/sweep.py` (one comparator for host and container) + both P0 sweeps; CI workflow written — see §7 |

### F — Deferred

Semantic IR, symbol/type resolution, control flow, worker adapters, any `VERIFIED` state, Delphi equivalence claims and pathological-input parser robustness all remain deferred exactly as `docs/p0/P1_TASKS.md` §F requires. No attempt was made to pull them forward.

---

## 3. Changed-file inventory

Nothing under `docs/p0/` or `corpus/` (other than the new `expectations.txt`) was altered; no P0 history was rewritten.

**Modified — 3**

| File | Change |
|---|---|
| `README.md` | A5: status, capabilities, dialect matrix, architecture, workflow, stack, structure, prerequisites, installation, configuration, commands, testing, security, limitations, roadmap, references |
| `tools/p0/sweep-fpc.ps1` | A4: `-Baseline <file>` archive mode (UTF-8 no-BOM, refuses overwrite) |
| `tools/p0/sweep-fpc-docker.sh` | E5: expectations read from `corpus/expectations.txt` instead of a hard-coded table; `--baseline <file>`; **exits 1 on any `MISMATCH`** (previously it always exited 0) |

**New — root / corpus / CI (3)**

| File | Purpose |
|---|---|
| `.gitignore` | keeps `__pycache__/` and `.pytest_cache/` out of a future commit |
| `corpus/expectations.txt` | single source of truth for fixture verdicts (24 entries + a `linux=` platform override) |
| `.github/workflows/p1-gates.yml` | pytest + guard + host sweep + container sweep; every step fails the build |

**New — `tools/p1/` (22 files)**

`__init__.py` · `errors.py` · `limits.py` · `pathsafe.py` · `hashing.py` · `zipingest.py` · `gitingest.py` · `model.py` · `classify.py` · `plex.py` · `dialects.py` · `projects.py` · `metadata.py` · `deps.py` · `graph.py` · `statuses.py` · `emit.py` · `pipeline.py` · `cli.py` · `guard.py` · `sweep.py` · `run_gates.ps1`

**New — `tests/` (14 files)**

`conftest.py` · `unit/`: `test_classify.py`, `test_deps.py`, `test_dialects.py`, `test_graph.py`, `test_hashing.py`, `test_projects.py`, `test_sweep.py` · `integration/`: `test_pipeline.py`, `test_determinism.py` · `security/`: `test_adversarial_archives.py`, `test_git_ingestion.py`, `test_no_llm_guard.py`, `test_no_silent_drop.py`

**New — `docs/p1/` (4 files)**

`P1_IMPLEMENTATION_PLAN.md` · `P1_VERIFICATION_REPORT.md` (this file) · `evidence/fpc-host-p1.txt` · `evidence/fpc-container-p1.txt`

**Test-fixture boundary:** P1 fixtures live in `tests/fixtures/p1/` only. `corpus/` remains P0's golden corpus and was not used as a dumping ground for test inputs.

---

## 4. Test results

```
python -m pytest tests -q
612 passed, 1 warning in 35.04s
```

| Suite | Tests | Focus |
|---|---|---|
| `tests/unit/` | 438 | path safety, limits, hashing/encoding, classification, scanning, dialects, visibility table, profiles, shapes, dependency graph, capability states, report emission, the corpus gate |
| `tests/integration/` | 32 | end-to-end console / ambiguous / GUI trees; determinism (byte-identical reruns) |
| `tests/security/` | 142 | adversarial archives, Git attack surface, no-silent-drop, no-LLM guard |

The single warning is `UserWarning: Duplicate name: 'a.pas'` emitted by CPython's own `zipfile` while *constructing* a hostile archive in a test — it is the test fixture being adversarial, not a product warning.

**Authoritative fixture outputs asserted by the tests** (so a regression cannot quietly change them):

- *Console tree* — classification `{binary:1, documentation:2, pascal_include:1, pascal_program:1, pascal_project:1, pascal_unit:3, sql:1}`; one root `src/MiniApp.dpr`, primary `SUPPORTED`, entry `src/MiniApp.dpr:1:9`; profile `mode=objfpc`, `platform=Win32`, `app_type=console`; graph **12 nodes / 14 edges / 6 resolved / 8 unresolved**; diagnostics exactly `COMPILER_SIGNAL_CONFLICT`; 40 capability states ∈ {`PARTIAL`, `SUPPORTED`, `UNAVAILABLE`, `UNSUPPORTED`}, **no `VERIFIED`**.
- *Ambiguous tree* — two roots, both `UNKNOWN` and `primary:false`, `MULTIPLE_PROJECT_ROOTS` at line 1, blockers `AMBIGUOUS_PROJECT_ROOT` ×2, both entry-point edges resolved.
- *GUI tree* — root `lcl/App.lpr` primary `SUPPORTED`, shape `gui_lcl/high/SUPPORTED`, blocker `GUI_SHAPE_DETECTED`; graph **9 nodes / 9 edges / 2 resolved / 7 unresolved**; framework gaps `{unit:controls, unit:forms, unit:graphics, unit:interfaces}`.

---

## 5. Gate results and recorded evidence

| Gate | Command | Result |
|---|---|---|
| Tests | `python -m pytest tests -q` | 612 passed |
| No-LLM guard | `python tools/p1/cli.py guard --root .` | `gate: PASS (findings: 0)`, exit 0 |
| Host sweep | `python tools/p1/sweep.py --host` | `SUMMARY\|fixtures=24\|expected=24\|MATCH=24\|MISMATCH=0`, exit 0 |
| Container sweep | `python tools/p1/sweep.py --docker` | same, exit 0 |
| All four in order | `powershell -File tools\p1\run_gates.ps1` | `GATE\|PASS\|all gates green` |

Archived runs (UTF-8 no-BOM, CRLF, matching the P0 evidence convention):

- `docs/p1/evidence/fpc-host-p1.txt` — `SWEEP|platform=windows|fixtures=24|compiler=fpc.exe:3.2.2`
- `docs/p1/evidence/fpc-container-p1.txt` — `SWEEP|platform=linux|fixtures=24|compiler=fpc:3.2.2`

The pinned image was pulled and its digest **verified against the pin**: `sha256:6c951541251e24e67d358ec7a5b2dfb3121069cdf73fd0252226868dbecd3872`.

**The gate was proven to fail, not merely proven to pass.** A temporary copy of the corpus with `language/variant_record.pas` declared `FAIL-DEPENDENCY` (when it compiles) produced:

```
EXPECTATION|language/variant_record.pas|expected=FAIL-DEPENDENCY|actual=PASS|MISMATCH
SUMMARY|fixtures=24|PASS=20|FAIL=4|MATCH=23|MISMATCH=1
exit=1
baseline exists: True  (51 lines: TOOL, PLATFORM, 24×RESULT, 24×EXPECTATION, SUMMARY)
```

`bash -n` syntax-checks the container script clean; both PowerShell scripts parse with 0 errors via `[Parser]::ParseFile`.

---

## 6. Security findings

### 6.1 A real product bug, found by the new tests and fixed

`emit._merge_diagnostics` called `diagnostic.as_dict()` on `item.scan.diagnostics`, but `plex` fills that list from `DiagnosticSink.to_list()`, which returns **plain dicts**. The consequence was that **any Pascal source containing a lexer diagnostic crashed the whole pipeline** at report-writing time with `AttributeError` — a malformed or hostile input causing a hard failure instead of a located diagnostic.

- Fix: accept both shapes, copy before annotating with the file path (`tools/p1/emit.py`).
- Root cause removed: `plex.ScanResult.diagnostics` is now annotated `list[dict[str, object]]` with a comment naming `DiagnosticSink.to_list()` as its source, and the now-unused `Diagnostic` import was dropped (`tools/p1/plex.py`).
- Regression coverage: `tests/security/test_no_silent_drop.py` exercises a file whose only content is unknown syntax and asserts the diagnostic carries `code`, `file`, `line` and `column`.

This is exactly the class of defect E4 exists to catch, and it was invisible until an end-to-end path ran a file with a diagnostic.

### 6.2 Controls verified as working

| Threat | Result |
|---|---|
| Zip-slip / `..` / absolute / backslash paths | refused before extraction; staging root cannot be escaped |
| Symlink and hardlink entries | `SYMLINK_ENTRY`, never followed |
| Device / FIFO / socket entries | `SPECIAL_FILE_ENTRY`, refused |
| Submodule entries | `SUBMODULE_ENTRY`, refused |
| Zip bomb | per-entry, total and ratio limits; `ZIP_BOMB_RATIO`, `ENTRY_TOO_LARGE`, `TOTAL_TOO_LARGE` |
| Oversize / too many entries | `LIMIT_EXCEEDED`, `TOO_MANY_ENTRIES` |
| Duplicate entries | `DUPLICATE_ENTRY`, refused (never last-writer-wins) |
| Non-ZIP or unreadable input | `NOT_A_ZIP`, `INPUT_UNREADABLE` |
| Git: network clone | **refused** — `REMOTE_INPUT_UNSUPPORTED`; local path and `file://` only |
| Git: hook execution | impossible — hookless template, `--no-checkout`, `--no-recurse-submodules`, `--no-local`, scrubbed environment |
| Git: forged commit | `INVALID_COMMIT_PIN` unless 40-hex; `COMMIT_NOT_FOUND` / `COMMIT_MISMATCH` otherwise |
| Execution of uploaded binaries or scripts | never performed by the pipeline |
| Silent data loss | every exclusion/truncation is a diagnostic; `DIAGNOSTICS_TRUNCATED` when the sink is full |
| Model / AI constructs in the product | ADR 0005 guard, 0 findings |

Original source files and their bytes are preserved: SHA-256 is taken over exactly what was ingested, and the pipeline never writes into the input.

### 6.3 Design notes worth recording

- The guard only scans paths under `tools/`, `tests/`, `scripts/` and `.github/`; a manifest at the repository root is therefore *not* visited, and a file named `guard.py.bak` is not a scannable source suffix. Both were mistaken for bugs while writing tests and are now documented behaviour with tests that pin them.
- `UNRESOLVED_UNIT_REFERENCES` fires only for `missing-unit` edges. RTL, database and framework gaps legitimately produce no diagnostic — verified, not a defect.
- `metadata.build_requirements` returns `PARTIAL`/`UNKNOWN` and never `SUPPORTED`, and emits `COMPILER_SIGNAL_CONFLICT` when a project file and its sources disagree.

---

## 7. Unverified items (stated, not glossed)

1. **`.github/workflows/p1-gates.yml` has never executed.** GitHub Actions cannot run here and pushing is prohibited. The YAML parses (PyYAML), and *every command it runs* was executed locally on this machine, but the workflow itself is `IMPLEMENTED, NOT VERIFIED`. It is pinned to `ubuntu-24.04` and installs FPC via `apt`; a future run may still reveal an environment difference (PowerShell-on-Linux behaviour, apt FPC packaging).
2. **Actions are referenced by major tag (`@v4`, `@v5`), not by commit SHA.** Pinning to SHAs would be stronger supply-chain hygiene; it was not done because no SHA could be verified offline.
3. **No Delphi compiler exists in this environment**, so no Delphi-equivalence statement and no `VERIFIED` state is possible. FPC's `-Mdelphi` is a proxy only.
4. **A1 and A2 are unresolved** and cannot be resolved by the agent.

---

## 8. Remaining limitations

Carried forward in `README.md` §Current limitations, summarised:

- P1 is **not committed**; P2–P8 have not started; **no Java is generated**.
- Dialect detection is evidence-based (`{$MODE}` → project settings → extension) and reports `unknown` when it has no signal; Turbo Pascal and ISO 7185 need `{$MODE tp}` / `{$MODE iso}` to be recognised as such.
- **LCL/VCL unit-name collision:** `lcl/uMainForm.pas` in the GUI fixture is labelled `framework: vcl` because both frameworks use the same unit names. Whole-tree shape detection still resolves to `gui_lcl` (it counts references), but per-file framework labelling is unreliable for mixed trees.
- Build-requirement inference is conservative by design (`PARTIAL`/`UNKNOWN` only).
- GUI conversion remains an explicit non-goal; binary-only components are classified, never decompiled; a DB inventory list is not a support claim.
- No `LICENSE` exists, so nothing in this repository may be distributed or claimed as licensed.

---

## 9. Recommended next phase

**Do not start P2 without explicit approval.** The recommended sequence:

1. **Owner decisions first:** A1 (choose and commit a `LICENSE` + third-party notices) and A2 (raise the DelphiAST issue, or formally adopt in-repo patch maintenance with a named owner). Both are cheap and both unblock honest reporting.
2. **Commit P1** as a single reviewed commit (no history rewriting, nothing pushed) after this report is reviewed.
3. **Run the CI workflow once** after the first push and record the result, flipping the workflow from `IMPLEMENTED, NOT VERIFIED` to `IMPLEMENTED AND TESTED`.
4. **Then start P2 — Frontends and Semantic IR** (`docs/p0/P1_TASKS.md` §F: dialect adapters, directive/preprocessor model, unit graph, symbol/type resolution, control-flow/effects, IR versioning), keeping the P1 gates green as the regression floor. Any attempt to pull a deferred item forward requires an ADR.

---

## 10. Reproducing this report

```powershell
python -m pytest tests -q                       # 612 passed
python tools/p1/cli.py guard --root .           # gate: PASS (findings: 0)
python tools/p1/sweep.py --host                 # MATCH=24 MISMATCH=0, exit 0
python tools/p1/sweep.py --docker               # MATCH=24 MISMATCH=0, exit 0
powershell -File tools\p1\run_gates.ps1         # GATE|PASS|all gates green
```

`tools/p1/run_gates.ps1 -SkipContainer` (or `-SkipSweep`) exists for machines without Docker or FPC; a skipped gate is printed as `SKIP` and never as `PASS`, and CI does not use those switches.
