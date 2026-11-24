# Stage 1 Verification Report — Ingestion and Discovery

**Scope:** Stage 1 of the six-stage architecture (roadmap P0/P1 plus the Stage 1 completion work).
**Contract:** [`STAGE1_DESIGN.md`](STAGE1_DESIGN.md) · **Guide:** [`STAGE1_USER_GUIDE.md`](STAGE1_USER_GUIDE.md)
**Date:** 18 November 2026 · **Environment:** Windows 11, Python 3.11.9, git 2.55.0, FPC 3.2.2 (host)
**Stage 2 was not started.**

> **Historical record (18 November 2026).** Current results, the FastAPI/React/tenancy work and the closure audit are in [`STAGE1_ACCEPTANCE.md`](STAGE1_ACCEPTANCE.md) and [`STAGE1_CLOSURE_REPORT.md`](STAGE1_CLOSURE_REPORT.md); counts below are as of that date.

## 1. Verdict

Stage 1 is implemented end to end and verified in this environment, with the limitations in §6 stated, not hidden.

| Check | Result |
|---|---|
| Full test suite (`python -m pytest tests -q`) | **1627 passed, 6 skipped, 0 failed** (317 s) |
| Original P1 tests | all still pass unchanged (612 → part of the 1,627) |
| No-LLM guard (`python tools/p1/cli.py guard --root .`) | **PASS**, 0 findings |
| Host corpus sweep (`python tools/p1/sweep.py --host`) | **24/24 MATCH**, 0 MISMATCH |
| End-to-end `discover` | directory, ZIP, local Git and **real smart-HTTP remote Git** produce the same analysis; output schema-valid and byte-identical on rerun |
| Dashboard | run against the real `discover` through the job runner; headless-Chrome render compared with the reference mock-up |
| Not verified | container sweep (not re-run this session), GitHub Actions workflow (never executed), SSH against a real server, HTTPS against a public TLS host |

The 6 skips are symlink-creation tests that need a Windows privilege this account lacks; junction handling is covered by real-junction tests instead.

## 2. What was delivered against the Stage 1 requirements

| Requirement | Delivered by | Evidence |
|---|---|---|
| ZIP uploads | `zipingest.py` (existing, hardened) + dashboard upload | adversarial archive tests; upload tests |
| Git repository URLs | `remotegit.py`, `remotegit_policy.py`, `gitingest.py`, `gitproc.py`, `gittree.py`, `treelimits.py` | `test_remotegit_policy.py` (197), `test_remote_git.py` (27), `test_git_limits.py`, `test_git_process.py`, `test_remote_git_http.py` (real smart-HTTP) |
| Immutable checkpoint pinned to the exact commit before any processing | `checkpoint*.py`, `stage1.py` | ref→40-hex SHA first; byte-exact read-only copy; analysis reads the checkpoint, never staging; verify-before-reuse; sealed metadata |
| Original source preserved | checkpoint `source/` and `original/input.zip` | byte-for-byte and hash tests |
| Every file and directory inventoried | `model.py`, `inventory.py`, `classify.py` | blueprint `inventory`, `inventory.csv`; empty directories preserved |
| Dialects, projects, entry points, compiler configuration | `dialects.py`, `projects.py`, `compilercfg.py`, `plex.py` | unit + pipeline tests |
| Databases, libraries, integrations, build requirements, runtime dependencies | `metadata.py`, `libraries.py`, `integrations.py`, `runtimedeps.py`, `inventory.py` | unit tests + enterprise-fixture assertions |
| Evidence-backed blueprint, dependency graphs, unresolved dependencies, diagnostics, machine-readable reports | `blueprint*.py`, `emit.py`, `schemacheck.py`, JSON Schema | schema validation of every generated blueprint; evidence rule asserted over every finding |
| Extends P0/P1 rather than rewriting | new modules beside `tools/p1/`; edits to existing files are additive (`model`, `gitingest`, `plex`, `dialects`, `classify`, `metadata`, `projects`, `emit`, `cli`) | the 612 original tests pass unchanged |
| Security protections | see §4 | `tests/security/` (411) |
| Deterministic processing | no wall-clock/absolute paths outside `run-record.json` | byte-identical reruns in separate stores |
| Dashboard per reference image | `server.py`, `jobs.py`, `web/` | headless-Chrome render |
| README reflects architecture and status | `README.md` | six-stage section, Stage 1 section, corrected status/limitations |

## 3. Defects found in P1 and fixed

1. **`plex.py` dropped Delphi `uses Unit in 'path.pas' {Form}` clauses** (the form of virtually every `.dpr`) and dotted unit names (`System.SysUtils`, `FireDAC.Comp.Client`) as `USES_MALFORMED`, so whole clauses — and any unresolved unit in them — vanished from the graph. Found by the blueprint author on the enterprise fixture; fixed with regression tests (`tests/unit/test_plex_uses.py`); malformed clauses are still reported.
2. **Directory inputs followed Windows junctions and file symlinks** (`os.walk` descends junctions; `Path.is_file` follows symlinks), pulling out-of-tree files into the inventory. Reproduced with a real junction; `walk_files` now refuses any symlink/junction (`SYMLINK_ENTRY`); `tests/security/test_directory_links.py`.
3. **Stock Delphi units (`SOAPHTTPClient`, `InvokeRegistry`, `SvcMgr`, …) were reported as missing-unit errors.** Added to the RTL tables by exact name; whole-namespace rules were deliberately avoided so a customer's own `Web.Core`/`Xml.Custom` is not hidden (`tests/unit/test_dialects_rtl.py`).

## 4. Independent reviews and their outcomes

Three read-only reviews were run against the finished modules by separate reviewer agents; none reported a CRITICAL issue. Every HIGH and MEDIUM finding was fixed with a test that failed first.

