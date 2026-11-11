/** Database Records (/ops/records): browse entities across stores, scoped per role. */

import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import {
  RECORD_ENTITIES,
  type Record_,
  type RecordEntity,
  type RecordFilters,
  c3Keys,
  listRecords,
} from "../../api/c3";
import { ApiError } from "../../api/http";
import { useAuth } from "../../auth/AuthProvider";
import { DataTable, EmptyState, ErrorState, Pagination, type Column } from "../../shared";

const PAGE_SIZE = 25;

// A small, readable set of columns per entity; the row drawer shows the full JSON.
const PREVIEW_COLUMNS: Record<RecordEntity, string[]> = {
  houses: ["house_id", "name", "tenant_id"],
  rooms: ["room_id", "name", "room_type", "house_id"],
  feeds: ["feed_id", "name", "status", "house_id"],
  clips: ["id", "status", "feed_id", "uploaded_at"],
  detections: ["id", "top_label", "top_confidence", "house_id", "detected_at"],
  alerts: ["alert_id", "severity", "status", "triggered_at"],
  activity_patterns: ["id", "house_id", "room_id", "date"],
};

function filtersFrom(params: URLSearchParams): RecordFilters {
  return {
    tenantId: params.get("tenant") ?? undefined,
    houseId: params.get("house") ?? undefined,
    filter: params.get("filter") ?? undefined,
    from: params.get("from") || undefined,
    to: params.get("to") || undefined,
    page: Number(params.get("page") ?? 1) || 1,
    pageSize: PAGE_SIZE,
  };
}

export default function RecordsPage() {
  const [params, setParams] = useSearchParams();
  const { session } = useAuth();
  const entity = (params.get("entity") as RecordEntity | null) ?? "detections";
  const filters = useMemo(() => filtersFrom(params), [params]);
  const [drawerRow, setDrawerRow] = useState<Record_ | null>(null);

  const q = useQuery({
    queryKey: c3Keys.records(entity, filters),
    queryFn: () => listRecords(entity, filters),
    placeholderData: keepPreviousData,
  });

  function setParam(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    if (name !== "page") next.delete("page");
    setParams(next, { replace: true });
  }

  const cols = PREVIEW_COLUMNS[entity];
  const columns: Column<Record_>[] = cols.map((key) => ({
    key,
    header: key,
    render: (row) => <span className="text-ink">{formatCell(row[key])}</span>,
  }));

  const scopeNote =
    session?.role === "cloud_staff"
      ? "Cloud staff: all tenants (narrow with a tenant filter)."
      : "You see only records for your own houses.";

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">Records</h1>

      {/* Entity chips */}
      <div className="flex flex-wrap gap-1.5">
        {RECORD_ENTITIES.map((e) => (
          <button
            key={e}
            type="button"
            onClick={() => setParam("entity", e)}
            className={`rounded-md border px-2.5 py-1.5 text-xs font-medium ${
              e === entity ? "border-accent bg-accent-soft text-accent" : "border-border-strong text-muted hover:bg-surface-2"
            }`}
          >
            {e}
          </button>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-2">
        {session?.role === "cloud_staff" && (
          <FilterInput label="Tenant" value={params.get("tenant") ?? ""} onChange={(v) => setParam("tenant", v)} placeholder="tenant UUID" />
        )}
        <FilterInput label="House" value={params.get("house") ?? ""} onChange={(v) => setParam("house", v)} placeholder="house UUID" />
        <FilterInput label="Filter" value={params.get("filter") ?? ""} onChange={(v) => setParam("filter", v)} placeholder="field:value" />
        {(params.get("tenant") || params.get("house") || params.get("filter")) && (
          <button
            type="button"
            onClick={() => setParams(new URLSearchParams(entity === "detections" ? {} : { entity }), { replace: true })}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs text-muted hover:bg-surface-2 hover:text-ink"
          >
            <X className="h-3.5 w-3.5" /> Clear
          </button>
        )}
      </div>

      <p className="text-xs text-muted">{scopeNote}</p>

      {q.isPending ? (
        <div className="py-8 text-center text-sm text-muted">Loading records…</div>
      ) : q.isError ? (
        <ErrorState
          message={
            q.error instanceof ApiError && q.error.status === 403
              ? "You don't have access to these records."
              : q.error instanceof ApiError && q.error.status === 429
                ? "Too many requests — slow down and retry."
                : `Could not load records: ${q.error.message}`
          }
          onRetry={() => q.refetch()}
        />
      ) : q.data.data.length === 0 ? (
        <EmptyState title="No records" description={`No ${entity} match the current scope and filters.`} />
      ) : (
        <>
          <DataTable columns={columns} rows={q.data.data} rowKey={(r) => String(r.id ?? r[cols[0]] ?? Math.random())} onRowClick={(r) => setDrawerRow(r)} />
          <Pagination page={q.data.meta.page} pageSize={q.data.meta.page_size} total={q.data.meta.total} onChange={(p) => setParam("page", String(p))} />
        </>
      )}

      {drawerRow && <RecordDrawer row={drawerRow} onClose={() => setDrawerRow(null)} />}
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return String(v);
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function FilterInput({
  label,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <label className="inline-flex items-center gap-1.5 rounded-md border border-border-strong bg-surface px-2.5 py-1.5 text-xs text-ink">
      <span className="text-muted">{label}</span>
      <input
        className="w-44 border-0 bg-transparent p-0 text-xs text-ink focus:outline-none"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

function RecordDrawer({ row, onClose }: { row: Record_; onClose: () => void }) {
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose} role="dialog" aria-label="Record detail">
      <div className="h-full w-full max-w-md overflow-auto bg-surface p-5 shadow-lg" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between">
          <h2 className="text-lg font-semibold text-ink">Record</h2>
          <button type="button" onClick={onClose} aria-label="Close" className="text-muted hover:text-ink">
            ✕
          </button>
        </div>
        <pre className="mt-4 whitespace-pre-wrap break-words rounded-lg border border-border bg-canvas p-3 text-xs text-ink">
          {JSON.stringify(row, null, 2)}
        </pre>
      </div>
    </div>
  );
}
