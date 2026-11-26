# Stage 1 closure report

**Date:** 24 November 2026 · **Branch:** `feat/stage1-ingestion-discovery` (closure work committed after owner approval; base was `61a071b`)
**Scope of this audit:** full working tree, commit history, P0/P1 work, Stage 1 implementation, acceptance evidence, security fixes and documentation. No existing work was overwritten or removed; no test was weakened; nothing was pushed or merged; Stage 2 was not started; the COBOL repository was not modified; no project licence was selected or changed.

## 1. Verdict

**Stage 1 is functionally complete and its evidence is reproducible, with the unresolved blockers in §5 outstanding.** It is *not* closed against external validation (§6): several claims can only be verified on infrastructure this audit did not have (real Git hosts, CI, Linux, a human security review). The repository licence is an open owner decision (ADR 0006).

## 2. Verified results (re-run during this audit)

| Check | Command | Result |
|---|---|---|
| Python suite, working tree | `python -m pytest tests -q` | **1785 passed, 6 skipped, 0 failed** (187 s). Skips: symlink-creation tests needing a Windows privilege |
| Python suite, clean copy (no `.git`, caches, store, `node_modules`) | same, in a scratch copy of the tree | 1765 passed, 6 skipped, 0 failed — results do not depend on the working directory or leftover state |
| Frontend, clean `npm ci` | `typecheck`, `npm test`, `npm run build`, `npm audit --omit=dev` | typecheck clean; **93 passed**; build OK; 0 vulnerabilities |
| No-LLM guard | `python tools/p1/cli.py guard --root .` | PASS, 0 findings |
| Live service | real `uvicorn`, real `discover` | ZIP upload → 5 steps → blueprint; React UI rendered from the real job in headless Chrome (before and after the review fixes); token mode: no/bad token 401, good token 200 with a spoofed tenant header ignored; public bind without TLS refused |
| Backend coverage of new modules (coverage.py, targeted tests) | `fastapi_app` 91 %, `jobs` 91 %, `reports` 95 %, `server` 90 %, `server_security` 96 %, `tenancy` 100 %, `tenant_auth` 97 % | all ≥ 80 %. `api_main.py` had **no tests** at audit start; 13 added. Project-wide coverage is not measured |
| Frontend coverage | `vitest --coverage` | 99.7 % statements, 90.7 % branches |
| Notices drift | `python tools/release/generate_notices.py --check` + `tests/unit/test_notices.py` | current |
| Link/secret scan of tracked + new files | scripted | no broken links; no credentials; local absolute paths only in pre-existing `docs/p0/evidence`, `tools/p0` (see F-8) |
| **GitHub Actions `p1-gates` (first-ever execution, 26 Nov 2026)** | `gh run` on `ubuntu-24.04`, jobs: tests + guard / frontend / fixture sweep | **All 3 jobs green**: PR run [`45789568402`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45789568402) and post-merge `main` run [`45790563117`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45790563117) — pytest `1787 passed, 4 skipped` + guard `PASS (0 findings)`, React 93/93 + build, both sweeps `MATCH=24 MISMATCH=0`. First attempt ([`45787617127`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45787617127)) failed 7 POSIX-permission tamper-test setups → fixed `f275ca6` (test harness only) |

### Mutation checks (do the key tests actually fail?)

| Mutation (applied, test run, file restored byte-identical) | Result |
|---|---|
| `discover()` spawns a process | AC-6 non-execution test **fails** ✔ |
| Every tenant resolved to the default job manager | AC-9 isolation test **fails** ✔ |
| Token mode trusts `X-P1-Tenant` | token-binding test **fails** ✔ |

The frontend agent additionally confirmed that each new behavioural test failed against the pre-fix code (17 failures before the fixes).

## 3. Audit findings: missing, weak or misleading evidence

