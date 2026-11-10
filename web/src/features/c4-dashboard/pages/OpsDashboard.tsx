/** System Dashboard (C4-13): cloud_staff KPIs + charts. */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  fetchDashboardSummary,
  fetchTenants,
  type DashboardRange,
} from "../../../api/c4";
import { ApiError } from "../../../api/http";
import {
  ChartCard,
  ErrorState,
  FilterBar,
  KpiTile,
  SeverityBadge,
} from "../../../shared";
import { SEED_HOUSES } from "../houseOptions";

const POLL_MS = 15_000;

function BarRow({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="w-24 truncate text-slate-600">{label}</span>
      <div className="h-2 flex-1 rounded bg-slate-100">
        <div className="h-2 rounded bg-slate-700" style={{ width: `${pct}%` }} />
      </div>
      <span className="w-8 text-right text-slate-500">{value}</span>
    </div>
  );
}

export default function OpsDashboard() {
  const [range, setRange] = useState<DashboardRange>("24h");
  const [tenantId, setTenantId] = useState("");
  const [houseId, setHouseId] = useState("");

  const tenantsQ = useQuery({ queryKey: ["c4", "tenants"], queryFn: fetchTenants });

  const houses = useMemo(() => {
    if (!tenantId) return SEED_HOUSES;
    const tenant = tenantsQ.data?.find((t) => t.tenant_id === tenantId);
    if (!tenant) return SEED_HOUSES;
    const alias = tenant.name.toLowerCase().includes("sunrise")
      ? "sunrise"
      : tenant.name.toLowerCase().includes("acme")
        ? "acme"
        : null;
    if (!alias) return SEED_HOUSES;
    return SEED_HOUSES.filter((h) => h.tenant_alias === alias);
  }, [tenantId, tenantsQ.data]);

  const summaryQ = useQuery({
    queryKey: ["c4", "summary", "ops", range, tenantId, houseId],
    queryFn: () =>
      fetchDashboardSummary({
        range,
        tenantId: tenantId || undefined,
        houseId: houseId || undefined,
      }),
    refetchInterval: POLL_MS,
  });

  const data = summaryQ.data?.data;
  const unavailable = summaryQ.data?.meta.unavailable ?? [];
  const sev = data?.alerts_by_severity;
  const sevMax = Math.max(sev?.critical ?? 0, sev?.high ?? 0, sev?.medium ?? 0, sev?.low ?? 0, 1);
  const dayMax = Math.max(...(data?.alerts_by_day.map((d) => d.count) ?? [0]), 1);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-900">System Dashboard</h1>
        <p className="mt-1 text-sm text-slate-500">
          Live summary across tenants. C1 feeds unavailable until C1 ships; C4-09 rollup deferred.
        </p>
      </div>

      <FilterBar
        onReset={() => {
          setRange("24h");
          setTenantId("");
          setHouseId("");
        }}
      >
        <select
          className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
          value={range}
          onChange={(e) => setRange(e.target.value as DashboardRange)}
        >
          <option value="24h">24h</option>
          <option value="7d">7d</option>
          <option value="30d">30d</option>
        </select>
        <select
          className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
          value={tenantId}
          onChange={(e) => {
            setTenantId(e.target.value);
            setHouseId("");
          }}
        >
          <option value="">All tenants</option>
          {(tenantsQ.data ?? []).map((t) => (
            <option key={t.tenant_id} value={t.tenant_id}>
              {t.name}
            </option>
          ))}
        </select>
        <select
          className="rounded border border-slate-300 bg-white px-2 py-1 text-sm"
          value={houseId}
          onChange={(e) => setHouseId(e.target.value)}
        >
          <option value="">All houses</option>
          {houses.map((h) => (
            <option key={h.house_id} value={h.house_id}>
              {h.name}
            </option>
          ))}
        </select>
      </FilterBar>

      {unavailable.length > 0 && (
        <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          Unavailable: {unavailable.join(", ")}
        </div>
      )}

      {summaryQ.isError && (
        <ErrorState message={`Could not load summary: ${summaryQ.error instanceof ApiError ? summaryQ.error.message : "Error"}`} onRetry={() => summaryQ.refetch()} />
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KpiTile label="Houses" value={data?.kpis.houses ?? "—"} />
        <KpiTile
          label="Feeds online"
          value={data ? `${data.kpis.feeds_online}/${data.kpis.feeds_total}` : "—"}
          hint={unavailable.includes("c1") ? "C1 unavailable" : undefined}
        />
        <KpiTile label="Alerts" value={data?.kpis.alerts ?? "—"} />
        <KpiTile label="Clips classified" value={data?.kpis.clips_classified ?? "—"} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Alerts by severity">
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
        <ChartCard title="Alerts by day">
          {(data?.alerts_by_day?.length ?? 0) === 0 ? (
            <p className="text-sm text-slate-400">No daily buckets</p>
          ) : (
            <div className="space-y-2">
              {data!.alerts_by_day.map((d) => (
                <BarRow key={d.date} label={d.date.slice(5)} value={d.count} max={dayMax} />
              ))}
            </div>
          )}
        </ChartCard>
        <ChartCard title="Top detections" subtitle="by label">
          {(data?.detections_top?.length ?? 0) === 0 ? (
            <p className="text-sm text-slate-400">No detections</p>
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
        <ChartCard title="Recent alerts">
          <ul className="divide-y divide-slate-100">
            {(data?.recent_alerts ?? []).length === 0 && (
              <li className="py-4 text-center text-sm text-slate-400">None</li>
            )}
            {(data?.recent_alerts ?? []).map((a) => (
              <li key={a.alert_id} className="flex items-center gap-2 py-2 text-sm">
                <SeverityBadge severity={a.severity as "critical" | "high" | "medium" | "low"} />
                <Link to={`/alerts/${a.alert_id}`} className="hover:underline">
                  {a.alert_type_code}
                </Link>
                <span className="ml-auto text-xs text-slate-400">{a.house_name}</span>
              </li>
            ))}
          </ul>
        </ChartCard>
      </div>
    </div>
  );
}
