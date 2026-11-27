# Pascal Semantic IR contract

**Status:** proposed S2.0 design baseline; schema approval is an S2.0 exit condition.  
**Scope:** source-language semantic representation for Stage 2. This is not Java IR and not a conversion plan.

## 1. Purpose

The Semantic IR is the stable, parser-independent representation of a Pascal application that downstream stages can inspect. It must preserve source-language meaning and uncertainty rather than normalize everything into Java concepts.

The IR is built from a verified Stage 1 checkpoint plus explicit build-variant profiles. It must be deterministic, source-traceable, versioned and fail-closed.

The P0 requirements in [SEMANTIC_IR_REQUIREMENTS.md](../p0/SEMANTIC_IR_REQUIREMENTS.md) are the authoritative minimum coverage input to the S2.0 schema review. This document organizes those requirements into a proposed contract.

## 2. Top-level structure

The exact serialization format is to be approved in S2.0. The conceptual document envelope should contain:

| Section | Required content |
|---|---|
| Identity | IR schema version, analysis ID, Stage 1 checkpoint ID/digest and deterministic configuration fingerprint |
| Toolchain provenance | Parser adapter IDs/versions, profile resolver version, preprocessor version and relevant compiler/profile facts |
| Build variants | Dialect, compiler/version, language mode, target OS/CPU/ABI, defines, options and source-encoding context |
| Sources | Source-unit identity, checkpoint path, content hash, original spans, include origins and parse disposition |
| Syntax | Normalized AST nodes, node kinds, parent/child relationships and source spans |
| Symbols and scopes | Stable symbol IDs, declaring scope, symbol kind, name, visibility, declaration span, references and resolution state |
| Types and layouts | Type graph, exact scalar/aggregate facts, field order, bounds, packing/alignment and layout evidence |
| Semantics | Typed expressions/statements, conversions, evaluation order, assignments, routine calls and exception behaviour |
| Graphs | Unit/dependency relationships, call graph and control-flow graph with typed edges |
| Side effects | Database, file, environment, clock/random, native, network and messaging operation facts |
| Diagnostics | Stable diagnostic codes, severity, category, source span, build variant, evidence and blockers |
| Coverage/evidence | Feature-level disposition, fixture/compiler evidence references and explicitly unvalidated areas |

## 3. Provenance and source spans

Every source-derived fact must be traceable to:
- the immutable Stage 1 checkpoint digest;
- the exact source file path and content hash;
- the active build variant;
- one or more original-source spans (file, start/end line and column).

Preprocessed text must not erase its origin. A node originating from an include file must point to the include file's source span, while also retaining the inclusion chain that caused it to be active.

Compiler/profile facts that do not originate from source text must identify the toolchain/profile, version, relevant option and evidence record.

Parser-specific node IDs and classes must not leak into the public IR contract. IR node and symbol identifiers must be stable for identical inputs and configuration; avoid random UUIDs and traversal-order dependence on unordered containers.

## 4. Build-variant context

All resolution must be scoped to a build variant. At minimum, the variant context must be able to represent:
- dialect family and declared dialect version;
- compiler identity and exact version, or an explicit unknown/unavailable state;
- compiler language mode;
- target OS, CPU architecture and ABI;
- active conditional defines and relevant compiler options;
- range/overflow checking and alignment/packing options where applicable;
- calling-convention defaults and overrides;
- source encoding/code page where known;
- resolved include/search paths within the checkpoint.

The same source identifier may have different active symbols, syntax, types or dependencies in distinct variants. Do not merge these facts into one unconditional result.

## 5. Symbol and scope model

The model must represent at least:
- program, unit, package and module identities;
- interface/implementation and nested scopes;
- constants, variables, labels, types, parameters, procedures/functions, fields, properties, classes/interfaces and generic declarations in the supported slice;
- declaration site, scope parent, visibility, overload group and qualified name;
- references/use sites and resolution target;
- forward declarations, nested routines and mode-dependent predefined/implicit units;
- resolution status and reason when unresolved or ambiguous.

Use deterministic symbol identity based on checkpoint, build variant, declaring unit/scope and declaration location/content. The chosen exact ID formula is an S2.0 design decision.

## 6. Type and data-layout model

Do not represent a Pascal type as only a display string. The type graph must carry structured facts where relevant.

### Scalar and ordinal facts

