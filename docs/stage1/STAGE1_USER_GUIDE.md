# Stage 1 — Ingestion and Discovery: user guide

Stage 1 takes a complete customer Pascal application, freezes it as an
**immutable checkpoint**, and produces an **evidence-backed Application
Blueprint**. It never compiles, executes or converts anything, makes no
network call except the Git fetch you ask for, and uses no LLM or ML.

## Inputs

| Input | How | Notes |
|---|---|---|
| Git repository (HTTPS) | `discover https://host/org/repo.git --ref main` | resolved to an exact 40-hex commit before anything else |
| Git repository (SSH) | `--allow-ssh` + `P1_GIT_SSH_KEY` + `P1_GIT_KNOWN_HOSTS` | host key must be in the known-hosts file; no agent, no prompts |
| Local Git repository | `discover /path/to/repo` or `file://…` | a branch, tag or commit may be pinned with `--ref` |
| ZIP archive | `discover app.zip` | original archive is preserved byte-for-byte in the checkpoint |
| Local directory | `discover /path/to/dir` | copied into the checkpoint; symlinks are refused |

Remote Git safety (details in `STAGE1_DESIGN.md` §4): HTTPS always, SSH only
when configured, no credentials in URLs, private/loopback/link-local hosts
refused unless an operator allow-lists them (`--allow-host` or
`P1_GIT_ALLOW_HOSTS`), resolved address pinned for the fetch, redirects
disabled, submodules and symlinks refused, hooks never run.
`P1_GIT_TOKEN` (HTTPS) is sent only to the exact host and never appears in
command lines, logs or outputs.

## Command line

```text
python tools/p1/cli.py discover <source> --store <dir> [--ref REF] [--label NAME]
                                [--kind git|zip|directory] [--allow-ssh] [--allow-host HOST]
python tools/p1/cli.py checkpoint verify <store>/checkpoints/<CP-id>
python tools/p1/cli.py serve [--store <dir>] [--port 8765] [--allow-local-root DIR]
```

`discover` exits `0` on success and `1` when the input is refused; a refused
input produces **no** blueprint.

## Dashboard

```text
python tools/p1/cli.py serve --store .stage1-store
# open http://127.0.0.1:8765/
```

The dashboard is a stdlib server with a vanilla-JS page (no build step, no
CDN). It binds to loopback, rejects foreign `Host`/`Origin` headers and has
**no authentication** (that arrives with Stage 6) — do not expose it. The
Local Directory source is disabled unless you pass `--allow-local-root`.

## Store layout

```text
<store>/checkpoints/<CP-id>/checkpoint.json   written once, read-only
                           /source/           the preserved tree (read-only)
                           /original/input.zip  (ZIP inputs only)
<store>/discoveries/<CP-id>/application-blueprint.json
                            application-manifest.json   dependency-graph.json
                            unresolved-dependencies.json diagnostics.json
                            inventory.csv  discovery-report.md  run-record.json
<store>/jobs/<id>/job.json                    dashboard job state
```

`CP-<12 hex>` is derived from the content (kind, commit, source digest):
re-ingesting the same commit or archive reuses the same checkpoint after
re-verifying it. A checkpoint that fails verification is **never** reused or
overwritten (`CHECKPOINT_TAMPERED`).

## What the blueprint contains

Project and source provenance (commit, checkpoint id), summary counts, file
distribution, detected dialect/compiler/version with evidence, every project
and entry point, an application structure tree, key dependencies (top 5),
libraries (framework / RTL / database / third-party, bundled vs external vs
unresolved), databases and SQL files, external integrations (HTTP, SOAP,
FTP, SMTP, COM/OLE, services, reporting, …), runtime dependencies (DLL/BPL,
config files, registry keys, environment variables, hard-coded paths), build
scripts and compiler configuration, unresolved dependencies with severity and
remediation, dependency graphs, discovered components, diagnostics, blockers
and explicit limitations. Every finding carries located evidence
(`file`, `line`, `column`, redacted `text`). The schema is
`docs/stage1/schemas/application-blueprint.schema.json`.

`run-record.json` is the only artefact with wall-clock data. Everything else
is byte-identical for identical input.

## Honest limits

Detection is not support: findings are `PARTIAL`/`UNKNOWN`, never
`SUPPORTED`. Stage 1 does no symbol/type resolution, builds no semantic IR,
does not connect to databases, does not decompile binaries, and the Delphi
release name is reported as the raw `ProjectVersion` (no unverified mapping).
Proxy-only networks are unsupported for remote Git (a proxy would bypass
address pinning).
