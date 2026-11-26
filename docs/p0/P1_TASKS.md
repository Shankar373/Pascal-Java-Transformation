# P1 Task Breakdown — Ingestion and Discovery MVP

Derived from P0 findings. Each task states **why it exists** (the P0 evidence
that created it) and its **acceptance condition**, so no task can be closed on
the strength of a partial implementation.

Aligned to the master prompt's P1 scope:

> - Secure ZIP/Git input, file hashing/classification, project roots, app-shape
>   detection and build/compiler profiles.
> - Emit machine-readable `application-manifest.json`, `dependency-graph.json`
>   and human-readable discovery report.
> - Preserve unknown file types and unresolved dependency edges.
> - Add archive adversarial tests, deterministic discovery tests and no-LLM
>   dependency guard.

---

## A. P0 carry-over items (close first — they are gaps, not features)

| ID | Task | Why (P0 evidence) | Acceptance |
|---|---|---|---|
| A1 | Decide and add a **project licence** + generate a third-party notices file | `LICENCE_REVIEW.md` §4 — repo root contains only `README.md`, no `LICENSE` | Owner-approved `LICENSE` present; notices file lists MIT/MPL/GPL/LGPL components with revisions |
| A2 | Notify upstream DelphiAST of the FPC helper-recursion bug and track the patch | `PARSER_EVALUATION.md` §4 — candidate unusable under FPC without a local patch | Upstream issue link recorded, or explicit decision to maintain the patch in-repo, with a named owner |
| A3 | Add **`tp` and `iso` corpus fixtures** swept in their own modes | `DIALECT_COMPILER_MATRIX.md` §7 — `tp`/`iso` have probe coverage only, no fixture sweep | `-Mtp` and `-Miso` fixtures present and swept on host **and** pinned container; results in evidence |
| A4 | Preserve **pre-fix parser baselines** as archived files | `fixture-fixes.md` footnote 1 — parser pre-fix output was overwritten, an acknowledged evidence gap | Sweep scripts gain a `-Baseline`/archive mode so a pre-change run can be retained; gap documented as closed |
| A5 | Update `README.md` status to reflect P0 completion | Deferred by instruction until validation report and working-tree changes are reviewed | README status section matches actual evidence; no claim stronger than the evidence file behind it |

---

## B. Ingestion and secure input

| ID | Task | Acceptance |
|---|---|---|
| B1 | **Secure ZIP ingestion** — path-traversal, symlink, zip-bomb, deep-nesting and duplicate-entry defences | Archive adversarial suite passes; malicious archives rejected with a diagnostic, never extracted outside the staging root |
| B2 | **Secure Git input** — clone into an isolated workdir, verify commit hash, no submodule/credential leakage | Given a pinned commit, re-ingestion yields byte-identical file hashes |
| B3 | **File hashing and classification** — SHA-256 per file, extension + content sniffing, encoding detection | Manifest lists every ingested file with hash, class and encoding; unknown types are *preserved*, not dropped |
| B4 | **Project root detection** — `.dpr`/`.lpr`/`.dproj`/`.lpi`/`.dpk`/`.pas` layout heuristics | Roots reported with the evidence that justified each; ambiguous layouts produce a `BLOCKED`/`UNKNOWN` state, not a guess |
| B5 | **App-shape detection** — console, GUI (LCL/VCL/FMX), library/package, service | Shape recorded per project root with the detecting fixture/probe; `FAIL-DEPENDENCY` shapes (e.g. `Forms`) surfaced as capability gaps |

---

## C. Profiles

| ID | Task | Why (P0 evidence) | Acceptance |
|---|---|---|---|
| C1 | **Build/compiler profile model** — mode, defines, target platform, unit search paths, range/overflow state as a first-class tuple | `SEMANTIC_IR_REQUIREMENTS.md` I3/I4: mode and platform are context | Profile resolves to an explicit mode table; `-Miso` accepted even though absent from `-h` (`P18`) |
| C2 | **Per-platform capability scoping** | `ado_style_connection.pas` PASS/Windows vs FAIL/Linux | Every capability state is `(construct, mode, platform)`; the Windows/Linux delta for `ComObj` appears in the report |
| C3 | **Mode-dependent symbol visibility table** | `probes.txt` `P06`–`P11`, `system.ppu`/`objpas.ppu` scan | Discovery knows `AssignFile` originates in `ObjPas`, auto-included only under `objfpc`/`delphi`, and that `System.AssignFile` never resolves |

---

## D. Discovery outputs

| ID | Task | Acceptance |
|---|---|---|
| D1 | **`application-manifest.json`** — versioned schema, file inventory, hashes, dialects, shapes, profiles, capability states | Schema is versioned and validated in CI; every field traces to a file hash or probe |
| D2 | **`dependency-graph.json`** — `uses`/`requires` edges, resolved and unresolved | Unresolved edges are **preserved explicitly** with reason (`missing unit`, `platform-absent`, `external`), never silently pruned |
| D3 | **Human-readable discovery report** — renders D1/D2 with blockers and capability gaps | Report states exactly what is known, unknown and blocked; no `SUPPORTED` claim without an evidence file |
| D4 | **Unknown file types preserved** | Non-Pascal assets are inventoried and carried through untouched, flagged `DISCOVERY-ONLY` |

---

## E. Tests and gates

| ID | Task | Why | Acceptance |
|---|---|---|---|
| E1 | **Archive adversarial tests** | P1 bullet | Suite covers traversal, bomb, symlink, nesting, duplicate names, zero-byte and encoding-bomb inputs |
| E2 | **Deterministic discovery tests** | P1 bullet | Same input + same tool versions ⇒ byte-identical manifest and graph (IR invariant I6) |
| E3 | **No-LLM dependency guard (CI gate)** | `docs/decisions/0005` | CI **fails** if model SDKs, embedding packages, vector-store packages, AI endpoints, model-weight files or inference configuration appear in product dependencies or deployment manifests |
| E4 | **Parser negative tests — no silent drops** | master prompt P2 requirement, seeded now | Fixtures with unknown syntax produce a blocker with file/line/col; a test proves nothing is dropped silently |
| E5 | **Fixture-corpus regression gate** | `corpus/README.md` contract | Host + pinned-container sweeps run in CI; any new `MISMATCH` against expectations fails the build |

---

## F. Explicitly deferred (do **not** claim in P1)

| Deferred item | Earliest phase | Reason |
|---|---|---|
| Semantic IR implementation | P2 | P0 produced requirements only (`SEMANTIC_IR_REQUIREMENTS.md` §5) |
| Symbol/type resolution, control-flow and effect model | P2 | Neither parser candidate has a symbol table |
| FPC worker adapter + customer-licensed Delphi worker interface | P3 | Delphi is `ORACLE_UNAVAILABLE`; interface/test double is a P3 deliverable |
| Any `VERIFIED` capability state | P3+ | Requires original-vs-Java differential tests; a parse pass is `NOT_VERIFIED` |
| Delphi equivalence claims | blocked | Delphi compiler unavailable; FPC `-Mdelphi` is a proxy only |
| Pathological/oversized parser input robustness | P1 optional, P2 likely | P0 tested only synthetic valid + small malformed inputs |

---

## Suggested execution order

1. **A1–A5** (close P0 gaps — cheap, and they unblock honest reporting)
2. **B1–B3** (secure ingestion — everything downstream depends on it)
3. **C1–C3 + D1–D4** (profiles and manifests)
4. **E1–E5** (gates wired in from the start, not retrofitted)
5. **F** stays deferred; any attempt to pull it forward requires an ADR.
