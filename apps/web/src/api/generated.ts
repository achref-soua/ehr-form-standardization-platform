/* Generated contract surface. Run `make openapi` to regenerate from FastAPI. */
export type PersonaRole = "engineer" | "steward" | "researcher" | "operator";

export interface Persona {
  id: string;
  display_name: string;
  role: PersonaRole;
}

export interface SessionResponse {
  actor: Persona;
  csrf_token: string;
  expires_in_seconds: number;
}

export interface Establishment {
  id: string;
  name: string;
  region: string;
  active: boolean;
}

export interface SourceSystem {
  id: string;
  establishment_id: string;
  source_key: string;
  family: string;
  version: string;
}

export interface FormVersion {
  id: string;
  establishment_id: string;
  form_id: string;
  family: string;
  version: string;
  title: string;
  source_fingerprint: string;
  compatibility_fingerprint: string;
  mapping_status: string;
  definition: { items?: Array<Record<string, unknown>> };
}

export interface MappingDraft {
  id: string;
  status: string;
  authored_by: string;
  approved_by: string | null;
  form_id: string;
  form_version: string;
  payload: Record<string, unknown>;
}

export interface MappingRelease {
  release_id: string;
  parent_release_id: string | null;
  checksum_sha256: string;
  signing_key_id: string;
  authored_by: string;
  approved_by: string;
  approved_at: string;
}

export interface PipelineRun {
  id: string;
  job_type: string;
  status: string;
  payload: Record<string, unknown>;
  attempts: number;
  maximum_attempts: number;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  last_error: string | null;
  correlation_id: string;
}

export interface QuarantineRecord {
  id: string;
  job_id: string;
  establishment_id: string;
  form_id: string;
  item_path: string | null;
  reason: string;
  status: string;
  evidence: Record<string, unknown>;
  context: Record<string, unknown>;
  created_at: string;
}

export interface DocumentEvidence {
  id: string;
  title: string;
  media_type: string;
  synthetic: boolean;
  text: string;
  model_version: string;
  confidence: number;
  candidate: Record<string, string>;
  bounding_boxes: number[][];
}

export interface ResearchRelease {
  release_id: string;
  parent_release_id: string | null;
  mapping_release_id: string;
  checksum_sha256: string;
  published_count: number;
  quarantined_count: number;
  created_at: string;
}

export interface OmopEvent {
  table: string;
  id: number;
  person_id: number;
  concept_id: number;
  date: string;
  datetime: string;
  value_as_string: string;
  source_value: string;
  research_release_id: string;
}

export interface CatalogConcept {
  concept_key: string;
  display_name: string;
  definition: string;
  vocabulary_id: string;
  concept_code: string;
  limitations: string;
  updated_at: string;
}

export interface CoverageMetric {
  establishment_id: string;
  period_start: string;
  period_end: string;
  eligible_count: number | null;
  recorded_count: number;
  usable_count: number;
  positive_count: number;
  completion: string | number | null;
  usable_coverage: string | number | null;
  prevalence: string | number | null;
  method: string;
  quality_status: string;
  research_release_id: string;
}

export interface LineageGraph {
  nodes: Array<{ id: string; label: string; kind: string; metadata?: Record<string, unknown> }>;
  edges: Array<{ source: string; target: string; relation: string }>;
}

export interface HealthStatus {
  status: string;
  version: string;
  environment: string;
  deployment_mode: string;
  demo_mode: boolean;
  time: string;
  components: Record<string, string>;
}

export interface AuditEvent {
  id: string;
  occurred_at: string;
  actor_id: string;
  action: string;
  resource_type: string;
  resource_id: string;
  correlation_id: string;
  metadata: Record<string, unknown>;
}

export interface CursorPage<T> {
  data: T[];
  next_cursor: string | null;
  total: number;
}
