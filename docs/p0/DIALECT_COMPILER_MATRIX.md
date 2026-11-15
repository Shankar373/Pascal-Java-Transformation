# P0 Dialect / Compiler Matrix

Every cell below is an observed FPC 3.2.2 behavior with its evidence file.
Nothing is inferred from documentation or memory: a cell is filled only where a
probe or sweep produced the line cited.

**Evidence files** (all under `docs/p0/evidence/`):

| File | Contains |
|---|---|
| `probes.txt` | 18 isolated dialect probes `P01`–`P18` + RTL `.ppu` identifier scan |
| `fpc-host.txt` | host sweep, Windows Win32 FPC 3.2.2, 24 fixtures |
| `fpc-host-prefix.txt` | same sweep *before* fixture corrections (baseline) |
| `fpc-docker.txt` | pinned Linux container sweep, 24 fixtures + expectation check |
| `fpc-run.txt` | execution of the produced programs (exit codes, stdout) |
| `tool-versions.txt` | tool versions and image digest |

**Reproduce:**

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\probes.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\sweep-fpc.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\run-fpc.ps1
docker run --rm -v <repo>:/repo:ro freepascal/fpc:3.2.2-bookworm-full `
  bash /repo/tools/p0/sweep-fpc-docker.sh
```

---

## 1. Compiler availability

| Compiler | Platform | Version | Verified how | Status |
|---|---|---|---|---|
| Free Pascal `fpc.exe` | Windows Win32 (host) | `3.2.2` | `probes.txt` line 1, `tool-versions.txt` | **Available** |
| Free Pascal `fpc` | Linux x86_64 (container) | `3.2.2` | `fpc-docker.txt` `TOOL|/usr/bin/fpc|version=3.2.2` | **Available** |
| Container image | Linux | `freepascal/fpc:3.2.2-bookworm-full` @ `sha256:6c951541…ed3872` | `tool-versions.txt` | **Pinned** |
| Embarcadero Delphi / RAD Studio | Windows | — | see §6 | **UNAVAILABLE (blocker)** |

Two independent compilers at the same version, different OS/ABI, both exercised
over the same corpus — this is the reproducibility baseline for P1+.

## 2. Dialect feature matrix (probe evidence)

`PASS` = compiled; `FAIL` = rejected with the quoted diagnostic.

### 2.1 Function result identifier

| Probe | Mode | Construct | Result | Diagnostic |
|---|---|---|---|---|
| `P01` | `-Mfpc` | `Result := 1` | **FAIL** | `Identifier not found "Result"` |
| `P02` | `-Mtp` | `Result := 1` | **FAIL** | `Identifier not found "Result"` |
| `P03` | `-Mobjfpc` | `Result := 1` | **PASS** | — |
| `P04` | `-Mdelphi` | `Result := 1` | **PASS** | — |
| `P05` | `-Mfpc` | `F := 1` (function name) | **PASS** | control for `P01` |

**Rule.** `Result` exists only in `objfpc` and `delphi` modes. `fpc` and `tp`
require assignment to the function name. A converter must emit the correct form
*per active mode*, not per file.

### 2.2 File management identifiers — declared in `ObjPas`, not `System`

| Probe | Mode | Construct | Result | Diagnostic |
|---|---|---|---|---|
| `P06` | `-Mfpc` | bare `AssignFile`/`CloseFile` | **FAIL** | `Identifier not found "AssignFile"` |
| `P07` | `-Mobjfpc` | bare `AssignFile`/`CloseFile` | **PASS** | — |
| `P08` | `-Mdelphi` | bare `AssignFile`/`CloseFile` | **PASS** | — |
| `P09` | `-Mfpc` + `uses ObjPas` | bare `AssignFile`/`CloseFile` | **PASS** | `Warning: Don't load OBJPAS unit manually, use {$mode objfpc} or {$mode delphi} instead` |
| `P10` | `-Mfpc` | `System.AssignFile(...)` | **FAIL** | `Identifier not found "AssignFile"` |
| `P11` | `-Mobjfpc`, no `uses` | `ObjPas.AssignFile(...)` | **PASS** | — |

`.ppu` identifier scan (`probes.txt` lines 21–22):