**Remote Git / checkpoint security review**

| Finding | Severity | Resolution |
|---|---|---|
| `P1_GIT_TOKEN` would be sent to any HTTPS host a requester names | HIGH | token only for hosts in `P1_GIT_TOKEN_HOSTS`; INFO diagnostic otherwise |
| Entry-count/depth/name limits not enforced for Git/directory (an 83 KB tree bomb expanded to 64,000 files in 271 s) | HIGH | limits enforced from `git ls-tree` **before** checkout and while walking directories; bomb now refused in seconds |
| Case/Unicode path collisions silently dropped a file | MEDIUM | `PATH_COLLISION` in the tree listing and in the checkpoint |
| `checkpoint.json` fields not bound by any hash | MEDIUM | seal over the whole document (HMAC with `P1_STORE_KEY`, SHA-256 otherwise); loaded fields re-validated |
| Unbounded git output; `ls-remote` unwatched; raw `TimeoutExpired` | MEDIUM | 8 MiB caps, shared runner/timeouts, `GIT_TIMEOUT` |
| SSH read user/system config and global known_hosts | MEDIUM | `-F` devnull, `GlobalKnownHostsFile`, `IdentityAgent=none`, `UpdateHostKeys=no`, `CheckHostIP=no` |
| Whole parent environment passed to git | MEDIUM | allow-listed environment |
| IPv6 zone ids; old git silently ignoring address pinning; UNC/`::` local sources | LOW | refused / `GIT_TOO_OLD` fails closed / `UNSUPPORTED_SOURCE` |

**Web-server security review** — HIGH: junction/symlink inside an allowed local root escaped containment (fixed in `walk_files`, §3). MEDIUM: directory TOCTOU between submit and run (containment re-checked in the worker with a real retargeted-junction test); upload/connection exhaustion (bounded semaphores, slot reserved before streaming, per-request deadline, startup sweep, pruned jobs); API Git validation weaker than `remotegit` (API now calls the same parser). LOW: duplicate Cache-Control, duplicate Host, Host/Origin policy width. Verified sound by the reviewer with ~120 crafted raw requests: Host/DNS-rebinding, CSRF, path/artifact allow-list, upload paths, information disclosure, header injection, XSS/DOM sinks, CSP.

**Code review (orchestrator, blueprint, schema)** — MEDIUM: one missing dependency counted two or three times at different severities (now one item at the highest severity); evidence `file` could be a bare ambiguous basename (now always a real inventory path); blueprint scrubbed differently from files and built twice (single build, shared scrub roots); failures other than `IngestionError` never emitted a `failed` step and could name the wrong step (fixed); key-dependency ranking mixed incomparable measures (normalised to distinct referencing files, unresolved first); blanket namespace rules in the RTL tables (replaced by exact names); unit-count/tree attribution disagreement (aligned and documented). Several LOW items fixed (unused import, `discover` split into small functions, cleanup error masking, inconsistent `--ref` and a store inside the input directory now refused up front).

One reviewer recommendation was **not** adopted as asked: the `inventory.csv` path cell keeps its formula-injection apostrophe guard (a spreadsheet evaluates any cell beginning `= + - @` regardless of CSV quoting, so a path cannot be both verbatim and injection-safe). The rule is documented and tested.

## 5. Hostile-input performance check

Nine adversarial files (megabyte-long lines, 300k quoted tokens, 100k-item `uses`, 3 MB identifiers, 80k-item batch lines, 500k-entry config) were analysed individually: 0.1–21 s each, no hang and no super-linear blow-up. Token-dense source costs roughly 5–10 s per MB because the scanner is pure Python — a real limit recorded in §6.

## 6. Limitations and unverified items (stated, not glossed)

1. **GitHub Actions workflow** `.github/workflows/p1-gates.yml` has never executed here; it does not yet run the Stage 1 suite beyond what `pytest tests` covers.
2. **Container corpus sweep** was not re-run in this session (host sweep: 24/24).
3. **SSH remotes** are verified by command-construction tests only; **HTTPS** was exercised against a local smart-HTTP server (loopback allow-listed through a test-only policy flag that cannot be set from the CLI or API), not a public TLS host.
4. Submodule and symlink entries in a repository are **refused**, so such repositories cannot be ingested yet.
5. Detection is name/pattern based (false positives and `unresolved` unknown libraries are possible); DFM component classes, `with` statements and timer-driven jobs are not analysed; Delphi release names are not mapped (raw `ProjectVersion` is reported).
6. Throughput limit above; no total analysis-time budget.
7. The checkpoint seal is unkeyed unless `P1_STORE_KEY` is set (detects accidental/partial tampering only).
8. The dashboard has no authentication (Stage 6); keep it on loopback. The visual check used headless Chrome at 1672 px and 500 px; there is no automated browser E2E suite.
9. No project-wide coverage gate: the `coverage` package is not installed; authors measured new modules with the stdlib `trace` module (92–99 %).
10. Open owner blockers carried from P1: **A1** no `LICENSE` file; **A2** DelphiAST upstream notification.
11. No Delphi compiler exists in this environment: no Delphi-equivalence or `VERIFIED` claim is made anywhere (capability states never contain `VERIFIED`).

## 7. Reproducing

```powershell
python -m pytest tests -q                        # 1627 passed, 6 skipped
python tools/p1/cli.py guard --root .            # gate: PASS (findings: 0)
python tools/p1/sweep.py --host                  # MATCH=24 MISMATCH=0
python tools/p1/cli.py discover <source> --store .stage1-store
python tools/p1/cli.py serve --store .stage1-store
python tests/fixtures/stage1/make_sample.py      # regenerate the UI sample after detector changes
```
