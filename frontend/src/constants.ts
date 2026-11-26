export const ID_RE = /^[0-9a-f]{16}$/;
export const POLL_MIN_MS = 1000;
export const POLL_MAX_MS = 8000;
export const POLL_GROWTH = 1.15;
export const POLL_MAX_ERRORS = 6;

export const STEP_DEFS: ReadonlyArray<readonly [string, string]> = [
  ["ingestion", "Ingestion"],
  ["checkpoint", "Checkpoint"],
  ["scanning_inventory", "Scanning & Inventory"],
  ["dependency_analysis", "Dependency Analysis"],
  ["blueprint", "Application Blueprint"],
];

export const DONE_TEXT: Readonly<Record<string, string>> = {
  ingestion: "Completed", checkpoint: "Created", scanning_inventory: "Completed",
  dependency_analysis: "Completed", blueprint: "Generated",
};

export const SOURCE_LABEL: Readonly<Record<string, string>> = {
  git: "Git Repository", zip: "ZIP Archive", directory: "Local Directory",
};
export const ORIGIN_LABEL: Readonly<Record<string, string>> = {
  git: "Repository", zip: "Archive", directory: "Directory",
};

export const COMPONENT_ICON: Readonly<Record<string, string>> = {
  gui_application: "monitor", database: "database", com_activex: "gear", reports: "chart",
  scheduled_jobs: "calendar", services: "gear", build_scripts: "terminal",
  documentation: "book", integrations: "link",
};

export const PIPELINE_STAGES: ReadonlyArray<readonly [string, string]> = [
  ["Stage 2", "Pascal Language Engineering"],
  ["Stage 3", "Modernization Intelligence"],
  ["Stage 4", "Java Generation & Compatibility"],
  ["Stage 5", "Runtime and Verification"],
  ["Stage 6", "Enterprise Platform & Operations"],
];

export const DOWNLOADS: ReadonlyArray<readonly [string, string]> = [
  ["Blueprint (JSON)", "blueprint"],
  ["Checkpoint manifest (JSON)", "artifacts/checkpoint-manifest.json"],
  ["Project inventory (JSON)", "artifacts/project-inventory.json"],
  ["Architecture report (JSON)", "artifacts/architecture-report.json"],
  ["Dependency graph (JSON)", "artifacts/dependency-graph.json"],
  ["Application manifest (JSON)", "artifacts/application-manifest.json"],
  ["Unresolved dependencies (JSON)", "artifacts/unresolved-dependencies.json"],
  ["Diagnostics (JSON)", "artifacts/diagnostics.json"],
  ["Inventory (CSV)", "artifacts/inventory.csv"],
];
