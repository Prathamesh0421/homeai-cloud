/** System Dashboard (C4-13): cloud_staff KPIs + charts + 24h severity timeline. */

import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import {
  fetchDashboardSummary,
  fetchTenants,
  type DashboardRange,
} from "../../../api/c4";
import { ApiError } from "../../../api/http";
import {
  ChartCard,
  ErrorState,
  FilterSelect,
  KpiTile,
  SeverityBadge,
  SEVERITY_HEX,
  type Severity,
} from "../../../shared";
import { Button } from "@/components/ui/button";
import { SEED_HOUSES } from "../houseOptions";

const POLL_MS = 15_000;

const RANGE_PRESETS: { value: DashboardRange; label: string }[] = [
  { value: "24h", label: "24h" },
  { value: "7d", label: "7d" },
  { value: "30d", label: "30d" },
];

const SOURCE_NAME: Record<string, string> = {
  c1: "Device manager",
  c2: "Alert service",
  c3: "Data service",
};

function sourceNames(codes: string[]): string {
  return codes.map((c) => SOURCE_NAME[c] ?? c.toUpperCase()).join(", ");
}

function BarRow({ label, value, max }: { label: string; value: number; max: number }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-2 text-sm">
      <span className="w-24 truncate text-muted">{label}</span>
      <div className="h-2 flex-1 rounded-full bg-surface-2">
        <div className="h-2 rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </div>
      <span className="tnum w-8 text-right text-muted">{value}</span>
    </div>
  );
}

