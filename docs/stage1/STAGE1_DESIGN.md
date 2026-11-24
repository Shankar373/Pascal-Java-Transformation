# Stage 1 — Ingestion and Discovery: design contract

**Status:** design contract for the Stage 1 completion work. It extends the
committed P0/P1 modules (`tools/p1/`); nothing in P1 is rewritten.
**Stage 1 of the six-stage architecture = roadmap phase P1 + this work.**
No Stage 2 work (parsers, AST, Semantic IR) is part of this document.

Hard rules inherited from the repository (ADR 0005 and the README): no LLM, no
ML, no network calls other than the explicit Git fetch, Python stdlib only,
deterministic output, fail closed, never silently drop a file or a finding.

## 1. Goal

Accept a complete customer Pascal application as a **ZIP**, a **Git URL
(HTTPS/SSH, branch/tag/commit)** or a **local directory**, freeze it as an
**immutable checkpoint pinned to the exact commit before any processing**,
preserve the original source, then produce an **evidence-backed Application
Blueprint** (JSON, machine-readable) with every file, directory, dialect,
project, entry point, compiler configuration, database, library, external
integration, build requirement and runtime dependency; dependency graphs;
unresolved dependencies; diagnostics.

## 2. Flow

```
request ─▶ [1 Ingestion] ─▶ [2 Checkpoint] ─▶ [3 Scanning & Inventory]
                                         ─▶ [4 Dependency Analysis] ─▶ [5 Blueprint]
```

| Step | Module | Behaviour |
|---|---|---|
| 1 Ingestion | `zipingest`, `gitingest`, `remotegit` (new), `model.ingest_directory` | validate + stage untrusted bytes in a temp dir (existing hardening) |
| 2 Checkpoint | `checkpoint` (new) | copy the *validated* staging tree into the checkpoint store, record provenance, make read-only, compute the source digest; **all later steps read from the checkpoint, never from staging** |
| 3 Scanning & Inventory | `pipeline.analyse_tree`, `inventory` (new) | classify/scan every file; list every directory; build scripts; compiler configs |
| 4 Dependency Analysis | `deps`, `metadata`, `integrations` (new) | unit/include/package graph, databases, native libs, libraries, integrations, runtime dependencies |
| 5 Blueprint | `blueprint` (new), `emit` | blueprint + auxiliary machine-readable reports |

Orchestrator: `p1/stage1.py::discover(request, store, progress=None)` (§7).
The legacy `p1.pipeline.run()` and CLI `ingest`/`gate` keep working unchanged.

## 3. Immutable checkpoint (`p1/checkpoint.py`)

Store layout (`<store>` = a directory the operator chooses; default
`./.stage1-store`, git-ignored):

```
<store>/checkpoints/<CP-id>/
    checkpoint.json        written once, never modified (schema §3.2)
    source/                the preserved tree (bytes exactly as ingested)
    original/input.zip     ZIP inputs only: the uploaded archive verbatim
<store>/discoveries/<CP-id>/    outputs of analysis (blueprint, reports, …)
```

* **Checkpoint id** `CP-<first 12 hex of sha256(kind \0 commit \0 source_digest)>`.
  Content-derived and deterministic: re-ingesting the same commit / archive
  yields the same id and is **idempotent** (the existing checkpoint is
  verified and reused, `reused: true`).
* **Source digest** = sha256 over `"<path>\0<sha256>\0<size>\n"` for every file
  sorted by path. This is the single fingerprint of the preserved source.
* **Immutability:** `source/` files and `checkpoint.json` are made read-only
  (`0o444`); `verify_checkpoint(path)` re-hashes everything and reports
  `modified` / `missing` / `extra` paths and a digest mismatch. A tampered
  checkpoint is **never reused**: error `CHECKPOINT_TAMPERED`. Creation is
  atomic (build in `<id>.tmp-*`, `os.replace` into place; a crash leaves no
  half checkpoint). Concurrent creation of the same id is safe.
* **Pinned before processing:** for Git the commit SHA (40-hex) and tree id
  are recorded *before* analysis; the checkpoint records the ref the user
  asked for and the SHA it resolved to.
* No wall-clock time in `checkpoint.json` (determinism). Ingest wall-clock time
  belongs to the run record (§8), not the checkpoint.

### 3.2 `checkpoint.json` (`stage1.checkpoint/1.0`)

