import { vi } from "vitest";

const formDefinition = {
  items: [
    { path: "Q1", label: "Allergie connue ?", data_type: "coding" },
    { path: "Q2", label: "Substance allergène", data_type: "string" },
  ],
};

export const responses: Record<string, unknown> = {
  "/api/v1/session": {
    actor: {
      id: "steward@demo.local",
      display_name: "Clinical Data Steward",
      role: "steward",
    },
    csrf_token: "csrf-token",
    expires_in_seconds: 28_800,
  },
  "/api/v1/session/personas": [],
  "/api/v1/establishments?limit=200": {
    data: [
      { id: "site-a", name: "Site A", region: "North", active: true },
      { id: "site-b", name: "Site B", region: "West", active: true },
      { id: "site-c", name: "Site C", region: "East", active: true },
      { id: "site-d", name: "Site D", region: "Paris", active: true },
    ],
    next_cursor: null,
    total: 4,
  },
  "/api/v1/sources": [
    {
      id: "source-1",
      establishment_id: "site-a",
      source_key: "site-a-ehr",
      family: "FHIR R4",
      version: "2026.1",
    },
  ],
  "/api/v1/form-versions": [
    {
      id: "form-v3",
      establishment_id: "site-a",
      form_id: "ATCD_ALLERGIES",
      family: "allergy-history",
      version: "3",
      title: "Antécédents allergiques",
      source_fingerprint: "a".repeat(64),
      compatibility_fingerprint: "b".repeat(64),
      mapping_status: "RELEASED",
      definition: formDefinition,
    },
    {
      id: "form-v4",
      establishment_id: "site-a",
      form_id: "ATCD_ALLERGIES",
      family: "allergy-history",
      version: "4",
      title: "Antécédents allergiques",
      source_fingerprint: "c".repeat(64),
      compatibility_fingerprint: "d".repeat(64),
      mapping_status: "REVIEW_REQUIRED",
      definition: formDefinition,
    },
  ],
  "/api/v1/mappings": [
    {
      id: "draft-1",
      status: "IN_REVIEW",
      authored_by: "engineer@demo.local",
      approved_by: null,
      form_id: "ATCD_ALLERGIES",
      form_version: "4",
      payload: {
        changed_items: ["Q1"],
        change: "Value set adds Inconnu",
        tests: ["Inconnu remains UNKNOWN"],
      },
    },
  ],
  "/api/v1/mapping-releases": [
    {
      release_id: "mapping_2026_08_v3",
      parent_release_id: null,
      checksum_sha256: "a".repeat(64),
      signing_key_id: "demo-key",
      authored_by: "engineer@demo.local",
      approved_by: "steward@demo.local",
      approved_at: "2026-08-28T12:00:00Z",
    },
  ],
  "/api/v1/pipeline-runs": [
    {
      id: "run-1",
      job_type: "pipeline.run",
      status: "SUCCEEDED",
      payload: { batch_id: "batch-v3" },
      attempts: 1,
      maximum_attempts: 3,
      created_at: "2026-08-28T12:00:00Z",
      started_at: "2026-08-28T12:00:00Z",
      finished_at: "2026-08-28T12:01:00Z",
      last_error: null,
      correlation_id: "correlation-v3",
    },
    {
      id: "run-2",
      job_type: "pipeline.run",
      status: "FAILED",
      payload: { batch_id: "batch-v4" },
      attempts: 1,
      maximum_attempts: 3,
      created_at: "2026-08-28T12:00:00Z",
      started_at: "2026-08-28T12:00:00Z",
      finished_at: "2026-08-28T12:01:00Z",
      last_error: "UNKNOWN_FORM_VERSION",
      correlation_id: "correlation-v4",
    },
  ],
  "/api/v1/quarantine": [
    {
      id: "quarantine-1",
      job_id: "run-2",
      establishment_id: "site-a",
      form_id: "ATCD_ALLERGIES",
      item_path: "Q1",
      reason: "UNKNOWN_FORM_VERSION",
      status: "OPEN",
      evidence: { object_key: "raw/response.json", checksum: "8f3c" },
      context: { version: "4", changed_value: "Inconnu" },
      created_at: "2026-08-28T12:00:00Z",
    },
  ],
  "/api/v1/documents": [
    {
      id: "document-482",
      title: "Synthetic allergy scan",
      media_type: "image/png",
      synthetic: true,
      text: "Allergie à la pénicilline avec urticaire.",
      model_version: "paddleocr-golden/1.0",
      confidence: 0.97,
      candidate: {
        substance: "Penicillin",
        reaction: "Urticaria",
        assertion: "PRESENT",
        status: "EVIDENCE_LINKED_CANDIDATE",
      },
      bounding_boxes: [[54, 96, 612, 142]],
    },
  ],
  "/api/v1/omop/releases": [
    {
      release_id: "release_2026_08",
      parent_release_id: null,
      mapping_release_id: "mapping_2026_08_v3",
      checksum_sha256: "d".repeat(64),
      published_count: 842,
      quarantined_count: 37,
      created_at: "2026-08-28T12:00:00Z",
    },
  ],
  "/api/v1/omop/events": [
    {
      table: "observation",
      id: 1,
      person_id: 1,
      concept_id: 2000001,
      date: "2026-08-12",
      datetime: "2026-08-12T09:30:00Z",
      value_as_string: "EXPLICITLY_ABSENT",
      source_value: "Q1=Non",
      research_release_id: "release_2026_08",
    },
  ],
  "/api/v1/catalog/concepts?query=": [
    {
      concept_key: "allergy-history",
      display_name: "Allergy history",
      definition: "Known or explicitly absent allergy history.",
      vocabulary_id: "EHRFS_DEMO",
      concept_code: "DEMO-NKDA",
      limitations: "Synthetic demonstration.",
      updated_at: "2026-08-28T12:00:00Z",
    },
  ],
  "/api/v1/catalog/coverage": [
    {
      establishment_id: "site-a",
      period_start: "2026-01-01",
      period_end: "2026-08-31",
      eligible_count: 1000,
      recorded_count: 870,
      usable_count: 840,
      positive_count: 210,
      completion: 0.87,
      usable_coverage: 0.84,
      prevalence: 0.25,
      method: "Structured form",
      quality_status: "VALIDATED",
      research_release_id: "release_2026_08",
    },
    {
      establishment_id: "site-b",
      period_start: "2026-01-01",
      period_end: "2026-08-31",
      eligible_count: null,
      recorded_count: 431,
      usable_count: 392,
      positive_count: 88,
      completion: null,
      usable_coverage: null,
      prevalence: 0.224,
      method: "CDA rules",
      quality_status: "LIMITED",
      research_release_id: "release_2026_08",
    },
    {
      establishment_id: "site-c",
      period_start: "2026-01-01",
      period_end: "2026-08-31",
      eligible_count: 700,
      recorded_count: 0,
      usable_count: 0,
      positive_count: 0,
      completion: 0,
      usable_coverage: 0,
      prevalence: null,
      method: "No mapped source",
      quality_status: "ABSENT",
      research_release_id: "release_2026_08",
    },
  ],
  "/api/v1/lineage": {
    nodes: [
      { id: "raw:1", kind: "raw", label: "response.json" },
      { id: "canonical:1", kind: "canonical", label: "Q1 explicitly absent" },
      { id: "omop:1", kind: "omop", label: "Observation 1" },
    ],
    edges: [
      { source: "raw:1", target: "canonical:1", relation: "canonicalized_as" },
      { source: "canonical:1", target: "omop:1", relation: "published_as" },
    ],
  },
  "/api/v1/health": {
    status: "healthy",
    version: "0.1.0",
    environment: "test",
    deployment_mode: "central",
    demo_mode: true,
    time: "2026-08-28T12:00:00Z",
    components: {
      api: "ready",
      database: "ready",
      object_store: "configured",
      worker: "lease-backed",
      ocr: "optional-profile",
      scheduler: "optional",
    },
  },
  "/api/v1/audit": [
    {
      id: "audit-1",
      occurred_at: "2026-08-28T12:00:00Z",
      actor_id: "steward@demo.local",
      action: "mapping.release.approved",
      resource_type: "mapping_release",
      resource_id: "mapping-v3",
      correlation_id: "correlation-audit",
      metadata: { synthetic: true },
    },
  ],
};

