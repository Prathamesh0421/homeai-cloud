/** Alerts list (/alerts): filters, newest first, polls every 15 s (the in-app channel). */

import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
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
  FilterBar,
  Pagination,
  SeverityBadge,
  StatusChip,
  STATUS_LABEL,
  SEVERITY_LABEL,
  type Column,
} from "../../shared";
import { dayEndIso, dayStartIso, labelText, percent, relativeTime } from "./format";

export const POLL_MS = 15_000;
const PAGE_SIZE = 25;

const selectClass = "rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-700";

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

  const columns: Column<AlertSummary>[] = [
    {
      key: "severity",
      header: "Severity",
      render: (a) => <SeverityBadge severity={a.severity} />,
      sortValue: (a) => SEVERITIES.indexOf(a.severity),
    },
    {
      key: "type",
      header: "Alert",
      render: (a) => (
        <div>
          {/* A real link too: DataTable rows are clickable but not keyboard-focusable. */}
          <Link
            to={`/alerts/${a.alert_id}`}
            className="font-medium text-slate-800 hover:underline"
            onClick={(e) => e.stopPropagation()}
          >
            {a.alert_type_name}
          </Link>
          <div className="text-xs text-slate-500">
            {labelText(a.top_label)} · {percent(a.top_confidence)}
          </div>
        </div>
      ),
      sortValue: (a) => a.alert_type_name,
    },
    {
      key: "where",
      header: "House / room",
      render: (a) => (
        <span className="text-slate-700">
          {a.house_name ?? "House unavailable"}
          {a.room_name ? ` · ${a.room_name}` : ""}
        </span>
      ),
    },
    {
      key: "status",
      header: "Status",
      render: (a) => <StatusChip status={a.status} />,
      sortValue: (a) => ALERT_STATUSES.indexOf(a.status),
    },
    {
      key: "triggered",
      header: "Triggered",
      render: (a) => (
        <time dateTime={a.triggered_at} title={new Date(a.triggered_at).toLocaleString()}>
          {relativeTime(a.triggered_at)}
        </time>
      ),
      sortValue: (a) => a.triggered_at,
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold text-slate-900">Alerts</h1>
        <span className="text-xs text-slate-500" aria-live="polite">
          {alerts.isFetching ? "Refreshing…" : "Updates every 15 s"}
        </span>
      </div>

      {fresh.length > 0 && (
        <div
          role="alert"
          className="flex items-center justify-between rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
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
              className="rounded bg-red-600 px-3 py-1 text-xs font-medium text-white hover:bg-red-500"
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

      <FilterBar onReset={() => setParams(new URLSearchParams(), { replace: true })}>
        <label className="text-xs text-slate-500">
          Status{" "}
          <select
            className={selectClass}
            value={params.get("status") ?? ""}
            onChange={(e) => setFilter("status", e.target.value)}
          >
            <option value="">All</option>
            <option value="open,acknowledged">Active (open or acknowledged)</option>
            {ALERT_STATUSES.map((s) => (
              <option key={s} value={s}>
                {STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-slate-500">
          Severity{" "}
          <select
            className={selectClass}
            value={params.get("severity") ?? ""}
            onChange={(e) => setFilter("severity", e.target.value)}
          >
            <option value="">All</option>
            {SEVERITIES.map((s) => (
              <option key={s} value={s}>
                {SEVERITY_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-slate-500">
          Type{" "}
          <select
            className={selectClass}
            value={params.get("type") ?? ""}
            onChange={(e) => setFilter("type", e.target.value)}
          >
            <option value="">All</option>
            {types.data?.map((t) => (
              <option key={t.code} value={t.code}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        {houses.length > 0 && (
          <label className="text-xs text-slate-500">
            House{" "}
            <select
              className={selectClass}
              value={params.get("house") ?? ""}
              onChange={(e) => setFilter("house", e.target.value)}
            >
              <option value="">All</option>
              {houses.map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </select>
          </label>
        )}
        <label className="text-xs text-slate-500">
          From{" "}
          <input
            type="date"
            className={selectClass}
            value={params.get("from") ?? ""}
            onChange={(e) => setFilter("from", e.target.value)}
          />
        </label>
        <label className="text-xs text-slate-500">
          To{" "}
          <input
            type="date"
            className={selectClass}
            value={params.get("to") ?? ""}
            onChange={(e) => setFilter("to", e.target.value)}
          />
        </label>
      </FilterBar>

      {alerts.isPending ? (
        <div className="py-8 text-center text-sm text-slate-500">Loading alerts…</div>
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
          title="No alerts"
          description="Nothing matches these filters. New alerts appear here within 15 seconds."
        />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={alerts.data.data}
            rowKey={(a) => a.alert_id}
            onRowClick={(a) => navigate(`/alerts/${a.alert_id}`)}
          />
          <Pagination
            page={alerts.data.meta.page}
            pageSize={alerts.data.meta.page_size}
            total={alerts.data.meta.total}
            onChange={(p) => setFilter("page", String(p))}
          />
        </>
      )}
    </div>
  );
}