```json
{
  "schema_version": "stage1.checkpoint/1.0",
  "checkpoint_id": "CP-3f7a2e9c01ab",
  "source": {"kind": "git|zip|directory", "origin": "<redacted url or name>",
             "ref": "main", "commit": "<40 hex>", "tree_id": "<40 hex>",
             "commit_timestamp": "2026-11-16T10:24:00+00:00",
             "archive_sha256": "<zip only>"},
  "source_digest": "<64 hex>",
  "file_count": 4892, "directory_count": 618, "total_bytes": 123456,
  "files": [{"path": "...", "sha256": "...", "size": 1}],
  "read_only": true
}
```

`CheckpointInfo` (dataclass, `as_dict()` = the dict above minus `files`) is
what `Discovery.checkpoint` carries.

## 4. Remote Git (`p1/remotegit.py`, extends `gitingest`)

Threat model: the URL, the repository and the server are attacker-influenced.

* **Schemes:** `https://` always; `ssh://` and scp-style `user@host:path` only
  when SSH is enabled (`allow_ssh=True`) **and** `P1_GIT_SSH_KEY` and
  `P1_GIT_KNOWN_HOSTS` are configured (else `SSH_NOT_CONFIGURED`). Refused:
  `http://`, `git://`, `file://` via the remote path, `ext::`, `ftp(s)`, any
  other scheme, URLs with userinfo (`CREDENTIALS_IN_URL`), control characters,
  leading `-`, whitespace, overlong URLs, hosts that are not valid DNS names
  or IP literals. `GIT_ALLOW_PROTOCOL` and `protocol.allow=never` + a
  per-protocol allow keep git itself on the allow-list.
* **SSRF policy:** resolve the host; refuse (`HOST_NOT_PUBLIC`) if *any* address
  is loopback, private (RFC 1918/ULA), link-local (incl. 169.254.169.254),
  CGNAT 100.64/10, multicast, reserved, unspecified or an IPv4-mapped form of
  those — unless the host is in an explicit operator allow-list
  (`NetworkPolicy.allow_hosts`, CLI `--allow-host`, env `P1_GIT_ALLOW_HOSTS`).
  The resolved IP is **pinned** for the fetch (`http.curloptResolve` for
  HTTPS; `HostName`/`HostKeyAlias` for SSH) to defeat DNS rebinding.
  Redirects are disabled (`http.followRedirects=false`).
* **Credentials:** HTTPS token from `P1_GIT_TOKEN` is passed through
  `GIT_CONFIG_COUNT/KEY/VALUE` env entries (never argv), sent only to the exact
  host, and scrubbed from every message, diagnostic and artefact. SSH uses
  `BatchMode=yes`, `StrictHostKeyChecking=yes`, `IdentitiesOnly=yes`,
  `-i $P1_GIT_SSH_KEY`, `UserKnownHostsFile=$P1_GIT_KNOWN_HOSTS`, agent
  forwarding off.
* **Ref → exact commit:** `git ls-remote` resolves branch, tag (annotated tags
  peeled) or `HEAD` to a SHA; a 40-hex input is used as the pin directly;
  abbreviated SHAs are refused for remotes (`REF_AMBIGUOUS`). Ref names are
  validated against `git check-ref-format` rules and a safe-character regex.
  The SHA is fetched (`git fetch --depth=1 --no-tags
  --no-recurse-submodules origin <sha>`); if the server refuses SHA fetches,
  the ref is fetched and `HEAD` must equal the pinned SHA, else
  `COMMIT_MOVED`. After fetch the existing safe-checkout path runs
  (`--detach`, `core.symlinks=false`, `core.autocrlf=false`, hooks disabled,
  symlink/submodule refusal via `ls-tree`, `HEAD == pin` verification).
* **Resource bounds:** per-git-invocation timeout (existing), a watchdog that
  kills git when the staging directory exceeds `limits.max_total_bytes`
  (`LIMIT_EXCEEDED`), and the existing entry-count / size limits afterwards.
* Errors are `IngestionError` subclasses with stable `code`s listed above;
  none echo a credential.

## 5. New detectors (shapes in `p1/findings.py`)

All detectors are pure functions of already-ingested data
(`list[AnalysedFile]`, a `text_of: dict[path, str]` for inventory-only text
files, the roots/graph where needed). They never execute anything, never read
outside the checkpoint, and return findings **sorted deterministically with
non-empty evidence**. Detection is `PARTIAL`/`UNKNOWN`, never `SUPPORTED`.

