# COBOL repository reuse audit

**Audited repository:** `Shankar373/Cobol-Java-Transformation` (read-only; not modified)
**Pinned commit:** `b0c1f6bb58be9b61fe0b7b94a59f945c55697ca9` (2026-11-03, "Merge pull request #9: consolidate feat/phase3-coverage into main")
**Method:** static reading of a `--depth 50` clone; nothing from it was executed. Compared against `tools/p1/` (~18.8k lines) so that nothing already built in Pascal is recommended for porting.
**Licence of the audited repo:** Apache-2.0 (`LICENSE`, `NOTICE`, `PROJECT_LICENSE_DECISION.md` dated 2026-11-03).

## 1. Headline

The COBOL repository contributes **very little to Stage 1**. Its ingestion is a 391-line ZIP-only module (`api/ingestion.py`; Git ingest is explicitly "interface only, not implemented"); it has no immutable checkpoint, tenancy or job model. Pascal's Stage 1 (secure ZIP/Git/remote-Git ingestion, checkpoint, inventory, tenancy, jobs, reports, server, dashboard) is already substantially ahead. The COBOL value lies in **Stages 2–6**, mostly as reference or adapt-and-reuse after Pascal's own IR exists. **No COBOL code was copied for Stage 1.**

Classifications: **DIRECT REUSE** (copy as-is with attribution) · **ADAPT AND REUSE** (port structure/logic, rewrite language-bound parts) · **REFERENCE ONLY** (read for design; write independently) · **PASCAL-SPECIFIC DEVELOPMENT** (no useful COBOL counterpart).

## 2. Classification

### Stage 1 — Ingestion and Discovery

| Component | Purpose | Class | Rationale |
|---|---|---|---|
| `api/ingestion.py` (391) | ZIP ingest + COBOL discovery | REFERENCE ONLY | Pascal `zipingest.py`/`pathsafe.py`/`treelimits.py` cover and exceed it; declared-ratio idea already covered (§4) |
| `api/limits.py`, `api/paths.py`, `api/name_derivation.py` | env limits, durable-vs-scratch paths, id derivation | REFERENCE ONLY | Trivial / already covered by `limits.py`, `checkpoint`, `tenancy` |
| `engine/transformation/application_discovery.py` (657) | CALL/COPY discovery | PASCAL-SPECIFIC DEVELOPMENT | COBOL semantics; Pascal `uses`/include discovery is in `deps.py`/`plex.py` |
| `engine/source_hash.py`, `engine/domain/identities.py` | hashing, typed ids | REFERENCE ONLY | `hashing.py`, `model.py` exist |
| `fixtures/workload-*` (≈60 dirs) | COBOL fixtures | PASCAL-SPECIFIC DEVELOPMENT | COBOL content; the *layout* (one fixture per capability + descriptor) is the idea |

### Stage 2 — Language Engineering

| Component | Class | Rationale |
|---|---|---|
| `engine/transformation/cobol_parser.py` (4681) | PASCAL-SPECIFIC DEVELOPMENT | Grammar-bound; Pascal parsers are selected under ADR 0001 |
| `engine/transformation/ir.py` (2034), `docs/PHASE6A_UNIVERSAL_IR.md` | REFERENCE ONLY | IR shape and fail-closed unknown-construct policy are instructive |
| `copybook_model.py`/`copybook_resolver.py` | PASCAL-SPECIFIC DEVELOPMENT | Analogous to unit/include resolution, different semantics |
| `semantic_capability.py`, `docs/CAPABILITY_MATRIX.md`, `cobol_coverage_registry.json` | ADAPT AND REUSE | The registry *pattern* (SUPPORTED/PARTIAL/UNSUPPORTED/UNKNOWN) is language-neutral; entries must be rewritten |
| `engine/sql/*`, `engine/cics/*`, `engine/jcl/*` | REFERENCE ONLY / PASCAL-SPECIFIC | Embedded SQL, CICS and JCL have no direct Pascal analogue (Delphi BDE/ADO/FireDAC differ) |

### Stage 3 — Modernization Intelligence

| Component | Class | Rationale |
|---|---|---|
| `engine/modernization/capability_analyzer.py` (1637) | ADAPT AND REUSE | Report structure and fail-closed logic port well; construct entries do not |
| `modernization_planner.py`, `transformation_plan.py`, `external_dependency_edges.py`, `application_assembler.py` | REFERENCE ONLY | Overlap Pascal `blueprint*.py`, `graph.py`, `deps.py` |

### Stage 4 — Java Generation and Compatibility

| Component | Class | Rationale |
|---|---|---|
| `cobol_to_java_mapping.py` (6236), `group_storage.py`, `figurative.py`, `file_io_support_template.py`, `engine/cics/generator.py` | PASCAL-SPECIFIC DEVELOPMENT | Entirely COBOL constructs (PIC, groups, figuratives, CICS) |
| `java_ir.py`, `java_generator.py`, `application_generator.py` | ADAPT AND REUSE | Target-side Java IR is largely language-neutral; port after Pascal Stage 2 IR exists |

### Stage 5 — Runtime and Verification

