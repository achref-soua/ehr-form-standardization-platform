import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import {
  Background,
  Controls,
  MarkerType,
  ReactFlow,
  type Edge,
  type Node,
} from "@xyflow/react";
import {
  Box,
  CheckCircle2,
  Cpu,
  FileSearch,
  Fingerprint,
  HardDrive,
  Info,
  ScanText,
  Server,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import "@xyflow/react/dist/style.css";
import { api } from "../api/client";
import type {
  CatalogConcept,
  OmopEvent,
  Persona,
  ResearchRelease,
} from "../api/generated";
import {
  DataTable,
  ErrorState,
  LoadingState,
  Mono,
  PageHeader,
  Panel,
  Percent,
  StatusBadge,
} from "../components/ui";

export function DocumentLabPage({ actor }: { actor: Persona }) {
  const client = useQueryClient();
  const documents = useQuery({
    queryKey: ["documents"],
    queryFn: api.documents,
  });
  const ocr = useMutation({
    mutationFn: api.requestOcr,
    onSuccess: () => client.invalidateQueries({ queryKey: ["runs"] }),
  });
  if (documents.isPending) return <LoadingState />;
  if (documents.error) return <ErrorState error={documents.error} />;
  const document = documents.data[0];
  if (!document) return null;
  return (
    <>
      <PageHeader
        eyebrow="Local evidence extraction"
        title="Document lab"
        description="Native text is preferred. OCR runs locally only for relevant image-only documents and candidates remain evidence-linked until reviewed."
        action={
          <button
            type="button"
            className="button button-primary"
            disabled={
              !(["engineer", "steward"] as string[]).includes(actor.role) ||
              ocr.isPending
            }
            onClick={() => ocr.mutate()}
          >
            <ScanText />
            {ocr.isPending ? "Queueing…" : "Run local OCR"}
          </button>
        }
      />
      <div className="document-layout">
        <Panel
          title={document.title}
          subtitle="Committed golden evidence · no model download required"
        >
          <div
            className="document-canvas"
            aria-label="Synthetic French allergy form with detected evidence box"
          >
            <div className="paper-sheet">
              <div className="paper-brand">
                <span>CH DÉMONSTRATION</span>
                <small>DOCUMENT SYNTHÉTIQUE</small>
              </div>
              <h3>FICHE D’ALLERGIES</h3>
              <p>
                Nom : <span className="redacted">PERSONNE SYNTHÉTIQUE</span>
              </p>
              <p>Date : 12 / 08 / 2026</p>
              <div className="ocr-box">
                <span>Allergie à la pénicilline avec urticaire.</span>
                <small>0.97</small>
              </div>
              <p>Observations complémentaires :</p>
              <div className="paper-lines" />
              <div className="signature-box">
                Emplacement signature — aucun paraphe réel
              </div>
            </div>
          </div>
        </Panel>
        <Panel
          title="Extraction evidence"
          subtitle={`${document.model_version} · local profile`}
          className="ocr-evidence"
        >
          <div className="confidence-ring">
            <strong>{Math.round(document.confidence * 100)}%</strong>
            <span>OCR confidence</span>
          </div>
          <dl className="detail-list">
            <div>
              <dt>Substance</dt>
              <dd>{document.candidate.substance}</dd>
            </div>
            <div>
              <dt>Reaction</dt>
              <dd>{document.candidate.reaction}</dd>
            </div>
            <div>
              <dt>Assertion</dt>
              <dd>
                <StatusBadge
                  value={document.candidate.assertion ?? "UNKNOWN"}
                />
              </dd>
            </div>
            <div>
              <dt>Method</dt>
              <dd>OCR + deterministic French rules</dd>
            </div>
          </dl>
          <div className="evidence-callout">
            <Info />
            <p>
              This is a candidate, not a published fact. The bounding box, model
              version, checksum, and rule decision travel together.
            </p>
          </div>
          {ocr.data ? (
            <div className="success-note">
              <CheckCircle2 />
              OCR job queued: {ocr.data.job_id.slice(0, 12)}…
            </div>
          ) : null}
        </Panel>
      </div>
      <Panel
        title="Decision pipeline"
        subtitle="Abstention is a first-class result."
      >
        <div className="stage-row">
          {[
            "Native text",
            "OCR if needed",
            "Lexical match",
            "Negation",
            "Confidence gate",
            "Review",
          ].map((stage, index) => (
            <div key={stage}>
              <span>{index + 1}</span>
              <strong>{stage}</strong>
              <StatusBadge value={index < 5 ? "EVIDENCE" : "REQUIRED"} />
            </div>
          ))}
        </div>
      </Panel>
    </>
  );
}

export function OmopPage() {
  const releases = useQuery({
    queryKey: ["omop-releases"],
    queryFn: api.researchReleases,
  });
  const events = useQuery({
    queryKey: ["omop-events"],
    queryFn: api.omopEvents,
  });
  if (releases.isPending || events.isPending) return <LoadingState />;
  if (releases.error || events.error)
    return (
      <ErrorState
        error={releases.error ?? events.error ?? new Error("Unknown error")}
      />
    );
  const releaseColumns: ColumnDef<ResearchRelease>[] = [
    {
      accessorKey: "release_id",
      header: "Release",
      cell: ({ getValue }) => (
        <span className="stacked-cell">
          <strong>{String(getValue())}</strong>
          <small>immutable manifest</small>
        </span>
      ),
    },
    { accessorKey: "mapping_release_id", header: "Mapping" },
    { accessorKey: "published_count", header: "Published" },
    { accessorKey: "quarantined_count", header: "Quarantined" },
    {
      accessorKey: "checksum_sha256",
      header: "Checksum",
      cell: ({ getValue }) => <Mono>{String(getValue()).slice(0, 16)}…</Mono>,
    },
  ];
  const eventColumns: ColumnDef<OmopEvent>[] = [
    {
      accessorKey: "table",
      header: "Domain table",
      cell: ({ getValue }) => <StatusBadge value={String(getValue())} />,
    },
    { accessorKey: "id", header: "Row ID" },
    {
      accessorKey: "concept_id",
      header: "Concept",
      cell: ({ getValue }) => <Mono>{String(getValue())}</Mono>,
    },
    { accessorKey: "value_as_string", header: "Value" },
    { accessorKey: "source_value", header: "Source evidence" },
    { accessorKey: "research_release_id", header: "Membership" },
  ];
  return (
    <>
      <PageHeader
        eyebrow="Research projection"
        title="OMOP explorer"
        description="The official OMOP 5.4 domain model is a versioned projection. Canonical Parquet remains the lossless semantic source."
      />
      <div className="omop-principle">
        <ShieldCheck />
        <div>
          <strong>No custom release columns in standard OMOP tables</strong>
          <span>
            Release membership and lineage live in dedicated extension tables.
          </span>
        </div>
      </div>
      <Panel
        title="Research releases"
        subtitle="Corrections appear only in descendants; prior releases remain reproducible."
      >
        <DataTable
          data={releases.data}
          columns={releaseColumns}
          label="Research releases"
        />
      </Panel>
      <Panel
        title="Projected facts"
        subtitle="Destination table is selected from the bound concept domain."
      >
        <DataTable
          data={events.data}
          columns={eventColumns}
          label="OMOP events"
        />
      </Panel>
    </>
  );
}

export function CatalogPage() {
  const [query, setQuery] = useState("");
  const concepts = useQuery({
    queryKey: ["concepts", query],
    queryFn: () => api.concepts(query),
  });
  const coverage = useQuery({ queryKey: ["coverage"], queryFn: api.coverage });
  if (concepts.isPending || coverage.isPending) return <LoadingState />;
  if (concepts.error || coverage.error)
    return (
      <ErrorState
        error={concepts.error ?? coverage.error ?? new Error("Unknown error")}
      />
    );
  const conceptColumns: ColumnDef<CatalogConcept>[] = [
    {
      accessorKey: "display_name",
      header: "Research concept",
      cell: ({ row }) => (
        <span className="stacked-cell">
          <strong>{row.original.display_name}</strong>
          <small>{row.original.definition}</small>
        </span>
      ),
    },
    { accessorKey: "vocabulary_id", header: "Vocabulary" },
    {
      accessorKey: "concept_code",
      header: "Code",
      cell: ({ getValue }) => <Mono>{String(getValue())}</Mono>,
    },
    { accessorKey: "limitations", header: "Known limitations" },
  ];
  const chartData = coverage.data.map((item) => ({
    site: item.establishment_id.toUpperCase(),
    usable: Math.round(Number(item.usable_coverage ?? 0) * 100),
    prevalence: Math.round(Number(item.prevalence ?? 0) * 100),
  }));
  return (
    <>
      <PageHeader
        eyebrow="Discoverable data"
        title="Research catalog"
        description="Coverage is reported with explicit denominators, methods, missing-state distributions, limitations, and release identities."
      />
      <label className="catalog-search">
        <FileSearch />
        <span className="sr-only">Search research concepts</span>
        <input
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search a research concept"
        />
      </label>
      <Panel
        title="Available concepts"
        subtitle="A demo vocabulary supports software testing; standardization claims require a compatible Athena snapshot."
      >
        <DataTable
          data={concepts.data}
          columns={conceptColumns}
          label="Catalog concepts"
        />
      </Panel>
      <div className="dashboard-grid">
        <Panel
          title="Coverage vs prevalence"
          subtitle="Different questions; both retain their denominators."
        >
          <div className="chart-wrap">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData}>
                <CartesianGrid
                  strokeDasharray="3 3"
                  vertical={false}
                  stroke="#dfe5e7"
                />
                <XAxis dataKey="site" axisLine={false} tickLine={false} />
                <YAxis domain={[0, 100]} axisLine={false} tickLine={false} />
                <Tooltip />
                <Bar dataKey="usable" fill="#246589" radius={[5, 5, 0, 0]} />
                <Bar
                  dataKey="prevalence"
                  fill="#d69d45"
                  radius={[5, 5, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </Panel>
        <Panel
          title="Site comparison"
          subtitle="Same release, transparent denominator availability."
        >
          <div className="site-comparison">
            {coverage.data.map((item) => (
              <div key={item.establishment_id}>
                <span>
                  {item.establishment_id.toUpperCase()}{" "}
                  <StatusBadge value={item.quality_status} />
                </span>
                <strong>
                  <Percent value={item.usable_coverage} />
                </strong>
                <small>
                  {item.method} · n={item.usable_count}
                </small>
              </div>
            ))}
          </div>
        </Panel>
      </div>
    </>
  );
}

export function LineagePage() {
  const lineage = useQuery({ queryKey: ["lineage"], queryFn: api.lineage });
  if (lineage.isPending) return <LoadingState />;
  if (lineage.error) return <ErrorState error={lineage.error} />;
  const nodes: Node[] = lineage.data.nodes.map((node, index) => ({
    id: node.id,
    position: { x: index * 220, y: index % 2 === 0 ? 40 : 180 },
    data: { label: node.label },
    className: `lineage-node lineage-${node.kind}`,
  }));
  const edges: Edge[] = lineage.data.edges.map((edge, index) => ({
    id: `e-${index}`,
    source: edge.source,
    target: edge.target,
    label: edge.relation.replaceAll("_", " "),
    markerEnd: { type: MarkerType.ArrowClosed },
    animated: false,
  }));
  return (
    <>
      <PageHeader
        eyebrow="End-to-end evidence"
        title="Lineage view"
        description="Trace a catalog number back through an OMOP row, quality decision, mapping release, canonical answer, and immutable raw object."
      />
      <Panel
        title="Observation 1 lineage"
        subtitle="Every publishable fact has a complete evidence path."
      >
        <div className="lineage-canvas">
          <ReactFlow
            nodes={nodes}
            edges={edges}
            fitView
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable
            minZoom={0.55}
            maxZoom={1.6}
          >
            <Background gap={20} size={1} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      </Panel>
      <div className="lineage-ledger">
        {lineage.data.nodes.map((node, index) => (
          <div key={node.id}>
            <span>{index + 1}</span>
            <div>
              <strong>{node.label}</strong>
              <Mono>{node.id}</Mono>
            </div>
            <StatusBadge value={node.kind} />
          </div>
        ))}
      </div>
    </>
  );
}

export function HealthPage() {
  const health = useQuery({
    queryKey: ["health"],
    queryFn: api.health,
    refetchInterval: 15_000,
  });
  const audit = useQuery({ queryKey: ["audit"], queryFn: api.audit });
  if (health.isPending || audit.isPending) return <LoadingState />;
  if (health.error || audit.error)
    return (
      <ErrorState
        error={health.error ?? audit.error ?? new Error("Unknown error")}
      />
    );
  const icons = {
    api: Server,
    database: HardDrive,
    object_store: Box,
    worker: Cpu,
    ocr: Fingerprint,
  };
  return (
    <>
      <PageHeader
        eyebrow="Operational evidence"
        title="System health"
        description="Liveness, readiness, release metadata, redacted audit events, and bounded-service posture for local and federated modes."
      />
      <div className="health-hero">
        <div>
          <span className="pulse-dot" />
          <strong>All core systems operational</strong>
          <small>
            Checked {new Date(health.data.time).toLocaleTimeString()}
          </small>
        </div>
        <StatusBadge value={health.data.status} />
      </div>
      <div className="health-grid">
        {Object.entries(health.data.components).map(([name, status]) => {
          const Icon =
            name in icons ? icons[name as keyof typeof icons] : Server;
          return (
            <div key={name}>
              <Icon />
              <div>
                <strong>{name.replaceAll("_", " ")}</strong>
                <small>{status}</small>
              </div>
              <CheckCircle2 />
            </div>
          );
        })}
      </div>
      <div className="dashboard-grid">
        <Panel title="Build metadata">
          <dl className="detail-list">
            <div>
              <dt>Version</dt>
              <dd>{health.data.version}</dd>
            </div>
            <div>
              <dt>Environment</dt>
              <dd>{health.data.environment}</dd>
            </div>
            <div>
              <dt>Deployment mode</dt>
              <dd>{health.data.deployment_mode}</dd>
            </div>
            <div>
              <dt>Demo authentication</dt>
              <dd>
                <StatusBadge
                  value={health.data.demo_mode ? "ENABLED" : "DISABLED"}
                />
              </dd>
            </div>
          </dl>
        </Panel>
        <Panel title="Safety boundaries">
          <ul className="test-vectors">
            <li>
              <ShieldCheck />
              Patient-level identifiers pseudonymized before central archival
            </li>
            <li>
              <ShieldCheck />
              Site bundles enforce small-cell suppression
            </li>
            <li>
              <TriangleAlert />
              Pseudonymized health data remain personal data
            </li>
          </ul>
        </Panel>
      </div>
      <Panel
        title="Recent audit events"
        subtitle="Every privileged mutation carries actor and correlation identity."
      >
        <div className="audit-list">
          {audit.data.map((event) => (
            <div key={event.id}>
              <span className="audit-icon">
                <ShieldCheck />
              </span>
              <div>
                <strong>{event.action}</strong>
                <small>
                  {event.actor_id} · {event.resource_type}:{event.resource_id}
                </small>
              </div>
              <Mono>{event.correlation_id}</Mono>
            </div>
          ))}
        </div>
      </Panel>
    </>
  );
}
