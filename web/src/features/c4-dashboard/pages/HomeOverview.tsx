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

function BarRow({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="w-20 truncate text-slate-600">{label}</span>
      <div className="h-2 flex-1 rounded bg-slate-100">
        <div className="h-2 rounded bg-slate-700" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right text-slate-500">{value}</span>
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
          <h1 className="text-2xl font-semibold text-slate-900">Home Overview</h1>
          <p className="mt-1 text-sm text-slate-500">
            Welcome, {session?.email}. Live from C2/C3; C1 feeds show unavailable until C1 ships.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <select
            className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
            value={houseId}
            onChange={(e) => setHouseId(e.target.value)}
          >
            {houses.map((h) => (
              <option key={h.house_id} value={h.house_id}>
                {h.name}
              </option>
            ))}
          </select>
          <select
            className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
            value={range}
            onChange={(e) => setRange(e.target.value as DashboardRange)}
          >
            <option value="24h">24h</option>
            <option value="7d">7d</option>
            <option value="30d">30d</option>
          </select>
          <Link to="/home/settings" className="rounded border border-slate-300 px-2 py-1.5 text-sm hover:bg-slate-50">
            Settings
          </Link>
          <Link to="/alerts" className="rounded border border-slate-300 px-2 py-1.5 text-sm hover:bg-slate-50">
            Alerts
          </Link>
        </div>
      </div>

      {unavailable.length > 0 && (
        <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Unavailable sources: {unavailable.join(", ")}
        </div>
      )}

      {summaryQ.isError && (
        <ErrorState message={`Could not load summary: ${summaryQ.error instanceof ApiError ? summaryQ.error.message : "Error"}`} onRetry={() => summaryQ.refetch()} />
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KpiTile label="Open alerts" value={data?.kpis.open_alerts ?? "—"} />
        <KpiTile
          label="Feeds online"
          value={
            data
              ? `${data.kpis.feeds_online}/${data.kpis.feeds_total}`
              : "—"
          }
          hint={unavailable.includes("c1") ? "C1 unavailable" : undefined}
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
            <p className="text-sm text-slate-400">No data</p>
          )}
        </ChartCard>

        <ChartCard title="Top detections">
          {(data?.detections_top?.length ?? 0) === 0 ? (
            <p className="text-sm text-slate-400">No detections in range</p>
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

      <section className="rounded-lg border border-slate-200 bg-white">
        <div className="border-b border-slate-100 px-4 py-2 text-sm font-semibold text-slate-800">
          Recent alerts
        </div>
        <ul className="divide-y divide-slate-100">
          {(data?.recent_alerts ?? []).length === 0 && (
            <li className="px-4 py-6 text-center text-sm text-slate-400">No recent alerts</li>
          )}
          {(data?.recent_alerts ?? []).map((a) => (
            <li key={a.alert_id} className="flex items-center gap-3 px-4 py-2 text-sm">
              <SeverityBadge severity={a.severity as "critical" | "high" | "medium" | "low"} />
              <Link to={`/alerts/${a.alert_id}`} className="font-medium text-slate-800 hover:underline">
                {a.alert_type_code}
              </Link>
              <span className="text-slate-500">{a.room_name ?? a.house_name}</span>
              <span className="ml-auto text-xs text-slate-400">
                {a.triggered_at ? new Date(a.triggered_at).toLocaleString() : ""}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
