# Stage 2 roadmap — Pascal Language Engineering

**Status:** PLANNED — this document defines the proposed implementation sequence; no Stage 2 implementation is claimed.  
**Planning baseline:** current main after Stage 1 closure.  
**Input contract:** a verified Stage 1 checkpoint and its Application Blueprint.  
**Output contract:** a versioned, deterministic Pascal Semantic IR plus diagnostics and an evidence-backed support statement.

## 1. Purpose

Stage 1 discovers the application estate: files, project roots, dialect hints, dependencies and an immutable source checkpoint. It deliberately does not parse Pascal into an AST or determine program semantics.

Stage 2 adds that missing language-engineering layer. It must answer, with source-linked evidence:

- Which Pascal build variant is being analysed (dialect, compiler/version, mode, target platform, defines and relevant options)?
- What are the syntactic constructs in every supported Pascal source unit?
- Which declarations, identifiers, routines, types and units refer to one another across the project?
- What are the exact source-language type and data-layout facts?
- What expressions, statements, calls, control-flow and exception relationships are present?
- Which operations may observe or change external state (database, files, environment, clock, randomness, native code, network or messaging)?
- What could not be parsed or resolved, and why?

The stage must make uncertainty visible. It must not turn a parse success into a semantic-support claim.

## 2. Goals and non-goals

### Goals

1. Establish a parser-independent contract so the pipeline does not depend on a particular parser's node model.
2. Model dialect and build configuration explicitly; language mode and target platform are semantic context, not incidental metadata.
3. Preprocess supported directives and includes deterministically while preserving original-source provenance.
4. Produce syntax trees/AST structures for declared language subsets.
5. Resolve project-wide units, scopes, declarations, references, overloads and type relationships.
6. Resolve exact source type facts and record/array/set/ordinal layouts wherever the compiler profile and evidence allow.
7. Represent expressions, statements, evaluation order, control flow, exceptions, calls and side-effect facts.
8. Publish a versioned Semantic IR with stable diagnostics, source references and deterministic serialization.
9. Expose Stage 2 outputs through service/API and workbench interfaces.
10. Prove coverage through a reproducible golden corpus and explicitly scoped validation evidence.

### Non-goals

- Deciding whether a construct or application can be modernized. That is Stage 3.
- Creating a transformation plan or modernization recipe. That is Stage 3.
- Building Java IR, Java source, runtime adapters or Java projects. That is Stage 4.
- Executing customer Pascal applications, generated Java applications or customer build scripts.
- Running a behavioural-equivalence oracle or issuing equivalence certificates. That is Stage 5.
- Mutating customer source, schemas, databases, filesystems or external integrations.
- Decompiling binary-only inputs or pretending that missing source can be semantically reconstructed.
- Universal support for all Pascal dialects, compiler versions, frameworks or operating systems.
- Introducing LLM/ML inference, embeddings, RAG, vector stores or probabilistic decisions into the product.

## 3. Inputs, outputs and invariants

### Inputs

- Stage 1 immutable checkpoint identity and content hashes.
- Application Blueprint: project roots, entry points, source inventory, dependency edges, dialect/build hints and discovery diagnostics.
- Explicit analysis profile supplied by the operator or established by deterministic evidence. Conflicting or incomplete configuration must remain visible.
- Versioned Stage 2 toolchain/profile configuration, pinned parser adapters and bounded analysis limits.

### Outputs

- One or more explicit build-variant analysis results.
- Parsed source units with original and preprocessed source maps.
- Project-wide symbol, scope, reference and type models.
- Exact data-layout facts or explicit unresolved-layout diagnostics.
- Semantic expressions/statements, call relationships, control-flow and side-effect facts.
- A versioned Pascal Semantic IR, diagnostics, per-feature evidence and coverage report.
- API/workbench views of project and file-level semantic analysis.

### Invariants