/** 24h detection timeline: one row per house, ticks colored by severity. */
function SeverityTimeline({ alerts }: { alerts: { alert_id: string; house_name: string | null; severity: string; triggered_at: string | null }[] }) {
  const byHouse = useMemo(() => {
    const map = new Map<string, { house: string; ticks: { id: string; sev: Severity; at: number }[] }>();
    for (const a of alerts) {
      if (!a.triggered_at) continue;
      const house = a.house_name ?? "Unknown house";
      if (!map.has(house)) map.set(house, { house, ticks: [] });
      const t = new Date(a.triggered_at).getTime();
      map.get(house)!.ticks.push({ id: a.alert_id, sev: a.severity as Severity, at: t });
    }
    return [...map.values()];
  }, [alerts]);

  if (byHouse.length === 0) {
    return <p className="text-sm text-muted">No alerts in range.</p>;
  }

  const now = Date.now();
  const spanMs = 24 * 60 * 60 * 1000;
  const start = now - spanMs;

  return (
    <div className="space-y-2.5">
      {byHouse.map((row) => (
        <div key={row.house}>
          <div className="mb-1 text-xs font-medium text-muted">{row.house}</div>
          <div className="relative h-7 rounded-md bg-surface-2">
            {row.ticks.map((t) => {
              const left = Math.max(0, Math.min(100, ((t.at - start) / spanMs) * 100));
              return (
                <span
                  key={t.id}
                  title={new Date(t.at).toLocaleString()}
                  className="absolute top-1 h-5 w-1 rounded-full"
                  style={{ left: `${left}%`, backgroundColor: SEVERITY_HEX[t.sev] }}
                />
              );
            })}
          </div>
        </div>
      ))}
      <div className="flex items-center gap-3 pt-1 text-[11px] text-muted">
        <span>-24h</span>
        <span className="flex-1" />
        <span>now</span>
      </div>
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
  const c1Down = unavailable.includes("c1");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight text-ink">System dashboard</h1>
        <p className="mt-1 text-sm text-muted">Live activity across all tenants and houses.</p>
      </div>

      {/* Filters: range presets + tenant/house selects */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-md border border-border-strong p-0.5">
          {RANGE_PRESETS.map((p) => (
            <button
              key={p.value}
              type="button"
              onClick={() => setRange(p.value)}
              className={`rounded px-3 py-1.5 text-sm transition-colors ${
                range === p.value ? "bg-primary text-white" : "text-muted hover:text-ink"
              }`}
            >
              {p.label}
            </button>
          ))}
        </div>
        <FilterSelect
          label="Tenant"
          value={tenantId}
          onValueChange={(v) => {
            setTenantId(v);
            setHouseId("");
          }}
          options={(tenantsQ.data ?? []).map((t) => ({ value: t.tenant_id, label: t.name }))}
          placeholder="All tenants"
          className="w-[12rem]"
        />
        <FilterSelect
          label="House"
          value={houseId}
          onValueChange={setHouseId}
          options={houses.map((h) => ({ value: h.house_id, label: h.name }))}
          placeholder="All houses"
          className="w-[12rem]"
        />
      </div>

      {unavailable.length > 0 && (
        <div className="flex items-start justify-between gap-3 rounded-md border border-warning/30 bg-warning-soft px-3 py-2.5 text-sm text-warning">
          <span>
            {sourceNames(unavailable)} is unreachable.{" "}
            {c1Down ? "House and feed counts may be incomplete." : "Some counts may be incomplete."}
          </span>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => summaryQ.refetch()}
            disabled={summaryQ.isFetching}
          >
            <RefreshCw className={`h-3.5 w-3.5 ${summaryQ.isFetching ? "animate-spin" : ""}`} />
            Retry
          </Button>
        </div>
      )}

      {summaryQ.isError && (
        <ErrorState
          message={`Could not load summary: ${summaryQ.error instanceof ApiError ? summaryQ.error.message : "Error"}`}
          onRetry={() => summaryQ.refetch()}
        />
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <KpiTile label="Houses" value={c1Down ? "Unavailable" : (data?.kpis.houses ?? "—")} />
        <KpiTile
          label="Feeds online"
          value={c1Down ? "Unavailable" : (data ? `${data.kpis.feeds_online}/${data.kpis.feeds_total}` : "—")}
          tone={
            c1Down
              ? "default"
              : data && data.kpis.feeds_online < data.kpis.feeds_total
                ? "warning"
                : "default"
          }
          hint={
            !c1Down && data && data.kpis.feeds_online < data.kpis.feeds_total
              ? `${data.kpis.feeds_total - data.kpis.feeds_online} feed${data.kpis.feeds_total - data.kpis.feeds_online === 1 ? "" : "s"} offline`
              : undefined
          }
        />
        <KpiTile label="Alerts" value={data?.kpis.alerts ?? "—"} />
        <KpiTile label="Clips classified" value={data?.kpis.clips_classified ?? "—"} />
      </div>

      {/* Lead with the 24h severity timeline — the memorable element for an audio-detection product. */}
      <ChartCard title="24h detection timeline" subtitle="alerts by house, colored by severity">
        <SeverityTimeline alerts={data?.recent_alerts ?? []} />
      </ChartCard>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Alerts by severity">
          {sev && (sev.critical + sev.high + sev.medium + sev.low) > 0 ? (
            <div className="space-y-2">
              <BarRow label="critical" value={sev.critical} max={sevMax} />
              <BarRow label="high" value={sev.high} max={sevMax} />
              <BarRow label="medium" value={sev.medium} max={sevMax} />
              <BarRow label="low" value={sev.low} max={sevMax} />
            </div>
          ) : (
            <p className="text-sm text-muted">No alerts in the last {range === "24h" ? "24h" : range}.</p>
          )}
        </ChartCard>
        <ChartCard title="Alerts by day">
          {(data?.alerts_by_day?.length ?? 0) === 0 ? (
            <p className="text-sm text-muted">No daily buckets</p>
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
            <p className="text-sm text-muted">No detections</p>
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
          <ul className="divide-y divide-border/60">
            {(data?.recent_alerts ?? []).length === 0 && (
              <li className="py-4 text-center text-sm text-muted">None</li>
            )}
            {(data?.recent_alerts ?? []).map((a) => (
              <li key={a.alert_id} className="flex items-center gap-2 py-2.5 text-sm">
                <SeverityBadge severity={a.severity as "critical" | "high" | "medium" | "low"} />
                <Link to={`/alerts/${a.alert_id}`} className="font-medium text-ink hover:underline">
                  {a.alert_type_code}
                </Link>
                <span className="ml-auto text-xs text-muted">{a.house_name}</span>
              </li>
            ))}
          </ul>
        </ChartCard>
      </div>
    </div>
  );
}
