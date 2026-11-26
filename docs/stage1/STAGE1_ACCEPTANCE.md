# Stage 1 acceptance record — Ingestion and Discovery

**Contract:** [`PRODUCT_REQUIREMENTS.md`](../product/PRODUCT_REQUIREMENTS.md) §5 · **Design:** [`STAGE1_DESIGN.md`](STAGE1_DESIGN.md) · **Security:** [`STAGE1_SECURITY.md`](STAGE1_SECURITY.md)
**Run:** 24 November 2026 (local gates, Windows 11, Python 3.11.9, Node 22, git 2.55) · **26 November 2026 (GitHub Actions, ubuntu-24.04)** · branch `feat/stage1-ingestion-discovery`, merged to `main` as `d370632` via PR #1 with history preserved
**Stage 2 was not started. The COBOL repository was not modified. Every commit and push in this closure (the POSIX test fix and these documentation updates) was made with the owner's explicit approval.**

## 1. Result

| Gate | Result |
|---|---|
| Python suite `python -m pytest tests -q` | **1785 passed, 6 skipped, 0 failed** (187 s; an independent clean copy of the tree, taken earlier in the closure audit, gave 1765 passed, 6 skipped). The 6 skips are symlink-creation tests that need a Windows privilege this account lacks |
| Acceptance suite `tests/acceptance/` (real API + real `discover`, no fakes) | 14 passed |
| FastAPI service tests `tests/integration/test_fastapi_app.py` | 43 passed |
| No-LLM guard (`cli.py guard --root .`) | PASS, 0 findings |
| React workbench: `npm ci`, `typecheck`, `test`, `build` (clean tree) | 93 tests passed, ~99.7 % statement coverage, build OK, `npm audit --omit=dev`: 0 vulnerabilities |
| Live smoke over real uvicorn | ZIP upload → 5 steps completed → blueprint; React UI served with CSP and rendered from the real job in headless Chrome (matches the reference mock-up layout); token mode: no token 401, bad token 401, good token 200 with a spoofed `X-P1-Tenant` ignored; non-loopback bind with tokens but no TLS refused |
| Independent security review of the FastAPI/tenancy layer | No CRITICAL/HIGH. 4 MEDIUM + cheap LOW items fixed (§4) |
| **GitHub Actions `p1-gates` on `ubuntu-24.04` (first-ever execution, 26 Nov 2026)** | **All 3 jobs green** on PR run [`45789568402`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45789568402) and post-merge `main` run [`45790563117`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45790563117): tests **1787 passed, 4 skipped, 0 failed** in 33 s + no-LLM guard `PASS (0 findings)`; React workbench 93/93 + typecheck + build; fixture-corpus sweep **host and container each MATCH=24, MISMATCH=0** (`fpc:3.2.2`, platform linux). The first attempt ([`45787617127`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45787617127)) failed 7 checkpoint-tamper tests with `PermissionError` on POSIX `0o555` directories — fixed in `f275ca6` by unlocking parent directories in the **test harness only** (every assertion untouched; no test skipped or weakened) |

**Verdict: Stage 1 meets every acceptance criterion below in this environment, with the limitations in §5 stated, not hidden.**

## 2. Acceptance criteria and evidence

