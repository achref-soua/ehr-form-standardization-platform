import { render, screen } from "@testing-library/react";
import type { ColumnDef } from "@tanstack/react-table";
import { describe, expect, it } from "vitest";

import {
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  Mono,
  PageHeader,
  Panel,
  Percent,
  Stat,
  StatusBadge,
} from "./ui";

describe("shared presentation contracts", () => {
  it("renders headers, panels, and statistics with optional content", () => {
    render(
      <>
        <PageHeader
          eyebrow="Evidence"
          title="Title"
          description="Description"
          action={<button>Act</button>}
        />
        <PageHeader eyebrow="Evidence" title="Second" description="No action" />
        <Panel title="Panel" subtitle="Subtitle">
          <span>Body</span>
        </Panel>
        <Panel>
          <span>Bare panel</span>
        </Panel>
        <Stat label="Metric" value={42} detail="Detail" tone="good" />
      </>,
    );
    expect(screen.getByRole("button", { name: "Act" })).toBeVisible();
    expect(screen.getByText("Bare panel")).toBeVisible();
    expect(screen.getByText("42")).toBeVisible();
  });

  it("classifies statuses and renders every state primitive", () => {
    render(
      <>
        <StatusBadge value="SUCCEEDED" />
        <StatusBadge value="REVIEW_REQUIRED" />
        <StatusBadge value="QUEUED" />
        <LoadingState />
        <ErrorState error={new Error("offline")} />
        <EmptyState title="Nothing here" detail="The view is empty" />
        <Mono>abc</Mono>
        <Percent value={0.843} />
        <Percent value={null} />
      </>,
    );
    expect(screen.getByText("SUCCEEDED")).toHaveClass("badge-good");
    expect(screen.getByText("REVIEW REQUIRED")).toHaveClass("badge-warn");
    expect(screen.getByText("QUEUED")).toHaveClass("badge-neutral");
    expect(screen.getByText("offline")).toBeVisible();
    expect(screen.getByText("84%")).toBeVisible();
    expect(screen.getByText("—")).toBeVisible();
  });

  it("renders a typed TanStack table", () => {
    type Row = { id: string; value: number };
    const columns: ColumnDef<Row>[] = [
      { accessorKey: "id", header: "Identifier" },
      { accessorKey: "value", header: "Value" },
    ];
    render(
      <DataTable
        data={[{ id: "row-a", value: 7 }]}
        columns={columns}
        label="Example rows"
      />,
    );
    expect(screen.getByRole("table", { name: "Example rows" })).toBeVisible();
    expect(screen.getByText("row-a")).toBeVisible();
  });

  it("supports grouped headers with placeholders", () => {
    type Row = { first: string; second: string };
    const columns: ColumnDef<Row>[] = [
      {
        header: "Group",
        columns: [
          { accessorKey: "first", header: "First" },
          { accessorKey: "second", header: "Second" },
        ],
      },
    ];
    render(
      <DataTable
        data={[{ first: "A", second: "B" }]}
        columns={columns}
        label="Grouped rows"
      />,
    );
    expect(screen.getByRole("columnheader", { name: "Group" })).toBeVisible();
  });
});
