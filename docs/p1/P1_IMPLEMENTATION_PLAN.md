# P1 Implementation Plan — Secure Ingestion and Pascal Application Discovery

- **Phase:** P1 (from `docs/p0/P1_TASKS.md`)
- **Predecessor:** P0 commit `fbf59d2fd8a39e4cfc768a5c1bf10a5e11092a00`
- **Status:** approved plan, implemented incrementally under the same plan
- **Governing documents:** `docs/p0/P1_TASKS.md`, `docs/p0/SEMANTIC_IR_REQUIREMENTS.md`
  (invariants I1–I7), `docs/decisions/0005-no-llm-ci-gate.md`, `corpus/README.md`

---

## 1. Scope

P1 accepts Pascal enterprise input (ZIP archive, Git repository, or an already
staged directory) and produces an **evidence-backed application inventory**:
file inventory, classification, dialect/compiler profile, project roots and
entry points, application shape, dependency graph with source references, and a
structured discovery report.

### In scope

| Task | Deliverable |
|---|---|
| B1 | Secure ZIP ingestion (traversal, symlink, bomb, nesting, duplicates, encoding bomb) |
| B2 | Secure Git ingestion (isolated workdir, pinned commit, no submodules/hooks/credentials) |
| B3 | SHA-256 hashing, extension + content classification, encoding detection, unknown preservation |
| B4 | Project root detection with per-root evidence; ambiguous ⇒ `UNKNOWN`/`BLOCKED` |
| B5 | Application shape detection with the detecting evidence |
| C1 | Build/compiler profile as a first-class tuple (mode, defines, platform, unit paths, checks) |
| C2 | Capability states scoped as `(construct, mode, platform)` |
| C3 | Mode-dependent symbol visibility knowledge (from P0 `probes.txt`) |
| D1–D4 | `application-manifest.json`, `dependency-graph.json`, discovery report, unknown preservation |
| E1–E5 | Adversarial archive suite, determinism test, no-LLM guard, no-silent-drop tests, corpus gate |
| A3–A5 | P0 carry-over that can be closed without an owner decision |

### Out of scope (never claimed in P1)

Semantic IR, symbol/type resolution, control-flow/effects, Java code generation,
compiler execution of ingested code, any `VERIFIED` capability state, Delphi
equivalence. These remain `UNSUPPORTED` (not attempted) or `UNAVAILABLE`
(toolchain absent) in the emitted capability table.

### Hard rules honoured

1. **Deterministic / no-LLM.** No model, SDK, embedding, vector store, RAG or
   AI endpoint anywhere in product code or tests. Guard (`E3`) fails the build.
2. **Never execute ingested content.** No build scripts, no binaries, no
   `git submodule`, no hook execution, no compiler invocation on input.
3. **Preserve bytes.** Ingested files are copied/hashed as-is; nothing is
   rewritten, re-encoded or normalised.
4. **Fail closed (I1) / no silent acceptance (I2).** Rejected input produces a
   typed diagnostic with location; nothing is dropped without a recorded reason.
5. **Traceability (I5).** Every discovery claim carries file/line/column or a
   file hash.

---

## 2. Technology decision

| Decision | Choice | Why |
|---|---|---|
| Language | **Python 3.11.9** (present on host) | `zipfile`/`hashlib`/`subprocess`/`xml.etree` are stdlib; deterministic; trivially satisfies the no-LLM guard |
| Dependencies | **stdlib only** | No dependency manifest exists to scan, no supply-chain surface, reproducible on any Python ≥ 3.11 |
| Tests | **pytest 9.0.3** (present) + `unittest`-compatible layout | Already installed; no new install required |
| Parsers | **own deterministic lexer** for discovery; tree-sitter/DelphiAST remain **not integrated** | P0 ADR 0001: both are non-authoritative and neither has a symbol table. P1 discovery needs `uses`/directive/`{$I}` spans, not full parse trees. P0 tool findings are reused as *knowledge* (capability matrix, probe results), not as a claimed integration |
| Git | system `git` via `subprocess` with a hardened environment | No credential helper, no network prompt, no hooks, no submodules |

Nothing is claimed as integrated unless a test executes it in this repository.

---

## 3. Layout

