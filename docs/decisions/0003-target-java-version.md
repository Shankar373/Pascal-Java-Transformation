# ADR 0003: Target Java version and output profiles

- **Status:** Accepted
- **Date:** 2026-11-13
- **Phase:** P0 (decision only — no Java is generated in P0)
- **Source of truth:** master prompt *Recommended technology stack* and
  *Java target policy*; architecture v3.0 *Version notes*

## Context

Generated code must target a specific Java baseline, and that choice is expensive
to reverse once customers build on it. The constraints:

- **Spring Boot 4.1.2** requires at least Java 17 and is compatible up to
  Java 27.
- **Java 25 is Oracle's current LTS.** Java 27 is the current *feature* release
  and is **non-LTS**. The next planned LTS on Oracle's roadmap is Java 29
  (September 2027).
- The architecture requires **two output profiles** — Plain Java and Spring
  Boot — both consuming **one common target-neutral Java IR**.
- P0 produced **no Java output at all**, so this is a forward decision, not a
  retrospective description of work done.

## Decision

1. **Java 25 LTS is the production baseline** for generated code and for the
   control plane.
2. **Java 27 is an optional feature-release compatibility test target only** —
   never an LTS baseline. Generated code must not *require* Java 27.
3. **Spring Boot 4.1.2** is the backend framework for the Spring profile, with
   Spring Framework 7.0.10+ and Spring Security from the Boot-managed set.
4. **Two profiles from one IR:** Plain Java (JDBC) and Spring Boot
   (JDBC or MyBatis for explicit SQL) are both generated from the same
   target-neutral Java IR. Profile choice is a build-time switch, not a
   second transformation pipeline.
5. **Maven 3.10.0 + Maven Wrapper**, with exact versions pinned and security
   patches re-verified before release.

## Consequences

- **LTS-only production baseline** means customers get a supportable runtime;
  feature-release testing is bounded and explicit rather than accidental.
- **One IR, two profiles** keeps the two outputs semantically comparable —
  differential testing (P6) can compare *profiles* without conflating them with
  *different source semantics*.
- **Toolchain gap to close before P5:** the P0 environment has **Temurin JDK
  21.0.12.1** installed, which is *not* the Java 25 baseline. P0 did not need
  it (no Java is generated), but P5 must provision JDK 25 and the pinned Maven
  version, or this ADR's baseline cannot be exercised. Recorded as a P5
  prerequisite rather than silently worked around.
- **Point-in-time versions.** The stack snapshot is dated 12 November 2026;
  Java 29 arriving in September 2027 will require re-evaluation of this ADR.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Java 17 baseline | The conservative choice, but it is below Spring Boot 4.1.2's floor only in *headroom*, not in necessity — and it would forgo the current LTS immediately on adoption. |
| Java 27 baseline | Non-LTS. Adopting a feature release as the production baseline would make every customer's runtime a short-lived target. |
| Java 21 baseline | Not an LTS-floor issue, but it is not the current LTS either; would be outdated on arrival. (Note: JDK 21 is what happens to be installed in P0 — convenience, not a decision.) |
| Separate transformation pipelines per profile | Would double the surface for semantic drift between Plain Java and Spring Boot outputs, undermining P6 differential certification. |
| Kotlin or another JVM language | Out of scope; the prompt specifies Java, and a second language would complicate the equivalence argument for no coverage gain. |

## Revisit triggers

- Java 29 (September 2027) becomes the current LTS and Java 25 ages out.
- Spring Boot releases a major that drops Java 25 support.
- A customer environment mandates a different LTS (then: add a *profile*, do
  not fork the IR).
