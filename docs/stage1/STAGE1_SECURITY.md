# Stage 1 security record — Ingestion and Discovery

**Contract:** [`PRODUCT_REQUIREMENTS.md`](../product/PRODUCT_REQUIREMENTS.md) §5 (S1-S1…S1-S6, S1-N1…N3) · **Design:** [`STAGE1_DESIGN.md`](STAGE1_DESIGN.md) §3, §4, §8, §8.1 · **Acceptance:** [`STAGE1_ACCEPTANCE.md`](STAGE1_ACCEPTANCE.md) §4, §5
**Status:** living security record for Stage 1. Created 26 November 2026 to close the documented `STAGE_1_SECURITY.md` gap; the owner approved the path `docs/stage1/STAGE1_SECURITY.md` (repo naming convention) instead of the literal `docs/stage-1/STAGE_1_SECURITY.md`.
**Scope:** Stage 1 only. Stages 2–6 security requirements are not determined here. Nothing in this record selects a repository licence (ADR 0006 remains open).

## 1. Hard rules this record defends

| Rule | Source | Enforcement |
|---|---|---|
| **No LLM / ML / embeddings / RAG / probabilistic generation** in the shipped product; every decision deterministic | ADR 0005, README, R-1 | `tools/p1/guard.py` gate (`cli.py guard --root .`), `tests/security/test_no_llm_guard.py`, CI `tests` job, blueprint field `generator.llm_assisted: false` |
| **Non-execution:** customer input is never executed — no scripts, executables, builds, compilers, database operations | PRODUCT_REQUIREMENTS §Stage 1, AC-6 | pure-function pipeline; AC-6 test patches `subprocess.Popen`, `os.system`, `os.exec*`, `os.spawn*`, `os.startfile` and asserts zero process creation and zero side-effect files (watcher coverage caveat F-12) |
| **Fail closed** with a stable error code; never silently drop a file or a finding | README, design §1 | `IngestionError` codes; `tests/security/test_no_silent_drop.py`; refused runs publish no blueprint |
| **Evidence on every finding** (file, line, column, redacted excerpt) | R-4, AC-3 | blueprint evidence rule + `test_ac3_*`; scrubber in `server_security` |

## 2. Threat model

**Assets:** the host (files, processes, availability), other tenants' data, Git/SSH credentials, checkpoint integrity (the input of record for every later stage), and the determinism guarantee itself.

**Adversaries and trust boundaries:**

| Boundary | Untrusted side | Primary controls |
|---|---|---|
| Ingestion | Customer ZIP / directory / Git server (attacker-influenced URL, repo content, server responses) | staged-then-validated intake, hostile-archive refusal before any write outside staging (S1-S1), remote-Git scheme/SSRF/credential policy with exact-commit pinning (S1-S2), tree limits before checkout, symlink/submodule/hook refusal |
| HTTP API | Any client that can reach the bind address | `Host`/`Origin`/`X-P1-Request` checks, method allow-list, bounded bodies, capped streamed uploads with magic-byte checks, id/name allow-lists, sanitised errors, CSP and security headers (S1-S3) |
| Tenant | Another tenant (or a client spoofing a tenant header) | storage roots per tenant, cross-tenant reads answer 404, reserved ids refused, 64-tenant cap; in token mode the tenant is derived from the bearer token and `X-P1-Tenant` is ignored (S1-S4) |
| Network | On-path attacker, DNS rebinding, cloud-metadata endpoints | non-public addresses refused unless operator-allow-listed, resolved IP pinned for the fetch, redirects off, credentials only via environment and scrubbed from messages/artefacts, cleartext non-loopback bind refused in token mode |
| Operator | Mis-configuration | local-directory roots operator-trust and shared (disabled unless explicitly enabled), token file mode 0600, TLS required for non-loopback binds (`--ssl-certfile/--ssl-keyfile` or `--behind-tls-proxy`) |

**Explicitly out of scope (stated, not hidden):** identity/RBAC/audit (Stage 6, L-3), per-tenant disk quotas, header-read timeouts behind no reverse proxy (B-6/L-4), browser end-to-end security testing (L-5), and any human penetration test — X-1 is still open.

## 3. Requirements → controls → evidence

