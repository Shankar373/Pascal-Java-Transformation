# Stage 2 dialect and compiler-profile support matrix

**Status:** proposed declarations for S2.0 review; no Stage 2 semantic support is certified by this document.  
**Purpose:** distinguish a dialect/profile we intend to recognise from a compiler configuration and feature set we have actually validated.

## 1. Rules for declaring support

A dialect name alone is not a sufficient profile. Every semantic result must be scoped to the applicable dimensions:

- dialect family and dialect/version where known;
- compiler and exact version (or explicitly unknown);
- language mode;
- target OS/CPU/ABI;
- conditional defines and relevant compiler options;
- source encoding;
- feature-level evidence and known limitations.

The support matrix must never claim that a compiler compatibility mode is identical to the compiler it emulates. In particular, Free Pascal's -Mdelphi mode is not a Delphi compiler or a substitute for licensed Delphi validation.

Statuses:
- **PLANNED:** profile is in the product scope, but parser/semantic implementation is not complete.
- **PARSER-ONLY:** syntax can be parsed for a named slice; no project-wide semantic correctness claim.
- **PARTIAL:** explicitly listed semantic features are resolved and tested; gaps remain.
- **SUPPORTED (SCOPED):** declared feature set is validated for the exact profile/platform/toolchain; not a universal dialect claim.
- **UNAVAILABLE:** validation requires a compiler/toolchain/licence that is not available.
- **UNKNOWN:** evidence is insufficient to assign another status.
- **UNSUPPORTED:** the specific construct/profile is deliberately refused.

## 2. Initial profile declarations

| Profile ID | Intended language family | Initial compiler/reference context | Initial declaration | Important boundary |
|---|---|---|---|---|
| fpc-3.2.2 | Free Pascal | Pinned FPC 3.2.2 host/container baseline already used by P0 corpus | **Baseline for staged semantic validation** | Feature and mode coverage must still be proven; compiler acceptance of a fixture is not semantic completeness |
| fpc-objfpc-3.2.2 | Object Pascal under FPC ObjFPC mode | FPC 3.2.2, -Mobjfpc / source mode directive | **PLANNED** | Mode-specific visibility, types and syntax must be tested individually |
| fpc-delphi-mode-3.2.2 | Delphi-compatible syntax under FPC | FPC 3.2.2, -Mdelphi / source mode directive | **PLANNED** | This is an FPC mode only; it does not certify real Delphi compatibility |
| fpc-fpc-mode-3.2.2 | FPC mode | FPC 3.2.2, -Mfpc | **PLANNED** | Mode-specific language and predefined-unit rules must be explicit |
| fpc-tp-mode-3.2.2 | Turbo Pascal compatibility mode under FPC | FPC 3.2.2, -Mtp | **PLANNED** | Compatibility mode is not validation by historical Turbo/Borland compilers |
| fpc-iso-mode-3.2.2 | ISO mode under FPC | FPC 3.2.2, -Miso | **PLANNED** | ISO 7185 conformance requires a separately scoped standard corpus |
| delphi-native | Native Delphi/Object Pascal | Exact Delphi version and target platform must be supplied | **UNAVAILABLE until licensed reference compiler/toolchain is available** | DelphiAST parsing and FPC -Mdelphi do not establish native Delphi compiler correctness |
| turbo-borland-native | Turbo/Borland Pascal | Exact compiler generation and target environment must be supplied | **PLANNED / reference unavailable** | FPC compatibility-mode results must not be reported as native compiler evidence |
| iso-7185 | ISO 7185 Pascal | Standard-defined language subset plus explicit reference/compiler profile | **PLANNED** | Do not imply complete ISO compliance from a small fixture set |

These are planning declarations, not claims that every listed mode has already passed Stage 2 semantic analysis. P0's 24 fixtures and FPC 3.2.2 sweeps remain feasibility evidence only.

## 3. Profile resolution rules

1. Prefer explicit project/compiler configuration from the Stage 1 checkpoint.
2. Use source directives and deterministic file/project metadata as additional evidence.
3. Preserve conflicts between project metadata, source directives and observed facts as diagnostics.
4. Never silently select a dialect or mode merely because one parser accepts the syntax.
5. Generate separate build variants when conditional symbols or target platforms select different source.
6. If required context is absent, retain an unresolved/ambiguous profile and block dependent semantic facts.
7. Do not silently fall back from a native Delphi/Turbo/ISO claim to an FPC compatibility mode.

## 4. Feature-level coverage matrix

The implementation must publish a matrix at least at this granularity:

| Feature family | Required evidence |
|---|---|
| Lexical and directive rules | Token/directive fixtures, nested comments and mode-specific behaviour |
| Units and project structure | Unit identity, project entry points, uses/package resolution |
| Declarations and scopes | constants, variables, parameters, nested routines, visibility, shadowing |
| Routine semantics | overloads, forward declarations, methods, virtual/dynamic calls, generics where declared |
| Scalar types | signedness, width, ranges, enum ordinals, numeric precision and scale |
| Strings | ShortString, length-constrained strings, AnsiString, UnicodeString/WideString distinctions and encoding |
| Aggregates | arrays and lower bounds, sets and ordinal domains, records and variant records |
| Layout/ABI | field order, packing, alignment, offsets, size and calling conventions |
| Expressions | typing, implicit conversions, evaluation order, boolean/short-circuit rules |
| Statements and control flow | branches, loops, labels/goto, returns/exits and exception edges |
| Side effects | file/database/native/network/environment/time/random/messaging facts |
| Platform-specific dependencies | OS/CPU/compiler-specific units, native libraries and conditional variants |

Every matrix row records profile, compiler/version, mode, target platform, fixture IDs, expected/observed result, evidence link and known gaps.

## 5. Evidence restrictions

- Parser acceptance proves only that a parser produced a tree for a fixture.
- Compiler syntax acceptance proves only the tested compiler accepted that exact fixture and options.
- Neither parser agreement nor compiler acceptance alone proves correct symbol resolution, type layout or runtime semantics.
- Compiler-backed claims must identify the exact compiler build, version, mode, options and platform.
- No native Delphi correctness claim is permitted without a licensed native Delphi reference toolchain and a suitable evidence record.
- The current 24-fixture P0 corpus is a starting corpus, not sufficient evidence for broad dialect certification.

## 6. Change control

Any addition/removal of a declared dialect, compiler version, mode or platform must include:
- a written rationale and profile identifier;
- parser/toolchain version and licence/provenance review;
- new positive, negative and boundary fixtures;
- a full affected-corpus re-run;
- updates to this matrix and the Stage 2 acceptance record.

Do not update parser/compiler dependencies solely because a newer release exists. Re-run the pinned evaluation and preserve reproducibility.
