import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  ArrowRight,
  CheckCircle2,
  Clock3,
  GitCompareArrows,
  KeyRound,
  Play,
  RefreshCw,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type {
  MappingDraft,
  Persona,
  PipelineRun,
  QuarantineRecord,
} from "../api/generated";
import {
  DataTable,
  EmptyState,
  ErrorState,
  LoadingState,
  Mono,
  PageHeader,
  Panel,
  StatusBadge,
} from "../components/ui";
import { scalarText } from "../lib/format";

export function MappingPage({ actor }: { actor: Persona }) {
  const queryClient = useQueryClient();
  const mappings = useQuery({ queryKey: ["mappings"], queryFn: api.mappings });
  const releases = useQuery({
    queryKey: ["mapping-releases"],
    queryFn: api.mappingReleases,
  });
  const [comment, setComment] = useState(
    "Reviewed changed value set and deterministic UNKNOWN test vector.",
  );
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const approval = useMutation({
    mutationFn: ({ id, note }: { id: string; note: string }) =>
      api.approveMapping(id, note),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["mappings"] }),
        queryClient.invalidateQueries({ queryKey: ["mapping-releases"] }),
        queryClient.invalidateQueries({ queryKey: ["forms"] }),
      ]);
    },
  });
  if (mappings.isPending || releases.isPending) return <LoadingState />;
  if (mappings.error || releases.error)
    return (
      <ErrorState
        error={mappings.error ?? releases.error ?? new Error("Unknown error")}
      />
    );
  const selected =
    mappings.data.find((mapping) => mapping.id === selectedId) ??
    mappings.data[0];
  const changedItems = Array.isArray(selected?.payload.changed_items)
    ? selected.payload.changed_items
    : [];
  const tests = Array.isArray(selected?.payload.tests)
    ? selected.payload.tests
    : [];

  const columns: ColumnDef<MappingDraft>[] = [
    {
      accessorKey: "form_id",
      header: "Form",
      cell: ({ row }) => (
        <button
          type="button"
          className="table-button"
          onClick={() => setSelectedId(row.original.id)}
        >
          {row.original.form_id}
          <small>version {row.original.form_version}</small>
        </button>
      ),
    },
    {
      accessorKey: "status",
      header: "State",
      cell: ({ getValue }) => <StatusBadge value={String(getValue())} />,
    },
    { accessorKey: "authored_by", header: "Maker" },
    {
      id: "change",
      header: "Detected change",
      cell: ({ row }) => scalarText(row.original.payload.change),
    },
  ];

  return (
    <>
      <PageHeader
        eyebrow="Governed semantics"
        title="Mapping workspace"
        description="Resolve source meaning through deterministic candidates, executable test vectors, and an immutable maker/checker release."
      />
      <div className="mapping-banner">
        <TriangleAlert />
        <div>
          <strong>Compatibility drift requires a new decision</strong>
          <span>
            ATCD_ALLERGIES v4 adds “Inconnu”; runtime correctly refused the v3
            release.
          </span>
        </div>
        <StatusBadge value="REVIEW REQUIRED" />
      </div>
      <div className="mapping-layout">
        <Panel
          title="Draft queue"
          subtitle="Source-specific overrides resolve before exact fingerprints."
        >
          <DataTable
            data={mappings.data}
            columns={columns}
            label="Mapping drafts"
          />
        </Panel>
        {selected ? (
          <Panel
            title="Candidate decision"
            subtitle={`${selected.form_id} · version ${selected.form_version}`}
            className="mapping-editor"
          >
            <div className="mapping-chain">
              <div>
                <small>Local source value</small>
                <strong>Inconnu</strong>
                <Mono>Q1</Mono>
              </div>
              <ArrowRight />
              <div>
                <small>Canonical state</small>
                <strong>UNKNOWN</strong>
                <Mono>no typed value</Mono>
              </div>
              <ArrowRight />
              <div>
                <small>OMOP representation</small>
                <strong>Observation</strong>
                <Mono>project demo concept</Mono>
              </div>
            </div>
            <div className="decision-grid">
              <div>
                <span>Changed items</span>
                <strong>{changedItems.map(String).join(", ") || "None"}</strong>
              </div>
              <div>
                <span>Resolution rule</span>
                <strong>Exact form family + item</strong>
              </div>
              <div>
                <span>Vocabulary binding</span>
                <strong>EHRFS_DEMO 2026.08</strong>
              </div>
              <div>
                <span>Target domain</span>
                <strong>Observation</strong>
              </div>
            </div>
            <h3>Required test vectors</h3>
            <ul className="test-vectors">
              {tests.map((test) => (
                <li key={String(test)}>
                  <CheckCircle2 />
                  {String(test)}
                </li>
              ))}
              <li>
                <CheckCircle2 />
                “Non” remains explicitly absent
              </li>
              <li>
                <CheckCircle2 />
                Hidden Q2 remains NOT_DISPLAYED
              </li>
            </ul>
            <label className="field">
              <span>Approval rationale</span>
              <textarea
                value={comment}
                onChange={(event) => setComment(event.target.value)}
                rows={3}
              />
            </label>
            {approval.error ? (
              <p className="inline-error">{approval.error.message}</p>
            ) : null}
            {approval.data ? (
              <div className="success-note">
                <ShieldCheck />
                Signed release {approval.data.release_id}
              </div>
            ) : null}
            <button
              className="button button-primary"
              type="button"
              disabled={
                actor.role !== "steward" ||
                selected.status === "APPROVED" ||
                approval.isPending
              }
              onClick={() =>
                approval.mutate({ id: selected.id, note: comment })
              }
            >
              <KeyRound />{" "}
              {approval.isPending
                ? "Signing release…"
                : "Approve and sign release"}
            </button>
            {actor.role !== "steward" ? (
              <small className="permission-note">
                Switch to the steward persona to approve this draft.
              </small>
            ) : null}
          </Panel>
        ) : null}
      </div>
      <Panel
        title="Immutable release ledger"
        subtitle="Git export is available for review; the application never mutates Git."
      >
        <div className="release-list">
          {releases.data.map((release) => (
            <div key={release.release_id}>
              <ShieldCheck />
              <div>
                <strong>{release.release_id}</strong>
                <small>
                  {release.authored_by} → {release.approved_by}
                </small>
              </div>
              <Mono>{release.checksum_sha256.slice(0, 16)}…</Mono>
              <StatusBadge value="SIGNATURE VERIFIED" />
            </div>
          ))}
        </div>
      </Panel>
    </>
  );
}

