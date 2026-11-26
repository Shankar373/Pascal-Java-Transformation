# P0 Golden Corpus

Synthetic Pascal fixtures authored for P0 feasibility evaluation. They are **test inputs**, not
converted applications. Every fixture is original, self-contained and carries a header stating
its dialect target and expected compiler behavior.

## Layout

| Directory | Covers |
|---|---|
| `corpus/dialects/iso7185/` | ISO 7185-style Standard Pascal subset (no Object Pascal) |
| `corpus/dialects/turbo/` | Turbo Pascal dialect subset (`-Mtp`) |
| `corpus/dialects/fpc/` | Free Pascal modes (`{$mode objfpc}`, `{$mode delphi}`) |
| `corpus/dialects/delphi/` | Delphi/Object Pascal constructs |
| `corpus/directives/` | Compiler directives, conditional compilation, includes, range/overflow checks |
| `corpus/language/` | Records, variant records, strings, arrays/sets/enums, currency, exceptions, files, nested routines, pointers |
| `corpus/applications/console_multiunit/` | Multi-unit console project (cross-unit resolution test) |
| `corpus/applications/project_files/` | Project/package files (`.dpr`, `.lpr`, `.dproj`, `.lpi`, `.dpk`) for discovery tests |
| `corpus/dbaccess/` | Embedded SQL fixtures and fixtures with unavailable DB-framework dependencies |
| `corpus/applications/lazarus_app/` | LCL-dependent fixture (expected: dependency unavailable in this environment) |

## Expected compile behavior (host: FPC 3.2.2)

- `PASS` — compiles (and runs where a program) under the documented FPC mode.
- `FAIL-DEPENDENCY` — compilation must fail with a missing-unit error; this is the expected
  result and proves dependency discovery, not a defect.
- `DISCOVERY-ONLY` — parsed/classified but not compiled (project metadata files).

Results are recorded in `docs/p0/evidence/`. Never edit a fixture to make a tool pass; add a
new fixture instead, and record dialect gaps as findings.