1. **Checkpoint-bound:** every result identifies the Stage 1 checkpoint digest and source file hash. Do not analyse an unsealed, silently changed copy.
2. **Build-variant-bound:** every resolution is associated with the active dialect/compiler/mode/defines/platform context. Do not merge mutually exclusive variants into one false program.
3. **Source traceability:** every node, symbol, type fact, reference, edge and diagnostic traces to one or more source spans or a compiler/profile fact.
4. **Deterministic:** same checkpoint, profile, tool versions and configuration produce byte-identical semantic artefacts. Timestamps belong only in execution/run metadata, not the semantic content hash.
5. **Fail-closed:** unresolved names, ambiguous overloads, unknown directives, unsupported syntax and uncertain layout are explicit. Do not invent defaults.
6. **Parser neutrality:** downstream semantic analysis consumes the agreed adapter output contract, not parser-specific AST classes.
7. **No execution:** no customer program, script, build command, database operation or external integration is run.
8. **No silent omissions:** every inventoried Pascal source receives a parse disposition, even if parsing fails or is not supported.

## 4. Phase plan

The phases are sequential gates. Work may overlap internally only after the preceding phase's contracts are stable; later work must not bypass an unresolved gate.

### S2.0 — Architecture and contracts

**Purpose:** define the interfaces, data contracts and support declarations before implementing the language engine.

**Covers**
- Initial dialect/compiler/mode/platform support declarations and the evidence required for each status.
- Common parser SPI and parser result contract, independent of Tree-sitter or DelphiAST node types.
- Preprocessor/include contract: build variants, directive evaluation, include resolution, source maps, limits and unsupported-directive handling.
- Canonical source-span and provenance types.
- Diagnostic model: stable code, severity, category, location, evidence, affected variant, resolution state and blocker relationship.
- Symbol/scope/type/semantic model boundaries.
- Versioned Semantic IR schema, stable IDs, deterministic ordering/serialization and schema-evolution policy.
- Security and non-execution boundary for parser workers.
- Initial golden-corpus plan and phase acceptance tests.

**Deliverables**
- Approved dialect/profile matrix.
- Parser SPI and parse-result contract.
- Preprocessor contract and source-map model.
- Diagnostic and blocker contract.
- Semantic IR schema v1 design (conceptual schema plus machine-readable schema where appropriate).
- Architecture decisions for unresolved trade-offs.

**Exit gate**
- Contracts reviewed and approved.
- Every output field has a definition, source/provenance rule and deterministic representation.
- Unsupported/ambiguous behaviour has a fail-closed representation.
- Phase test plan and initial feature-slice are agreed.
- No parser implementation or broad semantic implementation is claimed complete by S2.0 alone.

### S2.1 — Dialect profiles, preprocessing and parsing

**Purpose:** turn checkpoint source files into parser-neutral syntax structures for explicit build variants.

**Covers**
- Implement explicit dialect/compiler profiles from the S2.0 matrix. Resolve profiles from project metadata and source directives; retain conflicts rather than silently choosing one.
- Model compiler modes, conditional defines, target OS/CPU, source encoding and relevant compiler options.
- Deterministically process supported compiler directives and include files from the checkpoint only.
- Preserve a source map from every expanded token/node back to the original file and line/column. Include files must retain their own source identity.
- Bound include depth, expanded bytes, number of variants and directive evaluation work. Detect cycles and path escapes.
- Integrate parser candidates behind the shared SPI:
  - Tree-sitter Pascal remains the error-tolerant structural/discovery parser where appropriate.
  - DelphiAST remains a separately invoked AST provider for semantic parsing of constructs it supports, with the documented FPC patch and licence/provenance controls.
  - Neither parser is a semantic authority; parser disagreement or partial recovery must produce explicit status/diagnostics.
- Classify each source/build variant as parsed, parsed-with-recovery, unsupported, ambiguous or failed according to the contract.

**Deliverables**
- Dialect profile resolver and explicit build-variant model.
- Deterministic preprocessor/include resolver and source maps.
- Parser adapter implementations and normalized AST output.
- Per-file/per-variant parse reports and diagnostics.
- Bounded worker/process boundary and parser health tests.

