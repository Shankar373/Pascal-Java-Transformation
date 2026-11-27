# Stage 2 acceptance and exit criteria

**Status:** acceptance contract proposed for S2.0 review. No Stage 2 implementation or acceptance is claimed.  
**Roadmap:** [STAGE2_ROADMAP.md](STAGE2_ROADMAP.md)  
**IR contract:** [STAGE2_SEMANTIC_IR_CONTRACT.md](STAGE2_SEMANTIC_IR_CONTRACT.md)

## 1. Acceptance principles

- Acceptance is based on the exact commit SHA and exact supported profile/feature scope.
- Every positive claim must have reproducible evidence. Parser acceptance, AI code review or a green general test suite is not proof of semantic correctness.
- Unsupported, ambiguous and unavailable cases must be tested as negative/boundary cases.
- No customer application, customer build script, database or external integration is executed during Stage 2.
- The product remains deterministic and passes the no-LLM guard.
- No tests may be skipped, weakened or have assertions removed merely to obtain a green gate. Any unavoidable environment skip is named and justified.

## 2. Phase acceptance gates

### S2.0 — Architecture and contracts

- [ ] Dialect/compiler/mode/platform profile matrix reviewed; no compatibility-mode overclaim.
- [ ] Parser SPI and normalized parse-result contract approved.
- [ ] Preprocessor/include/build-variant and source-map contracts approved.
- [ ] Diagnostic and blocker model approved.
- [ ] Versioned Semantic IR conceptual and machine-readable schema approved.
- [ ] Source identity, content hash and span conventions defined.
- [ ] Stable IDs and deterministic serialization rules defined.
- [ ] Security/non-execution boundary and resource limits defined.
- [ ] Golden-corpus expansion plan and phase test plan approved.

### S2.1 — Dialect profiles, preprocessing and parsing

- [ ] Every Pascal source in the test corpus receives an explicit parse disposition per build variant.
- [ ] Supported syntax fixtures produce stable normalized trees and accurate original-source spans.
- [ ] Include resolution is checkpoint-bound; include cycles, traversal and outside-root references fail safely.
- [ ] Conditional directives produce distinct explicit variants; unknown conditions do not become false by default.
- [ ] Nested comments/directives and mode-dependent behaviour have regression fixtures.
- [ ] Malformed input and parser recovery are reported; recovered trees are not automatically treated as semantically valid.
- [ ] Parser adapters run through the common SPI and expose no parser-specific model to downstream consumers.
- [ ] Time, memory, include-depth, expanded-size and variant-count limits are enforced.
- [ ] No customer code, scripts or build commands execute.

### S2.2 — Project-wide symbol and type resolution

- [ ] Unit/program identity and cross-unit uses resolution have positive, negative and ambiguous fixtures.
- [ ] Scope, visibility, shadowing, overload and nested-routine resolution match the named profile.
- [ ] Mode-dependent predefined/implicit units are represented and tested.
- [ ] Resolved references have stable symbol IDs and declaration/use-site provenance.
- [ ] Type graph covers the declared initial slice; unsupported types remain explicit.
- [ ] Numeric signedness/width/range, precision/scale and string kind/encoding/length are exact where claimed.
- [ ] Array bounds, enum ordinals, set domains and record/variant-record layout are validated against profile evidence where available.
- [ ] Calling convention, packing, alignment and ABI facts are never guessed.
- [ ] Unresolved/ambiguous symbols and unknown layouts block dependent conclusions.

### S2.3 — Semantic and behavioural-fact analysis

- [ ] Expressions and statements have typed semantic annotations for the declared feature slice.
- [ ] Operator semantics, conversions and evaluation order have golden assertions.
- [ ] Control-flow graph covers supported branches, loops, exits/jumps and exceptional edges.
- [ ] Routine call edges distinguish resolved, unresolved, virtual, indirect and dynamic cases where applicable.
- [ ] Exception handlers and propagation/cleanup paths are represented for supported constructs.
- [ ] Side-effect facts cover each declared category and point to source evidence.
- [ ] No database, file service, network, native integration or external process is contacted.
- [ ] Unknown or unsupported semantics are never silently lowered or discarded.