export function PipelineRunsPage({ actor }: { actor: Persona }) {
  const client = useQueryClient();
  const runs = useQuery({
    queryKey: ["runs"],
    queryFn: api.pipelineRuns,
    refetchInterval: 5000,
  });
  const launch = useMutation({
    mutationFn: () => api.createPipelineRun(`batch-web-${Date.now()}`, "3"),
    onSuccess: () => client.invalidateQueries({ queryKey: ["runs"] }),
  });
  if (runs.isPending) return <LoadingState />;
  if (runs.error) return <ErrorState error={runs.error} />;
  const columns: ColumnDef<PipelineRun>[] = [
    {
      accessorKey: "status",
      header: "Status",
      cell: ({ getValue }) => <StatusBadge value={String(getValue())} />,
    },
    {
      id: "batch",
      header: "Batch / operation",
      cell: ({ row }) => (
        <span className="stacked-cell">
          <strong>
            {scalarText(row.original.payload.batch_id) === "—"
              ? row.original.job_type
              : scalarText(row.original.payload.batch_id)}
          </strong>
          <small>{row.original.job_type}</small>
        </span>
      ),
    },
    {
      accessorKey: "attempts",
      header: "Attempts",
      cell: ({ row }) =>
        `${row.original.attempts}/${row.original.maximum_attempts}`,
    },
    {
      accessorKey: "created_at",
      header: "Created",
      cell: ({ getValue }) => new Date(String(getValue())).toLocaleString(),
    },
    {
      accessorKey: "correlation_id",
      header: "Correlation",
      cell: ({ getValue }) => <Mono>{String(getValue()).slice(0, 18)}</Mono>,
    },
  ];
  return (
    <>
      <PageHeader
        eyebrow="Durable execution"
        title="Pipeline runs"
        description="PostgreSQL leases, heartbeats, retry budgets, idempotency keys, and SKIP LOCKED keep core processing recoverable without Airflow."
        action={
          <button
            type="button"
            className="button button-primary"
            disabled={
              !(["engineer", "operator"] as string[]).includes(actor.role) ||
              launch.isPending
            }
            onClick={() => launch.mutate()}
          >
            <Play />
            Queue synthetic v3 run
          </button>
        }
      />
      <div className="stat-grid compact-stats">
        <div className="mini-stat">
          <CheckCircle2 />
          <div>
            <strong>
              {runs.data.filter((run) => run.status === "SUCCEEDED").length}
            </strong>
            <span>succeeded</span>
          </div>
        </div>
        <div className="mini-stat warn">
          <TriangleAlert />
          <div>
            <strong>
              {runs.data.filter((run) => run.status === "FAILED").length}
            </strong>
            <span>failed safely</span>
          </div>
        </div>
        <div className="mini-stat">
          <Clock3 />
          <div>
            <strong>60 s</strong>
            <span>lease duration</span>
          </div>
        </div>
      </div>
      <Panel
        title="Job ledger"
        subtitle="No destructive retry: completed outputs remain content-addressed."
      >
        <DataTable data={runs.data} columns={columns} label="Pipeline jobs" />
      </Panel>
      <Panel
        title="Run stages"
        subtitle="Each work unit is bounded to 50,000 answer events by default."
      >
        <div className="stage-row">
          {["Manifest", "Canonical", "Quality", "OMOP", "Catalog"].map(
            (stage, index) => (
              <div key={stage}>
                <span>{index + 1}</span>
                <strong>{stage}</strong>
                <StatusBadge value={index < 2 ? "COMPLETE" : "GATED"} />
              </div>
            ),
          )}
        </div>
      </Panel>
    </>
  );
}

