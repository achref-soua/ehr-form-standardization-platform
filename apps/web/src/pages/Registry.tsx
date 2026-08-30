import { useQuery } from "@tanstack/react-query";
import type { ColumnDef } from "@tanstack/react-table";
import { Database, FileDiff, Fingerprint, Search } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { api } from "../api/client";
import type { FormVersion, SourceSystem } from "../api/generated";
import {
  DataTable,
  ErrorState,
  LoadingState,
  Mono,
  PageHeader,
  Panel,
  StatusBadge,
} from "../components/ui";

export function SourcesPage() {
  const sources = useQuery({ queryKey: ["sources"], queryFn: api.sources });
  const sites = useQuery({
    queryKey: ["establishments"],
    queryFn: api.establishments,
  });
  if (sources.isPending || sites.isPending) return <LoadingState />;
  if (sources.error || sites.error)
    return (
      <ErrorState
        error={sources.error ?? sites.error ?? new Error("Unknown error")}
      />
    );

  const columns: ColumnDef<SourceSystem>[] = [
    { accessorKey: "source_key", header: "Source" },
    {
      accessorKey: "establishment_id",
      header: "Site",
      cell: ({ getValue }) => <Mono>{String(getValue())}</Mono>,
    },
    { accessorKey: "family", header: "Input contract" },
    { accessorKey: "version", header: "Version" },
    {
      id: "state",
      header: "Inventory",
      cell: () => <StatusBadge value="INVENTORIED" />,
    },
  ];
  return (
    <>
      <PageHeader
        eyebrow="Input boundary"
        title="Source explorer"
        description="Inventory every source before touching patient-level content. Connectors preserve the original object and reject ambiguous semantics."
      />
      <div className="stat-grid compact-stats">
        <div className="mini-stat">
          <Database />
          <div>
            <strong>{sources.data.length}</strong>
            <span>source contracts</span>
          </div>
        </div>
        <div className="mini-stat">
          <Fingerprint />
          <div>
            <strong>2</strong>
            <span>fingerprints per form</span>
          </div>
        </div>
        <div className="mini-stat">
          <FileDiff />
          <div>
            <strong>0</strong>
            <span>guessed fields</span>
          </div>
        </div>
      </div>
      <Panel
        title="Registered source systems"
        subtitle="FHIR order is semantic; unordered EAV inputs are normalized before hashing."
      >
        <DataTable
          data={sources.data}
          columns={columns}
          label="Registered source systems"
        />
      </Panel>
      <Panel
        title="Adapter boundary"
        subtitle="Supported paths in the bounded demonstration"
      >
        <div className="adapter-grid">
          {[
            "FHIR R4 Questionnaire",
            "QuestionnaireResponse",
            "Tabular / EAV",
            "CDA narrative",
            "JSON / secure XML",
            "Document upload",
          ].map((adapter) => (
            <div key={adapter}>
              <StatusBadge value="SUPPORTED" />
              <strong>{adapter}</strong>
              <small>Typed validation · explicit failures</small>
            </div>
          ))}
        </div>
      </Panel>
    </>
  );
}

export function FormsPage() {
  const forms = useQuery({ queryKey: ["forms"], queryFn: api.forms });
  const { formVersionId } = useParams();
  const [params, setParams] = useSearchParams();
  const query = params.get("query") ?? "";
  if (forms.isPending) return <LoadingState />;
  if (forms.error) return <ErrorState error={forms.error} />;
  const selected =
    forms.data.find((form) => form.id === formVersionId) ?? forms.data[0];
  const filtered = forms.data.filter((form) =>
    `${form.title} ${form.form_id}`.toLowerCase().includes(query.toLowerCase()),
  );

  const columns: ColumnDef<FormVersion>[] = [
    {
      accessorKey: "title",
      header: "Form",
      cell: ({ row }) => (
        <Link className="entity-link" to={`/forms/${row.original.id}`}>
          {row.original.title}
          <small>{row.original.form_id}</small>
        </Link>
      ),
    },
    {
      accessorKey: "version",
      header: "Version",
      cell: ({ getValue }) => <Mono>v{String(getValue())}</Mono>,
    },
    { accessorKey: "family", header: "Family" },
    {
      accessorKey: "mapping_status",
      header: "Mapping",
      cell: ({ getValue }) => <StatusBadge value={String(getValue())} />,
    },
    {
      accessorKey: "source_fingerprint",
      header: "Definition",
      cell: ({ getValue }) => <Mono>{String(getValue()).slice(0, 10)}…</Mono>,
    },
  ];

  return (
    <>
      <PageHeader
        eyebrow="Semantic inventory"
        title="Form registry"
        description="Compare complete source definitions with the compatibility surface that controls safe mapping reuse."
      />
      <div className="toolbar">
        <label className="search-field">
          <Search />
          <span className="sr-only">Search forms</span>
          <input
            value={query}
            onChange={(event) =>
              setParams(event.target.value ? { query: event.target.value } : {})
            }
            placeholder="Search form or identifier"
          />
        </label>
        <span>{filtered.length} versions</span>
      </div>
      <div className="split-view">
        <Panel title="Detected versions">
          <DataTable data={filtered} columns={columns} label="Form versions" />
        </Panel>
        {selected ? (
          <Panel
            title={`Version ${selected.version}`}
            subtitle={selected.title}
            className="detail-panel"
          >
            <dl className="detail-list">
              <div>
                <dt>Source fingerprint</dt>
                <dd>
                  <Mono>{selected.source_fingerprint}</Mono>
                </dd>
              </div>
              <div>
                <dt>Compatibility fingerprint</dt>
                <dd>
                  <Mono>{selected.compatibility_fingerprint}</Mono>
                </dd>
              </div>
              <div>
                <dt>Mapping state</dt>
                <dd>
                  <StatusBadge value={selected.mapping_status} />
                </dd>
              </div>
              <div>
                <dt>Questionnaire order</dt>
                <dd>Preserved as declared</dd>
              </div>
            </dl>
            <h3>Definition items</h3>
            <div className="item-list">
              {(selected.definition.items ?? []).map((item, index) => (
                <div key={typeof item.path === "string" ? item.path : index}>
                  <span>{index + 1}</span>
                  <div>
                    <strong>
                      {typeof item.label === "string"
                        ? item.label
                        : String(item.path)}
                    </strong>
                    <small>
                      {String(item.data_type)} · {String(item.path)}
                    </small>
                  </div>
                </div>
              ))}
            </div>
          </Panel>
        ) : null}
      </div>
    </>
  );
}