**Exit gate**
- Every Pascal source in the Stage 1 corpus has an explicit parse disposition.
- Supported fixture constructs produce stable normalized trees and correct source spans.
- Conditional variants and includes are reproducible and correctly source-mapped.
- Parser failures, malformed input, cycles, path escapes and resource limits fail safely.
- No customer script, executable, build command or application is executed.
- No unsupported construct is silently represented as valid syntax.

### S2.2 — Project-wide symbol and type resolution

**Purpose:** turn parsed units into a project-wide declaration and type model, not merely a collection of independent syntax trees.

**Covers**
- Unit/program/package identity and resolution of uses, requires, include and project references against the checkpoint and declared search paths.
- Scope hierarchy: unit, interface/implementation, routine, nested routine, class/record and local scopes as applicable.
- Declaration collection and resolution for constants, variables, types, labels, parameters, procedures/functions, properties, fields, classes/interfaces and generic declarations in the supported slice.
- Visibility and name lookup rules, qualified names, mode-dependent implicit/predefined units and shadowing.
- Forward declarations, overloaded routines, nested procedures, method dispatch metadata and generic relationships where supported.
- Type graph: aliases, ordinal/subrange/enum, integer, floating, fixed-point/currency-like, strings, arrays, sets, pointers, procedural types, records/variant records, classes/interfaces and generic types.
- Exact type facts: signedness, bit width, bounds, precision, scale, encoding, string kind/length, ordinal values, array bounds, set domain and target/compiler dependence.
- Data layout: record field order, variant alternatives, packing, alignment, field offsets, size, ABI/calling convention and binary-serialization-relevant facts when evidence is available.
- Unresolved or ambiguous references/types must produce stable diagnostics and block dependent semantic conclusions.

**Deliverables**
- Project-wide symbol table and scope graph.
- Cross-unit reference and call-target resolution facts (where statically resolvable).
- Versioned type graph with exact facts and provenance.
- Record/array/set/ordinal layout facts or explicit unknown-layout blockers.
- Resolution reports and diagnostics.

**Exit gate**
- Cross-unit declaration/reference fixtures resolve to expected symbol IDs.
- Scope, visibility, shadowing, overload and mode-dependent lookup tests pass.
- Exact type/layout facts match pinned compiler/profile evidence for the validated slice.
- Unknown types, duplicate/ambiguous symbols, unresolved units and unsupported layout constructs fail closed.
- Resolution is deterministic and all facts trace to source/profile evidence.

### S2.3 — Semantic analysis and behavioural facts

**Purpose:** represent what the parsed and typed Pascal constructs mean structurally, without executing the customer application or deciding Java convertibility.

**Covers**
- Semantic annotations for literals, identifiers, operators, expressions, assignments, calls and type conversions.
- Expression typing, lvalue/rvalue status, evaluation order, short-circuit/boolean rules and implicit conversions where profile-defined.
- Statement semantics for blocks, conditionals, case/select, loops, exits, returns, gotos/labels, exception handling and supported language constructs.
- Control-flow graph with explicit blocks, edges, loop back-edges, exceptional edges and routine exits.
- Routine call graph and call-target certainty; indirect/virtual/dynamic calls remain marked unresolved when necessary.
- Exception classes/handlers, propagation and finally/cleanup structure for supported constructs.
- Side-effect facts for database/SQL operations, file I/O, environment/configuration, clock, random sources, native libraries/FFI/COM, network, messaging and process boundaries.
- Distinguish statically observed syntax from inferred behaviour. Embedded SQL strings, for example, are extracted as source facts; they are not executed.
- Preserve source-language semantics even when a construct is unsupported by a later target. Do not normalize away overflow, range checks, rounding, encoding or exception behaviour.