```
tools/p1/                     Python package (stdlib only)
  __init__.py
  statuses.py    capability status vocabulary + registry rules
  errors.py      typed failure taxonomy + diagnostics (file/line/col)
  limits.py      deterministic ingestion limits (single source of truth)
  hashing.py     streaming SHA-256 + encoding detection
  classify.py    extension table + content sniffing + class vocabulary
  pathsafe.py    path hardening (traversal, ADS, reserved names, depth)
  zipingest.py   secure ZIP ingestion
  gitingest.py   secure Git ingestion
  plex.py        deterministic Pascal lexer (tokens, comments, directives)
  dialects.py    dialect / mode / compiler profile extraction
  projects.py    project roots, entry points, application shape
  metadata.py    DB technology, SQL, native libs, OS deps, build/runtime reqs
  deps.py        uses / requires / {$I} / external extraction → edges
  graph.py       node/edge model + deterministic serialisation
  emit.py        application-manifest.json, dependency-graph.json, report
  guard.py       no-LLM / no-probabilistic dependency guard (E3)
  pipeline.py    ingest → classify → discover → graph → emit
  cli.py         `ingest`, `guard`, `gate` subcommands

tests/
  conftest.py                   puts tools/ on sys.path, shared fixtures
  fixtures/p1/…                 representative P1 fixtures (NOT corpus/)
  unit/…                        classification, hashing, lexer, dialect, metadata
  security/…                    E1 adversarial archive + E4 no-silent-drop
  integration/…                 E2 determinism, end-to-end pipeline, E3 guard

tools/p1/run_gates.ps1          E5 local/CI gate runner (sweeps + pytest + guard)
```

**Fixture boundary:** `corpus/` is P0 evidence governed by `corpus/README.md`.
P1 discovery fixtures live in `tests/fixtures/p1/` so P0 expectations, sweeps
and evidence are never disturbed by P1 test data.

---

## 4. Security model (B1/B2)

### 4.1 Limits (single source: `limits.py`)

| Limit | Value | Rationale |
|---|---:|---|
| `MAX_ENTRIES` | 10 000 | entry-count attack |
| `MAX_TOTAL_BYTES` | 512 MiB | aggregate expansion |
| `MAX_ENTRY_BYTES` | 128 MiB | single-entry expansion |
| `MAX_COMPRESSION_RATIO` | 200.0 | zip bomb (checked pre-extract **and** while streaming) |
| `MAX_PATH_DEPTH` | 32 | deep nesting |
| `MAX_PATH_LENGTH` | 4096 | path exhaustion |
| `MAX_NAME_LENGTH` | 255 | per-component exhaustion |
| `MAX_SNIFF_BYTES` | 1 MiB | content sniff bounded; hashing is not |
| `MAX_DIAGNOSTICS` | 500 | report cannot grow without bound |

Declared sizes are never trusted: bytes actually written are counted and the
run aborts as soon as a limit is exceeded.

### 4.2 Path hardening (`pathsafe.py`)

A ZIP/Git entry name is rejected when it:

