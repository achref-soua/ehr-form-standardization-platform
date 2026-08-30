import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { vi } from "vitest";

import { App } from "./App";
import { installFetchMock, responses } from "./test/mockApi";

function renderApp(route: string) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[route]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("workspace routing", () => {
  const routes = [
    ["/", "Standardization command center"],
    ["/sources", "Source explorer"],
    ["/forms", "Form registry"],
    ["/forms/form-v4", "Form registry"],
    ["/mappings", "Mapping workspace"],
    ["/runs", "Pipeline runs"],
    ["/quarantine", "Quarantine"],
    ["/documents", "Document lab"],
    ["/omop", "OMOP explorer"],
    ["/catalog", "Research catalog"],
    ["/lineage", "Lineage view"],
    ["/health", "System health"],
  ] as const;

  it.each(routes)("renders %s with backend state", async (route, heading) => {
    installFetchMock();
    renderApp(route);
    expect(
      await screen.findByRole("heading", { level: 1, name: heading }),
    ).toBeVisible();
    expect(screen.getByText("Bounded demonstration")).toBeVisible();
  });

  it("approves a reviewed mapping with the steward persona", async () => {
    const fetchMock = installFetchMock();
    const user = userEvent.setup();
    renderApp("/mappings");
    await user.click(
      await screen.findByRole("button", { name: "Approve and sign release" }),
    );
    expect(
      await screen.findByText(/Signed release mapping-v4-signed/),
    ).toBeVisible();
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/mappings/draft-1/approve",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("queues local OCR while preserving candidate status", async () => {
    installFetchMock();
    const user = userEvent.setup();
    renderApp("/documents");
    await user.click(
      await screen.findByRole("button", { name: "Run local OCR" }),
    );
    expect(await screen.findByText(/OCR job queued/)).toBeVisible();
    expect(screen.getByText(/candidate, not a published fact/i)).toBeVisible();
  });

  it("switches persona and queues an operator pipeline run", async () => {
    const fetchMock = installFetchMock();
    const user = userEvent.setup();
    renderApp("/runs");
    await user.click(
      await screen.findByRole("button", { name: /Clinical Data Steward/i }),
    );
    await user.click(
      await screen.findByRole("menuitem", { name: /Operator/i }),
    );
    expect(await screen.findByText("Platform Operator")).toBeVisible();
    await user.click(
      screen.getByRole("button", { name: "Queue synthetic v3 run" }),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/pipeline-runs",
      expect.objectContaining({ method: "POST" }),
    );
  });

  it("filters quarantine evidence and navigates with the responsive menu", async () => {
    installFetchMock();
    const user = userEvent.setup();
    renderApp("/quarantine");
    await user.click(
      await screen.findByRole("button", { name: "UNKNOWN FORM VERSION" }),
    );
    expect(screen.getByText("Preserved evidence")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Open navigation" }));
    expect(
      screen.getAllByRole("button", { name: "Close navigation" })[0],
    ).toBeVisible();
    await user.click(screen.getByRole("link", { name: "Form registry" }));
    expect(
      await screen.findByRole("heading", { name: "Form registry" }),
    ).toBeVisible();
  });

  it("persists form and catalog search terms in their respective controls", async () => {
    installFetchMock();
    const user = userEvent.setup();
    const view = renderApp("/forms");
    const formSearch = await screen.findByPlaceholderText(
      "Search form or identifier",
    );
    await user.type(formSearch, "no-match");
    expect(screen.queryByText("ATCD_ALLERGIES")).not.toBeInTheDocument();
    view.unmount();
    renderApp("/catalog");
    const catalogSearch = await screen.findByPlaceholderText(
      "Search a research concept",
    );
    await user.type(catalogSearch, "allergy");
    expect(await screen.findByText("Allergy history")).toBeVisible();
  });

  it("separates the live release count from measured scale evidence", async () => {
    installFetchMock();
    renderApp("/");
    expect(await screen.findByText("842")).toBeVisible();
    expect(screen.getByText("release_2026_08")).toBeVisible();
    expect(screen.getByText("100,000,000")).toBeVisible();
    expect(screen.getByText(/not an end-to-end API/i)).toBeVisible();
    expect(screen.queryByText("18,420")).not.toBeInTheDocument();
  });

  it("reports an empty live release without inventing publication", async () => {
    installFetchMock({ "/api/v1/omop/releases": [] });
    renderApp("/");
    expect(await screen.findByText("No research release")).toBeVisible();
  });

  it("renders a recoverable boot error when the API is unavailable", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("API unavailable")),
    );
    renderApp("/");
    expect(
      await screen.findByText(
        "Data could not be loaded",
        {},
        { timeout: 4000 },
      ),
    ).toBeVisible();
    expect(screen.getByText("API unavailable")).toBeVisible();
  });

  it("redirects unknown stable URLs to the command center", async () => {
    installFetchMock();
    renderApp("/not-a-workspace");
    expect(
      await screen.findByRole("heading", {
        name: "Standardization command center",
      }),
    ).toBeVisible();
  });

  it.each([
    ["/", "/api/v1/catalog/coverage"],
    ["/sources", "/api/v1/sources"],
    ["/forms", "/api/v1/form-versions"],
    ["/mappings", "/api/v1/mappings"],
    ["/runs", "/api/v1/pipeline-runs"],
    ["/quarantine", "/api/v1/quarantine"],
    ["/documents", "/api/v1/documents"],
    ["/omop", "/api/v1/omop/events"],
    ["/catalog", "/api/v1/catalog/concepts"],
    ["/lineage", "/api/v1/lineage"],
    ["/health", "/api/v1/audit"],
  ])("renders an explicit error state for %s", async (route, failingPath) => {
    installFetchMock({}, failingPath);
    renderApp(route);
    expect(await screen.findByText("Injected API failure")).toBeVisible();
  });

  it.each([
    ["/", "/api/v1/omop/releases"],
    ["/sources", "/api/v1/establishments"],
    ["/mappings", "/api/v1/mapping-releases"],
    ["/quarantine", "/api/v1/mapping-releases"],
    ["/omop", "/api/v1/omop/releases"],
    ["/catalog", "/api/v1/catalog/coverage"],
    ["/health", "/api/v1/health"],
  ])(
    "reports failures from the secondary query on %s",
    async (route, failingPath) => {
      installFetchMock({}, failingPath);
      renderApp(route);
      expect(await screen.findByText("Injected API failure")).toBeVisible();
    },
  );

  it("renders honest empty states for missing forms, mappings, documents, and quarantine", async () => {
    installFetchMock({ "/api/v1/form-versions": [] });
    const forms = renderApp("/forms");
    expect(
      await screen.findByRole("heading", { name: "Form registry" }),
    ).toBeVisible();
    expect(screen.queryByText("Definition items")).not.toBeInTheDocument();
    forms.unmount();

    installFetchMock({ "/api/v1/mappings": [] });
    const mappings = renderApp("/mappings");
    expect(
      await screen.findByRole("heading", { name: "Mapping workspace" }),
    ).toBeVisible();
    expect(screen.queryByText("Candidate decision")).not.toBeInTheDocument();
    mappings.unmount();

    installFetchMock({ "/api/v1/quarantine": [] });
    const quarantine = renderApp("/quarantine");
    expect(await screen.findByText("No records in this view")).toBeVisible();
    quarantine.unmount();

    installFetchMock({ "/api/v1/documents": [] });
    renderApp("/documents");
    await screen.findByText("Clinical Data Steward");
    expect(
      screen.queryByRole("heading", { name: "Document lab" }),
    ).not.toBeInTheDocument();
  });

  it("renders alternate optional source values without coercion", async () => {
    installFetchMock({
      "/api/v1/pipeline-runs": [
        {
          id: "run-no-batch",
          job_type: "pipeline.replay",
          status: "QUEUED",
          payload: {},
          attempts: 0,
          maximum_attempts: 3,
          created_at: "2026-08-28T12:00:00Z",
          started_at: null,
          finished_at: null,
          last_error: null,
          correlation_id: "fallback-run",
        },
      ],
    });
    const runs = renderApp("/runs");
    expect((await screen.findAllByText("pipeline.replay"))[0]).toBeVisible();
    runs.unmount();

    installFetchMock({
      "/api/v1/mappings": [
        {
          id: "draft-empty",
          status: "APPROVED",
          authored_by: "engineer@demo.local",
          approved_by: "steward@demo.local",
          form_id: "EMPTY_MAPPING",
          form_version: "1",
          payload: { changed_items: "not-an-array", tests: null },
        },
      ],
    });
    renderApp("/mappings");
    expect(await screen.findByText("None")).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Approve and sign release" }),
    ).toBeDisabled();
  });

  it("renders missing OCR assertion and disabled demo authentication explicitly", async () => {
    const documents = responses["/api/v1/documents"] as Array<
      Record<string, unknown>
    >;
    installFetchMock({
      "/api/v1/documents": [
        {
          ...documents[0],
          candidate: { substance: "Penicillin", reaction: "Urticaria" },
        },
      ],
    });
    const view = renderApp("/documents");
    expect(await screen.findByText("UNKNOWN")).toBeVisible();
    view.unmount();

    const health = responses["/api/v1/health"] as Record<string, unknown>;
    installFetchMock({ "/api/v1/health": { ...health, demo_mode: false } });
    renderApp("/health");
    expect(await screen.findByText("DISABLED")).toBeVisible();
  });
});