| Component | Class | Rationale |
|---|---|---|
| `engine/oracle/*` | REFERENCE ONLY | Drives GnuCOBOL; Pascal needs an FPC/Delphi oracle. **Do not copy** (see §3) |
| `engine/candidate/*` (Docker Java/Spring adapters, image provenance) | ADAPT AND REUSE | Mostly language-neutral; image pinning/provenance port directly |
| `engine/comparators/framework.py`, `engine/execution/*` | ADAPT AND REUSE | Generic comparison and sandbox/workspace handling (record comparators are COBOL-flavoured). Execution is forbidden in Stage 1 |
| `engine/evidence/*`, `engine/verdict/*`, `engine/contracts/*`, `contracts/*.md` | ADAPT AND REUSE | Language-neutral untrusted-evidence → validated-manifest → verdict design; reword COBOL terms |
| `tests/adversarial/*` | REFERENCE ONLY | Attack-class checklist; bound to COBOL APIs |

### Stage 6 — Enterprise Platform

| Component | Class | Rationale |
|---|---|---|
| `api/app.py` (FastAPI, bearer auth, headers), `api/store.py` | REFERENCE ONLY | Pascal `server_security.py`, `tenancy.py`, `tenant_auth.py` cover this; `store.py` has no tenant column |
| `api/service.py`, `api/serialization.py` | PASCAL-SPECIFIC DEVELOPMENT / REFERENCE | Bound to the COBOL run lifecycle |
| `api/artifact_seal.py` | ADAPT AND REUSE (later) | Candidate hardening for the checkpoint seal; compare with `checkpoint_verify.py` first |
| `deployment/nginx`, `docker-compose.production.yml`, `Dockerfile.production`, `scripts/deploy|backup/*` | ADAPT AND REUSE | Stage 6 topology and operations |
| `scripts/supply-chain/*` (notices, release manifest, lock hashing) | DIRECT REUSE (candidate) | Language-neutral; verify hard-coded paths before use in Stage 6 |
| `frontend/` generic shell (Sidebar, Header, Button, Badge, StatCard, CopyButton, tokens) | REFERENCE ONLY | The Pascal workbench was built to the existing reference mock-up and CSP-safe CSS instead; COBOL pages are run/approval screens and its client stores the API token in `localStorage` (XSS-exposed) |
| `frontend/scripts/verify-bundle-secrets.mjs` | ADAPT AND REUSE (later) | Useful once the bundle is released |

## 3. Licence, notices and provenance

* **No COBOL source was copied** into this repository for Stage 1, so no Apache-2.0 attribution is currently owed and no NOTICE entry has been added. Had any file been copied, the obligations are: retain the Apache-2.0 text and the file's copyright notice, state changes, and carry the applicable `NOTICE` content.
* **Must not be carried over:** `Dockerfile.gnucobol`, `engine/oracle/*`, `tests/data/indexed_bdb` — they involve **GnuCOBOL (GPL-3.0 compiler / LGPL-3.0 runtime) and Berkeley DB (Sleepycat)**. The COBOL repo keeps them in a separate oracle image invoked as a process and notes legal review is needed before redistributing that image. Pascal's ADR 0002 likewise keeps FPC out-of-process.
* The COBOL repo has repo-level provenance only (one test file carries a header); per-file attribution would have to be added at copy time.
* **Open item for the owner:** this repository has **no root `LICENSE` file**. The COBOL repo is Apache-2.0. Engineering has not added or changed a licence (instruction R-6); any future port of Apache-2.0 code into a repo with a different or undeclared licence needs the owner's explicit decision first.
* Third-party additions in this work: FastAPI/Starlette/uvicorn/pydantic (MIT/BSD-3) and React/Vite (MIT) — see §5 of the [Stage 1 acceptance record](../stage1/STAGE1_ACCEPTANCE.md); their licences should be added to a Pascal notices file when a release process exists.

## 4. Security lessons from the COBOL ingestion, checked against Pascal

| COBOL practice / weakness | Pascal status |
|---|---|
| Per-entry compression-ratio limit on declared sizes before any write | Covered by the adversarial archive tests (`tests/security/test_adversarial_archives.py`) |
| Case-fold/separator duplicate detection | Covered (`test_duplicate_entries_are_refused`, `PATH_COLLISION`) |
| Raw-name traversal check **and** resolved-path containment | Covered (`pathsafe.py`) |
| Symlink entries refused | Covered (ZIP, Git, directory/junction) |
| Failed ingest discards the workspace; OS errors not leaked | Covered; asserted again in acceptance AC-10 |
| Whole ZIP held in memory | Pascal streams uploads to disk under a byte cap and deadline |
| Extraction trusts declared sizes | Pascal enforces actual-byte counts while streaming (`test_declared_size_lies`) |
| Windows reserved names / NTFS streams | Covered by `pathsafe.py` (`is_reserved_device_name`, colon/ADS refusal); unit-tested |
| API token in `localStorage` | Not copied; the workbench holds an optional tenant token in memory only (never `localStorage`/`sessionStorage`/cookies) |

## 5. Recommendation

1. Keep Stage 1 as built; port nothing from COBOL for it.
2. When Stage 2 produces a Pascal IR, adapt the capability-registry pattern, `capability_analyzer` report structure, `java_ir`, candidate adapters and evidence/verdict contracts.
3. Evaluate `scripts/supply-chain/*` for Stage 6 release hygiene once the owner has settled the licence position.