`p1/inventory.py`

* `list_directories(root: Path, files: list[IngestedFile]) -> list[DirectoryEntry]`
  — every directory, including empty ones (found by walking `root`).
* `detect_build_scripts(analysed, text_of, roots) -> list[BuildScriptFinding]`
  — `.bat .cmd .ps1 .sh Makefile *.mk *.iss *.nsi .groupproj`, MSBuild `.dproj`
  targets, CI config (`.github/workflows/*.yml`, `.gitlab-ci.yml`,
  `azure-pipelines.yml`, `Jenkinsfile`, `appveyor.yml`): tools invoked
  (`dcc32/dcc64/dccosx/msbuild/rsvars/lazbuild/fpc/make/inno/nsis`) and the
  project files they name (resolved against the input).
* `detect_compiler_configs(analysed, text_of) -> list[CompilerConfigFinding]`
  — `.cfg` (`dcc32.cfg`/`fpc.cfg`), `.dof`, `.dproj`/`.lpi` option blocks:
  switches (`-U -I -R -O -D -E -N -LE -LN -$`), defines, search paths.

`p1/integrations.py`

* `detect_integrations(analysed, text_of) -> list[IntegrationFinding]` —
  categories in `INTEGRATION_CATEGORIES` from `uses` units, component classes
  and literals: Indy (`Id*`), Synapse, ICS, WinInet/WinHTTP/`URLMon`, MSXML,
  `SOAPHTTPClient`/`InvokeRegistry`, Winsock/`ssockets`, FTP, SMTP/POP/IMAP,
  MQ/AMQP/MQTT, COM/OLE (`ComObj`, `CreateOleObject`, `.ocx`), DCOM, LDAP,
  serial (`CPort`, `Synaser`), `TService`/`SvcMgr`, scheduled jobs
  (`schtasks`, cron files, `TTimer`-driven batch), printing, reporting
  (QuickReport/FastReport/ReportBuilder/Rave). Endpoints = URLs/hosts/ports/
  queue names from string literals, **credentials redacted**, capped.
* `detect_libraries(analysed, roots, graph_unresolved) -> list[LibraryFinding]`
  — from `uses`/`requires`, package `requires`, unit prefixes and the existing
  `dialects.classify_unit`: framework (VCL/FMX/LCL), RTL, database, and the
  known third-party families (DevExpress, TMS, JEDI/JVCL, Raize, Indy, Zeos,
  Synapse, FastReport, QuickReport, VirtualTreeView, FastMM, mORMot, …),
  `origin` = `bundled` when the units exist in the input, `external` for a
  recognised absent library, `unresolved` otherwise.
* `detect_runtime_dependencies(analysed, text_of, native_libs, os_deps,
  databases, integrations, libraries) -> list[RuntimeDependencyFinding]` —
  DLL/BPL/OCX/COM names, `.ini`/config files opened by name
  (`TIniFile.Create`, `TMemIniFile`, `ReadFromFile`), registry keys
  (`TRegistry`/`OpenKey`), environment variables (`GetEnvironmentVariable`),
  hard-coded absolute paths (`C:\…`, `\\server\share`), database client
  libraries, Windows services. `resolved_in_input` is checked against the
  inventory.

`p1/classify.py` may be **extended** (new extensions such as `.iss .nsi .mk
.dof`, `Jenkinsfile`, CI YAML names) but existing classifications and their
tests must not change.

## 6. Blueprint (`p1/blueprint.py`, `stage1.application-blueprint/1.0`)

`build_blueprint(discovery: Discovery) -> dict` is a **pure, deterministic**
function (no wall clock, no absolute paths, sorted keys on serialisation).
Top-level keys (all required unless marked optional):

