# Stage 2 — Pascal Language Engineering

**Status:** PLANNED — planning documentation only; implementation has not started.  
**Predecessor:** Stage 1 — Ingestion and Discovery (implemented, accepted and merged to main).  
**Successor:** Stage 3 — Modernization Intelligence.

Stage 2 turns the immutable Stage 1 Application Blueprint and source checkpoint into a deterministic, project-wide understanding of Pascal syntax and semantics. Its principal output is a versioned **Pascal Semantic IR** with source provenance, parsed structure, resolved symbols, exact type/layout facts, semantic relationships, control flow, side-effect facts and explicit diagnostics.

Stage 2 determines **what the Pascal application says and means**. It does not decide whether the application can be converted (Stage 3), generate Java (Stage 4), or execute either application to prove behavioural equivalence (Stage 5).

## Documents

- [Stage 2 roadmap and phase plan](STAGE2_ROADMAP.md)
- [Dialect and compiler-profile support matrix](STAGE2_DIALECT_SUPPORT_MATRIX.md)
- [Pascal Semantic IR contract](STAGE2_SEMANTIC_IR_CONTRACT.md)
- [Stage 2 acceptance and exit criteria](STAGE2_ACCEPTANCE.md)

## Phase sequence

| Phase | Name | Primary result |
|---|---|---|
| S2.0 | Architecture and contracts | Approved dialect declarations, parser/preprocessor contracts, diagnostics and Semantic IR schema |
| S2.1 | Dialect profiles, preprocessing and parsing | Deterministic, source-mapped parsed units for declared build variants |
| S2.2 | Project-wide symbol and type resolution | Resolved scopes, declarations, references, types and data layouts |
| S2.3 | Semantic and behavioural-fact analysis | Typed expressions/statements, call/control-flow facts, exceptions and side-effect inventory |
| S2.4 | Semantic IR integration and API/workbench | Versioned, persisted, queryable project Semantic IR and visible diagnostics |
| S2.5 | Validation and Stage 2 closure | Evidence-backed dialect/feature coverage, determinism and regression certification |

A phase is complete only when its exit criteria are met and recorded. A green test suite alone does not establish universal Pascal support.

## Important constraints

1. **Deterministic product:** no LLM, ML inference, embeddings, RAG, vector database or probabilistic code generation.
2. **Fail closed:** unknown syntax, ambiguous build variants, unresolved symbols and unprovable type/layout facts become located diagnostics and blockers. Never guess.
3. **Immutable input:** analyze the sealed Stage 1 checkpoint; do not silently rewrite customer source.
4. **No customer-program execution:** Stage 2 may run product-owned parser workers in isolation and perform bounded static analysis. It must not run customer scripts, build steps, executables, database operations or integrations. The original-program oracle belongs to Stage 5.
5. **Evidence-scoped support:** report support per dialect, compiler/version, mode, platform and feature where those dimensions affect meaning. A compatibility mode is not proof of compatibility with the compiler it imitates.
6. **Stage boundaries:** Stage 2 produces semantic facts, not conversion decisions, Java code or behavioural-equivalence claims.

## Current baseline

- Stage 1 supplies immutable checkpoints, file inventory, project/dialect hints and dependency discovery.
- tools/p1/plex.py is a deterministic scanner/tokenizer; it is not a full Pascal parser and does not produce an AST.
- P0 evaluated Tree-sitter Pascal and DelphiAST on the same 24-fixture corpus. Their selected roles and constraints are recorded in [ADR 0001](../decisions/0001-parser-adapter-selection.md).
- Neither parser supplies project-wide symbol/type resolution; that is Stage 2 work.
- [P0 Semantic IR requirements](../p0/SEMANTIC_IR_REQUIREMENTS.md) are the evidence-backed starting requirements, not an implemented IR.

See [the roadmap](STAGE2_ROADMAP.md) before implementation begins.