| # | Finding | Severity | Disposition |
|---|---|---|---|
| F-1 | `api_main.py` (the service entry point) had no tests | Medium | **Fixed** — 13 tests |
| F-2 | No code-review pass had been run beyond one security review (project rules require it) | Medium | **Done** — independent Python and React reviews run; no CRITICAL/HIGH |
| F-3 | Python review MEDIUMs: 500 responses lacked security headers; `ClientDisconnect` logged as a server fault; startup with ≥64 tenant dirs raised the wrong exception; `tenant_gate` allocated per call; artefact cap 256 MiB (memory DoS); no tenant cap on the stdlib server; `reports._needles` weaker than the blueprint's scrubber | Medium | **Fixed**, each with a test. The scrubber weakness was checked against the real Windows artefacts: no host path had leaked, so it was a latent weakness, not an observed leak |
| F-4 | React review MEDIUMs: a stale 401 could wipe a freshly entered token; polling did not resume after re-entering a token; View Report could be popup-blocked; invalid menu ARIA; tabs Home/End wrong; config error hidden; unvalidated ids in URLs | Medium | **Fixed**, each guarded by a test that failed first |
| F-5 | **Tests that could not fail** (malformed-id deep link, stale responses, Home/End, a global left mutated, an `…evil.json` filename test that codified a bug) | Medium | **Strengthened**; the wrong filename expectation was corrected (the only existing assertion changed, and why is recorded in the test) |
| F-6 | A frontend dev dependency (`user-event` 14.6.13) was 6 days old | Low | Pinned to 14.6.8 (≥ 6 weeks old); all other pinned versions are ≥ 15 days old |
| F-7 | A generated `frontend/coverage/` directory (absolute local paths) was untracked and not ignored | Low | Removed and git-ignored |
| F-8 | Pre-existing: `docs/p0/evidence/tool-versions.txt` and `tools/p0/sweep-treesitter.ps1` contain a local absolute user path | Low | **Not changed** (committed before this work); sanitise before any public release |
| F-9 | Third-party notices file was promised by ADR 0002 and never generated | Medium | **Done** — `THIRD_PARTY_NOTICES.md`, generator, drift test |
| F-10 | Counts in docs were stale/inconsistent (1,627/1,633/1,748/1,754) | Low | Updated to the verified 1,791 (1,785 + 6 skipped) and 93; the 18 Nov report is marked historical |
| F-11 | AC-8 (directory vs ZIP) asserts equal projects/dialect and a library *subset*, not full equality, because the ZIP carries planted files | Low (weak) | Documented here; a strict equality test on identical trees would be a worthwhile follow-up |
| F-12 | AC-6's watcher covers `subprocess.Popen` and `os.system/exec*/spawn*/startfile`, not `ctypes`, `multiprocessing` or `os.posix_spawn`; mutation-verified for `Popen` only | Low (weak) | Documented; the design forbids those calls and the guard test scans for them only for LLM constructs, not process APIs — a static "no process API in analysis modules" test is a recommended addition |
| F-13 | "Matches the reference mock-up" rests on one screenshot judged by eye at one viewport | Low (weak) | Stated as such; no pixel-diff or automated browser E2E |
| F-14 | Frontend commit could not be fully exercised in the per-commit simulation (only the guard ran in that step) | Low | Frontend was verified on the full working tree (clean `npm ci` → typecheck, test, build, audit) |
| F-15 | All security/code reviews were AI-agent reviews of read code; none was a human review or penetration test | Medium | See external checklist X-1 |

## 4. Baseline readiness (what Stage 2 may rely on)

Stage 1 outputs are a stable, schema-versioned contract:

* **Immutable, sealed checkpoint** `CP-<12 hex>` (`stage1.checkpoint/1.0`), verified before reuse; analysis reads it, never staging.
* **Blueprint** `stage1.application-blueprint/1.0` with a published JSON Schema, plus `unresolved-dependencies`, `diagnostics`, `dependency-graph`, `application-manifest`, `checkpoint-manifest`, `project-inventory`, `architecture-report`, `inventory.csv`, human report, `run-record.json` (only wall-clock artefact).
* **Determinism** asserted byte-for-byte across stores; **evidence** on every finding; **non-execution** asserted by test and mutation-checked.
* **Tenant-scoped storage** and optional per-tenant bearer tokens.
* **Limits stated in the artefacts themselves**: no AST/symbols/types, "SUPPORTED/PARTIAL/UNKNOWN" = scanned-or-not, not convertibility.

Stage 2 prerequisites that are **not** Stage 1 deliverables: parser SPI and profiles (ADR 0001 selects candidates), Semantic IR requirements (`docs/p0/SEMANTIC_IR_REQUIREMENTS.md`), a licensed Delphi oracle for Stage 5. Stage 2 must not start until the owner approves and the commits below are made.

