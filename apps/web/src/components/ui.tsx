import type { PropsWithChildren, ReactNode } from "react";
import { AlertTriangle, CheckCircle2, LoaderCircle } from "lucide-react";
import {
  flexRender,
  getCoreRowModel,
  useReactTable,
  type ColumnDef,
} from "@tanstack/react-table";

export function PageHeader({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <header className="page-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        <p className="lede">{description}</p>
      </div>
      {action ? <div className="page-action">{action}</div> : null}
    </header>
  );
}

export function Panel({
  title,
  subtitle,
  children,
  className = "",
}: PropsWithChildren<{
  title?: string;
  subtitle?: string;
  className?: string;
}>) {
  return (
    <section className={`panel ${className}`}>
      {title ? (
        <div className="panel-heading">
          <div>
            <h2>{title}</h2>
            {subtitle ? <p>{subtitle}</p> : null}
          </div>
        </div>
      ) : null}
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  detail,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  detail: string;
  tone?: "neutral" | "good" | "warn";
}) {
  return (
    <div className={`stat stat-${tone}`}>
      <p>{label}</p>
      <strong>{value}</strong>
      <span>{detail}</span>
    </div>
  );
}

export function StatusBadge({ value }: { value: string }) {
  const normalized = value.toLowerCase();
  const tone = [
    "succeeded",
    "released",
    "healthy",
    "ready",
    "passed",
    "approved",
  ].some((term) => normalized.includes(term))
    ? "good"
    : ["failed", "quarantine", "review", "unknown", "warning"].some((term) =>
          normalized.includes(term),
        )
      ? "warn"
      : "neutral";
  return (
    <span className={`badge badge-${tone}`}>{value.replaceAll("_", " ")}</span>
  );
}

export function LoadingState({
  label = "Loading verified data",
}: {
  label?: string;
}) {
  return (
    <div className="state-card" role="status">
      <LoaderCircle className="spin" aria-hidden="true" />
      <p>{label}</p>
    </div>
  );
}

export function ErrorState({ error }: { error: Error }) {
  return (
    <div className="state-card state-error" role="alert">
      <AlertTriangle aria-hidden="true" />
      <div>
        <strong>Data could not be loaded</strong>
        <p>{error.message}</p>
      </div>
    </div>
  );
}

export function EmptyState({
  title,
  detail,
}: {
  title: string;
  detail: string;
}) {
  return (
    <div className="state-card">
      <CheckCircle2 aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{detail}</p>
      </div>
    </div>
  );
}

export function Mono({ children }: PropsWithChildren) {
  return <code className="mono">{children}</code>;
}

export function Percent({ value }: { value: string | number | null }) {
  if (value === null) return <span className="percent">—</span>;
  return <span className="percent">{Math.round(Number(value) * 100)}%</span>;
}

export function DataTable<T>({
  data,
  columns,
  label,
}: {
  data: T[];
  columns: ColumnDef<T>[];
  label: string;
}) {
  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
  });
  return (
    <div
      className="table-scroll"
      role="region"
      aria-label={`${label} scrollable table`}
      tabIndex={0}
    >
      <table aria-label={label}>
        <thead>
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <th key={header.id} scope="col">
                  {header.isPlaceholder
                    ? null
                    : flexRender(
                        header.column.columnDef.header,
                        header.getContext(),
                      )}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.map((row) => (
            <tr key={row.id}>
              {row.getVisibleCells().map((cell) => (
                <td key={cell.id}>
                  {flexRender(cell.column.columnDef.cell, cell.getContext())}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
