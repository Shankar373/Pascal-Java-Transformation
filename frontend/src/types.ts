/** Shapes of the Stage 1 API. Every blueprint field is optional: render defensively. */

export interface ApiErrorBody {
  code: string;
  message: string;
}

export interface AppConfig {
  local_directory_enabled: boolean;
  ssh_enabled: boolean;
  max_upload_bytes: number;
  auth_required?: boolean;
  ui?: string;
}

export interface JobStep {
  id: string;
  name: string;
  status: string;
  message?: string | null;
}

export interface Evidence {
  file?: string;
  line?: number;
  text?: string;
}

export interface JobSummary {
  project?: string;
  total_files?: number;
}

export interface JobView {
  id: string;
  tenant?: string;
  status: string;
  kind?: string | null;
  label?: string | null;
  ref?: string | null;
  steps: JobStep[];
  error: ApiErrorBody | null;
  checkpoint_id?: string | null;
  created_at?: string;
  run?: { ingested_at?: string | null };
  summary?: JobSummary | null;
  blueprint?: Blueprint | null;
}

export interface DiscoveryList {
  items: JobView[];
}

export interface Accepted {
  id: string;
}

export type CreateRequest =
  | { kind: "git"; url: string; ref: string | null }
  | { kind: "directory"; path: string };

export interface IngestionSource {
  kind?: string;
  origin?: string;
  ref?: string;
  commit?: string;
}

export interface BlueprintSummary {
  total_files?: number;
  directories?: number;
  pascal_sources?: number;
  projects?: number;
  database_artifacts?: number;
  external_dependencies?: number;
  blockers?: number;
  diagnostics?: Partial<Record<"error" | "warning" | "info", number>>;
}

export interface DistributionGroup {
  label: string;
  count: number;
  percent?: number;
}

export interface Dialect {
  label?: string;
  evidence?: Evidence[];
  compiler?: { name?: string };
  version?: { value?: string };
}

export interface StructureNode {
  name: string;
  kind?: string;
  counts?: { files?: number };
  children?: StructureNode[];
  truncated?: boolean;
}

export interface KeyDependency {
  name: string;
  status?: string;
  reason?: string;
}

export interface ComponentInfo {
  id: string;
  label: string;
  present?: boolean;
  count?: number;
}

export interface ProjectRow {
  path?: string;
  kind?: string;
  shape?: string;
  unit_count?: number;
  form_count?: number;
  package_count?: number;
  status?: string;
  evidence?: Evidence[];
}

export interface LibraryRow {
  name?: string;
  category?: string;
  origin?: string;
  references?: number;
  evidence?: Evidence[];
}

export interface DatabaseRow {
  name?: string;
  kind?: string;
  engine?: string;
  evidence?: Evidence[];
}

export interface SqlFileRow {
  path?: string;
  statements?: number;
  tables?: number;
  evidence?: Evidence[];
}

export interface IntegrationRow {
  category?: string;
  name?: string;
  endpoints?: string[];
  count?: number;
  evidence?: Evidence[];
}

export interface RuntimeRow {
  kind?: string;
  name?: string;
  resolved_in_input?: boolean;
  evidence?: Evidence[];
}

export interface NativeLibraryRow {
  name?: string;
  resolved_in_input?: boolean;
  references?: number;
  evidence?: Evidence[];
}

export interface BuildScriptRow {
  path?: string;
  kind?: string;
  tools?: string[];
  projects?: string[];
  evidence?: Evidence[];
}

export interface CompilerConfigRow {
  path?: string;
  kind?: string;
  switches?: string[];
  defines?: string[];
  search_paths?: string[];
  evidence?: Evidence[];
}

export interface UnresolvedRow {
  id?: string;
  kind?: string;
  name?: string;
  severity?: string;
  reason?: string;
  referenced_by?: Evidence[];
}

export interface DiagnosticRow {
  severity?: string;
  code?: string;
  message?: string;
  file?: string;
  line?: number;
}

export interface BlockerRow {
  code?: string;
  detail?: string;
  message?: string;
}

export interface Dependencies {
  key?: KeyDependency[];
  libraries?: LibraryRow[];
  databases?: DatabaseRow[];
  sql_files?: SqlFileRow[];
  integrations?: IntegrationRow[];
  runtime?: RuntimeRow[];
  native_libraries?: NativeLibraryRow[];
  build?: {
    scripts?: BuildScriptRow[];
    compiler_configs?: CompilerConfigRow[];
    requirements?: Record<string, unknown>;
  };
}

export interface Blueprint {
  project?: {
    name?: string;
    ingestion_source?: IngestionSource;
    checkpoint?: { id?: string };
  };
  stage?: { status?: string };
  summary?: BlueprintSummary;
  file_distribution?: { total?: number; groups?: DistributionGroup[] };
  dialect?: Dialect;
  structure?: StructureNode | null;
  dependencies?: Dependencies;
  components?: ComponentInfo[];
  projects?: ProjectRow[];
  unresolved?: UnresolvedRow[];
  diagnostics?: DiagnosticRow[];
  blockers?: BlockerRow[];
  limitations?: string[];
}