## 5. Unresolved blockers and open decisions

| ID | Item | Owner/needs |
|---|---|---|
| B-1 | **Repository licence unresolved** — no root `LICENSE`; ADR 0006 records options and closure criteria. Blocks any public/customer release and any decision to port COBOL (Apache-2.0) code | Owner |
| B-2 | No external validation of Git hosting paths: SSH to a real server, HTTPS to a public TLS host, a real private repository (token path tested only against a local smart-HTTP server) | Needs credentials/hosts |
| B-3 | ~~CI workflow (`p1-gates.yml`, including the new `frontend` job) has **never run on GitHub Actions**; container fixture sweep not re-run~~ **RESOLVED 26 Nov 2026** — three jobs green on [run `45789568402`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45789568402) (PR) and [run `45790563117`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45790563117) (`main`), including both fixture sweeps; first attempt failed 7 tamper-test setups, fixed `f275ca6` | **Closed** |
| B-4 | No Linux/macOS run; all evidence is Windows 11 / Python 3.11 / Node 22 | Needs another host or CI |
| B-5 | Identity: no OIDC/RBAC, token revocation needs a restart, no per-tenant disk quota, local-directory roots shared by tenants (Stage 6) | Product decision |
| B-6 | Resource exhaustion not fully closed: no uvicorn header-read timeout (needs a reverse proxy), upload writes block the event loop, per-tenant worker polls every 50 ms (capped at 64 tenants), artefacts read fully into memory up to 64 MiB | Hardening backlog |
| B-7 | Third-party licences are permissive except weak-copyleft MPL-2.0 (`certifi`, test-time only; DelphiAST via committed diff) — compatible with any outbound licence, but legal sign-off is the owner's | Owner/legal |
| B-8 | Remaining LOW review items not fixed: `issue_token` concurrency/duplicates (`tenant_auth.py`), catch-all route 404 vs 405 for POST, `_register_routes` is ~85 lines of nested closures | Backlog |

## 6. External validation checklist

- [ ] **X-1** Human security review / penetration test of the API, uploads, token mode and checkpoint sealing (focus: tenant isolation, archive/Git ingestion, DoS)
- [ ] **X-2** Real remote Git: HTTPS public, HTTPS private (token + `P1_GIT_TOKEN_HOSTS`), SSH with pinned host keys; branch/tag/commit pinning; a hostile repository (tree bomb, submodule, symlink, hooks)
- [x] **X-3** Push the branch and confirm `p1-gates` is green on `ubuntu-24.04` (tests, no-LLM guard, frontend job, FPC host + container sweeps) — **done 26 Nov 2026**: [PR run `45789568402`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45789568402), [`main` run `45790563117`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45790563117)
- [ ] **X-4** Linux and macOS runs of the Python suite and the service; real symlink tests (the 6 skips) on a host that permits them — **Linux done** (CI `1787 passed, 4 skipped`; local WSL Ubuntu 24.04 full suite green; symlink tests now execute and pass on POSIX). **macOS still open**
- [ ] **X-5** Customer-representative Pascal estates (Delphi VCL/FMX, FPC/Lazarus, Turbo/Borland, ISO) — compare blueprint against a human-built inventory; review false negatives/positives
- [ ] **X-6** Browser E2E (Playwright) across Chrome/Firefox/Edge/Safari including token flow, upload progress, downloads, keyboard-only and screen-reader pass
- [ ] **X-7** Deployment behind a TLS reverse proxy (`--behind-tls-proxy`), header/body timeouts, backup/restore of the store, durable (non-tmpfs) store location
- [ ] **X-8** Load/soak: concurrent tenants, large archives near the limits, queue-full behaviour, restart during a running job
- [ ] **X-9** Owner decision on the repository licence (ADR 0006), then add `LICENSE`, update the notices header, sanitise F-8 paths, decide CLA/DCO
- [ ] **X-10** Legal confirmation of `THIRD_PARTY_NOTICES.md` and the MPL-2.0 handling

## 7. Commits (approved by the owner and created)