| Req | Control (implementation) | Evidence |
|---|---|---|
| S1-S1 hostile archives | `p1/zipingest.py` validates traversal, absolute paths, duplicates/case-fold collisions, bombs, symlinks, reserved names **before** any write outside staging; upload temp files removed on every failure path | `tests/security/test_adversarial_archives.py`, `test_no_silent_drop.py`, AC-10 (`test_ac10_*`) |
| S1-S2 remote Git | `p1/remotegit.py`: HTTPS always, SSH only with key + known-hosts configured; `http://`/`git://`/`ext::`/userinfo/control chars refused; SSRF policy (loopback, RFC1918, link-local incl. 169.254.169.254, CGNAT, multicast, reserved, IPv4-mapped forms) refused unless allow-listed; resolved IP pinned, redirects off; token via `GIT_CONFIG_COUNT/KEY/VALUE` (never argv), host-scoped, scrubbed; ref → exact 40-hex commit; hooks/filters/submodules/symlinks refused; entry/depth/name/blob/size limits enforced from the tree listing before checkout; staging-size watchdog kills git | `tests/security/test_remote_git.py`, `test_git_ingestion.py`, `test_git_limits.py`, `test_git_process.py`, `tests/unit/test_remotegit_policy.py`, `tests/integration/test_remote_git_http.py` (real smart-HTTP), AC-13 |
| S1-S3 API hardening | `p1/server_security.py` + FastAPI `GuardMiddleware`: single allowed `Host` (DNS rebinding), cross-origin `Origin` refused on POST, `X-P1-Request` required, method allow-list, absolute-path check, JSON 16 KiB cap, uploads need `Content-Length`, are byte-capped, deadline-bound, magic-byte checked; ids `[0-9a-f]{16}`; artefact names from a start-up allow-list; errors carry a stable code and no filesystem paths/tokens; CSP `default-src 'self'`, `nosniff`, `no-referrer` | `tests/security/test_server_security.py`, `tests/integration/test_fastapi_app.py`, AC-14 |
| S1-S4 tenant isolation | `p1/tenancy.py`: ids `[a-z0-9][a-z0-9_-]{0,62}`, reserved store names refused, default tenant at store root, others under `tenants/<id>/`, cross-tenant read → 404; `p1/tenant_auth.py`: SHA-256 digests only, constant-time comparison, 0600 file, tenant derived from token (header ignored) | `tests/security/test_tenant_isolation.py`, `tests/unit/test_tenancy.py`, token-mode tests in `test_fastapi_app.py`, AC-9 |
| S1-S5 bounded resources & recovery | bounded job queue and one worker thread; one in-flight upload per tenant; 10 s JSON read deadline; 256 MiB serve cap; per-invocation git timeout + staging watchdog; failed runs remove staging/uploads; interrupted jobs marked on restart; finished discoveries survive restart | `tests/unit/test_jobs.py`, `tests/security/test_git_limits.py`, AC-11/AC-12 |
| S1-S6 secrets never in outputs/errors/logs | `scrub_message` removes URLs, userinfo, tokens and host paths from messages and artefacts; integration endpoints redact credentials in evidence | `tests/security/test_server_security.py` (scrub cases), review item F-3 |
| AC-4 checkpoint integrity | files `0o444`, directories `0o555` (POSIX), content seal (`stage1.checkpoint/1.0`), `verify_checkpoint` re-hashes everything; tampered checkpoints never reused (`CHECKPOINT_TAMPERED`); atomic creation; traversal in `checkpoint.json` refused; symlinked content reported, never followed | `tests/security/test_checkpoint_integrity.py` (67 cases incl. seal binding) |
| AC-6 non-execution | §1 row above | `test_ac6_*` (mutation-verified: breaking non-execution fails the test) |
| S1-N1 determinism | byte-identical blueprint from the same input in separate stores; no wall clock in artefacts except `run-record.json` | `tests/integration/test_determinism.py`, AC-7 |
| S1-N2 no test weakened | additive-only test changes recorded in the acceptance record; CI runs the full suite and the guard | AC-16, closure report §7 |

## 4. Security review outcomes (all fixed, each with a test)

| Finding | Severity | Resolution |
|---|---|---|
| Unbounded tenant creation via `X-P1-Tenant` in open mode | MEDIUM | capped at 64 tenants (`TOO_MANY_TENANTS`); test |
| One tenant could hold every upload slot; JSON body had no read deadline | MEDIUM | one in-flight upload per tenant; 10 s deadline; tests |
| `--allow-local-root` could contain the store (cross-tenant exposure) | MEDIUM | start-up refusal (`ROOT_OVERLAPS_STORE`); test |
| Bearer tokens over cleartext HTTP on a non-loopback bind | MEDIUM | refused unless TLS configured or `--behind-tls-proxy`; verified live |
| `ID_PATTERN` accepted a trailing newline | LOW | `\Z` anchors; test |
| Reserved tenant names in token file; split first TCP chunk rejected as non-ZIP; unbounded artefact read; duplicate `Cache-Control` | LOW | validated at load; magic bytes buffered across chunks; 256 MiB cap; header de-duplicated |
| 500 responses lacked security headers; `ClientDisconnect` logged as server fault; wrong exception at ≥64 tenant dirs; per-call `tenant_gate`; 256 MiB artefact cap; no tenant cap on stdlib server; weaker report scrubber | MEDIUM (F-3) | fixed with tests; scrubber weakness checked against real artefacts — no observed leak |
| React review MEDIUMs (stale-401 token wipe, no poll resume, popup-blocked download, invalid menu ARIA, wrong Home/End, hidden config error, unvalidated URL ids) | MEDIUM (F-4) | fixed, each guarded by a test that failed first |