**Deliverables**
- Typed expression and statement annotations.
- Control-flow and routine-call graphs with evidence.
- Exception-flow facts.
- Side-effect inventory linked to source spans and dependencies.
- Explicit unknown/unsupported semantic diagnostics.

**Exit gate**
- Semantic fixtures assert exact annotations, graph edges, evaluation order and side-effect facts.
- Mode-dependent and platform-dependent semantics are represented in context.
- No side-effect target is contacted and no customer program is run.
- Unsupported or ambiguous constructs remain visible and cannot be mistaken for resolved semantics.

### S2.4 — Semantic IR integration, persistence, API and workbench

**Purpose:** make the semantic model a stable, inspectable project artefact that downstream stages and users can consume.

**Covers**
- Implement the approved versioned IR schema and deterministic serializer.
- Persist semantic artefacts against immutable checkpoint and analysis/profile identity. Avoid mutating the Stage 1 checkpoint or overloading Stage 1 discovery records.
- Provide project/unit/symbol/type/diagnostic/graph query paths in FastAPI with bounded responses and tenant isolation consistent with Stage 1 patterns.
- Expose parse status, build variants, symbol references, type/layout facts, control flow, side-effect facts, provenance and blockers in the React workbench.
- Support deterministic JSON/schema downloads and human-readable reports.
- Define schema version compatibility, migration and unsupported-version behaviour.
- Ensure each API response makes clear that semantic analysis is not a conversion-support or behavioural-equivalence verdict.

**Deliverables**
- Versioned Semantic IR model and schema validator.
- Persistence and content-addressed semantic artefacts.
- Stage 2 API endpoints and typed frontend clients.
- Workbench semantic views and downloads.
- Operational limits, access controls and API tests.

**Exit gate**
- Semantic IR validates against its published schema and is linked to the exact Stage 1 checkpoint.
- API/UI can inspect project, unit, symbols, types, diagnostics and semantic graphs for validated fixtures.
- Serialization is deterministic; repeated analyses with identical inputs produce identical semantic artefact hashes.
- Tenant boundaries, resource limits, error contracts and no-LLM guard remain intact.
- Stage 1 APIs and artefacts remain backward compatible unless a separately approved migration is supplied.

### S2.5 — Validation, evidence and Stage 2 closure

**Purpose:** establish exactly which dialect/mode/platform/features the Stage 2 engine understands and where it does not.

**Covers**
- Expand the 24-fixture P0 corpus into a structured semantic golden corpus covering declarations, expressions, procedures, types/layouts, directives, units, classes, exceptions, file/database/native side effects and malformed/unsupported cases.
- Keep expected outcomes explicit; fixtures must cover positive, negative, ambiguous and platform/mode-dependent cases.
- Validate parser output and semantic facts against pinned compiler/profile evidence where available. Keep Delphi compiler claims blocked without a licensed Delphi reference toolchain.
- Differential-check parser adapters where useful, but do not treat parser agreement as compiler correctness.
- Validate semantic schema, deterministic serialization, stable diagnostics, provenance and API behaviour.
- Add adversarial resource/path/include tests and prove non-execution boundaries.
- Run supported OS/CI lanes and record gaps where a lane/toolchain is unavailable.
- Publish a dialect × compiler/version × mode × platform × feature coverage matrix with evidence links and known limitations.

**Deliverables**
- Expanded golden corpus and versioned expected results.
- Parser, semantic, IR, API, determinism, security and regression reports.
- Feature-level coverage matrix with SUPPORTED, PARTIAL, UNSUPPORTED, UNAVAILABLE or UNKNOWN meanings defined by evidence.
- Stage 2 acceptance record and residual-risk list.

**Exit gate**
- All mandatory Stage 2 gates pass on the exact candidate commit.
- Every corpus fixture has a documented expected and observed result; no hidden skips or weakened assertions.
- Every claimed supported feature has positive evidence and relevant negative/boundary tests.
- Unknown and unsupported features remain blockers; there is no universal-support claim.
- CI and no-LLM guard are green; non-execution and determinism tests pass.
- Stage 2 acceptance record lists unverified toolchains/platforms and outstanding limitations.
- Stage 3 may consume only the sealed, versioned Semantic IR outputs from an accepted Stage 2 baseline.