Commits 1–3 are `1c4b926`, `5b39235` and `3aca820`; commit 4 is the one that adds this report. Each boundary was simulated cumulatively on a clean export of `HEAD` before committing; each state passed its targeted tests, and every working-tree change belongs to exactly one commit. Messages follow the repo's conventional-commit style (no `Co-Authored-By` trailer, per the configured git workflow).

| # | Message | Contents |
|---|---|---|
| 1 | `feat(stage1): derive checkpoint-manifest, project-inventory and architecture reports` | `tools/p1/reports.py`, `stage1.py`, `server_security.py` (artefact allow-list, anchored id patterns), `tests/unit/test_reports.py`, `tests/integration/test_stage1_reports.py` |
| 2 | `feat(stage1): add tenant isolation, tenant tokens and FastAPI service` | `tenancy.py`, `tenant_auth.py`, `jobs.py`, `server.py`, `fastapi_app.py`, `api_main.py`, `cli.py`, `web/app.js`, `requirements-api.txt`, `requirements-dev.txt`, test fixture `fakes.py`, tenancy/API/acceptance tests |
| 3 | `feat(stage1): add React workbench for the FastAPI service` | `frontend/` (source, exact-pinned `package-lock.json`, 93 tests), `.gitignore` entries |
| 4 | `docs(stage1): add requirements, architecture, reuse audit, acceptance, closure report, notices and CI` | `README.md`, `docs/**` (product, architecture, reuse, ADR 0006, acceptance, closure, design, user guide), `THIRD_PARTY_NOTICES.md`, `tools/release/generate_notices.py`, `tests/unit/test_notices.py`, `.github/workflows/p1-gates.yml` |

Notes: git reports LF→CRLF normalisation warnings on this Windows checkout (`core.autocrlf=true`); commits will be normalised and no `.gitattributes` is added. `frontend/node_modules`, `frontend/dist` and `frontend/coverage` are ignored.

## 8. Closure addendum (26 November 2026 — release engineering)

Executed with the owner's explicit approvals (PR-first merge; fix + doc push authority; `docs/stage1/STAGE1_SECURITY.md` path; licence decision deferred):

1. **Merge-readiness verified:** clean tree at `5dfc763` == origin; `main` a strict ancestor (0/5); `git merge-tree` dry-run conflict-free; local gates re-run green (pytest 1785/6/0, guard PASS, frontend 93/93 + build, notices `--check` current); diff secret scan clean (only fake test credentials).
2. **PR #1 opened and merged with history preserved** — merge commit `d370632` on `main`; branch not deleted; no force-push.
3. **First GitHub Actions execution** (closes B-3/X-3): attempt 1 ([`45787617127`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45787617127)) failed 7 tests in `tests/security/test_checkpoint_integrity.py` (`PermissionError` — checkpoints store `0o555` directories, which POSIX enforces and Windows ignores for create/delete/rename). **Fix `f275ca6`:** `_unlock` now also opens the target's ancestor directory chain up to the first writable directory, and four tamper tests gained the explicit unlock call they implicitly had on Windows. **Test harness only — no assertion changed, no test skipped or weakened**; verified before push on Windows (64 passed/3 skipped) and WSL Ubuntu 24.04 (full suite 1787 passed/4 skipped, guard PASS). Attempt 2 ([`45789568402`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45789568402)) green on all 3 jobs; post-merge [`main` run `45790563117`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45790563117) green.
4. **`docs/stage1/STAGE1_SECURITY.md` created** (owner-approved path; the literal `docs/stage-1/STAGE_1_SECURITY.md` deviation is recorded there and in the acceptance header) — consolidates S1-S1…S1-S6/S1-N1…N3 requirements, threat model, control→test matrix, review outcomes, residual risks and the operator checklist.
5. **Licence (B-1/X-9):** the four option families (Apache-2.0 / MIT-BSD / proprietary / copyleft) were presented with implications; the owner **deferred** — ADR 0006 remains OPEN, no `LICENSE` file created.
6. **Notices (B-7/X-10):** `THIRD_PARTY_NOTICES.md` verified current and summarised for legal review (permissive runtime deps; MPL-2.0 = `certifi` test-only + DelphiAST diff; GPL only as external processes). **No legal approval is claimed.**
7. **Acceptance record updated** so claims match evidence (L-2, L-8, gate table, header). Stages 2–6 remain `PLANNED`; Stage 2 was not started.
