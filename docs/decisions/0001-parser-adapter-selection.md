# ADR 0001: Initial Pascal parser adapter selection

- **Status:** Accepted
- **Date:** 2026-11-13
- **Phase:** P0
- **Evidence:** `docs/p0/PARSER_EVALUATION.md`, `docs/p0/evidence/`
  (`treesitter.txt`, `delphiast.txt`, `parser-performance.txt`,
  `parser-recovery.txt`, `delphiast-fpc-helper-recursion.patch`)

## Context

The platform needs Pascal parsers for discovery (P1) and for a Semantic IR
(P2). Two maintained open-source candidates exist for Object Pascal:

| | tree-sitter-pascal | DelphiAST |
|---|---|---|
| Revision evaluated | `042119e` | `3840253` |
| Licence (read from `LICENSE`) | MIT | MPL-2.0 |
| Error recovery | multiple errors, keeps building the tree | stops at first error |
| Spans | full `[row,col]-[row,col]` ranges on every node | first error `line:col` only |
| Symbol table | none | none |
| Builds under FPC as-is | yes | **no — needs a patch** |
| Documented usage | whole file | one unit at a time |

Both were tested against the same 24-fixture golden corpus before either was
endorsed: **24/24 acceptance each**, against a compiler oracle of 21 PASS /
3 declared dependency failures.

**Selection was explicitly not based on stars, download counts, recency or
popularity.** It is based on measured behaviour (recovery, spans, licence,
buildability) and on the distinct jobs the two jobs require.

## Decision

**Adopt both parsers as complementary adapters with separate, non-overlapping
roles.**

1. **`tree-sitter-pascal` is the primary discovery/inventory parser.**
   Used to walk arbitrary, possibly broken legacy input and produce a complete
   file inventory with spans. Its error recovery (`nodes_after_error=yes` in
   `parser-recovery.txt`) is the property that earns this role: one odd line
   must not cost us the other 5,000 lines of a real estate.

2. **`DelphiAST` is the AST provider for semantic analysis** of constructs it
   supports, run **as a separate process**, with the documented FPC patch
   maintained in-repo (`evidence/delphiast-fpc-helper-recursion.patch`).
   Its fail-closed behaviour — first error only, no partial AST — is the
   property that earns *this* role: semantic work must not proceed on a
   best-effort tree.

3. **Neither parser is a semantic authority.** Neither has a symbol table and
   neither resolves `uses` edges. Resolution is P2 work and belongs to the
   Semantic IR, not to a parser.

4. **Compiler metadata stays authoritative.** Where FPC can answer a dialect
   question (`probes.txt`), the compiler's answer overrides both parsers.

## Consequences

**Positive**

- Discovery is resilient to malformed input; semantic analysis fails closed.
- Two independent parsers over one corpus give a cross-check: a construct both
  accept is stronger evidence than one parser alone.
- MIT + MPL-2.0 are both permissive enough for this architecture; neither
  forces our own source open at the project level.

**Negative / costs**

- **Two adapters to maintain.** Mitigation: a shared `PascalParserAdapter`
  contract (P2) so downstream code never branches on which parser ran.
- **DelphiAST requires a maintained FPC patch** and is not usable as-is. The
  patch is a permanent fork liability with an upstream-notification task
  (`P1_TASKS.md` A2).
- **MPL-2.0 file-level copyleft** attaches to modified DelphiAST files; the
  patch must remain published as a diff against MPL source. If DelphiAST is
  ever *linked into* the shipped product rather than invoked as a process, its
  covered files must ship their source.
- **Measurement caveats.** Time/memory figures are single-run with ~2×
  run-to-run variance and are not a ranking; see `PARSER_EVALUATION.md` §6.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| **tree-sitter only** | No structured AST for P2 semantic work; would force building an AST layer from a CST, duplicating DelphiAST. |
| **DelphiAST only** | Fails closed on the first error — unacceptable for *discovery* over unknown legacy input, where losing the rest of the file is the failure mode we most need to avoid. Also unusable under FPC without a patch, so it cannot be the sole dependency. |
| **Select on popularity/stars** | Explicitly forbidden by the master prompt, and irrelevant: both candidates are low-star niche tools whose fitness can only be established by testing. |
| **Write our own parser** | Out of scope for P0, high cost, and P0 established that two existing candidates already accept the corpus. Revisit only if both fail a future requirement. |
| **Adopt a third candidate** | None other maintained for Object Pascal. Re-evaluate if one appears; the evaluation harness (`sweep-*.ps1`, `measure-parsers.ps1`, `probe-recovery.ps1`) is reusable for any new candidate. |

## Revisit triggers

- Upstream fixes or rejects the DelphiAST FPC patch (A2 outcome).
- A parser candidate fails a real-world customer corpus the synthetic corpus
  did not represent.
- The dual-adapter contract proves more costly than the recovery benefit.
- Delphi itself becomes available and provides an authoritative reference
  parser we can compare against.