```
system.ppu | ...rtl\system.ppu  | AssignFile=False | CloseFile=False | Rewrite=True  | Reset=True
objpas.ppu | ...rtl\objpas.ppu  | AssignFile=True  | CloseFile=True  | Rewrite=False | Reset=True
```

**Rule.** `AssignFile`/`CloseFile` live in **`ObjPas`**; `Rewrite`/`Reset` live
in `System`. `objfpc`/`delphi` modes pull `ObjPas` in automatically; `fpc`/`tp`
do not, and `System.AssignFile` never resolves in any mode. This is the root
cause of the `file_io.pas` fixture failure and a hard requirement for the IR:
identifier visibility is **mode-dependent**, so the IR must record the active
mode alongside every resolved symbol.

### 2.3 Unit / file naming

| Probe | Situation | Result | Diagnostic |
|---|---|---|---|
| `P12` | `unit ProbeUnit` in `ProbeUnit.pas` | **PASS** | — |
| `P13` | `unit OtherName` in `ProbeUnit.pas` | **FAIL** | `Illegal unit name: OtherName (expecting PROGRAM)` |
| `P14` | `program WrongName` in `probe_prog.pas` | **PASS** | — |

**Rule.** A unit's name must equal its file name; a program's name need not
match. Discovery must derive unit identity from the *file name* and flag any
mismatch as a blocker instead of guessing. This defect class caused 2 fixture
failures (`delphi_classes.pas`, `nested_routines.pas`).

### 2.4 Comments and nested directives

| Probe | Mode | Construct | Result | Diagnostic |
|---|---|---|---|---|
| `P16` | `-Mfpc` | `{ outer {$mode objfpc} inner }` | **PASS** | `Warning: Comment level 2 found` |
| `P17` | `-Mdelphi` | `{ outer {$mode objfpc} inner }` | **FAIL** | `Fatal: Syntax error, "BEGIN" expected but "identifier INNER" found` |

**Rule.** Nested braces inside a brace comment are a *warning* under
`fpc`/`objfpc` and a *fatal syntax error* under `delphi`, because `delphi` ends
the comment at the first inner `}`. The same construct is rejected by both
parser candidates. Any comment or string rewriting must be mode-aware, and a
preprocessor must never assume comments are opaque.

### 2.5 Types

| Probe | Mode | Construct | Result |
|---|---|---|---|
| `P15` | `-Mfpc` | `StrValue: string[31]` in a variant record | **PASS** |

`ShortString[31]` is **not** a type (pre-fix error `Error in type definition`);
the length-suffixed form is `string[31]`.

### 2.6 Mode flags

| Probe | Mode | Result | Note |
|---|---|---|---|
| `P18` | `-Miso` | **PASS** | accepted by fpc 3.2.2 though absent from the `-h` mode list |

The profile resolver must accept `-Miso` as a valid mode and must not derive the
legal mode set from `-h` output alone.

## 3. Fixture sweep matrix — host (Windows Win32)

Source: `fpc-host.txt` — **21 PASS / 3 FAIL** across 24 fixtures.

| Fixture | Mode | Result |
|---|---|---|
| `applications/console_multiunit/miniapp.dpr` | objfpc | PASS |
| `applications/console_multiunit/uMath.pas` | objfpc | PASS |
| `applications/console_multiunit/uReport.pas` | objfpc | PASS |
| `applications/lazarus_app/lazarusapp.lpr` | objfpc | **FAIL** — `Can't find unit Forms` |
| `applications/lazarus_app/uMainForm.pas` | objfpc | **FAIL** — `Can't find unit Forms` |
| `applications/project_files/delphi_style_app.dpr` | delphi | PASS |
| `dbaccess/ado_style_connection.pas` | fpc | PASS (Windows only — see §5) |
| `dbaccess/bde_style_query.pas` | fpc | **FAIL** — `Can't find unit DBTables` |
| `dbaccess/embedded_sql.pas` | objfpc | PASS |
| `dialects/delphi/DelphiClasses.pas` | delphi | PASS |
| `dialects/fpc/mode_objfpc.pas` | objfpc | PASS |
| `dialects/iso7185/hello_iso.pas` | fpc | PASS |
| `dialects/turbo/tp_point.pas` | fpc | PASS |
| `directives/directive_ifdef.pas` | fpc | PASS |
| `directives/directive_include.pas` | fpc | PASS |
| `directives/directive_range_checks.pas` | fpc | PASS |
| `language/currency_math.pas` | fpc | PASS |
| `language/exception_flow.pas` | objfpc | PASS |
| `language/file_io.pas` | objfpc | PASS |
| `language/NestedRoutines.pas` | delphi | PASS |
| `language/pointer_alloc.pas` | fpc | PASS |
| `language/records_sets.pas` | fpc | PASS |
| `language/string_kinds.pas` | fpc | PASS |
| `language/variant_record.pas` | fpc | PASS |

