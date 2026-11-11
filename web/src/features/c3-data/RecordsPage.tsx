/** Database Records (/ops/records): browse entities across stores, scoped per role.
 *
 * Tenant and house are chosen from name selects (C4 tenants + C1 houses) instead
 * of pasting UUIDs. Column headers are humanized; UUID cells are truncated with a
 * copy button.
 */

import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Check, Copy, X } from "lucide-react";
import {
  RECORD_ENTITIES,
  type Record_,
  type RecordEntity,
  type RecordFilters,
  c3Keys,
  listRecords,
} from "../../api/c3";
import { fetchTenants } from "../../api/c4";
import { listHouses, c1Keys } from "../../api/c1";
import { ApiError } from "../../api/http";
import { useAuth } from "../../auth/AuthProvider";
import { DataTable, EmptyState, ErrorState, FilterSelect, Pagination, type Column } from "../../shared";

const PAGE_SIZE = 25;
/** Radix Select forbids value=""; use a sentinel for "all". */
const ALL = "__all__";

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

// Humanized column titles (snake_case → sentence case, with friendlier names).
const HEADER_LABELS: Record<string, string> = {
  house_id: "House",
  room_id: "Room",
  feed_id: "Feed",
  alert_id: "Alert",
  tenant_id: "Tenant",
  id: "ID",
  name: "Name",
  room_type: "Room type",
  status: "Status",
  severity: "Severity",
  top_label: "Top label",
  top_confidence: "Confidence",
  detected_at: "Detected",
  uploaded_at: "Uploaded",
  triggered_at: "Triggered",
  date: "Date",
};

function humanize(key: string): string {
  return HEADER_LABELS[key] ?? key.replace(/_/g, " ");
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

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

  const isCloud = session?.role === "cloud_staff";
  const tenantId = params.get("tenant") ?? "";
  const houseId = params.get("house") ?? "";

  // Tenant + house name selects (cloud staff only see the tenant select).
  const tenantsQ = useQuery({
    queryKey: ["c4", "tenants"],
    queryFn: fetchTenants,
    enabled: isCloud,
  });
  const tenantOptions = useMemo(
    () => [
      { value: ALL, label: "All tenants" },
      ...(tenantsQ.data ?? []).map((t) => ({ value: t.tenant_id, label: t.name })),
    ],
    [tenantsQ.data],
  );

  const housesQ = useQuery({
    queryKey: c1Keys.houses({ tenantId: tenantId || undefined, pageSize: 100 }),
    queryFn: () => listHouses({ tenantId: tenantId || undefined, pageSize: 100 }),
  });
  const houseOptions = useMemo(
    () => [
      { value: ALL, label: "All houses" },
      ...(housesQ.data?.data ?? []).map((h) => ({ value: h.house_id, label: h.name })),
    ],
    [housesQ.data],
  );

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
    // Reset house when tenant changes (house list is tenant-scoped).
    if (name === "tenant") next.delete("house");
    setParams(next, { replace: true });
  }

  const cols = PREVIEW_COLUMNS[entity];
  const columns: Column<Record_>[] = cols.map((key) => ({
    key,
    header: humanize(key),
    render: (row) => <Cell value={row[key]} />,
  }));

  const scopeNote = isCloud
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
        {isCloud && (
          <FilterSelect
            label="Tenant"
            value={tenantId || ALL}
            onValueChange={(v) => setParam("tenant", v === ALL ? "" : v)}
            options={tenantOptions}
            placeholder="All tenants"
            className="w-[12rem]"
          />
        )}
        <FilterSelect
          label="House"
          value={houseId || ALL}
          onValueChange={(v) => setParam("house", v === ALL ? "" : v)}
          options={houseOptions}
          placeholder="All houses"
          className="w-[12rem]"
        />
        <FilterInput label="Filter" value={params.get("filter") ?? ""} onChange={(v) => setParam("filter", v)} placeholder="field:value" />
        {(tenantId || houseId || params.get("filter")) && (
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

function Cell({ value }: { value: unknown }) {
  const [copied, setCopied] = useState(false);
  const text = formatCell(value);
  const isUuid = typeof value === "string" && UUID_RE.test(value);

  if (!isUuid) {
    return <span className="text-ink">{text}</span>;
  }

  async function copy() {
    try {
      await navigator.clipboard.writeText(String(value));
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // clipboard unavailable (e.g. insecure context) — ignore
    }
  }

  return (
    <span className="inline-flex items-center gap-1.5 text-ink">
      <span className="tnum font-mono text-xs" title={text}>
        {text.slice(0, 8)}…
      </span>
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          void copy();
        }}
        className="text-muted hover:text-ink"
        aria-label="Copy ID"
        tabIndex={-1}
      >
        {copied ? <Check className="h-3 w-3 text-success" /> : <Copy className="h-3 w-3" />}
      </button>
    </span>
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
