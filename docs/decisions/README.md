# Architecture Decision Records

Numbered, dated decisions for this platform. Each record states the context,
the decision, its consequences, the alternatives rejected **and why**, and the
triggers that would force a re-visit. A decision without a reversal condition
is an assumption, not a decision.

| # | Decision | Phase | Status |
|---|---|---|---|
| [0001](0001-parser-adapter-selection.md) | Initial Pascal parser adapter selection (tree-sitter-pascal + DelphiAST, complementary roles) | P0 | Accepted |
| [0002](0002-licence-decisions.md) | Open-source licence decisions (MIT / MPL-2.0 / GPL / LGPL boundaries) | P0 | Accepted |
| [0003](0003-target-java-version.md) | Target Java version and output profiles (Java 25 LTS baseline; Plain Java + Spring Boot from one IR) | P0 | Accepted |
| [0004](0004-database-policy.md) | Database policy — preserve-first (Mode A default; Mode B opt-in; PostgreSQL for platform metadata only) | P0 | Accepted |
| [0005](0005-no-llm-ci-gate.md) | No-LLM / no-probabilistic CI gate | P0 | Accepted |

## Conventions

- **Numbering** is zero-padded and sequential; a decision's number never
  changes once published.
- **Status** is `Proposed`, `Accepted`, `Superseded by NNNN`, or `Deprecated`.
- **Evidence over assertion.** P0 records cite the file under
  `docs/p0/evidence/` that backs them — a claim with no evidence file behind it
  does not belong in an ADR.
- **Nothing here is `VERIFIED`.** Capability state for every P0 decision is
  `NOT_VERIFIED` with respect to conversion correctness; P0 established
  feasibility, not equivalence.

## Open items tracked elsewhere

| Item | Where tracked |
|---|---|
| This repository has no `LICENSE` file — **OPEN, owner decision** | `docs/decisions/0006-pascal-repository-licence-unresolved.md` |
| Third-party notices file | Generated: `THIRD_PARTY_NOTICES.md` (`tools/release/generate_notices.py`) |
| DelphiAST FPC patch not yet reported upstream | `docs/p0/P1_TASKS.md` A2 |
| Deferred licence reviews (SchemaCrawler, JSqlParser) | `docs/p0/LICENCE_REVIEW.md` §5 |
| Local JDK 21 is not the Java 25 baseline | `docs/decisions/0003-target-java-version.md` |
