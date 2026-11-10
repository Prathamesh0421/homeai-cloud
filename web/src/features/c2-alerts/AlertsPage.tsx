/** Alerts list (/alerts): filters, newest first, polls every 15 s (the in-app channel). */

import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { ChevronDown, X } from "lucide-react";
import {
  ALERT_STATUSES,
  SEVERITIES,
  c2Keys,
  listAlertTypes,
  listAlerts,
  type AlertFilters,
  type AlertStatus,
  type AlertSummary,
  type Severity,
} from "../../api/c2";
import { ApiError } from "../../api/http";
import { useAuth } from "../../auth/AuthProvider";
import {
  DataTable,
  EmptyState,
  ErrorState,
  Pagination,
  StatusChip,
  STATUS_LABEL,
  SEVERITY_LABEL,
  SEVERITY_BAR,
  type Column,
} from "../../shared";
import { Button } from "@/components/ui/button";
import { AlertDrawer } from "./AlertDrawer";
import { dayEndIso, dayStartIso, labelText, percent, relativeTime } from "./format";

export const POLL_MS = 15_000;
const PAGE_SIZE = 25;

function filtersFrom(params: URLSearchParams): AlertFilters {
  const status = params.get("status");
  const from = params.get("from");
  const to = params.get("to");
  return {
    status: status ? (status.split(",") as AlertStatus[]) : undefined,
    severity: (params.get("severity") as Severity | null) ?? undefined,
    alertTypeCode: params.get("type") ?? undefined,
    houseId: params.get("house") ?? undefined,
    from: from ? dayStartIso(from) : undefined,
    to: to ? dayEndIso(to) : undefined,
    page: Number(params.get("page") ?? 1) || 1,
    pageSize: PAGE_SIZE,
  };
}

/**
 * Criticals that arrived since the previous poll of the *same* query. A new filter or page starts
 * over (its first result only records what is there), and placeholder data shown while a new
 * query loads is ignored, so older criticals that come into view are never announced as new.
 */
export function useNewCriticals(
  rows: AlertSummary[] | undefined,
  queryKey: string,
  isPlaceholder: boolean,
) {
  const seen = useRef<{ key: string; ids: Set<string> } | null>(null);
  const [fresh, setFresh] = useState<AlertSummary[]>([]);
  useEffect(() => {
    if (!rows || isPlaceholder) return;
    if (seen.current?.key !== queryKey) {
      seen.current = { key: queryKey, ids: new Set(rows.map((r) => r.alert_id)) };
      return;
    }
    const known = seen.current.ids;
    const arrived = rows.filter((r) => r.severity === "critical" && !known.has(r.alert_id));
    rows.forEach((r) => known.add(r.alert_id));
    if (arrived.length) setFresh((cur) => [...arrived, ...cur]);
  }, [rows, queryKey, isPlaceholder]);
  return { fresh, dismiss: () => setFresh([]) };
}

