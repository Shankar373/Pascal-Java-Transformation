# P0 Toolchain Feasibility

What is installed, what was proven to run, what is missing, and what it would
cost to obtain the missing piece. Every version below is copied from
`evidence/tool-versions.txt`; nothing is asserted from memory.

---

## 1. Verified toolchain inventory

Evidence: `evidence/tool-versions.txt` (captured 2026-11-13).

| Tool | Version | Role in this platform |
|---|---|---|
| Free Pascal `fpc` (host) | **3.2.2** (Win32) | compile oracle, dialect semantics probe |
| Free Pascal `fpc` (container) | **3.2.2** (Linux x86_64) | reproducible compile oracle |
| Docker Engine | **29.8.2** (client + server) | pinned oracle environment |
| Container image | `freepascal/fpc:3.2.2-bookworm-full` @ `sha256:6c951541…ed3872` | pinned, digest-verified |
| tree-sitter CLI | **0.24.5** (`1a983b7e…`) | candidate parser |
| gcc (WinLibs) | **16.2.0** (mingw64, UCRT POSIX SEH) | builds the tree-sitter grammar |
| Node.js | **v22.23.4** | tooling host (`cmd /c npm`) |
| npm | **10.9.9** | tooling host |
| Python | **3.11.9** | utility scripts |
| Java (Temurin) | **21.0.12.1** (LTS) | target platform for generated code |
| Maven | **3.9.16** | Java build for P5+ |

**Delphi / RAD Studio: not present** — see §4.

---

## 2. FPC — validated for build **and** run

The prompt requires "validate FPC build/run only for FPC-supported profiles".
Both halves were executed, not assumed.

### 2.1 Build (compile)

| Run | Evidence | Result |
|---|---|---|
| Host Windows Win32 | `evidence/fpc-host.txt` | **21 PASS / 3 FAIL** |
| Pinned Linux container | `evidence/fpc-docker.txt` | **20 PASS / 4 FAIL**, `MATCH=24`, `MISMATCH=0` |
| Pre-fix baseline | `evidence/fpc-host-prefix.txt` | 15 PASS / 9 FAIL |

The 3 host failures are the declared `FAIL-DEPENDENCY` set (absent units
`Forms` ×2, `DBTables`) — expected results, not defects. The 4th Linux failure
is `ado_style_connection.pas` → `Can't find unit ComObj`, the documented
platform split. Every fixture's observed verdict was checked against the
expectation in `corpus/README.md`; **24/24 matched, 0 mismatched.**

Reproduce:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools\p0\sweep-fpc.ps1
docker run --rm -v <repo>:/repo:ro freepascal/fpc:3.2.2-bookworm-full `
  bash /repo/tools/p0/sweep-fpc-docker.sh
```

### 2.2 Run (execute)

Evidence: `evidence/fpc-run.txt` — **16 RUN / 8 SKIP / 0 TIMEOUT / 0 empty exit codes.**

| Fixture | exit | first stdout line |
|---|---|---|
| `miniapp.dpr` | 0 | `total=55` |
| `delphi_style_app.dpr` | 0 | `calc total=10.99` |
| `embedded_sql.pas` | 0 | `sql select len=160` |
| `mode_objfpc.pas` | 0 | `objfpc counter=42` |
| `hello_iso.pas` | 0 | `iso7185 total=42` |
| `tp_point.pas` | 0 | `tp point=3,4` |
| `directive_ifdef.pas` | 0 | `directives=base+A+B` |
| `directive_include.pas` | 0 | `include magic=42` |
| `directive_range_checks.pas` | 0 | `checks small=32767 acc=0` |
| `currency_math.pas` | 0 | `price=19.99 tax=1.45 total=21.44` |
| `exception_flow.pas` | **2** | `caught=negative` |
| `file_io.pas` | 0 | `read=line one` |
| `pointer_alloc.pas` | 0 | `1 2 3 4` |
| `records_sets.pas` | 0 | `grid tag11=0 allowed=TRUE` |
| `string_kinds.pas` | 0 | `strlen=11 first=h shortlen=3` |
| `variant_record.pas` | 0 | `variant int=123456` |

`exception_flow.pas` exiting **2** is the fixture's own asserted behaviour
(`Halt(2)` on the error path) — a non-zero exit is *data*, not a failure.

The 8 skips each carry an explicit reason (never silent): 4 units with no
executable, 3 that did not compile (the declared dependency failures), and
`ado_style_connection.pas` marked compile-only because its body calls
`CreateOleObject(...)` and no ADO provider is registered — its header puts the
runtime path out of scope.

**This closes `corpus/README.md`'s claim** that `PASS` means "compiles (and
runs where a program)": every program fixture that compiles was in fact
executed and its observable behaviour recorded.

---

## 3. Reproducibility

- **Pinned image by digest**, not by tag:
  `freepascal/fpc:3.2.2-bookworm-full@sha256:6c951541251e24e67d358ec7a5b2dfb3121069cdf73fd0252226868dbecd3872`.
- The container sweep mounts the repo **read-only** (`:ro`) and sends all
  compiler output to `/tmp`, so a run cannot mutate the corpus or leave
  root-owned artefacts in the working tree.
- Each fixture compiles into a **fresh `-FE`/`-FU` temp directory**, so no stale
  `.ppu`/`.o` from an earlier fixture can influence a later one. (A stale `.ppu`
  once produced a false pass during development; fresh dirs are now mandatory.)
