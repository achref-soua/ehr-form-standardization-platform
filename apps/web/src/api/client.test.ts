import { beforeEach, describe, expect, it, vi } from "vitest";

import { api, rememberedDemoPersona, resetClientForTests } from "./client";
import type { ApiProblem } from "./client";

describe("API client", () => {
  beforeEach(() => resetClientForTests());

  it("defaults invalid remembered demo personas to the steward", () => {
    expect(rememberedDemoPersona()).toBe("steward");
    localStorage.setItem("ehrfs.demo.persona", "administrator");
    expect(rememberedDemoPersona()).toBe("steward");
  });

  it("carries the CSRF token and idempotency key on mutations", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        Response.json({
          actor: { id: "operator", display_name: "Operator", role: "operator" },
          csrf_token: "csrf-123",
          expires_in_seconds: 100,
        }),
      )
      .mockResolvedValueOnce(
        Response.json({ job_id: "job-1", status: "QUEUED" }),
      );
    vi.stubGlobal("fetch", fetchMock);

    await api.openSession("operator");
    expect(rememberedDemoPersona()).toBe("operator");
    await api.createPipelineRun("batch-1", "3");

    const init = fetchMock.mock.calls[1]?.[1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("X-CSRF-Token")).toBe("csrf-123");
    expect(headers.get("Idempotency-Key")).toBe("web-batch-1-3");
  });

  it("turns RFC problem responses into a typed error", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          Response.json(
            { title: "Access Denied", detail: "Insufficient role" },
            { status: 403, headers: { "X-Correlation-ID": "correlation-403" } },
          ),
        ),
    );

    await expect(api.audit()).rejects.toEqual(
      expect.objectContaining<ApiProblem>({
        name: "ApiProblem",
        status: 403,
        message: "Insufficient role",
        correlationId: "correlation-403",
      }),
    );
  });

  it.each([
    [{ title: "Only title" }, "Only title"],
    [{}, "Request failed"],
  ])("falls back through problem titles", async (body, message) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(Response.json(body, { status: 500 })),
    );
    await expect(api.health()).rejects.toMatchObject({ message });
  });

  it("uses the HTTP status text when an error body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response("not-json", { status: 502, statusText: "Bad Gateway" }),
        ),
    );
    await expect(api.health()).rejects.toMatchObject({
      message: "Bad Gateway",
    });
  });
});
