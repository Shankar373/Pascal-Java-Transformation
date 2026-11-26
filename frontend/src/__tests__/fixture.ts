import type { Blueprint, JobView } from "../types";

export const JOB_ID = "0123456789abcdef";
export const XSS = "<img src=x onerror=alert(1)>";

export const STEPS_DONE = [
  { id: "ingestion", name: "Ingestion", status: "completed", message: "" },
  { id: "checkpoint", name: "Checkpoint", status: "completed", message: "" },
  { id: "scanning_inventory", name: "Scanning & Inventory", status: "completed", message: "" },
  { id: "dependency_analysis", name: "Dependency Analysis", status: "warning", message: "" },
  { id: "blueprint", name: "Application Blueprint", status: "completed", message: "" },
];

export function makeBlueprint(overrides: Partial<Blueprint> = {}): Blueprint {
  return {
    project: {
      name: `Payroll ${XSS}`,
      ingestion_source: {
        kind: "git", origin: "https://git.example.com/org/payroll.git", ref: "main",
        commit: "abcdef1234567890",
      },
      checkpoint: { id: "chk-0001" },
    },
    stage: { status: "COMPLETED_WITH_BLOCKERS" },
    summary: {
      total_files: 1234, directories: 56, pascal_sources: 789, projects: 3,
      database_artifacts: 4, external_dependencies: 12, blockers: 1,
      diagnostics: { error: 1, warning: 2, info: 3 },
    },
    file_distribution: {
      total: 100,
      groups: [
        { label: "Pascal sources", count: 60, percent: 60 },
        { label: "Forms", count: 30, percent: 30 },
        { label: "Other", count: 10, percent: 10 },
      ],
    },
    dialect: {
      label: "Delphi",
      evidence: [{ text: "uses Vcl.Forms" }, { text: "uses Vcl.Forms" }, { text: "{$mode delphi}" }],
      compiler: { name: "dcc32" },
      version: { value: "XE2" },
    },
    structure: {
      name: "root", kind: "root",
      children: [{
        name: "Payroll", kind: "application",
        children: [
          { name: "Core", kind: "group", counts: { files: 12 }, children: [
            { name: "Salary.pas", kind: "file" },
          ] },
          { name: "Lonely", kind: "group", counts: { files: 1 } },
          { name: "Big", kind: "group", truncated: true, children: [] },
        ],
      }],
    },
    dependencies: {
      key: [
        { name: "FireDAC", status: "resolved", reason: "found in input" },
        { name: "Indy", status: "unresolved", reason: "missing" },
        { name: "k3", status: "resolved" }, { name: "k4", status: "resolved" },
        { name: "k5", status: "resolved" }, { name: "k6-hidden", status: "resolved" },
      ],
      libraries: [{ name: "FireDAC", category: "database", origin: "vendor", references: 1500, evidence: [{ file: "a.pas", line: 3 }] }],
      databases: [{ name: "PAYDB", kind: "firebird", engine: "Firebird 3" }],
      sql_files: [{ path: "db/schema.sql", statements: 12, tables: 4 }],
      integrations: [{ category: "http", name: "REST", endpoints: ["https://x.example"], count: 2 }],
      runtime: [{ kind: "dll", name: "x.dll", resolved_in_input: false }],
      native_libraries: [{ name: "user32", resolved_in_input: true, references: 3 }],
      build: {
        scripts: [{ path: "build.bat", kind: "batch", tools: ["dcc32"], projects: [] }],
        compiler_configs: [{ path: "Payroll.dof", kind: "dof", switches: ["-B"], defines: ["DEBUG"], search_paths: [] }],
        requirements: { compiler_versions: ["XE2", "XE3"], needs_ide: true },
      },
    },
    components: [
      { id: "gui_application", label: "GUI Application", present: true, count: 5 },
      { id: "reports", label: "Reports", present: false },
      { id: "mystery", label: "Mystery", present: true, count: 1 },
    ],
    projects: [{ path: "Payroll.dpr", kind: "dpr", shape: "gui", unit_count: 40, form_count: 9, package_count: 1, status: "ok" }],
    unresolved: [{ id: "U1", kind: "unit", name: "MissingUnit", severity: "HIGH", reason: "not found", referenced_by: [{ file: "b.pas", line: 7 }] }],
    diagnostics: [
      { severity: "error", code: "E1", message: `Bad ${XSS}`, file: "c.pas", line: 9 },
      { severity: "warning", code: "W1", message: "meh" },
    ],
    blockers: [{ code: "B1", detail: "Missing runtime" }, { message: "Second blocker" }],
    limitations: ["Static analysis only"],
    ...overrides,
  };
}

export function makeJob(overrides: Partial<JobView> = {}): JobView {
  return {
    id: JOB_ID, status: "completed", kind: "git", label: "payroll", steps: STEPS_DONE, error: null,
    created_at: "2026-01-02T03:04:05Z", run: { ingested_at: "2026-01-02T03:04:05Z" },
    blueprint: makeBlueprint(), ...overrides,
  };
}
