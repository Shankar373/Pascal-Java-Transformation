# P0 Licence Review

Every licence below was read from a **primary source** — the `LICENSE` file in
the evaluated clone, or the licence text shipped with the installed compiler —
not from a package registry, a summary page or memory. Where a licence could
not be verified, that is stated instead of filled in.

---

## 1. Components and licences

| Component | Revision / version | Licence | Evidence (primary source) |
|---|---|---|---|
| `tree-sitter-pascal` | `042119e` | **MIT** | `LICENSE` in clone: "MIT License / Copyright (c) 2018 Benjamin Gray"; `package.json` → `"license": "MIT"` |
| `DelphiAST` | `3840253` | **MPL-2.0** | `LICENSE` in clone: "Mozilla Public License Version 2.0" |
| Free Pascal **compiler** | 3.2.2 | **GNU GPL** (sources GPLv2+) | installed `doc/fpc/faq.txt`: *"Both compilers come under the GNU GPL"*; `COPYING.v2`, `COPYING.v3` shipped |
| Free Pascal **RTL + packages** | 3.2.2 | **LGPL with a linking modification** | installed `doc/fpc/copying.fpc`: *"object files and libraries linked into an application may be distributed without source code"*; `COPYING` = GNU Library GPL |
| `freepascal/fpc:3.2.2-bookworm-full` image | digest `sha256:6c951541…ed3872` | Debian base + FPC (GPL/LGPL) | image contents; used read-only, not redistributed |
| Embarcadero Delphi / RAD Studio | — | **Proprietary commercial** | vendor edition/licensing pages — see `TOOLCHAIN_FEASIBILITY.md` §4.2 |

---

## 2. Obligations and how they are met

### 2.1 tree-sitter-pascal — MIT

**Obligation:** retain the copyright notice and licence text when
redistributing; no copyleft on derivative works.

**Decision: ADOPT.** The notice is retained in the third-party notices file
(P1 deliverable). Nothing else is required. Permissive licence, no
source-disclosure trigger.

### 2.2 DelphiAST — MPL-2.0

**Obligations (file-level copyleft, not project-level):**

- Modified **covered files** must remain under MPL-2.0 and their source
  published.
- Unmodified proprietary files in the same product are **not** affected — MPL
  copyleft attaches to the file, not to the whole program.
- Keep the licence and notices; a patent grant applies to contributors.

**How the P0 patch is handled.** `evidence/delphiast-fpc-helper-recursion.patch`
modifies `Source/SimpleParser/SimpleParser.pas`, a covered file. That patch is
published in-repo **as a diff against the MPL source**, so the modified file is
available under MPL-2.0 as required. It is not silently folded into a
proprietary build.

**Decision: CONDITIONAL ADOPT.**

- Acceptable **as a separate process** invoked at build/discovery time.
- If it is ever **linked into the shipped product**, the MPL-covered files stay
  MPL and their source must ship with the product; proprietary files remain
  unaffected.
- The required patch is itself a maintenance liability (see
  `PARSER_EVALUATION.md` §4) and must be tracked, not forgotten.

### 2.3 Free Pascal compiler — GNU GPL

**Obligation concern:** the compiler is GPL. If it were *linked into* our
product, GPL obligations would attach to that combined work.

**How it is avoided:** FPC is used **only as an external executable** — our
code spawns `fpc.exe` / `fpc` as a child process and reads its output. Process
invocation is not linking; no combined work is created. FPC is also **not
redistributed** by us: it is either pre-installed on the build machine or
pulled as a pinned container image by whoever runs the oracle.

**Decision: ADOPT as an external oracle process, never as a linked library.**
This constraint must be preserved by design review in later phases — a future
"optimise by linking FPC directly" proposal would be a licence event, not a
refactor.

### 2.4 Free Pascal RTL / packages — LGPL with linking exception

**Obligation:** LGPL applies to the RTL itself. The `copying.fpc` modification
expressly permits distributing linked object files/libraries without source.

**Effect on generated programs:** the shipped FAQ states the licence
*"does not impose any kind of license on the created applications"*, so
closed-source applications linking the RTL are permitted — provided modified
RTL sources are made available if the RTL itself is modified.

**Decision: ADOPT.** We do not modify the RTL. Compiled Pascal *test fixtures*
are build artefacts of our own synthetic corpus, not redistributed RTL
derivatives.

### 2.5 Container image `freepascal/fpc:3.2.2-bookworm-full`

**Decision: ADOPT for CI/oracle use only.** Used read-only (`:ro` mount), not
baked into a shipped artefact. If an image is ever redistributed, its Debian
and FPC component notices must accompany it — recorded as a P7 hardening item,
not a P0 action.

### 2.6 Embarcadero Delphi / RAD Studio

**Decision: NOT ADOPTED (unavailable + proprietary).** Cannot be redistributed
by this platform; a customer supplies their own licence and Windows worker.
Recorded as a blocker with an interface/test double planned around it —
see `TOOLCHAIN_FEASIBILITY.md` §4.

---

## 3. Decision summary

| Component | Decision | Trigger for re-review |
|---|---|---|
| tree-sitter-pascal (MIT) | **ADOPT** | never (permissive) |
| DelphiAST (MPL-2.0) | **ADOPT, conditional** — separate process; MPL source published for modified files | if linked into shipped product |
| FPC compiler (GPL) | **ADOPT as external process only** | any proposal to link/embed FPC |
| FPC RTL (LGPL+exception) | **ADOPT** | if RTL is modified |
| Container image | **ADOPT for CI** | if redistributed |
| Delphi/RAD Studio | **NOT ADOPTED** — blocker | if a customer supplies licence + worker |

**Rejected outright:** none on licence grounds. No candidate was dropped
because of its licence; the licence is recorded as a *condition* on adoption.

---

## 4. Gap found: this repository has no licence

```
LICENSE / LICENCE / COPYING : not present
repository root contents    : README.md only
```

The repository declares **no licence for its own code**. That is a real gap:
it leaves the terms under which this platform's own source may be used, and
which third-party notices must accompany it, undefined.

This review does **not** invent one. Selecting a project licence is a
governance decision requiring the owner's explicit choice, so it is recorded
as an open item in `P1_TASKS.md` rather than guessed here.

---

## 5. What this review does not cover

- **Third-party notices file** — not yet generated; P1 task.
- **Dependency lock/attestation** — the corpus of *transitive* dependencies is
  not yet enumerated, because P0 added no shipped dependency. The no-LLM CI
  gate (`docs/decisions/0005`) is what will enforce the boundary when P1 does.
- **Legal advice** — this is an engineering record of licence texts read and
  obligations mapped, not counsel. The MPL/GPL boundary decisions above are the
  ones worth confirming with counsel before a commercial release.