export function installFetchMock(
  overrides: Record<string, unknown> = {},
  failingPath?: string,
): ReturnType<typeof vi.fn> {
  const fetchMock = vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
    const raw =
      typeof input === "string"
        ? input
        : input instanceof URL
          ? input.pathname + input.search
          : input.url;
    const url = new URL(raw, "http://localhost");
    if (url.pathname === failingPath) {
      return Response.json(
        { title: "Synthetic failure", detail: "Injected API failure" },
        { status: 503 },
      );
    }
    if (init?.method === "POST" && url.pathname === "/api/v1/session") {
      if (typeof init.body !== "string")
        throw new TypeError("Expected a JSON request body");
      const payload = JSON.parse(init.body) as { persona: string };
      const labels: Record<string, string> = {
        engineer: "Data Engineer",
        steward: "Clinical Data Steward",
        researcher: "Researcher",
        operator: "Platform Operator",
      };
      return Response.json({
        actor: {
          id: `${payload.persona}@demo.local`,
          display_name: labels[payload.persona],
          role: payload.persona,
        },
        csrf_token: `csrf-${payload.persona}`,
        expires_in_seconds: 28_800,
      });
    }
    if (init?.method === "POST" && url.pathname.includes("/mappings/")) {
      return Response.json({
        release_id: "mapping-v4-signed",
        checksum_sha256: "e".repeat(64),
        verified: true,
      });
    }
    if (init?.method === "POST" && url.pathname === "/api/v1/ocr") {
      return Response.json({ job_id: "ocr-job-1", status: "QUEUED" });
    }
    if (init?.method === "POST" && url.pathname === "/api/v1/replays") {
      return Response.json({ job_id: "replay-job-1", status: "QUEUED" });
    }
    if (init?.method === "POST" && url.pathname === "/api/v1/pipeline-runs") {
      return Response.json({ job_id: "run-job-1", status: "QUEUED" });
    }
    const key = `${url.pathname}${url.search}`;
    const value =
      overrides[key] ??
      overrides[url.pathname] ??
      responses[key] ??
      (url.pathname === "/api/v1/catalog/concepts"
        ? responses["/api/v1/catalog/concepts?query="]
        : responses[url.pathname]);
    if (value === undefined)
      return Response.json({ detail: `No mock for ${key}` }, { status: 404 });
    return Response.json(value, {
      headers: { "X-Correlation-ID": "test-correlation" },
    });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}