## 5. Cross-cutting engineering requirements

### Parser and compiler tooling

- Use the parser candidates and exact revisions already evaluated in [ADR 0001](../decisions/0001-parser-adapter-selection.md) as the starting point. Re-evaluate before changing versions or adding a parser.
- Keep Tree-sitter and DelphiAST behind one adapter contract.
- Run DelphiAST as an isolated helper process, not as an embedded dependency, consistent with the accepted ADR.
- Maintain the DelphiAST FPC patch as a documented diff and preserve required MPL-2.0 notices/source obligations. Do not broaden its distribution/linkage model without licence review.
- FPC -Mdelphi is a compatibility mode, not proof of equivalence to a licensed Delphi compiler.
- FPC 3.2.2 is the existing pinned P0 corpus baseline. Updating it is a controlled toolchain change with a re-run of the complete golden corpus.

### Preprocessing and build variants

- Build variants are explicit records, not a single guessed configuration.
- Includes resolve only within the immutable checkpoint and approved search roots.
- Conditional symbols are evaluated only under the selected profile. Unknown conditions are not treated as false.
- Preserve original source and include-origin spans after expansion.
- Apply hard limits to variants, include depth, expanded size and parser time/memory.
- Unsupported directives, compiler plugins and external preprocessing commands are never executed; they produce a diagnostic or a separately reviewed safe integration.

### Type and semantic precision

- Do not collapse source types into Java-like types in Stage 2.
- Preserve integer signedness/width, subrange limits, numeric precision/scale, string kind/encoding/length, array lower bounds, enum ordinals, set domains, record field order and packing/alignment.
- Model mode- and platform-dependent rules in the build-variant context.
- Do not infer record ABI/layout without a matching compiler/profile fact or a clearly labelled unknown.
- Preserve expression evaluation order, overflow/range-check settings, rounding, exception paths and side-effect ordering.

### Diagnostics and support vocabulary

Each diagnostic should carry a stable code, severity, category, source location, build variant, evidence, affected symbol/node (when known), and whether it blocks a dependent conclusion.

Recommended semantic statuses:
- RESOLVED: the fact was resolved under a named profile with evidence.
- PARTIAL: some required facts are known, but explicit gaps remain.
- UNRESOLVED: references or meaning cannot be determined.
- UNSUPPORTED: construct is outside declared implementation coverage.
- UNAVAILABLE: required compiler/toolchain evidence is not available.
- AMBIGUOUS: multiple incompatible interpretations remain.

Do not reuse Stage 1's discovery statuses to imply semantic or conversion support. Stage 3 owns conversion capability classification.

## 6. Suggested work order and gates

| Order | Work item | Depends on | Must not be bypassed |
|---|---|---|---|
| 1 | S2.0 contracts and support declarations | Stage 1 blueprint + P0 evidence | Yes |
| 2 | S2.1 dialect/preprocessor/parser pipeline | S2.0 approved contracts | Yes |
| 3 | S2.2 symbols/types/layouts | S2.1 stable parser and build variants | Yes |
| 4 | S2.3 semantic facts and graphs | S2.2 resolved symbol/type model | Yes |
| 5 | S2.4 IR persistence and API/workbench | S2.0 schema + S2.1–S2.3 model outputs | Yes |
| 6 | S2.5 validation and closure | All previous phases | Yes |

## 7. Stage 2 completion statement

Stage 2 is complete only when an accepted commit contains the parser/preprocessor, project-wide symbol/type resolution, semantic analysis, versioned IR/API integration, expanded validation evidence and an explicit coverage matrix.

Completion means **the declared and tested Pascal subset has a reproducible semantic representation**. It does not mean that all Pascal dialects are supported, that any construct is convertible, or that generated Java is behaviourally equivalent.