| Key | Content |
|---|---|
| `schema_version` | `"stage1.application-blueprint/1.0"` |
| `generator` | `{"llm_assisted": false, "stage": 1, "tool": "tools/p1"}` |
| `stage` | `{"id": 1, "name": "Ingestion and Discovery", "status": "COMPLETED" \| "COMPLETED_WITH_BLOCKERS", "steps": [{"id","name","status"}×5]}` ids: `ingestion`, `checkpoint`, `scanning_inventory`, `dependency_analysis`, `blueprint`; step status `COMPLETED` or `COMPLETED_WITH_WARNINGS`. A refused/failed run produces **no blueprint** (the run record carries the error). |
| `project` | `{"name","ingestion_source":{"kind","origin","ref","commit","commit_timestamp"},"checkpoint":{"id","source_digest","tree_id","file_count","directory_count"}}` |
| `summary` | `total_files, directories, total_bytes, pascal_sources, forms, projects, packages, database_artifacts, external_dependencies, unresolved_dependencies, diagnostics:{error,warning,info}, blockers` (all ints) |
| `file_distribution` | `{"total":int,"groups":[{"id","label","count","percent"}],"by_class":{class:int},"by_extension":{ext:int}}`; group ids: `pascal_source`(.pas .pp .p .inc), `project_package`(.dpr .dpk .dproj .lpr .lpi .lpk .groupproj …), `form_ui`(.dfm .lfm .fmx .xfm), `config_build`(configuration, build_script, sql, database), `other`; `percent` = float rounded to 1 dp, groups sum to 100.0 ± 0.1 |
| `dialect` | `{"primary","label","confidence","status","evidence":[…],"compiler":{"name","status","evidence"},"version":{"value","source","status"},"by_dialect":{dialect:int}}` — `version.value` is `"unknown"` unless a project file/directive states it |
| `projects` | `[{"path","kind","primary","shape","status","entry_point":{file,line,column},"profile":{…},"meta_files":[…],"unit_count","form_count","package_count","evidence":[…]}]` |
| `structure` | tree `{"name","path","kind","counts":{…},"children":[…]}`: application → projects → groups (`Units`, `Forms`, `Packages`, `Libraries`, `Resources`, `Config`, `Scripts`, `Docs`) each with a count and a bounded child list (`truncated: true` when capped) |
| `dependencies` | `{"key":[{"name","kind","category","status":"resolved"\|"unresolved","reason","references":int}] (top 5 by references, deterministic tie-break), "libraries":[LibraryFinding], "native_libraries":[…], "databases":[…], "sql_files":[…], "integrations":[IntegrationFinding], "runtime":[RuntimeDependencyFinding], "build":{"requirements":{…}, "scripts":[BuildScriptFinding], "compiler_configs":[CompilerConfigFinding]}}` |
| `unresolved` | flattened, id-sorted list: `{"id","kind":"unit"\|"include"\|"native-library"\|"library"\|"runtime"\|"project-file","name","reason","severity","referenced_by":[{"file","line","column"}],"remediation"}`; **nothing pruned** — unit/include/native edges from the graph plus unresolved libraries and runtime dependencies |
| `graphs` | `{"unit":{"ref":"dependency-graph.json","nodes":int,"edges":int,"resolved":int,"unresolved":int},"projects":[{"project","uses":[unit-paths],"packages":[…],"libraries":[…],"externals":[…]}],"packages":[{"package","requires":[…]}],"libraries":[{"library","used_by":[project paths]}]}` |
| `components` | fixed order: `gui_application, database, com_activex, reports, scheduled_jobs, services, build_scripts, documentation, integrations` → `{"id","label","present":bool,"count":int,"evidence":[…]}`; `present=false` has `count=0` |
| `inventory` | `{"directories":[DirectoryEntry], "file_count":int, "files_ref":"inventory.csv"}` — the full file list is in `application-manifest.json` / `inventory.csv`, not duplicated |
| `diagnostics` | merged, sorted list (same shape as the manifest's) |
| `blockers` | the build-requirement blockers plus `UNRESOLVED_DEPENDENCIES` etc. |
| `capability_states` | reuse `emit.capability_states` (never `VERIFIED`) |
| `limitations` | explicit list of what Stage 1 does *not* determine (no semantic analysis, binaries not decompiled, …) |

**Evidence rule:** every item in `dependencies.*`, `projects`, `components`
(when `present`), and `dialect` carries ≥ 1 located evidence entry
`{file,line,column,text}`; a test asserts this over every fixture.

Auxiliary machine-readable outputs written beside the blueprint
(`<store>/discoveries/<CP-id>/`):

| File | Content |
|---|---|
| `application-blueprint.json` | the blueprint |
| `application-manifest.json`, `dependency-graph.json`, `discovery-report.md` | existing P1 outputs (unchanged) |
| `unresolved-dependencies.json` | `{"schema_version":"stage1.unresolved/1.0","count":N,"items":[…]}` |
| `diagnostics.json` | `{"schema_version":"stage1.diagnostics/1.0","counts":{…},"items":[…]}` |
| `inventory.csv` | `path,class,extension,size,sha256,encoding,analysis_blocker` (LF, UTF-8, sorted) |
| `run-record.json` | **non-deterministic by design**: `{"checkpoint_id","ingested_at" (UTC ISO-8601), "steps":[{"id","status","started_at","duration_ms","message"}], "tool_versions":{…}}`; never read by the blueprint |

`docs/stage1/schemas/application-blueprint.schema.json` (JSON Schema 2020-12)
documents the blueprint; `p1/schemacheck.py` is a tiny stdlib validator
(`type, required, properties, items, enum, minimum, maximum, pattern,
additionalProperties, $ref (local), oneOf`) used by tests to validate every
generated blueprint and to prove that mutated documents are rejected.

## 7. Orchestrator and CLI

```python
@dataclass(frozen=True)
class DiscoveryRequest:
    kind: str                       # "git" | "zip" | "directory"
    source: str                     # URL, archive path, or directory path
    ref: str | None = None          # git branch/tag/SHA (remote or local)
    label: str | None = None        # display name; a name, never a path
    allow_ssh: bool = False
    network_policy: NetworkPolicy = NetworkPolicy()

Progress = Callable[[str, str, str], None]  # (step_id, status, message)

def discover(request, store: Path, *, progress: Progress | None = None,
             limits: Limits = DEFAULT_LIMITS) -> DiscoveryResult
# DiscoveryResult: checkpoint(CheckpointInfo), outdir(Path), blueprint(dict),
#                  outputs(dict[name→posix path]), reused(bool)
```

`progress` is called with `status` in `running|completed|warning|failed` for
each of the five step ids; the callback must never raise into the pipeline
(exceptions are swallowed and logged as a diagnostic).

CLI additions (existing `ingest`/`gate`/`guard` unchanged):

```
python tools/p1/cli.py discover <source> --store <dir> [--kind git|zip|directory]
        [--ref REF] [--label NAME] [--allow-ssh] [--allow-host HOST]...
python tools/p1/cli.py checkpoint verify <store>/checkpoints/<CP-id>
python tools/p1/cli.py serve [--store <dir>] [--host 127.0.0.1] [--port 8765]
        [--allow-local-root DIR]...
```

## 8. Web dashboard (`p1/server.py`, `p1/jobs.py`, `p1/web/`)

Implements the reference mock-up **Pascal-to-Java Discovery Dashboard** (kept
at `docs/stage1/reference/discovery-dashboard.png`): top nav, left "Modernization
Pipeline" with the six stages (Stage 1 active; Stages 2–6 shown as *Planned*,
never "completed"), "Ingest Application" / "Recent Discoveries" tabs, three
source cards (Git Repository / ZIP Archive / Local Directory), URL + Branch/Ref
form with **Ingest & Discover**, the five-step progress strip, and the
Application Blueprint panels (project information, summary tiles, file-distribution
donut, detected dialect, application structure tree, key dependencies top 5
with Resolved/Unresolved pills, discovered components, View Report, Download
Blueprint). Two front ends serve the same API contract: the **production
workbench** is React 18 + TypeScript + Vite (`frontend/`) served by a FastAPI
service (`p1/fastapi_app.py`, `python tools/p1/cli.py api`); the original
stdlib `http.server` + vanilla JS dashboard (`p1/server.py`, `p1/web/`) is
retained unchanged as a zero-dependency fallback and is used automatically by
the FastAPI service when `frontend/dist` has not been built (see §8.1). All values come from the blueprint; nothing is
hard-coded to the mock-up's sample data. The "Stage 1 – Completed" badge shows
**Completed**, **Completed with N blockers** or **Failed** from real status.

