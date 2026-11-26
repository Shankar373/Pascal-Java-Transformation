import type { ReactElement, ReactNode } from "react";
import { evShort, fmt, listCell, yesNo } from "../format";
import type {
  Blueprint, DatabaseRow, DiagnosticRow, Evidence, SqlFileRow, UnresolvedRow,
} from "../types";
import { Kv } from "./BlueprintPanels";
import type { Column } from "./DataTable";
import { DataTable } from "./DataTable";

interface DetailProps {
  title: string;
  count: number | null;
  children: ReactNode;
}

function Detail({ title, count, children }: DetailProps): ReactElement {
  return (
    <section className="card detail">
      <h2 className="section-title">
        {title}
        {count !== null ? <span className="count">{String(count)}</span> : null}
      </h2>
      {children}
    </section>
  );
}

interface SectionProps<T> {
  title: string;
  rows: readonly T[] | undefined;
  columns: ReadonlyArray<Column<T>>;
}

function Section<T>({ title, rows, columns }: SectionProps<T>): ReactElement {
  const list = Array.isArray(rows) ? rows : [];
  return (
    <Detail title={title} count={list.length}>
      {list.length ? <DataTable columns={columns} rows={list} /> : <p className="muted">None detected.</p>}
    </Detail>
  );
}

function SeverityPill({ value }: { value: string | undefined }): ReactElement {
  const sev = String(value || "info").toLowerCase();
  return <span className={`pill sev-${sev}`}>{sev}</span>;
}

function evidenceColumn<T extends { evidence?: Evidence[] }>(): Column<T> {
  return { label: "Evidence", get: (r) => evShort(r.evidence) };
}

interface DbRow {
  name?: string;
  type: string;
  info: string;
  evidence?: Evidence[];
}

function databaseRows(bp: Blueprint): DbRow[] {
  const dep = bp.dependencies ?? {};
  const dbs = (dep.databases ?? []).map((d: DatabaseRow): DbRow => (
    { name: d.name, type: d.kind || "database", info: d.engine ?? "", evidence: d.evidence }
  ));
  const sql = (dep.sql_files ?? []).map((f: SqlFileRow): DbRow => ({
    name: f.path, type: "SQL file", info: `${f.statements || 0} statements, ${f.tables || 0} tables`,
    evidence: f.evidence,
  }));
  return [...dbs, ...sql];
}

function Requirements({ reqs }: { reqs: Record<string, unknown> }): ReactElement | null {
  const keys = Object.keys(reqs);
  if (!keys.length) return null;
  return (
    <Detail title="Build Requirements" count={null}>
      <Kv wide rows={keys.map((k) => {
        const v = reqs[k];
        return [k.replace(/_/g, " "), Array.isArray(v) ? listCell(v) : String(v)] as const;
      })} />
    </Detail>
  );
}

const DIAGNOSTIC_COLUMNS: ReadonlyArray<Column<DiagnosticRow>> = [
  { label: "Severity", get: (r) => <SeverityPill value={r.severity} /> },
  { label: "Code", get: (r) => r.code },
  { label: "Message", get: (r) => r.message },
  { label: "Location", get: (r) => (r.file ? r.file + (r.line ? `:${r.line}` : "") : "") },
];

function Diagnostics({ bp }: { bp: Blueprint }): ReactElement {
  const counts = bp.summary?.diagnostics ?? {};
  const rows = bp.diagnostics ?? [];
  return (
    <Detail title="Diagnostics" count={rows.length}>
      <div>
        <ul className="chips">
          {(["error", "warning", "info"] as const).map((k) => (
            <li key={k} className={`chip sev-${k}`}>{`${counts[k] || 0} ${k}`}</li>
          ))}
        </ul>
        <DataTable columns={DIAGNOSTIC_COLUMNS} rows={rows} />
      </div>
    </Detail>
  );
}