- Two independent FPC builds (Windows host and Linux container) at the same
  version exercise the same corpus, giving a cross-OS differential rather than a
  single-platform assertion.
- All evidence files are **UTF-8 without BOM** so plain-text review and diff
  tools can read them; four had been written as UTF-16LE by PowerShell's
  `Tee-Object` and were normalised without altering content.

---

## 4. Delphi — UNAVAILABLE (blocker)

### 4.1 Availability check (performed, negative)

```
Embarcadero / Borland / CodeGear directories : NONE FOUND
delphi.exe on PATH                            : NO
dcc32.exe, dcc64.exe, bds.exe, rsvars.bat      : not found
Uninstall registry entries matching
  Delphi | RAD Studio | Embarcadero | Borland : NONE
Free Pascal present                           : 3.2.2
```

**State:** capability `UNAVAILABLE`, workflow `ORACLE_UNAVAILABLE`. No
Delphi-target profile can be executed in this environment. Per the engineering
rules this is an **explicit blocker** with an interface/test double planned
around it in P3 — it is never reported as having passed.

`corpus/dialects/delphi/*` fixtures are therefore validated by **FPC
`-Mdelphi`**, which is a *proxy* and must never be presented as Delphi
equivalence.

### 4.2 Licensing requirements (verified from vendor sources, not invented)

Facts sourced from Embarcadero's own product/edition pages, the RAD Studio
license agreement and the vendor FAQ:

| Topic | Requirement |
|---|---|
| Product | Delphi / RAD Studio (current major release: **13 "Florence"**) |
| Nature | **Proprietary commercial software**, Embarcadero (an Idera company) |
| Editions | Professional, Enterprise, Architect |
| Community Edition | Free but **non-commercial**: revenue under **US$5,000/yr**, teams of **≤5**, **one-year term**. **Not offered for RAD Studio** — only for Delphi/C++Builder |
| Metric | **Named User** (node-locked to one machine), or **Network Named / Network Concurrent** via a customer-run **AppWave License Server** |
| Term | Perpetual with first-year Update Subscription, or a term subscription |
| Indicative list prices (ComponentSource, USD) | Delphi Pro **$1,583.01**, Ent **$3,959.01**, Arch **$5,939.01**; RAD Studio Pro **$2,573.01**, Ent **$4,553.01**, Arch **$6,533.01** |
| Community suitability | **Not suitable** for an enterprise conversion platform (revenue/team limits, non-commercial, expiring) |

### 4.3 Execution requirements (why this is a real blocker, not a formality)

1. **Windows host required.** `dcc32`/`dcc64` are Windows executables; a Linux
   container cannot run them. The Delphi oracle must run on a licensed Windows
   worker.
2. **Licensing model vs. automation.** A *node-locked Named User* licence binds
   to a single workstation and is a poor fit for an unattended CI oracle worker
   that must be reproducible and re-runnable. The operationally relevant routes
   are **Network Named** or **Network Concurrent** licensing through the
   customer's **AppWave License Server**, which is itself an infrastructure
   component that must be deployed, reachable and maintained.
3. **Customer-supplied licence.** The platform cannot redistribute Delphi. A
   customer who wants Delphi-verified equivalence must supply their own licence
   and their own Windows worker; the platform must treat that worker as an
   external, optional oracle behind an interface.
4. **Per-seat cost is material** and recurring (Update Subscription), so
   "run every conversion through Delphi" is not a default-on capability — it is
   a paid, opt-in certification path.
5. **No AI assistant may be part of the oracle path.** RAD Studio releases ship
   an embedded agentic AI assistant; our no-LLM gate applies to *our shipped
   product's* dependencies and deployment manifests, and the pipeline invokes
   only the command-line compiler (`dcc32`/`dcc64`). This must stay true: no
   IDE, no assistant, no model endpoint in the oracle worker.

### 4.4 What is decided now vs. deferred

**Decided in P0:**
- Delphi is **not available** and is recorded as a blocker, not as a gap to be
  papered over.
- FPC `-Mdelphi` is accepted only as a **proxy** for Delphi-target fixtures,
  always labelled as such.
- The adapter interface + test double for a Delphi oracle is specified for P3
  so no later phase has to invent it.

**Deferred (explicitly not claimed in P0):**
- Actual Delphi execution, and therefore any `VERIFIED` state for
  Delphi-specific semantics. Everything Delphi-facing is `NOT_VERIFIED`.

---

## 5. Constraints carried forward

| # | Constraint | Consequence |
|---|---|---|
| C1 | Delphi unavailable | Delphi profiles `ORACLE_UNAVAILABLE`; FPC `-Mdelphi` proxy only |
| C2 | FPC is GPL (compiler) / modified LGPL (RTL) | licence obligations in `LICENCE_REVIEW.md`; oracle runs as a separate process |
| C3 | DelphiAST needs an FPC patch | patch maintained in-repo, candidate liability in ADR `0001` |
| C4 | Node/node-sitter require gcc-built grammar | grammar build is a documented, versioned prerequisite |
| C5 | Two FPC builds at the same version, different OS | cross-OS differential available; platform-dependent units must be recorded per target |
| C6 | No fixture may be weakened to pass | fixture corrections logged in `evidence/fixture-fixes.md` with root causes |
| C7 | Evidence must be plain-text reviewable | all evidence normalised to UTF-8 no-BOM |