| ID | Criterion (requirement) | Evidence |
|---|---|---|
| AC-1 | A ZIP journey completes all five steps: ingestion, checkpoint, scanning & inventory, dependency analysis, blueprint (S1-F1, F8) | `test_ac1_*`; live smoke |
| AC-2 | The blueprint validates against the published JSON Schema (S1-F7) | `test_ac2_*` |
| AC-3 | Every finding carries located evidence (file, line, redacted excerpt) (R-4) | `test_ac3_*` over `evidence_owners` |
| AC-4 | The checkpoint verifies and is read-only; analysis reads the checkpoint (S1-F3) | `test_ac4_*`; `tests/security/test_checkpoint_integrity.py` |
| AC-5 | All machine-readable reports and the human report are published and downloadable (S1-F7) | `test_ac5_*` (blueprint, manifest, graph, unresolved, diagnostics, checkpoint-manifest, project-inventory, architecture-report, inventory.csv, report) |
| AC-6 | **Nothing in the input is executed** — a ZIP containing `.bat`, `.sh`, `.ps1`, `.exe` and a `.pas` with `{$MESSAGE}`/`{$I}` directives produces zero process creation, no side-effect file, yet the scripts are discovered | `test_ac6_*` (patches `subprocess.Popen`, `os.system`, `os.exec*`, `os.spawn*`, `os.startfile`) |
| AC-7 | Deterministic: byte-identical blueprint from the same ZIP in two stores (S1-N1) | `test_ac7_*`; `tests/integration/test_determinism.py` |
| AC-8 | Directory input yields the same projects/dialect/libraries as ZIP input | `test_ac8_*` |
| AC-9 | Tenant isolation with real discoveries: A's blueprint/report/artefacts are 404 to tenant B and to the default tenant; storage is under `tenants/<id>/` (S1-S4) | `test_ac9_*`; `tests/security/test_tenant_isolation.py`; `test_fastapi_app.py` token-mode tests |
| AC-10 | Hostile archives (zip-slip, case-fold duplicates, absolute path) fail with a code and publish no checkpoint, discovery or leftover upload (S1-S1, S1-S5) | `test_ac10_*`; `tests/security/test_adversarial_archives.py` |
| AC-11 | A failed run does not block a subsequent clean run | `test_ac11_*` |
| AC-12 | Finished discoveries survive a service restart | `test_ac12_*`; `tests/unit/test_jobs.py` |
| AC-13 | Git (public and private) is resolved to an exact commit before processing; tokens only to allow-listed hosts, never in argv/URLs/outputs; hooks, submodules, symlinks refused; limits enforced pre-checkout (S1-F1, F2, S1-S2) | `tests/security/test_remote_git.py`, `test_git_ingestion.py`, `test_git_limits.py`, `test_git_process.py`, `tests/unit/test_remotegit_policy.py`, `tests/integration/test_remote_git_http.py` (real smart-HTTP) — see limitation L-1 |
| AC-14 | API hardening: Host/Origin/CSRF, bounded bodies, capped streamed uploads, id/name allow-lists, sanitised errors, CSP | `test_fastapi_app.py`, `tests/security/test_server_security.py` |
| AC-15 | React workbench over FastAPI provides the full ingest → progress → blueprint → download workflow (S1-F8) | `frontend/src/__tests__` (93), live render in headless Chrome, `/api/config` `"ui":"react"` |
| AC-16 | P0/P1 tests unchanged and passing; no test weakened (S1-N2) | Full suite; the only edits to existing test files were additive (fake discovery now also writes the three new report artefacts) and one fixture-setup correction in a new test |

## 3. What changed in this session

* **Fixed:** the in-progress tenancy work tripped the no-LLM guard (a comment used a forbidden word — reworded, guard untouched) and three tenancy tests (reserved store names such as `jobs`/`tenants` are now refused as tenant ids; the test fake now writes the three new report artefacts).
* **Added:** FastAPI service (`fastapi_app.py`, `api_main.py`), per-tenant bearer tokens (`tenant_auth.py`, `tenant-token` command), React/TypeScript/Vite workbench (`frontend/`), acceptance suite, product requirements, six-stage architecture page, COBOL reuse audit, CI job for the frontend, pinned `requirements-api.txt`.
* **Preserved:** the stdlib server and vanilla dashboard are unchanged and remain a zero-dependency fallback.
* **Not done on purpose:** no code was copied from the COBOL repository (§ audit); project licence untouched.

## 4. Security review outcome

Consolidated in [`STAGE1_SECURITY.md`](STAGE1_SECURITY.md) (requirements → controls → evidence matrix, threat model, residual risks, operator checklist).