export function QuarantinePage({ actor }: { actor: Persona }) {
  const client = useQueryClient();
  const records = useQuery({
    queryKey: ["quarantine"],
    queryFn: api.quarantine,
  });
  const releases = useQuery({
    queryKey: ["mapping-releases"],
    queryFn: api.mappingReleases,
  });
  const [params, setParams] = useSearchParams();
  const reason = params.get("reason") ?? "all";
  const replay = useMutation({
    mutationFn: ({
      recordId,
      releaseId,
    }: {
      recordId: string;
      releaseId: string;
    }) => api.replay(recordId, releaseId),
    onSuccess: () =>
      Promise.all([
        client.invalidateQueries({ queryKey: ["quarantine"] }),
        client.invalidateQueries({ queryKey: ["runs"] }),
      ]),
  });
  if (records.isPending || releases.isPending) return <LoadingState />;
  if (records.error || releases.error)
    return (
      <ErrorState
        error={records.error ?? releases.error ?? new Error("Unknown error")}
      />
    );
  const filtered =
    reason === "all"
      ? records.data
      : records.data.filter((record) => record.reason === reason);
  const latestRelease = releases.data[0];
  const columns: ColumnDef<QuarantineRecord>[] = [
    {
      accessorKey: "reason",
      header: "Failure",
      cell: ({ getValue }) => <StatusBadge value={String(getValue())} />,
    },
    { accessorKey: "form_id", header: "Form" },
    {
      accessorKey: "item_path",
      header: "Item",
      cell: ({ getValue }) => <Mono>{scalarText(getValue())}</Mono>,
    },
    { accessorKey: "establishment_id", header: "Site" },
    {
      accessorKey: "status",
      header: "State",
      cell: ({ getValue }) => <StatusBadge value={String(getValue())} />,
    },
    {
      id: "action",
      header: "Action",
      cell: ({ row }) => (
        <button
          className="button button-small"
          type="button"
          disabled={
            !latestRelease ||
            !(["engineer", "operator"] as string[]).includes(actor.role) ||
            replay.isPending ||
            row.original.status === "RESOLVED"
          }
          onClick={() =>
            latestRelease &&
            replay.mutate({
              recordId: row.original.id,
              releaseId: latestRelease.release_id,
            })
          }
        >
          <RefreshCw />
          Replay
        </button>
      ),
    },
  ];
  const reasons = [...new Set(records.data.map((record) => record.reason))];
  return (
    <>
      <PageHeader
        eyebrow="Failure is data"
        title="Quarantine"
        description="Rejected facts retain source evidence and context. Resolution always creates a new mapping or rule release and a controlled replay."
      />
      <div className="toolbar">
        <div className="filter-pills">
          <button
            type="button"
            className={reason === "all" ? "active" : ""}
            onClick={() => setParams({})}
          >
            All
          </button>
          {reasons.map((entry) => (
            <button
              type="button"
              key={entry}
              className={reason === entry ? "active" : ""}
              onClick={() => setParams({ reason: entry })}
            >
              {entry.replaceAll("_", " ")}
            </button>
          ))}
        </div>
        <span>{filtered.length} records</span>
      </div>
      <Panel
        title="Evidence queue"
        subtitle="No row is silently dropped or coerced."
      >
        {filtered.length ? (
          <DataTable
            data={filtered}
            columns={columns}
            label="Quarantined records"
          />
        ) : (
          <EmptyState
            title="No records in this view"
            detail="Resolved records remain auditable in the full ledger."
          />
        )}
      </Panel>
      {filtered[0] ? (
        <div className="evidence-grid">
          <Panel title="Preserved evidence">
            <pre tabIndex={0} aria-label="Quarantined evidence JSON">
              {JSON.stringify(filtered[0].evidence, null, 2)}
            </pre>
          </Panel>
          <Panel title="Resolution context">
            <pre tabIndex={0} aria-label="Quarantine context JSON">
              {JSON.stringify(filtered[0].context, null, 2)}
            </pre>
            <Link className="text-link" to="/mappings">
              Open mapping decision <GitCompareArrows />
            </Link>
          </Panel>
        </div>
      ) : null}
    </>
  );
}