API (JSON; all POSTs require header `X-P1-Request: 1`):

| Method + path | Behaviour |
|---|---|
| `GET /`, `/app.css`, `/app.js` | static allow-list only |
| `GET /api/config` | `{"local_directory_enabled","ssh_enabled","max_upload_bytes","stage":1}` |
| `POST /api/discoveries` | JSON `{"kind":"git","url","ref"}` or `{"kind":"directory","path"}` (only if the path is inside an `--allow-local-root`) → `202 {"id","status":"queued"}` |
| `POST /api/discoveries/upload?name=<file.zip>` | raw `application/zip` body streamed to a temp file under a hard byte cap → `202` as above |
| `GET /api/discoveries` | recent first (bounded) |
| `GET /api/discoveries/<id>` | `{"id","status":"queued\|running\|completed\|failed","steps":[…],"error":{"code","message"}\|null,"checkpoint_id","blueprint":{…}\|null,"run":{"ingested_at"}}` |
| `GET /api/discoveries/<id>/blueprint` | download (`Content-Disposition: attachment`) |
| `GET /api/discoveries/<id>/report` | the Markdown report, `text/plain; charset=utf-8` |
| `GET /api/discoveries/<id>/artifacts/<name>` | allow-listed file names only |

Security requirements: bind `127.0.0.1` by default; reject requests whose
`Host` header is not the bound host:port (DNS rebinding); reject cross-origin
`Origin` on POST; require the custom header; ids are `[0-9a-f]{16}`; no path
is ever built from user input beyond a validated id and an allow-listed name;
`Content-Security-Policy: default-src 'self'`, `X-Content-Type-Options:
nosniff`, `Referrer-Policy: no-referrer`; the UI inserts data with
`textContent` only (never `innerHTML` with data); error responses carry a
stable code and a sanitised message (no filesystem paths, no tokens); bounded
job queue and one worker thread; request-body and header limits; local
directory ingestion disabled unless explicitly enabled.

