/** Home Overview (C4-13): KPIs + recent alerts for house_owner. */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { fetchDashboardSummary, type DashboardRange } from "../../../api/c4";
import { ApiError } from "../../../api/http";
import { useAuth } from "../../../auth/AuthProvider";
import {
  ChartCard,
  ErrorState,
  KpiTile,
  SeverityBadge,
} from "../../../shared";
import { houseOptionsFor } from "../houseOptions";

const POLL_MS = 15_000;

const selectCls =
  "rounded-md border border-border-strong bg-surface px-2.5 py-1.5 text-sm text-ink";
const linkCls =
  "rounded-md border border-border-strong bg-surface px-2.5 py-1.5 text-sm text-ink hover:bg-surface-2";

function BarRow({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="w-20 truncate text-muted">{label}</span>
      <div className="h-2 flex-1 rounded-full bg-surface-2">
        <div className="h-2 rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right text-muted">{value}</span>
    </div>
  );
}

export default function HomeOverview() {
  const { session } = useAuth();
  const houses = useMemo(
    () => houseOptionsFor(session?.role ?? "", session?.houseIds ?? []),
    [session?.role, session?.houseIds],
  );
  const [houseId, setHouseId] = useState(houses[0]?.house_id ?? "");
  const [range, setRange] = useState<DashboardRange>("24h");

  const summaryQ = useQuery({
    queryKey: ["c4", "summary", houseId, range],
    queryFn: () => fetchDashboardSummary({ houseId, range }),
    enabled: Boolean(houseId),
    refetchInterval: POLL_MS,
  });

  const data = summaryQ.data?.data;
  const unavailable = summaryQ.data?.meta.unavailable ?? [];
  const sev = data?.alerts_by_severity;
  const sevMax = Math.max(
    sev?.critical ?? 0,
    sev?.high ?? 0,
    sev?.medium ?? 0,
    sev?.low ?? 0,
    1,
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Home Overview</h1>
          <p className="mt-1 text-sm text-muted">Welcome back, {session?.email}.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select className={selectCls} value={houseId} onChange={(e) => setHouseId(e.target.value)}>
            {houses.map((h) => (
              <option key={h.house_id} value={h.house_id}>
                {h.name}
              </option>
            ))}
          </select>
          <select
            className={selectCls}
            value={range}
            onChange={(e) => setRange(e.target.value as DashboardRange)}
          >
            <option value="24h">24h</option>
            <option value="7d">7d</option>
            <option value="30d">30d</option>
          </select>
          <Link to="/home/settings" className={linkCls}>
            Settings
          </Link>
          <Link to="/alerts" className={linkCls}>
            Alerts
          </Link>
        </div>
      </div>

      {unavailable.length > 0 && (
        <div className="rounded-md border border-warning/30 bg-warning-soft px-3 py-2 text-xs text-warning">
          {unavailable.includes("c1")
            ? "Device manager is unreachable. House and feed counts may be incomplete."
            : "Some sources are temporarily unavailable. Counts may be incomplete."}
        </div>
      )}

      {summaryQ.isError && (
        <ErrorState
          message={`Could not load summary: ${summaryQ.error instanceof ApiError ? summaryQ.error.message : "Error"}`}
          onRetry={() => summaryQ.refetch()}
        />
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KpiTile label="Open alerts" value={data?.kpis.open_alerts ?? "—"} />
        <KpiTile
          label="Feeds online"
          value={unavailable.includes("c1") ? "Unavailable" : (data ? `${data.kpis.feeds_online}/${data.kpis.feeds_total}` : "—")}
        />
        <KpiTile label="Alerts in range" value={data?.kpis.alerts ?? "—"} />
        <KpiTile label="Clips classified" value={data?.kpis.clips_classified ?? "—"} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Alerts by severity" subtitle={`Range ${range}`}>
          {sev ? (
            <div className="space-y-2">
              <BarRow label="critical" value={sev.critical} max={sevMax} />
              <BarRow label="high" value={sev.high} max={sevMax} />
              <BarRow label="medium" value={sev.medium} max={sevMax} />
              <BarRow label="low" value={sev.low} max={sevMax} />
            </div>
          ) : (
            <p className="text-sm text-muted">No data</p>
          )}
        </ChartCard>

        <ChartCard title="Top detections">
          {(data?.detections_top?.length ?? 0) === 0 ? (
            <p className="text-sm text-muted">No detections in range</p>
          ) : (
            <div className="space-y-2">
              {data!.detections_top.map((d) => (
                <BarRow
                  key={d.label}
                  label={d.label}
                  value={d.count}
                  max={data!.detections_top[0]?.count ?? 1}
                />
              ))}
            </div>
          )}
        </ChartCard>
      </div>

      <section className="rounded-xl border border-border bg-surface shadow-card">
        <div className="border-b border-border px-4 py-3 text-sm font-semibold text-ink">
          Recent alerts
        </div>
        <ul className="divide-y divide-border/60">
          {(data?.recent_alerts ?? []).length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-muted">No recent alerts</li>
          )}
          {(data?.recent_alerts ?? []).map((a) => (
            <li key={a.alert_id} className="flex items-center gap-3 px-4 py-3 text-sm">
              <SeverityBadge severity={a.severity as "critical" | "high" | "medium" | "low"} />
              <Link to={`/alerts/${a.alert_id}`} className="font-medium text-ink hover:underline">
                {a.alert_type_code}
              </Link>
              <span className="text-muted">{a.room_name ?? a.house_name}</span>
              <span className="ml-auto text-xs text-muted">
                {a.triggered_at ? new Date(a.triggered_at).toLocaleString() : ""}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