const UNRESOLVED_COLUMNS: ReadonlyArray<Column<UnresolvedRow>> = [
  { label: "Id", get: (r) => r.id }, { label: "Kind", get: (r) => r.kind }, { label: "Name", get: (r) => r.name },
  { label: "Severity", get: (r) => <SeverityPill value={r.severity} /> },
  { label: "Reason", get: (r) => r.reason },
  { label: "Referenced by", get: (r) => evShort(r.referenced_by) },
];

export function DetailSections({ bp, hidden }: { bp: Blueprint; hidden: boolean }): ReactElement {
  const dep = bp.dependencies ?? {};
  const build = dep.build ?? {};
  return (
    <div className={hidden ? "details is-off" : "details"}>
      <Section title="Projects" rows={bp.projects} columns={[
        { label: "Project", get: (r) => r.path }, { label: "Kind", get: (r) => r.kind },
        { label: "Shape", get: (r) => r.shape }, { label: "Units", get: (r) => fmt(r.unit_count) },
        { label: "Forms", get: (r) => fmt(r.form_count) }, { label: "Packages", get: (r) => fmt(r.package_count) },
        { label: "Discovery status", title: "Whether Stage 1 could scan this project. It is not a conversion-support claim.", get: (r) => r.status },
        evidenceColumn(),
      ]} />
      <Section title="Libraries" rows={dep.libraries} columns={[
        { label: "Library", get: (r) => r.name }, { label: "Category", get: (r) => r.category },
        { label: "Origin", get: (r) => r.origin }, { label: "References", get: (r) => fmt(r.references) },
        evidenceColumn(),
      ]} />
      <Section title="Databases" rows={databaseRows(bp)} columns={[
        { label: "Name", get: (r) => r.name }, { label: "Type", get: (r) => r.type },
        { label: "Detail", get: (r) => r.info }, evidenceColumn(),
      ]} />
      <Section title="External Integrations" rows={dep.integrations} columns={[
        { label: "Category", get: (r) => r.category }, { label: "Name", get: (r) => r.name },
        { label: "Endpoints", get: (r) => listCell(r.endpoints) }, { label: "Count", get: (r) => fmt(r.count) },
        evidenceColumn(),
      ]} />
      <Section title="Runtime Dependencies" rows={dep.runtime} columns={[
        { label: "Kind", get: (r) => r.kind }, { label: "Name", get: (r) => r.name },
        { label: "Present in input", get: (r) => yesNo(r.resolved_in_input) }, evidenceColumn(),
      ]} />
      <Section title="Native Libraries" rows={dep.native_libraries} columns={[
        { label: "Library", get: (r) => r.name },
        { label: "Present in input", get: (r) => yesNo(r.resolved_in_input) },
        { label: "References", get: (r) => fmt(r.references) }, evidenceColumn(),
      ]} />
      <Section title="Build Scripts" rows={build.scripts} columns={[
        { label: "Script", get: (r) => r.path }, { label: "Kind", get: (r) => r.kind },
        { label: "Tools", get: (r) => listCell(r.tools) }, { label: "Projects", get: (r) => listCell(r.projects) },
        evidenceColumn(),
      ]} />
      <Section title="Compiler Configuration" rows={build.compiler_configs} columns={[
        { label: "File", get: (r) => r.path }, { label: "Kind", get: (r) => r.kind },
        { label: "Switches", get: (r) => listCell(r.switches) }, { label: "Defines", get: (r) => listCell(r.defines) },
        { label: "Search paths", get: (r) => listCell(r.search_paths) }, evidenceColumn(),
      ]} />
      <Section title="Unresolved Dependencies" rows={bp.unresolved} columns={UNRESOLVED_COLUMNS} />
      <Requirements reqs={build.requirements ?? {}} />
      <Diagnostics bp={bp} />
      <Detail title="Limitations" count={null}>
        <ul className="bullets">{(bp.limitations ?? []).map((l, i) => <li key={i}>{l}</li>)}</ul>
      </Detail>
    </div>
  );
}