- contains `NUL`, any C0/C1 control character, or a bidi-override character;
- contains a `..` component after separator normalisation (`/` and `\`);
- is absolute (`/x`, `\x`), drive-qualified (`C:x`, `C:\x`), UNC (`\\srv\x`)
  or device-prefixed (`//?/`);
- contains `:` anywhere (NTFS alternate data stream / drive ambiguity);
- is a Windows reserved device name (`CON`, `PRN`, `AUX`, `NUL`, `COM1-9`,
  `LPT1-9`), with or without extension;
- ends with a space or dot (Windows strips them ⇒ collision/ambiguity);
- exceeds depth or length limits;
- does not survive `os.path.realpath` containment in the staging root
  (belt-and-braces after normalisation).

Additionally, names are compared **case-insensitively** for duplicate detection,
because the staging filesystem is case-insensitive: `A.pas` and `a.pas` collide
and are rejected as duplicates.

### 4.3 Symlinks and special files

- **ZIP:** unix mode is read from `external_attr >> 16`. `S_ISLNK`,
  `S_ISFIFO`, `S_ISBLK`, `S_ISSOCK`, `S_ISCHR` ⇒ reject. Directories are
  recorded, never linked.
- **Git:** `git ls-tree -r` is inspected **before** checkout; mode `120000`
  (symlink) or `160000` (gitlink/submodule) ⇒ reject with diagnostic.

### 4.4 Git hardening (`gitingest.py`)

- Fresh staging directory per run; clone target is inside it.
- Environment: `GIT_CONFIG_NOSYSTEM=1`, `GIT_TERMINAL_PROMPT=0`,
  `GIT_ASKPASS` empty, `HOME`/`XDG_CONFIG_HOME` redirected into staging ⇒ no
  user credential helper, no user `gitconfig`, no interactive prompt.
- Flags: `--no-recurse-submodules`, `--template <empty>` (no template hooks),
  no `post-checkout`/`post-commit` execution.
- Pinned commit verified: `git rev-parse HEAD` must equal the requested commit;
  otherwise the run fails (`UNAVAILABLE` input, not a silent partial ingest).
- **No network egress** for the default path: the input is a local repository
  path or `file://` URL. Remote URLs are rejected unless explicitly enabled,
  because a remote clone is not reproducible and risks credential use.
- Re-ingestion of the same pinned commit must yield byte-identical
  `(path, sha256)` pairs (B2 acceptance, tested).

### 4.5 Never-execute guarantee

Ingestion only ever runs `git` with the fixed argument vectors above. No file
from the input is executed, imported, opened for write, or passed to a shell.
A test asserts the subprocess argument vector contains no user-controlled
executable and that `shell=True` is never used.

---

## 5. Discovery model

### 5.1 Classification vocabulary (`classify.py`)

`pascal_program`, `pascal_unit`, `pascal_include`, `pascal_package`,
`pascal_project`, `ui_definition`, `resource`, `configuration`, `database`,
`sql`, `build_script`, `documentation`, `licence`, `version_control`,
`binary`, `unknown`.

Detection = **extension table first, content sniff second** (magic bytes and
Pascal/SQL/XML keywords). A file whose class cannot be determined is emitted as
`unknown` with `preserved: true` — never dropped (D4).

### 5.2 Encoding detection (`hashing.py`)

BOM (UTF-8/16/32) → strict UTF-8 → NUL-driven UTF-16 heuristic → `cp1252`
fallback. Result is `(encoding, confidence)`; **bytes are never modified**.

### 5.3 Dialect and profile (`dialects.py`)

Evidence sources: `{$MODE}`, `{$MODESWITCH}`, `{$H}`, `{$J}`, `{$R}`, `{$Q}`,
`{$IFDEF FPC}`/`{$IFNDEF FPC}` balance, file extensions (`.lpr/.lpi/.lpk/.lfm`
⇒ Lazarus/FPC, `.dpr/.dproj/.dpk/.dfm` ⇒ Delphi), framework units
(`Vcl.*`/`FMX.*`/`LCL*`/`Interfaces`), `uses Windows` legacy, `unit` name vs
filename mismatch.

Profile tuple (C1): `(mode, defines, platform, unit_search_paths, range_check,
overflow_check, string_model, app_type, output_kind)`. Project files (`.dproj`
MSBuild XML, `.lpi` Lazarus XML) contribute defines and unit paths.

Modes accepted explicitly, including the `-Miso` case that P0 `P18` proved is
accepted by FPC although absent from `-h`.

### 5.4 Project roots and shapes (B4/B5)

Roots are anchored on `.dpr`/`.lpr`/`.dproj`/`.lpi`/`.dpk`/`.lpk`, with the
anchor file and its parse evidence recorded. If two roots compete and neither
dominates, the state is `UNKNOWN` with both candidates listed — never a guess.

Shapes: `console`, `gui_vcl`, `gui_lcl`, `gui_fmx`, `library`, `package`,
`service`, `unknown`. Each carries the detecting evidence and confidence.
`FAIL-DEPENDENCY` shapes from P0 (e.g. `Forms`) are surfaced as capability gaps,
not as failures.

### 5.5 Dependencies and graph (D2)

Edges are produced from `uses` / `requires` / `{$I}` / `external` with
`(file, line, column, clause, conditional-context)` on every edge.

| Resolution | Meaning |
|---|---|
| `resolved` | target unit exists in the ingested tree |
| `unresolved` | reason recorded: `missing-unit`, `include-missing`, `rtl-unit`, `platform-unit`, `external-library`, `unparsable` |

Unresolved edges are **always preserved** in `dependency-graph.json`; pruning
them is a test failure.

### 5.6 Capability statuses (C2)

Vocabulary: `SUPPORTED`, `PARTIAL`, `UNSUPPORTED`, `UNAVAILABLE`, `UNKNOWN`.
Every emitted capability state is a `(construct, mode, platform)` triple where
the dimension is meaningful, and cites either an evidence file in
`docs/p0/evidence/` or `UNKNOWN`. `VERIFIED` is never produced in P1.

---

## 6. Output contracts

### 6.1 `application-manifest.json`

```
schema_version      "p1.application-manifest/1.0"
generator           {tool, phase, llm_assisted:false}
source              {kind, origin, commit, entry_count}
files[]             {path, sha256, size, class, class_evidence[],
                     encoding, encoding_confidence, bom, extension,
                     preserved, capability_status}
classification      {counts by class}
project_roots[]     {path, evidence[], entry_points[], status}
dialects[]          {file, dialect, mode, evidence[], confidence}
profiles[]          {root, mode, defines[], platform, unit_search_paths[],
                     range_check, overflow_check, string_model, app_type,
                     output_kind, evidence[]}
shapes[]            {root, shape, evidence[], confidence, status}
database[]          {technology, evidence[], confidence, status}
native_libs[]       {name, kind, evidence[], status}
os_dependencies[]   {platform, evidence[], status}
build_requirements  {compiler, flags[], unit_paths[], blockers[], status}
capability_states[] {construct, mode, platform, status, evidence}
diagnostics[]       {code, severity, message, file?, line?, column?}
```

### 6.2 `dependency-graph.json`

```
schema_version  "p1.dependency-graph/1.0"
nodes[]         {id, kind, path?, sha256?, origin}
edges[]         {from, to, relation, clause, file, line, column,
                 text, resolution, reason?, conditional[]}
unresolved[]    (projection of edges with resolution != resolved)
stats           {nodes, edges, resolved, unresolved}
```

### 6.3 `discovery-report.md`

Human rendering of the two JSON documents: scope, ingestion result, file
inventory summary, project roots, dialects/profiles/shapes, dependency graph
summary, blockers, unresolved dependencies, capability table, limitations.

### 6.4 Determinism (I6)

Same input + same tool versions ⇒ **byte-identical** outputs.

- `json.dumps(..., sort_keys=True, indent=2)` + trailing newline;
- all collections sorted by stable keys (paths use `/` separators);
- **no wall-clock time, no absolute paths, no temp/staging paths** in output;
- source-derived timestamps only (ZIP DOS time, Git commit time);
- verified by `tests/integration/test_determinism.py` (two runs, byte compare).

---

## 7. Test matrix

| ID | Test file | Covers |
|---|---|---|
| E1 | `security/test_adversarial_archives.py` | zip-slip `../`, absolute, drive, UNC, ADS `:`, reserved names, symlink, fifo/device, ratio bomb, oversized entry, entry-count, deep nesting, duplicate (incl. case-collision), zero-byte, encoding bomb, control chars in names, truncated/invalid ZIP |
| E1 | `security/test_git_ingestion.py` | symlink in tree, gitlink/submodule, wrong pinned commit, hook non-execution, environment isolation, byte-identical re-ingest |
| E2 | `integration/test_determinism.py` | two runs byte-identical for manifest, graph, report; JSON schema keys stable |
| E3 | `security/test_no_llm_guard.py` + `guard.py` | product/test code free of model SDKs, embeddings, vector stores, AI endpoints, model weights, inference config |
| E4 | `security/test_no_silent_drop.py` | unknown syntax ⇒ diagnostic with file/line/col; every input file appears in the manifest; every unresolved edge preserved |
| B3 | `unit/test_classify.py`, `unit/test_hashing.py` | class vocabulary, sniffing, encoding/BOM, hash stability |
| B4/B5 | `unit/test_projects.py` | roots with evidence, ambiguous ⇒ `UNKNOWN`, shapes |
| C1–C3 | `unit/test_dialects.py` | mode table incl. `-Miso`, defines, profile tuple, platform scoping |
| D | `unit/test_deps.py`, `unit/test_graph.py` | uses/requires/`{$I}`/external spans, unresolved reasons |
| — | `integration/test_pipeline.py` | end-to-end on representative fixtures |
| E5 | `tools/p1/run_gates.ps1` | host + pinned-container corpus sweeps, fails on any `MISMATCH` |

---

## 8. Execution order

1. **A-blockers recorded** — A1 (licence) and A2 (upstream notification) need
   owner decisions; document, continue.
2. **B1/B2** secure ingestion + limits + path hardening, with E1 tests first.
3. **B3** hashing/classification/encoding + tests.
4. **C1–C3 + B4/B5** lexer, dialect/profile/shape/roots + tests.
5. **D1–D4** deps → graph → emit → report + tests.
6. **E2/E3/E4** determinism, guard, no-silent-drop + tests.
7. **E5** gate runner; **A3/A4** fixture and baseline gaps; **A5** README status.
8. **Verification report** — stop; no commit without explicit approval.

---

## 9. Known limitations of this plan

- Discovery is **syntactic**: no symbol table, no cross-unit type resolution
  (deferred to P2 by `P1_TASKS.md` F).
- Dialect detection is heuristic and cannot be compiler-validated here because
  the Delphi oracle is `UNAVAILABLE`; FPC validation is limited to what P0
  evidence already covers.
- Content sniffing is bounded by `MAX_SNIFF_BYTES`; files larger than that are
  hashed and classed by extension only, with `class_evidence: ["extension"]`.
- CI is not configured in this repository; E5 ships as a runnable gate script
  with CI-ready semantics, and the `CI configured` capability stays `UNKNOWN`.
