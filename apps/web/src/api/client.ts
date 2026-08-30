import type {
  AuditEvent,
  CatalogConcept,
  CoverageMetric,
  CursorPage,
  DocumentEvidence,
  Establishment,
  FormVersion,
  HealthStatus,
  LineageGraph,
  MappingDraft,
  MappingRelease,
  OmopEvent,
  Persona,
  PersonaRole,
  PipelineRun,
  QuarantineRecord,
  ResearchRelease,
  SessionResponse,
  SourceSystem,
} from "./generated";

const API_ROOT = "/api/v1";
const DEMO_PERSONA_KEY = "ehrfs.demo.persona";
const PERSONA_ROLES = new Set<PersonaRole>([
  "engineer",
  "steward",
  "researcher",
  "operator",
]);

function personaStorage(): Storage | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function rememberedDemoPersona(): PersonaRole {
  const remembered = personaStorage()?.getItem(DEMO_PERSONA_KEY);
  return remembered && PERSONA_ROLES.has(remembered as PersonaRole)
    ? (remembered as PersonaRole)
    : "steward";
}

export class ApiProblem extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly correlationId: string | null,
  ) {
    super(message);
    this.name = "ApiProblem";
  }
}

let csrfToken = "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !(init.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  if (init?.method && init.method !== "GET")
    headers.set("X-CSRF-Token", csrfToken);
  const response = await fetch(`${API_ROOT}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });
  if (!response.ok) {
    const body = (await response
      .json()
      .catch(() => ({ detail: response.statusText }))) as {
      detail?: string;
      title?: string;
    };
    throw new ApiProblem(
      body.detail ?? body.title ?? "Request failed",
      response.status,
      response.headers.get("X-Correlation-ID"),
    );
  }
  return (await response.json()) as T;
}

export const api = {
  personas: () => request<Persona[]>("/session/personas"),
  openSession: async (persona: PersonaRole) => {
    const session = await request<SessionResponse>("/session", {
      method: "POST",
      body: JSON.stringify({ persona }),
    });
    csrfToken = session.csrf_token;
    personaStorage()?.setItem(DEMO_PERSONA_KEY, persona);
    return session;
  },
  establishments: () =>
    request<CursorPage<Establishment>>("/establishments?limit=200"),
  sources: () => request<SourceSystem[]>("/sources"),
  forms: () => request<FormVersion[]>("/form-versions"),
  mappings: () => request<MappingDraft[]>("/mappings"),
  mappingReleases: () => request<MappingRelease[]>("/mapping-releases"),
  approveMapping: (id: string, comment: string) =>
    request<{ release_id: string; checksum_sha256: string; verified: boolean }>(
      `/mappings/${id}/approve`,
      {
        method: "POST",
        headers: { "Idempotency-Key": `web-mapping-${id}` },
        body: JSON.stringify({ comment }),
      },
    ),
  pipelineRuns: () => request<PipelineRun[]>("/pipeline-runs"),
  createPipelineRun: (batchId: string, formVersion: string) =>
    request<{ job_id: string; status: string }>("/pipeline-runs", {
      method: "POST",
      headers: { "Idempotency-Key": `web-${batchId}-${formVersion}` },
      body: JSON.stringify({ batch_id: batchId, form_version: formVersion }),
    }),
  quarantine: () => request<QuarantineRecord[]>("/quarantine"),
  replay: (quarantineId: string, mappingReleaseId: string) =>
    request<{ job_id: string; status: string }>("/replays", {
      method: "POST",
      headers: {
        "Idempotency-Key": `web-replay-${quarantineId}-${mappingReleaseId}`,
      },
      body: JSON.stringify({
        quarantine_id: quarantineId,
        mapping_release_id: mappingReleaseId,
      }),
    }),
  documents: () => request<DocumentEvidence[]>("/documents"),
  requestOcr: () =>
    request<{ job_id: string; status: string }>("/ocr", {
      method: "POST",
      headers: { "Idempotency-Key": "web-ocr-document-482" },
    }),
  researchReleases: () => request<ResearchRelease[]>("/omop/releases"),
  omopEvents: () => request<OmopEvent[]>("/omop/events"),
  concepts: (query = "") =>
    request<CatalogConcept[]>(
      `/catalog/concepts?query=${encodeURIComponent(query)}`,
    ),
  coverage: () => request<CoverageMetric[]>("/catalog/coverage"),
  lineage: () => request<LineageGraph>("/lineage"),
  health: () => request<HealthStatus>("/health"),
  audit: () => request<AuditEvent[]>("/audit"),
};

export function resetClientForTests(): void {
  csrfToken = "";
  personaStorage()?.removeItem(DEMO_PERSONA_KEY);
}