**Caveat (F-15/X-1):** all of the above are reviews of read code by AI agents. **No human security review or penetration test has been performed** — X-1 remains open and must be completed before any customer-facing release.

## 5. Verification evidence

| Check | When | Result |
|---|---|---|
| `python -m pytest tests -q` (Windows 11, Py 3.11) | 26 Nov 2026 | 1785 passed, 6 skipped, 0 failed |
| `python -m pytest tests -q` (WSL Ubuntu 24.04, Py 3.12) | 26 Nov 2026 | 1787 passed, 4 skipped, 0 failed |
| `python tools/p1/cli.py guard --root .` | 26 Nov 2026 | PASS, 0 findings |
| GitHub Actions `p1-gates`, PR run [`45789568402`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45789568402) (ubuntu-24.04) | 26 Nov 2026 | **green, all 3 jobs**: tests `1787 passed, 4 skipped` + guard `PASS (0 findings)`; React 93/93 + build; host and container sweeps `MATCH=24 MISMATCH=0` |
| GitHub Actions `p1-gates`, post-merge `main` run [`45790563117`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45790563117) | 26 Nov 2026 | **green, all 3 jobs** (merge commit `d370632`) |
| First CI attempt [`45787617127`](https://github.com/Shankar373/Pascal-Java-Transformation/actions/runs/45787617127) | 26 Nov 2026 | 7 tamper-test setups failed on POSIX `0o555` directories → fixed `f275ca6` (test harness only; no assertion changed) |

Security-specific test modules: `tests/security/` — adversarial archives, checkpoint integrity, directory links, git ingestion/limits/process/remote, no-LLM guard, no-silent-drop, server security, tenant isolation (227 test functions).

## 6. Residual risks (not fixed, tracked)

* **X-1** human security review / penetration test — open.
* **L-3** identity: no OIDC, RBAC, rotation or revocation-without-restart; without a token file, `X-P1-Tenant` is storage isolation, **not authentication**; tenants share host resources; no per-tenant disk quota; local-directory roots are operator-trust and shared (Stage 6, B-5).
* **L-4 / B-6** resource exhaustion: no uvicorn header-read timeout (deploy behind a reverse proxy), upload writes block the event loop, 50 ms per-tenant worker poll (bounded by the 64-tenant cap), artefacts read fully into memory up to 256 MiB.
* **F-12** the AC-6 watcher covers `Popen`/`os.system`/`exec*`/`spawn*`/`startfile`, not `ctypes`, `multiprocessing` or `os.posix_spawn`; mutation-verified for `Popen` only. A static "no process API in analysis modules" test is the recommended hardening.
* **L-5** no browser E2E (Playwright) and no automated accessibility/mobile audit of the workbench.
* **L-1** Git paths unverified against real remote hosts (SSH server, public TLS, private repository).
* **B-8** low items: `issue_token` concurrency, catch-all 404-vs-405, `_register_routes` structure.

## 7. Operator deployment checklist

1. Terminate TLS (`--ssl-certfile/--ssl-keyfile`) or run behind a TLS reverse proxy (`--behind-tls-proxy`); the service refuses non-loopback binds with tokens and no TLS.
2. Multi-tenant deployments: always configure `--tenant-tokens-file` (0600), keep `X-P1-Tenant` open mode off, and **disable local-directory roots** (`--allow-local-root` off) — they are operator-trust and shared by all tenants.
3. Keep the store on durable storage (not tmpfs), back it up, and verify restore; checkpoints are tamper-*evident*, not tamper-*proof* against a privileged local attacker.
4. Pin and periodically refresh dependencies (`requirements-api.txt`, `frontend/package-lock.json`); run `npm audit --omit=dev` and `generate_notices.py --check` in your release pipeline.
5. Do not expose the stdlib fallback dashboard beyond loopback without an authenticating proxy (it has no authentication until Stage 6).