### 8.1 FastAPI service, tenancy and tokens

`p1/fastapi_app.py` is a thin adapter over the same tested core
(`JobManager`, `server_security`, `tenancy`). A pure-ASGI `GuardMiddleware`
applies, to every request: single allowed `Host`; `Origin`/`X-P1-Request` on
POST; method allow-list (GET/HEAD/POST); absolute-path check; tenant
resolution; security headers (CSP `default-src 'self'` etc.). Bodies are
bounded (JSON 16 KiB; uploads need `Content-Length`, are capped, deadline-
bound, magic-byte checked and removed on every failure path). Static files
come from a table built at start-up (no path from user input).

**Tenancy** (`p1/tenancy.py`): tenant ids match `[a-z0-9][a-z0-9_-]{0,62}` and
are never a store directory name (`tenants`, `jobs`, `uploads`, `checkpoints`,
`discoveries`). The default tenant uses the store root (backwards compatible);
others use `<store>/tenants/<id>/{jobs,uploads,checkpoints,discoveries}`. A
cross-tenant read answers 404 (indistinguishable from "does not exist").

**Tenant tokens** (`p1/tenant_auth.py`, `tenant-token` command): with
`--tenant-tokens-file` every `/api/*` request except `/api/config` needs
`Authorization: Bearer <token>`; the tenant is *derived from the token* and
`X-P1-Tenant` is ignored, so a client cannot pick another tenant. Only SHA-256
digests are stored (file mode 0600 on POSIX); lookup compares every entry in
constant time. Without a token file the server is single-user: `X-P1-Tenant`
is a storage boundary, **not** authentication, and a non-loopback bind is
refused unless `--allow-remote-bind` is given. Identity (OIDC), RBAC, rotation
and revocation UI are Stage 6.

## 9. Testing and verification requirements

* TDD: tests first; **≥ 80 % line coverage** on every new module
  (`pytest --cov` if available, otherwise a recorded `trace`/manual argument).
* Unit tests per detector with positive, negative and adversarial inputs;
  security tests for remote-Git URL/SSRF/ref validation (no network: inject a
  resolver); checkpoint tests (atomicity, idempotence, tamper detection,
  read-only, determinism); blueprint tests (schema validation, evidence rule,
  percent sums, determinism = byte-identical on rerun, same bytes via ZIP and
  Git give the same blueprint modulo `source` provenance).
* Integration: end-to-end `discover` over a realistic multi-project fixture
  (Delphi VCL + FireDAC + Indy + DevExpress + BPL package + .ini + bat + SQL +
  external DLL + unresolved units) for ZIP, local-Git and (via a local
  smart-HTTP server with the test-only allow-list) remote HTTPS.
* Existing 612 tests must keep passing unchanged.
* No test needs the public internet.

## 10. Out of scope (stated, not hidden)

Parsing beyond the existing scanner, symbol/type resolution, Semantic IR,
transformation, Java generation, oracle execution, database connections (never
connected; metadata only from source), binary decompilation, GUI conversion,
tenancy/RBAC (Stage 6). The blueprint states these in `limitations`.
