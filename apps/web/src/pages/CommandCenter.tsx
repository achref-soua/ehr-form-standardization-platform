import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Check,
  CircleAlert,
  FileCheck2,
  Gauge,
  Layers3,
  Play,
  ShieldCheck,
} from "lucide-react";
import { Link } from "react-router-dom";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { api } from "../api/client";
import type {
  CoverageMetric,
  CursorPage,
  Establishment,
  FormVersion,
  PipelineRun,
  QuarantineRecord,
  ResearchRelease,
} from "../api/generated";
import {
  ErrorState,
  LoadingState,
  PageHeader,
  Panel,
  Percent,
  Stat,
  StatusBadge,
} from "../components/ui";
import { scalarText } from "../lib/format";

export function CommandCenterPage() {
  const establishments = useQuery({
    queryKey: ["establishments"],
    queryFn: api.establishments,
  });
  const forms = useQuery({ queryKey: ["forms"], queryFn: api.forms });
  const runs = useQuery({ queryKey: ["runs"], queryFn: api.pipelineRuns });
  const quarantine = useQuery({
    queryKey: ["quarantine"],
    queryFn: api.quarantine,
  });
  const coverage = useQuery({ queryKey: ["coverage"], queryFn: api.coverage });
  const releases = useQuery({
    queryKey: ["research-releases"],
    queryFn: api.researchReleases,
  });

  const queries = [establishments, forms, runs, quarantine, coverage, releases];
  if (queries.some((query) => query.isPending)) return <LoadingState />;
  const error = queries.find((query) => query.error)?.error;
  if (error) return <ErrorState error={error} />;

  // All queries are successful after the guards above; casts preserve that discriminant
  // after collecting heterogeneous query results in the shared `queries` array.
  const establishmentData = establishments.data as CursorPage<Establishment>;
  const formData = forms.data as FormVersion[];
  const runData = runs.data as PipelineRun[];
  const quarantineData = quarantine.data as QuarantineRecord[];
  const coverageData = coverage.data as CoverageMetric[];
  const releaseData = releases.data as ResearchRelease[];
  const latestRelease = releaseData.reduce<ResearchRelease | undefined>(
    (latest, release) =>
      latest === undefined || release.created_at > latest.created_at
        ? release
        : latest,
    undefined,
  );
  const activeQuarantine = quarantineData.filter(
    (record) => record.status !== "RESOLVED",
  );
  const releasedForms = formData.filter(
    (form) => form.mapping_status === "RELEASED",
  );
  const chartData = coverageData.map((metric) => ({
    site: metric.establishment_id.toUpperCase(),
    completion: Math.round(Number(metric.completion) * 100),
    usable: Math.round(Number(metric.usable_coverage) * 100),
  }));

  return (
    <>
      <PageHeader
        eyebrow="Operational overview · release_2026_08"
        title="Standardization command center"
        description="Track source drift, mapping decisions, pipeline evidence, and publishable research data from one deterministic control plane."
        action={
          <Link className="button button-primary" to="/runs">
            <Play /> Run pipeline
          </Link>
        }
      />
      <div className="stat-grid">
        <Stat
          label="Connected sites"
          value={establishmentData.total}
          detail="4 synthetic establishments"
        />
        <Stat
          label="Released forms"
          value={`${releasedForms.length}/${formData.length}`}
          detail="Exact fingerprint binding"
          tone="good"
        />
        <Stat
          label="Open quarantine"
          value={activeQuarantine.length}
          detail="Unknown allergy v4 value set"
          tone="warn"
        />
        <Stat
          label="Published events"
          value={(latestRelease?.published_count ?? 0).toLocaleString("en-US")}
          detail={latestRelease?.release_id ?? "No research release"}
          tone="good"
        />
      </div>

      <Panel
        title="Measured scale evidence"
        subtitle="Reviewed local canonical/Parquet run · deliberately separate from the live seeded release above"
        className="scale-evidence-panel"
      >
        <div className="scale-evidence-grid">
          <div>
            <Layers3 aria-hidden="true" />
            <span>Canonical answer events</span>
            <strong>100,000,000</strong>
          </div>
          <div>
            <Layers3 aria-hidden="true" />
            <span>Bounded work units</span>
            <strong>2,000 × 50,000</strong>
          </div>
          <div>
            <Gauge aria-hidden="true" />
            <span>Recorded throughput</span>
            <strong>4.48–5.08M/s</strong>
          </div>
          <div>
            <Gauge aria-hidden="true" />
            <span>Peak worker RSS</span>
            <strong>87.69 MiB</strong>
          </div>
        </div>
        <p className="scale-boundary">
          This measured harness validates bounded canonical serialization,
          deterministic checksums, and zero duplicate publication. It is not an
          end-to-end API, PostgreSQL, MinIO, and OMOP load test.
        </p>
      </Panel>

      <div className="dashboard-grid">
        <Panel
          title="Cross-site usable coverage"
          subtitle="Allergy history · Jan–Jun 2026"
          className="chart-panel"
        >
          <div
            className="chart-wrap"
            role="img"
            aria-label="Usable coverage by establishment"
          >
            <ResponsiveContainer width="100%" height="100%">
              <BarChart
                data={chartData}
                margin={{ top: 12, right: 8, left: -18, bottom: 0 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  vertical={false}
                  stroke="#dfe5e7"
                />
                <XAxis dataKey="site" tickLine={false} axisLine={false} />
                <YAxis domain={[0, 100]} tickLine={false} axisLine={false} />
                <Tooltip cursor={{ fill: "#e7eff4" }} />
                <Bar
                  dataKey="completion"
                  fill="#a9bfcc"
                  radius={[5, 5, 0, 0]}
                  isAnimationActive={false}
                />
                <Bar
                  dataKey="usable"
                  fill="#246589"
                  radius={[5, 5, 0, 0]}
                  isAnimationActive={false}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="chart-legend">
            <span className="legend-completion" /> Completion{" "}
            <span className="legend-usable" /> Usable
          </div>
        </Panel>

        <Panel
          title="Evidence posture"
          subtitle="Controls required before publication"
        >
          <ul className="control-list">
            <li>
              <ShieldCheck />
              <div>
                <strong>Mapping signature verified</strong>
                <span>Ed25519 · key demo-key</span>
              </div>
              <Check />
            </li>
            <li>
              <FileCheck2 />
              <div>
                <strong>Vocabulary bound</strong>
                <span>Explicit non-clinical demo vocabulary</span>
              </div>
              <Check />
            </li>
            <li>
              <CircleAlert />
              <div>
                <strong>One drift gate active</strong>
                <span>ATCD_ALLERGIES version 4</span>
              </div>
              <Link to="/quarantine">Review</Link>
            </li>
          </ul>
        </Panel>
      </div>

      <div className="dashboard-grid lower-grid">
        <Panel
          title="Guided demonstration"
          subtitle="A real backend state transition, designed for a ten-minute walkthrough"
        >
          <ol className="demo-steps">
            <li className="done">
              <span>1</span>
              <div>
                <strong>Ingest released v3</strong>
                <small>Exact mapping accepted</small>
              </div>
            </li>
            <li className="active">
              <span>2</span>
              <div>
                <strong>Detect v4 drift</strong>
                <small>Changed value set quarantined</small>
              </div>
            </li>
            <li>
              <span>3</span>
              <div>
                <strong>Maker/checker approval</strong>
                <small>Steward signs immutable release</small>
              </div>
            </li>
            <li>
              <span>4</span>
              <div>
                <strong>Replay and compare</strong>
                <small>New research release, old untouched</small>
              </div>
            </li>
          </ol>
          <Link className="text-link" to="/mappings">
            Continue in mapping workspace <ArrowRight />
          </Link>
        </Panel>

        <Panel
          title="Latest pipeline activity"
          subtitle="Durable jobs survive API and worker restarts"
        >
          <div className="activity-list">
            {runData.slice(0, 4).map((run) => (
              <Link to="/runs" key={run.id} className="activity-row">
                <span className={`activity-dot ${run.status.toLowerCase()}`} />
                <div>
                  <strong>
                    {scalarText(run.payload.batch_id) === "—"
                      ? run.job_type
                      : scalarText(run.payload.batch_id)}
                  </strong>
                  <small>{run.correlation_id}</small>
                </div>
                <StatusBadge value={run.status} />
              </Link>
            ))}
          </div>
        </Panel>
      </div>

      <Panel
        title="Coverage ledger"
        subtitle="Transparent denominators and quality status by site"
      >
        <div className="coverage-strip">
          {coverageData.map((metric) => (
            <div key={metric.establishment_id}>
              <span>{metric.establishment_id.toUpperCase()}</span>
              <strong>
                <Percent value={metric.usable_coverage} />
              </strong>
              <small>
                {metric.usable_count}/{metric.eligible_count ?? "—"} usable
              </small>
            </div>
          ))}
        </div>
      </Panel>
    </>
  );
}
