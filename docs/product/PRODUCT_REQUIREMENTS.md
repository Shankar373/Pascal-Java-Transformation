# Product Requirements — Pascal-to-Java Enterprise Modernization Platform

**Status:** Stage 1 requirements are implemented and accepted ([acceptance](../stage1/STAGE1_ACCEPTANCE.md)); Stages 2–6 requirements are stated here as scope, not as delivered capability.
**Provenance:** This document consolidates the owner-approved requirements as they were given to the engineering team (the finalized six-stage architecture, the *Final architecture v3.0* reference document held outside this repository, and the owner's Stage 1 instruction of 24 November 2026). Where the external document is more detailed it prevails; any divergence found must be reported to the owner, not silently resolved here.

## 1. Product statement

A discovery-first platform that analyses a customer's complete legacy Pascal estate, converts only a measured, capability-scoped subset into maintainable Java, and certifies behavioural equivalence for exactly the scope that was tested. Universal discovery is the goal; universal automatic conversion is **not** promised.

## 2. Users and jobs

| User | Job to be done |
|---|---|
| Modernization architect | Hand over an application (ZIP, Git, private repo) and receive an evidence-backed picture of what it is, what it depends on and what cannot be resolved |
| Customer security reviewer | Confirm that the customer's code is never executed and that one tenant's material is never visible to another |
| Platform operator | Run the service with bounded resources, recover from failures, and audit what was produced from which source |

## 3. Hard rules (all stages)

| ID | Rule |
|---|---|
| R-1 | **No LLM/ML/embeddings/RAG/probabilistic generation** in the shipped product; every decision is deterministic and rule-based. Enforced by `tools/p1/guard.py` (ADR 0005) |
| R-2 | **Deterministic output:** same source bytes + configuration + tool versions ⇒ byte-identical results |
| R-3 | **Fail closed; nothing dropped silently:** unknown files, constructs and dependencies are reported, never ignored |
| R-4 | **Evidence-backed:** every finding cites a file and location; detection is never a support claim |
| R-5 | **Preserve the customer's database and contracts** unless migration is separately approved |
| R-6 | Existing licences, notices and provenance are preserved; the project licence is not changed by engineering |

## 4. Six stages

| # | Stage | Requirement summary | Status |
|---|---|---|---|
| 1 | Ingestion and Discovery | §5 below | Implemented, accepted |
| 2 | Pascal Language Engineering | Dialect/compiler profiles, preprocessor model, parser frontends, project-wide symbol/type resolution, Semantic IR | Not started |
| 3 | Modernization Intelligence | Versioned capability registry (SUPPORTED/PARTIAL/UNSUPPORTED/UNAVAILABLE/UNKNOWN), blockers, deterministic transformation plan | Not started |
| 4 | Java Generation and Compatibility | Target-neutral Java IR; Plain Java (JVM 25) and Spring Boot from one IR; compatibility library | Not started |
| 5 | Runtime and Verification | Oracle vs candidate runs, differential comparison, evidence ladder, scoped certification | Blocked (no Delphi licence; FPC only) |
| 6 | Enterprise Platform and Operations | OIDC/RBAC, audit trail, SBOM/signing, on-prem workers | Partial (ingestion hardening, tenant tokens) |

## 5. Stage 1 requirements

Stage 1 is **non-executing**: static discovery only. It never runs customer scripts, executables, builds, compilers or database operations.

### 5.1 Functional

| ID | Requirement |
|---|---|
| S1-F1 | Accept a **ZIP archive**, a **public Git URL**, a **private Git repository** (HTTPS token or SSH key, supplied by the operator through the environment — never in URLs or argv) and an operator-allow-listed **local directory** |
| S1-F2 | Resolve any Git branch/tag/HEAD to an **exact commit before anything else** and record commit and tree ids |
| S1-F3 | Freeze the validated tree into an **immutable, content-addressed checkpoint** with a tamper seal; analysis reads the checkpoint, never staging; reuse requires re-verification |
| S1-F4 | Produce a **complete inventory** of every file (hash, size, class, encoding) and every directory, including empty ones |
| S1-F5 | Discover Pascal **projects, entry points, dialect, compiler and version**, application shape and compiler configuration |
| S1-F6 | **Enterprise dependency analysis:** units/includes/packages, libraries (bundled/external/unresolved), databases (credentials redacted, never connected), SQL, integrations, runtime and native dependencies, build scripts, schedules |
| S1-F7 | Emit an **evidence-backed Application Blueprint** plus unresolved-dependency, diagnostics, dependency-graph, manifest, checkpoint-manifest, project-inventory and architecture reports as machine-readable JSON/CSV and a human report |
| S1-F8 | Provide a **usable React workbench over a FastAPI service**: ingest (Git/ZIP/directory), five-step progress, blueprint panels, recent discoveries, downloads |
| S1-F9 | Surface blockers honestly: a discovery may complete *with blockers*; a refused input produces **no** blueprint |

### 5.2 Security, isolation and resilience

| ID | Requirement |
|---|---|
| S1-S1 | Hostile archives (traversal, absolute paths, duplicates/case collisions, bombs, symlinks, reserved names) are refused before any write outside staging |
| S1-S2 | Remote Git: HTTPS always, SSH only when configured; no credentials in URLs; non-public hosts refused unless allow-listed; address pinned for the fetch; hooks, filters, submodules, symlinks refused; tree limits enforced before checkout |
| S1-S3 | API: Host/Origin/CSRF checks, bounded bodies, streamed capped uploads, validated ids, allow-listed artefact names, sanitised errors, CSP and security headers |
| S1-S4 | **Multi-tenant isolation:** each tenant's jobs, uploads, checkpoints, discoveries and artefacts live under that tenant's root; cross-tenant reads return 404; when tenant tokens are configured the tenant is derived from the bearer token, never from a client header |
| S1-S5 | Bounded resources (queue, concurrent uploads, connections, sizes, time) and recovery: failed runs clean up staging/uploads; interrupted jobs are marked on restart; finished results survive restart |
| S1-S6 | Secrets never appear in outputs, errors or logs |

### 5.3 Non-functional

| ID | Requirement |
|---|---|
| S1-N1 | Deterministic, byte-identical results across separate stores |
| S1-N2 | Comprehensive automated tests; no test weakened to pass; the P0/P1 suites keep passing unchanged |
| S1-N3 | Windows and POSIX portability of the ingestion core (Python 3.11+, stdlib only; FastAPI/uvicorn only for the HTTP front end) |

### 5.4 Out of scope for Stage 1 (stated, not hidden)

Parsing to an AST or Semantic IR; capability classification; any Java generation; building, compiling or running customer code; connecting to customer databases; OIDC/RBAC, audit log, SBOM and signing (Stage 6); a Delphi oracle (Stage 5).

## 6. Traceability

Each S1 requirement is mapped to design, implementation and test evidence in [`STAGE1_ACCEPTANCE.md`](../stage1/STAGE1_ACCEPTANCE.md). Reuse decisions against the sibling COBOL platform are in [`COBOL_REUSE_AUDIT.md`](../reuse/COBOL_REUSE_AUDIT.md).
