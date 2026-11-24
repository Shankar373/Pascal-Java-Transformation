import { Fragment } from "react";
import type { ReactElement, ReactNode } from "react";
import { COMPONENT_ICON, ORIGIN_LABEL, SOURCE_LABEL } from "../constants";
import { DASH, fmt, fmtDate } from "../format";
import { Icon } from "../icons";
import type { Blueprint, JobView } from "../types";
import { CopyButton, Panel } from "./Panel";

interface KvProps {
  rows: ReadonlyArray<readonly [string, ReactNode, ReactNode?]>;
  wide?: boolean;
}

export function Kv({ rows, wide = false }: KvProps): ReactElement {
  return (
    <dl className={wide ? "kv kv-wide" : "kv"}>
      {rows.map(([label, value, extra]) => (
        <Fragment key={label}>
          <dt>{label}</dt>
          <dd>{value}{extra ?? null}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

interface ProjectInfoProps {
  job: JobView;
  bp: Blueprint;
  onCopied: (message: string) => void;
}

export function ProjectInfo({ job, bp, onCopied }: ProjectInfoProps): ReactElement {
  const proj = bp.project ?? {};
  const src = proj.ingestion_source ?? {};
  const kind = src.kind ?? "";
  const commit = src.commit ? String(src.commit) : "";
  const refText = (src.ref || DASH) + (commit ? ` (${commit.slice(0, 7)})` : "");
  const cpId = proj.checkpoint?.id;
  return (
    <Panel title="Project Information" icon="info" cls="area-info">
      <Kv rows={[
        ["Project Name", proj.name || DASH],
        ["Ingestion Source", SOURCE_LABEL[kind] ?? (kind || DASH)],
        [ORIGIN_LABEL[kind] ?? "Origin", src.origin || DASH],
        ["Branch / Commit", refText, commit ? <CopyButton value={commit} label="commit" onCopied={onCopied} /> : null],
        ["Checkpoint ID", cpId || DASH, cpId ? <CopyButton value={cpId} label="checkpoint ID" onCopied={onCopied} /> : null],
        ["Ingested On", fmtDate(job.run?.ingested_at)],
      ]} />
    </Panel>
  );
}

export function Tiles({ bp }: { bp: Blueprint }): ReactElement {
  const s = bp.summary ?? {};
  const defs: ReadonlyArray<readonly [string, number | undefined, string, string]> = [
    ["Total Files", s.total_files, "file", "blue"],
    ["Directories", s.directories, "folder", "amber"],
    ["Pascal Sources", s.pascal_sources, "logo", "blue"],
    ["Projects", s.projects, "layers", "violet"],
    ["Database Artifacts", s.database_artifacts, "database", "violet"],
    ["External Dependencies", s.external_dependencies, "puzzle", "green"],
  ];
  return (
    <ul className="tiles area-tiles">
      {defs.map(([label, value, icon, tone]) => (
        <li key={label} className="tile">
          <span className={`tile-icon tone-${tone}`} aria-hidden="true"><Icon name={icon} /></span>
          <span className="tile-text">
            <span className="tile-label">{label}</span>
            <strong className="tile-value">{fmt(value)}</strong>
          </span>
        </li>
      ))}
    </ul>
  );
}

const MAX_EVIDENCE = 3;

export function DialectPanel({ bp }: { bp: Blueprint }): ReactElement {
  const d = bp.dialect ?? {};
  const texts: string[] = [];
  (d.evidence ?? []).forEach((e) => {
    if (e.text && !texts.includes(e.text) && texts.length < MAX_EVIDENCE) texts.push(e.text);
  });
  const compiler = d.compiler?.name;
  const named = Boolean(compiler) && compiler !== "unknown";
  const version = d.version?.value;
  return (
    <Panel title="Detected Pascal Dialect" icon="award" cls="area-dialect">
      <div className="dialect">
        <span className="chip chip-dialect">{d.label || "Unknown"}</span>
        <Kv wide rows={[
          ["Evidence", texts.length ? texts.join(", ") : DASH],
          ["Compiler", named ? `${compiler} (detected)` : "Not determined"],
          ["Version (in config)", version && version !== "unknown" ? `${version} (indicated)` : "Not stated in project files"],
        ]} />
      </div>
    </Panel>
  );
}

const MAX_KEY_DEPS = 5;

export function KeyDepsPanel({ bp }: { bp: Blueprint }): ReactElement {
  const keys = (bp.dependencies?.key ?? []).slice(0, MAX_KEY_DEPS);
  return (
    <Panel title="Key Dependencies (Top 5)" icon="link" cls="area-deps">
      <ul className="keydeps">
        {keys.length === 0 ? <li className="muted">No key dependencies detected.</li> : null}
        {keys.map((d, i) => {
          const ok = d.status === "resolved";
          return (
            <li key={i} title={d.reason || ""}>
              <span className="keydep-name">{d.name}</span>
              <span className={`pill ${ok ? "pill-ok" : "pill-bad"}`}>{ok ? "Resolved" : "Unresolved"}</span>
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}

export function ComponentsPanel({ bp }: { bp: Blueprint }): ReactElement {
  return (
    <Panel title="Discovered Components" icon="grid" cls="area-comps">
      <ul className="chips">
        {(bp.components ?? []).map((c) => {
          const present = Boolean(c.present);
          return (
            <li
              key={c.id} className={`chip chip-comp ${present ? "is-present" : "is-absent"}`}
              title={present ? `${c.label}: ${fmt(c.count)} found` : `${c.label}: not detected`}
            >
              <Icon name={COMPONENT_ICON[c.id] ?? "dot"} />
              <span>{c.label}</span>
              {present ? null : <span className="visually-hidden"> (not detected)</span>}
            </li>
          );
        })}
      </ul>
    </Panel>
  );
}