### S2.4 — Semantic IR integration, persistence, API and workbench

- [ ] Every semantic artefact validates against its schema and identifies the exact Stage 1 checkpoint/profile/toolchain.
- [ ] Semantic results are immutable/content-addressed or otherwise tamper-evident and do not modify Stage 1 checkpoints.
- [ ] Project, unit, symbol, type, graph and diagnostic queries are available through bounded API contracts.
- [ ] React workbench displays build variants, parse status, semantic facts, provenance and blockers without presenting conversion or equivalence verdicts.
- [ ] JSON and human-readable exports are deterministic and traceable.
- [ ] Tenant isolation, authentication assumptions, bounded response sizes and safe errors are tested.
- [ ] Stage 1 API and artefact compatibility is preserved or a separately approved migration exists.
- [ ] No-LLM guard passes.

### S2.5 — Validation and closure

- [ ] The golden corpus is expanded beyond P0's 24 feasibility fixtures with semantic positives, negatives and boundary cases.
- [ ] Every fixture has a profile, expected result, observed result and evidence reference.
- [ ] Parser, symbol/type, layout, semantic, API/schema, determinism, security and regression suites pass.
- [ ] Compiler-backed evidence names the exact compiler/version/mode/options/platform.
- [ ] Delphi native compiler claims remain unavailable until a licensed Delphi toolchain is tested.
- [ ] Windows and Linux lanes run; macOS/toolchain limitations are explicitly recorded if unavailable.
- [ ] CI runs on the exact candidate commit and all required jobs are green.
- [ ] No-LLM, non-execution, fail-closed and determinism gates pass.
- [ ] Coverage matrix names exactly which dialect/mode/platform/features are supported, partial, unsupported, unavailable or unknown.
- [ ] Acceptance record records residual risks, known gaps and unverified environments.

## 3. Mandatory cross-stage invariants

| Invariant | Evidence expected |
|---|---|
| Stage 1 checkpoint remains immutable | checkpoint verification before/after analysis; content hashes unchanged |
| Identical input/profile/tool versions produce identical semantic artefacts | separate-run byte/hash comparison |
| No customer application execution | instrumented process-boundary tests and code-level deny-list/static checks |
| Fail-closed unknowns | adversarial fixtures proving unknown syntax/directives/types cannot become resolved facts |
| Source traceability | every semantic fact/diagnostic resolves to source spans or explicit toolchain provenance |
| No LLM/ML inference | existing guard plus CI |
| Tenant isolation | cross-tenant reads and artifact access denied by API tests |
| Stage boundaries | API/report schemas have no conversion-support or behavioural-equivalence verdict field |

## 4. Minimum evidence pack for Stage 2 closure

1. Exact accepted commit SHA and CI run URLs.
2. Dialect/compiler/mode/platform/feature coverage matrix.
3. Versioned Semantic IR schema and compatibility policy.
4. Parser adapter and preprocessor test report.
5. Symbol/scope/type/layout resolution report.
6. Semantic/control-flow/side-effect analysis report.
7. Expanded corpus manifest, expected outcomes and results.
8. Determinism and non-execution test results.
9. API/workbench and tenant-isolation test results.
10. Residual limitations, unavailable toolchains and known false-positive/false-negative classes.
11. Licence/provenance status for parser tools and maintained patches.
12. Owner acceptance record.

## 5. Release and claim restrictions

Stage 2 may be marked **IMPLEMENTED AND TESTED** only for the exact feature/profile scope supported by the acceptance evidence. It must not be labelled universally complete.

Stage 2 acceptance does not:
- approve Stage 3 modernization capability decisions;
- authorize Java generation;
- prove Java output exists;
- prove behavioural equivalence;
- remove the need for Stage 5's original-program oracle;
- resolve the repository's open project-licence decision or any third-party legal review.

Stage 3 must consume the accepted, versioned Semantic IR and its diagnostics. It must not re-parse raw source or silently replace unresolved Stage 2 facts with assumptions.