The 3 FAILs are the declared `FAIL-DEPENDENCY` set (absent platform/framework
units) — see `corpus/README.md`. They are **expected results**, not defects.

The pre-fix baseline (`fpc-host-prefix.txt`, 15 PASS / 9 FAIL) and the exact
defect each correction fixed are recorded in `fixture-fixes.md`.

## 4. Fixture sweep matrix — pinned Linux container

Source: `fpc-docker.txt` — **20 PASS / 4 FAIL**, **24/24 expectations MATCH**.

| Fixture | Host | Linux container | Δ |
|---|---|---|---|
| all fixtures except `ado_style_connection.pas` | identical | identical | — |
| `dbaccess/ado_style_connection.pas` | PASS | **FAIL** — `Can't find unit ComObj used by AdoStyleConnection` | platform-dependent |
| `lazarusapp.lpr`, `uMainForm.pas`, `bde_style_query.pas` | FAIL | FAIL | same |

`SUMMARY|fixtures=24|PASS=20|FAIL=4|MATCH=24|MISMATCH=0`

## 5. Platform-dependent dependency (cross-compiler differential)

`ado_style_connection.pas` is the only fixture whose verdict differs by OS:

- **Windows host:** `PASS` — Windows FPC ships `ComObj`/`Variants`.
- **Linux container:** `FAIL` — `Can't find unit ComObj`.

Its header now states both outcomes explicitly. This is the smallest working
example of the discovery feature the platform must ship: *the same source maps
to different capability states on different targets*, so the capability state
must record the target platform, not just the dialect.

Note the fixture is compile-only: its body calls `CreateOleObject(...)`, which
has no registered provider here, so `fpc-run.txt` records it as
`SKIP|...|header: compile-only, no ADO provider registered`.

## 6. Delphi compiler — UNAVAILABLE (blocker)

Local verification performed:

```
Embarcadero/Borland/CodeGear dirs : NONE FOUND
delphi.exe on PATH                : NO
dcc32.exe / dcc64.exe / bds.exe / rsvars.bat : not found
Uninstall registry entries matching Delphi|RAD Studio|Embarcadero|Borland : NONE
Free Pascal present               : 3.2.2
```

Consequences, recorded rather than worked around:

- No Delphi-target profile can be *executed* in this environment.
- Workflow state for those profiles: `ORACLE_UNAVAILABLE`, capability `UNAVAILABLE`.
- `corpus/dialects/delphi/*` fixtures are validated by **FPC `-Mdelphi`**, which
  is a *proxy* for Delphi and must never be reported as Delphi equivalence.
- Licensing and onboarding requirements: `TOOLCHAIN_FEASIBILITY.md` §Delphi.

Per the engineering rules, an interface + test double is built around this in
P3 (`docs/decisions/0005`-class blocker record); the missing work is never
claimed to have passed.

## 7. Mode coverage actually exercised

| Mode | Fixtures exercised | Evidence |
|---|---|---|
| `fpc` (also the default with no `-M`) | 10 | `fpc-host.txt` mode column |
| `objfpc` | 7 | `fpc-host.txt` |
| `delphi` | 3 | `fpc-host.txt` |
| `tp` | probe only (`P02`) | `probes.txt` |
| `iso` | probe only (`P18`) | `probes.txt` |
| default (no `-M`) | equivalent to `fpc`; probe `P01`/`P06` behavior | `probes.txt` |

`tp` and `iso` have probe coverage but **no corpus fixture sweep in a `tp`/`iso`
mode** — recorded as a gap for P1 (`P1_TASKS.md`).