export default function AlertsPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { session } = useAuth();
  const filters = useMemo(() => filtersFrom(params), [params]);

  const alerts = useQuery({
    queryKey: c2Keys.alerts(filters),
    queryFn: () => listAlerts(filters),
    refetchInterval: POLL_MS,
    placeholderData: keepPreviousData,
  });
  const types = useQuery({ queryKey: c2Keys.alertTypes(), queryFn: listAlertTypes, staleTime: 3_600_000 });
  const { fresh, dismiss } = useNewCriticals(
    alerts.data?.data,
    JSON.stringify(filters),
    alerts.isPlaceholderData,
  );

  // House filter: the owner's houses, plus any house seen in results (names come from C1;
  // until a house shows up in results it is labelled by the end of its id, which differs).
  // For staff the options are the houses in the current results.
  const houses = useMemo(() => {
    const names = new Map<string, string>();
    session?.houseIds.forEach((h) => names.set(h, `House …${h.slice(-4)}`));
    alerts.data?.data.forEach((a) => names.set(a.house_id, a.house_name ?? a.house_id.slice(0, 8)));
    return [...names.entries()];
  }, [session, alerts.data]);

  function setFilter(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    if (name !== "page") next.delete("page");
    setParams(next, { replace: true });
  }

  const [drawerId, setDrawerId] = useState<string | null>(null);

  const columns: Column<AlertSummary>[] = [
    {
      key: "severity",
      header: "",
      render: (a) => (
        <span
          className={`inline-block h-9 w-1 rounded-full ${SEVERITY_BAR[a.severity]}`}
          role="img"
          aria-label={`Severity ${SEVERITY_LABEL[a.severity]}`}
        />
      ),
      sortValue: (a) => SEVERITIES.indexOf(a.severity),
    },
    {
      key: "type",
      header: "Alert",
      render: (a) => (
        <div>
          <Link
            to={`/alerts/${a.alert_id}`}
            className="font-medium text-ink hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {a.alert_type_name}
          </Link>
          <div className="text-xs text-muted">{labelText(a.top_label)}</div>
        </div>
      ),
      sortValue: (a) => a.alert_type_name,
    },
    {
      key: "where",
      header: "House / room",
      render: (a) => (
        <span className="text-muted">
          {a.house_name ?? "House unavailable"}
          {a.room_name ? ` · ${a.room_name}` : ""}
        </span>
      ),
    },
    {
      key: "triggered",
      header: "Triggered",
      render: (a) => (
        <time className="tnum" dateTime={a.triggered_at} title={new Date(a.triggered_at).toLocaleString()}>
          {relativeTime(a.triggered_at)}
        </time>
      ),
      sortValue: (a) => a.triggered_at,
    },
    {
      key: "confidence",
      header: "Confidence",
      render: (a) => <span className="tnum text-muted">{percent(a.top_confidence)}</span>,
      sortValue: (a) => a.top_confidence,
    },
    {
      key: "status",
      header: "Status",
      render: (a) => <StatusChip status={a.status} />,
      sortValue: (a) => ALERT_STATUSES.indexOf(a.status),
    },
    {
      key: "actions",
      header: "",
      render: (a) =>
        a.status === "open" || a.status === "acknowledged" ? (
          <span className="flex gap-1">
            <Button
              variant="ghost"
              size="sm"
              onClick={(e) => {
                e.stopPropagation();
                setDrawerId(a.alert_id);
              }}
            >
              View
            </Button>
          </span>
        ) : null,
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Alerts</h1>
        <span className="text-xs text-muted" aria-live="polite">
          {alerts.isFetching ? "Refreshing…" : "Updates every 15 s"}
        </span>
      </div>

      {fresh.length > 0 && (
        <div
          role="alert"
          className="flex items-center justify-between rounded-lg border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger"
        >
          <span>
            <span aria-hidden="true">▲ </span>
            {fresh.length === 1 ? "1 new critical alert" : `${fresh.length} new critical alerts`}:{" "}
            {fresh[0].alert_type_name}
            {fresh[0].house_name ? ` at ${fresh[0].house_name}` : ""}
          </span>
          <span className="flex gap-2">
            <button
              type="button"
              className="rounded-md bg-danger px-3 py-1.5 text-xs font-medium text-white hover:bg-danger/90"
              onClick={() => navigate(`/alerts/${fresh[0].alert_id}`)}
            >
              View
            </button>
            <button type="button" className="text-xs underline" onClick={dismiss}>
              Dismiss
            </button>
          </span>
        </div>
      )}

      {/* Filters as chip-style selects */}
      <div className="flex flex-wrap items-center gap-2">
        <FilterChip
          label="Status"
          value={params.get("status") ?? ""}
          onChange={(v) => setFilter("status", v)}
          options={[
            { value: "", label: "All" },
            { value: "open,acknowledged", label: "Active" },
            ...ALERT_STATUSES.map((s) => ({ value: s, label: STATUS_LABEL[s] })),
          ]}
        />
        <FilterChip
          label="Severity"
          value={params.get("severity") ?? ""}
          onChange={(v) => setFilter("severity", v)}
          options={[{ value: "", label: "All" }, ...SEVERITIES.map((s) => ({ value: s, label: SEVERITY_LABEL[s] }))]}
        />
        <FilterChip
          label="Type"
          value={params.get("type") ?? ""}
          onChange={(v) => setFilter("type", v)}
          options={[{ value: "", label: "All" }, ...(types.data?.map((t) => ({ value: t.code, label: t.name })) ?? [])]}
        />
        {houses.length > 0 && (
          <FilterChip
            label="House"
            value={params.get("house") ?? ""}
            onChange={(v) => setFilter("house", v)}
            options={[{ value: "", label: "All" }, ...houses.map(([id, name]) => ({ value: id, label: name }))]}
          />
        )}
        <FilterChip
          label="From"
          value={params.get("from") ?? ""}
          onChange={(v) => setFilter("from", v)}
          type="date"
        />
        <FilterChip
          label="To"
          value={params.get("to") ?? ""}
          onChange={(v) => setFilter("to", v)}
          type="date"
        />
        {(params.get("status") || params.get("severity") || params.get("type") || params.get("house") || params.get("from") || params.get("to")) && (
          <button
            type="button"
            onClick={() => setParams(new URLSearchParams(), { replace: true })}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1.5 text-xs text-muted hover:bg-surface-2 hover:text-ink"
          >
            <X className="h-3.5 w-3.5" /> Clear
          </button>
        )}
      </div>

      {alerts.isPending ? (
        <div className="py-8 text-center text-sm text-muted">Loading alerts…</div>
      ) : alerts.isError ? (
        <ErrorState
          message={
            alerts.error instanceof ApiError && alerts.error.status === 403
              ? "You don't have access to these alerts."
              : `Could not load alerts: ${alerts.error.message}`
          }
          onRetry={() => alerts.refetch()}
        />
      ) : alerts.data.data.length === 0 ? (
        <EmptyState
          title="No alerts in this range"
          description={`New alerts appear here within 15 seconds. Monitoring ${session?.houseIds.length ?? "your"} house${(session?.houseIds.length ?? 0) === 1 ? "" : "s"}.`}
        />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={alerts.data.data}
            rowKey={(a) => a.alert_id}
            onRowClick={(a) => setDrawerId(a.alert_id)}
          />
          <Pagination
            page={alerts.data.meta.page}
            pageSize={alerts.data.meta.page_size}
            total={alerts.data.meta.total}
            onChange={(p) => setFilter("page", String(p))}
          />
        </>
      )}

      <AlertDrawer alertId={drawerId} onOpenChange={(open) => !open && setDrawerId(null)} />
    </div>
  );
}

/** Compact chip-style filter: a labeled select or date input styled as a chip. */
function FilterChip({
  label,
  value,
  onChange,
  options,
  type,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options?: { value: string; label: string }[];
  type?: "date";
}) {
  const chipCls =
    "inline-flex items-center gap-1.5 rounded-md border border-border-strong bg-surface px-2.5 py-1.5 text-xs text-ink";
  const active = Boolean(value);
  return (
    <label className={chipCls}>
      <span className="text-muted">{label}</span>
      {type === "date" || !options ? (
        <input
          type="date"
          className="border-0 bg-transparent p-0 text-xs text-ink focus:outline-none"
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <span className="flex items-center gap-1">
          <select
            className="border-0 bg-transparent p-0 text-xs text-ink focus:outline-none"
            value={value}
            onChange={(e) => onChange(e.target.value)}
          >
            {options.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
          {active && <ChevronDown className="h-3 w-3 text-muted" aria-hidden="true" />}
        </span>
      )}
    </label>
  );
}
