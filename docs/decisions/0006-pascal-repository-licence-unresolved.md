# ADR 0006: The Pascal repository's own licence is unresolved

- **Status:** **OPEN — owner decision required.** Engineering has not selected, added or changed a licence.
- **Update 2026-11-26 (Stage 1 release closure):** the four option families (Apache-2.0; MIT/BSD-3-Clause; proprietary all-rights-reserved; copyleft) were presented to the owner with implications. The owner **deferred the decision** ("decide later"). Status remains OPEN; no `LICENSE` file was created. The decision still blocks public release and any porting of COBOL (Apache-2.0) code.
- **Date:** 2026-11-24
- **Phase:** Stage 1 closure
- **Evidence:** `git ls-files` (no `LICENSE`/`COPYING`/`NOTICE` file), `docs/p0/LICENCE_REVIEW.md` §4, `docs/reuse/COBOL_REUSE_AUDIT.md` §3, `THIRD_PARTY_NOTICES.md`

## Context

This repository has never carried a root licence file. Until one is chosen, the default legal position is that all rights are reserved by the copyright holders: others may not use, copy or modify the code, and contributors have no stated terms. The sibling COBOL repository is Apache-2.0 (`PROJECT_LICENSE_DECISION.md`, 2026-11-03).

## What the decision affects

| Question | Why it depends on the licence |
|---|---|
| Porting COBOL code (Apache-2.0) here | Apache-2.0 permits it with attribution, but mixing into a differently-licensed or unlicensed repository needs the owner to confirm the intended outbound terms. No COBOL code has been copied |
| Shipping third-party components | Current dependencies (MIT, BSD-3-Clause, PSF-2.0, Apache-2.0 and others, all permissive; see `THIRD_PARTY_NOTICES.md`) are compatible with proprietary or open outbound licensing. The one weak-copyleft item is MPL-2.0 (DelphiAST, via a committed diff only; `certifi`, test-time only). Neither forces a choice |
| FPC and Git (GPL) | Used strictly as external processes (ADR 0002); this stays true under any outbound licence |
| Customer/open-source release | Cannot be done lawfully without a licence; the `opensource-*` pipeline must not be run until this is closed |
| Contributor terms | No CLA/DCO is defined |

## Options (not a recommendation to adopt any)

1. Apache-2.0 — consistent with the COBOL repository; easiest code exchange.
2. Another permissive licence (MIT, BSD-3-Clause).
3. Proprietary / all rights reserved with an explicit `LICENSE` stating so (still a decision; makes the position explicit).
4. A copyleft licence — would need review against the planned Java output and runtime library.

## Decision

None. This record exists so the question is tracked, not forgotten.

## Closure criteria

1. The owner names the outbound licence and copyright holder(s).
2. A root `LICENSE` is added by the owner's instruction, `THIRD_PARTY_NOTICES.md` header is updated, and file headers/CLA policy are decided.
3. If COBOL code is to be ported, an attribution procedure (retain Apache-2.0 text, per-file notices, `NOTICE` content) is recorded in `docs/reuse/`.