| Finding | Severity | Resolution |
|---|---|---|
| Unbounded tenant creation via `X-P1-Tenant` in open mode (threads/dirs) | MEDIUM | Capped at 64 tenants (`TOO_MANY_TENANTS`); test added |
| One tenant could hold every upload slot; JSON body had no read deadline | MEDIUM | One in-flight upload per tenant; 10 s JSON read deadline; tests |
| `--allow-local-root` could contain the store, exposing other tenants' data | MEDIUM | Start-up refusal (`ROOT_OVERLAPS_STORE`); test |
| Bearer tokens over cleartext HTTP on a non-loopback bind | MEDIUM | Refused unless `--ssl-certfile/--ssl-keyfile` or `--behind-tls-proxy` (which then accepts `https://` origins); verified live |
| `ID_PATTERN` accepted a trailing newline | LOW | `\Z` anchors; test |
| Reserved tenant names accepted in a token file; split first TCP chunk rejected as non-ZIP; unbounded artefact read; duplicate `Cache-Control` | LOW | Validated at load; magic bytes buffered across chunks; 256 MiB serve cap; header de-duplicated |

## 5. Limitations and remaining blockers (honest)

* **L-1 — Git was not exercised through the HTTP API against a real remote.** The API refuses loopback/non-public hosts by design, so the real smart-HTTP and token tests run at the pipeline level (`ingest_remote_git`) with an explicit test policy. Verified: local Git, `file://`, real smart-HTTP on loopback. **Not verified:** SSH against a real server; HTTPS to a public TLS host; a private repository on a real hosting service.
* **L-2 — Verification status (updated 26 Nov 2026):** the GitHub Actions workflow **has now executed** — all three jobs green on [run `45789568402`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45789568402) (PR) and [run `45790563117`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45790563117) (`main`), covering Linux (ubuntu-24.04), the frontend job, and **both** fixture sweeps (host FPC + digest-pinned container). The first attempt failed 7 tamper-test setups on POSIX directory permissions; fixed in `f275ca6`. **Still not verified:** macOS; SSH against a real server; a public TLS host (L-1); no browser E2E (L-5).
* **L-3 — Identity.** Without a token file `X-P1-Tenant` is a storage boundary, **not authentication**. With tokens, tenant is derived from the token, but there is no OIDC, RBAC, token rotation or revocation without restart (Stage 6). Tenants share the single worker pipeline's host resources; there is no per-tenant disk quota. Local-directory ingestion roots are operator-trust and shared by all tenants — disable them in multi-tenant deployments.
* **L-4 — Resource exhaustion not fully closed:** no header-read timeout in uvicorn (put a proxy in front for slow-client protection); upload writes are synchronous on the event loop; each tenant's job worker polls every 50 ms (cap of 64 tenants bounds this).
* **L-5 — Frontend verification is jsdom plus one headless-Chrome render at 1672 px.** No automated browser end-to-end test (Playwright) and no mobile/accessibility audit beyond preserved ARIA attributes. Frontend dependency versions are exact-pinned and `npm audit` is clean, but their release age was not checked. Python dependencies are version-pinned, not hash-pinned.
* **L-6 — Status vocabulary.** Stage 1 outputs carry `SUPPORTED/PARTIAL/UNKNOWN` meaning "Stage 1 could scan this file/project", **not** conversion support; the UI column is labelled "Discovery status" and the guide says so. Capability classification is Stage 3.
* **L-7 — Detection limits** as before: no AST/symbol resolution, no binary decompilation, Delphi release name reported as raw `ProjectVersion`.
* **L-8 — Licence.** This repository has no root `LICENSE` file; the COBOL repo is Apache-2.0. Engineering did not add or change a licence. Third-party licences **are** listed in [`THIRD_PARTY_NOTICES.md`](../../THIRD_PARTY_NOTICES.md) (generated by `tools/release/generate_notices.py`, drift-tested; legal sign-off X-10 pending). On 26 Nov 2026 the owner was presented the four licence option families with implications and **deferred the decision** (ADR 0006 stays OPEN); it still blocks any public release and any porting of COBOL code.
* **Out of scope and unchanged:** Stages 2–6 (Stage 5 remains blocked on a licensed Delphi toolchain).

## 6. Reproducing

```text
pip install -r requirements-dev.txt
python -m pytest tests -q
python tools/p1/cli.py guard --root .
(cd frontend && npm ci && npm run typecheck && npm test && npm run build)
python tools/p1/cli.py api --store .stage1-store      # http://127.0.0.1:8766/
```
