# ADR 0002: Open-source licence decisions

- **Status:** Accepted
- **Date:** 2026-11-13
- **Phase:** P0
- **Evidence:** `docs/p0/LICENCE_REVIEW.md` (licence texts read from primary
  sources — `LICENSE` files in clones, installed FPC licence docs)

## Context

Every third-party component proposed for this platform carries licence
obligations that must be understood *before* adoption, not after integration.
Licences were read from primary sources rather than registry metadata.

| Component | Licence | Source read |
|---|---|---|
| tree-sitter-pascal `042119e` | MIT | clone `LICENSE` + `package.json` |
| DelphiAST `3840253` | MPL-2.0 | clone `LICENSE` |
| Free Pascal compiler 3.2.2 | GNU GPL (sources GPLv2+) | installed `doc/fpc/faq.txt`, `COPYING.v2` |
| Free Pascal RTL/packages 3.2.2 | LGPL **with linking modification** | installed `doc/fpc/copying.fpc` |
| Delphi / RAD Studio | Proprietary commercial | vendor edition/licensing pages |

Two hard structural facts shape the decision:

1. The **FPC compiler is GPL**, so linking it into our product would attach GPL
   obligations to the combined work.
2. **DelphiAST is MPL-2.0**, whose copyleft attaches to the *file*, not to the
   whole program — and P0 had to modify one of its files.

## Decision

1. **FPC is adopted only as an external executable process.** Our code spawns
   `fpc`/`fpc.exe` and reads its output. Process invocation is not linking; no
   combined work is created. FPC is never redistributed by us — it is
   pre-installed or pulled as a pinned container image by whoever runs the
   oracle.

2. **DelphiAST is adopted as a separate process, conditionally.** Its MPL-2.0
   obligations are met by publishing the required FPC patch as a **diff against
   the MPL source** (`docs/p0/evidence/delphiast-fpc-helper-recursion.patch`).
   If it is ever linked into the shipped product, its covered files must ship
   their source under MPL-2.0; our own files remain unaffected.

3. **tree-sitter-pascal (MIT) is adopted unconditionally**, retaining its
   copyright notice in a third-party notices file.

4. **The FPC RTL's linking exception is relied upon**: applications linking the
   RTL may be distributed without the RTL's source, and the shipped FAQ states
   the licence imposes no terms on created applications. We do not modify the
   RTL.

5. **Delphi is not adopted.** It cannot be redistributed; a customer supplies
   their own licence and Windows worker behind an interface (P3).

6. **No component was rejected on licence grounds.** Licences are recorded as
   *conditions* on adoption, not as vetoes.

## Consequences

- **Design constraint, permanently:** any proposal to embed or link FPC
  directly into the product is a **licence event requiring a new ADR**, not a
  refactor. This must be enforced in design review.
- **Maintenance liability:** the DelphiAST patch must be tracked and rebased;
  upstream notification is tracked as `P1_TASKS.md` A2.
- **Third-party notices file** must be generated (P1 task A1) covering MIT,
  MPL-2.0, GPL and LGPL components with their exact revisions.
- **Container redistribution** would require Debian + FPC notices to accompany
  the image; recorded as a P7 hardening item, not a P0 action.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Link FPC as a library for speed | Would make GPL apply to the combined work; process invocation costs ~ms per compile and is already proven sufficient. |
| Fork DelphiAST into a private closed-source copy | Violates MPL-2.0 for the modified covered files. |
| Drop DelphiAST because of MPL | Unnecessary — file-level copyleft is compatible with our architecture when invoked as a process; rejecting it would remove the only structured AST candidate for no gain. |
| Ship FPC inside our container image | Would impose redistribution obligations we do not need; the pinned upstream image already exists. |

## Open item (not decided here)

This repository currently has **no `LICENSE` file** — the root contains only
`README.md`. Selecting a project licence is an owner governance decision, so it
is recorded as an open item (`P1_TASKS.md` A1) rather than assumed.

## Revisit triggers

- Any proposal to link/embed FPC or a GPL component.
- DelphiAST linked into the shipped product rather than invoked as a process.
- Redistribution of the container image.
- Owner selects a project licence (closes the open item above).