- signedness, storage width and semantic range;
- ordinal bounds and enum member order/value;
- floating representation/precision where known;
- decimal/fixed-point precision and scale where known;
- subrange base type and inclusive lower/upper bounds.

### Strings

Distinguish at least:
- ShortString and explicit length-constrained string[N];
- AnsiString and its code-page/encoding facts;
- UnicodeString and WideString;
- implementation/mode-dependent meaning of unqualified string.

Preserve capacity, encoding, code page, reference-counting/ownership facts and ABI details only when the selected compiler/profile provides reliable evidence. Do not infer them from a generic type name.

### Aggregates and constructed types

- arrays: rank, each lower/upper bound, element type and storage facts;
- sets: ordinal domain, range and representation/size;
- records: declaration-order fields, field types, variant alternatives, packing, alignment, offsets and size;
- pointers and procedural types: target/signature, calling convention and nil/ownership facts where established;
- classes/interfaces/generics: inheritance, implemented interfaces, method signatures, generic parameters/constraints and dispatch facts for the supported slice.

For every layout fact, record its evidence source and applicable compiler/mode/platform. If a layout cannot be established, publish an explicit unknown-layout diagnostic and do not substitute a guessed layout.

## 7. Semantic model

The IR must represent:
- typed literals, identifiers, operators, expressions and explicit/implicit conversions;
- assignments, calls, argument binding, returns, exits and supported statements;
- expression evaluation order and profile-dependent boolean/overflow/range rules;
- control-flow nodes and typed edges for branches, loops, jumps, exceptional flow and exits;
- routine call relationships, including unresolved indirect/dynamic calls;
- exception declarations/handlers, propagation and cleanup/finally relationships;
- statically observed side-effect facts for database/SQL, file I/O, environment/configuration, time, randomness, native/COM/FFI, network, messaging and process interfaces.

Side-effect facts describe source operations and dependencies. They do not invoke them. An embedded SQL string is an extracted source fact, not permission to connect to a database.

## 8. Diagnostics and blocker contract

Each diagnostic should have:
- a stable machine-readable code;
- severity and category;
- concise human-readable message;
- file/span or explicit project-level location;
- build-variant identity;
- evidence/provenance;
- affected node/symbol/type when known;
- disposition (warning, unresolved, unsupported, unavailable, ambiguous);
- whether it blocks a dependent semantic conclusion.

Diagnostics are part of the semantic result and must be deterministic. A parser recovery warning must not be confused with a fully trusted semantic result.

Recommended dispositions:
- RESOLVED
- PARTIAL
- UNRESOLVED
- UNSUPPORTED
- UNAVAILABLE
- AMBIGUOUS

These are Stage 2 semantic dispositions, not Stage 3 conversion capability statuses.

## 9. Determinism and versioning

- Identical checkpoint + identical build variants + identical tool versions + identical configuration ⇒ byte-identical semantic artefacts.
- Sort maps, symbol collections, diagnostics and graph edges by documented stable keys before serialization.
- Keep wall-clock timestamps outside the content-addressed semantic payload.
- Include schema version and analysis configuration fingerprint.
- Define forward/backward compatibility and migration policy before consumers depend on the schema.
- A breaking semantic-model change requires a schema version change and explicit migration/rejection behaviour.
- Do not silently reinterpret old persisted IR under new compiler/parser semantics.

## 10. Stage boundaries

The Semantic IR must not contain a claim that a construct is convertible or behaviourally equivalent.

- Stage 2: what the Pascal program means and what remains unknown.
- Stage 3: whether the resolved construct is supported for a selected modernization target and how to plan it.
- Stage 4: generated Java and compatibility adapters.
- Stage 5: independent runtime comparison and evidence-backed equivalence verdict.

## 11. S2.0 decisions still required

The following must be made explicit and approved during S2.0 rather than silently hard-coded:
- final JSON/schema technology and naming conventions;
- stable ID strategy for nodes, symbols, types and graph edges;
- whether the public IR is a single graph document or partitioned per project/unit with a manifest;
- graph serialization/query strategy and maximum payload size;
- representation of multiple active build variants and variant-specific facts;
- exact diagnostic code namespace and severity policy;
- schema compatibility/migration policy;
- source-span convention (byte offsets, Unicode code points, line/column indexing) and encoding-error representation;
- which compiler facts are sourced from FPC metadata and how their version/provenance is sealed.
