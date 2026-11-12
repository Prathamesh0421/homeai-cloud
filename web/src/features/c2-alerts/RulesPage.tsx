/** Alert Rules (/ops/alert-rules, cloud_staff): tenant defaults and house rules, email sync.
 *  Rules are grouped by tenant with collapsible headers; enable is an inline
 *  switch; edit opens a side Sheet; min confidence shows a value + tiny bar;
 *  false-pos column hides when all zeros; "Create tenant defaults" tooltip
 *  explains the disabled state.
 */

import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight } from "lucide-react";
import {
  c2Keys,
  createTenantDefaults,
  listAlertTypes,
  listRules,
  syncSubscriptions,
  updateRule,
  type AlertRule,
  type RuleFilters,
  type SyncResult,
} from "../../api/c2";
import { fetchTenants } from "../../api/c4";
import { ApiError } from "../../api/http";
import {
  ConfirmDialog,
  EmptyState,
  ErrorState,
  FilterBar,
  Pagination,
  SeverityBadge,
  useToasts,
} from "../../shared";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import {
  Sheet,
  SheetContent,
} from "@/components/ui/sheet";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { labelText, percent } from "./format";
import { RuleForm, UUID } from "./RuleForm";

const PAGE_SIZE = 100;
const selectClass = "rounded-md border border-border-strong bg-surface px-2.5 py-1.5 text-sm text-ink";

/** Min confidence as a value with a tiny bar. */
function ConfidenceMini({ value }: { value: number }) {
  const pct = Math.round(value * 100);
  return (
    <span className="inline-flex items-center gap-2">
      <span className="tnum w-8 text-right text-xs text-muted">{percent(value)}</span>
      <span className="h-1.5 w-12 overflow-hidden rounded-full bg-surface-2">
        <span className="block h-full rounded-full bg-accent" style={{ width: `${pct}%` }} />
      </span>
    </span>
  );
}

function filtersFrom(params: URLSearchParams): RuleFilters {
  const enabled = params.get("enabled");
  return {
    tenantId: params.get("tenant") ?? undefined,
    houseId: params.get("house") ?? undefined,
    alertTypeCode: params.get("type") ?? undefined,
    isEnabled: enabled === null ? undefined : enabled === "true",
    page: Number(params.get("page") ?? 1) || 1,
    pageSize: PAGE_SIZE,
  };
}

function short(id: string): string {
  return `…${id.slice(-4)}`;
}

export function syncSummary(r: SyncResult): string {
  const parts = [`${r.subscribed} subscribed`, `${r.pending} waiting for email confirmation`];
  if (r.unsubscribed) parts.push(`${r.unsubscribed} unsubscribed (used the link in an email)`);
  if (r.removed) parts.push(`${r.removed} removed`);
  if (r.failed) parts.push(`${r.failed} house(s) failed, retried in 5 min`);
  return `${r.topics} house topic(s): ${parts.join(", ")}`;
}

type Editing = { mode: "create" } | { mode: "edit"; rule: AlertRule } | null;

export default function RulesPage() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => filtersFrom(params), [params]);
  const queryClient = useQueryClient();
  const { push } = useToasts();
  const [editing, setEditing] = useState<Editing>(null);
  const [disabling, setDisabling] = useState<AlertRule | null>(null);
  const [lastSync, setLastSync] = useState<SyncResult | null>(null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  // The house filter is typed: it applies only when empty or a whole UUID (the API rejects a
  // partial one with 422), not on every keystroke.
  const [houseText, setHouseText] = useState(params.get("house") ?? "");

  const rules = useQuery({
    queryKey: c2Keys.rules(filters),
    queryFn: () => listRules(filters),
    placeholderData: keepPreviousData,
  });
  const types = useQuery({ queryKey: c2Keys.alertTypes(), queryFn: listAlertTypes, staleTime: 3_600_000 });
  const tenants = useQuery({ queryKey: ["c4", "tenants"], queryFn: fetchTenants, staleTime: 300_000 });
  const tenantName = (id: string) => tenants.data?.find((t) => t.tenant_id === id)?.name ?? short(id);

  const reload = () => queryClient.invalidateQueries({ queryKey: ["c2", "rules"] });

  function setFilter(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    if (name !== "page") next.delete("page");
    setParams(next, { replace: true });
  }

  const toggle = useMutation({
    mutationFn: (rule: AlertRule) => updateRule(rule.rule_id, rule.version, { is_enabled: !rule.is_enabled }),
    onSuccess: (rule) => {
      push({ tone: "success", message: rule.is_enabled ? "Rule enabled" : "Rule disabled" });
      setDisabling(null);
      reload();
    },
    onError: (error) => {
      setDisabling(null);
      const stale = error instanceof ApiError && error.status === 412;
      push({
        tone: "warning",
        message: stale ? "This rule was changed by someone else; reloaded the list." : error.message,
      });
      reload();
    },
  });

  const defaults = useMutation({
    mutationFn: () => createTenantDefaults(filters.tenantId!),
    onSuccess: ({ created }) => {
      push({
        tone: "success",
        message: created ? `Created ${created} default rule(s)` : "This tenant already has every default rule",
      });
      reload();
    },
    onError: (error) => push({ tone: "error", message: error.message }),
  });

  const sync = useMutation({
    mutationFn: () => syncSubscriptions(filters.houseId),
    onSuccess: (result) => {
      setLastSync(result);
      push({ tone: result.failed ? "warning" : "success", message: "Email subscriptions synced" });
    },
    onError: (error) => {
      const busy = error instanceof ApiError && error.code === "sync_in_progress";
      push({
        tone: busy ? "info" : "error",
        message: busy ? "A sync is already running; try again in a few seconds." : error.message,
      });
    },
  });

  const rows = useMemo(() => rules.data?.data ?? [], [rules.data]);
  const anyFalsePos = rows.some((r) => r.false_positive_count_30d > 0);

  // Group rules by tenant.
  const groups = useMemo(() => {
    const map = new Map<string, AlertRule[]>();
    for (const r of rows) {
      if (!map.has(r.tenant_id)) map.set(r.tenant_id, []);
      map.get(r.tenant_id)!.push(r);
    }
    return [...map.entries()];
  }, [rows]);

  function toggleCollapse(tenantId: string) {
    setCollapsed((cur) => {
      const next = new Set(cur);
      if (next.has(tenantId)) next.delete(tenantId);
      else next.add(tenantId);
      return next;
    });
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Alert rules</h1>
        <div className="flex gap-2">
          <Button variant="secondary" disabled={sync.isPending} onClick={() => sync.mutate()}>
            {sync.isPending ? "Syncing…" : "Sync email subscriptions"}
          </Button>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <span tabIndex={0} className="inline-block">
                  <Button
                    variant="secondary"
                    disabled={!filters.tenantId || defaults.isPending}
                    onClick={() => defaults.mutate()}
                  >
                    Create tenant defaults
                  </Button>
                </span>
              </TooltipTrigger>
              <TooltipContent>
                {!filters.tenantId
                  ? "Choose a tenant to create its default rules."
                  : "Add the standard default rules for this tenant."}
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
          <Button onClick={() => setEditing({ mode: "create" })}>New rule</Button>
        </div>
      </div>

      {lastSync && (
        <p role="status" className="rounded-md border border-border bg-surface px-3 py-2 text-sm text-ink shadow-card">
          {syncSummary(lastSync)}
          {lastSync.pending > 0 && " — contacts must click the confirmation link SNS emailed them."}
        </p>
      )}

      {/* Edit/create Sheet */}
      {editing && types.data && (
        <Sheet open onOpenChange={(o) => !o && setEditing(null)}>
          <SheetContent
            aria-label={editing.mode === "edit" ? `Edit rule: ${editing.rule.alert_type_name}` : "New alert rule"}
            className="w-full max-w-lg overflow-y-auto"
          >
            <div className="px-5 py-5">
              <RuleForm
                key={editing.mode === "edit" ? editing.rule.rule_id : "new"}
                rule={editing.mode === "edit" ? editing.rule : undefined}
                tenants={tenants.data ?? []}
                types={types.data}
                defaultTenantId={filters.tenantId}
                onSaved={() => {
                  setEditing(null);
                  reload();
                }}
                onCancel={() => setEditing(null)}
                onConflict={reload}
              />
            </div>
          </SheetContent>
        </Sheet>
      )}

      <FilterBar
        onReset={() => {
          setHouseText("");
          setParams(new URLSearchParams(), { replace: true });
        }}
      >
        <label className="text-xs text-muted">
          Tenant{" "}
          <select className={selectClass} value={params.get("tenant") ?? ""} onChange={(e) => setFilter("tenant", e.target.value)}>
            <option value="">All</option>
            {tenants.data?.map((t) => (
              <option key={t.tenant_id} value={t.tenant_id}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-muted">
          House id{" "}
          <input
            className={selectClass}
            value={houseText}
            onChange={(e) => {
              const text = e.target.value;
              setHouseText(text);
              const id = text.trim();
              if (id === "" || UUID.test(id)) setFilter("house", id);
            }}
            aria-invalid={houseText.trim() !== "" && !UUID.test(houseText.trim())}
            placeholder="any"
          />
        </label>
        <label className="text-xs text-muted">
          Type{" "}
          <select className={selectClass} value={params.get("type") ?? ""} onChange={(e) => setFilter("type", e.target.value)}>
            <option value="">All</option>
            {types.data?.map((t) => (
              <option key={t.code} value={t.code}>
                {t.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-muted">
          Enabled{" "}
          <select className={selectClass} value={params.get("enabled") ?? ""} onChange={(e) => setFilter("enabled", e.target.value)}>
            <option value="">All</option>
            <option value="true">Enabled</option>
            <option value="false">Disabled</option>
          </select>
        </label>
      </FilterBar>

      {rules.isPending ? (
        <div className="py-8 text-center text-sm text-muted">Loading rules…</div>
      ) : rules.isError ? (
        <ErrorState message={`Could not load rules: ${rules.error.message}`} onRetry={() => rules.refetch()} />
      ) : rows.length === 0 ? (
        <EmptyState
          title="No rules"
          description={
            filters.tenantId
              ? "This tenant has no matching rules. Create its defaults, or add a house rule."
              : "No rules match these filters."
          }
        />
      ) : (
        <div className="space-y-4">
          {/* Sticky-ish header row legend */}
          <div className="hidden grid-cols-12 gap-2 px-3 text-xs font-medium uppercase tracking-wide text-muted sm:grid">
            <span className="col-span-2">Alert type</span>
            <span className="col-span-3">Applies to</span>
            <span className="col-span-2">Min conf.</span>
            <span className="col-span-2">Severity</span>
            {anyFalsePos && <span className="col-span-1 tnum">FP 30d</span>}
            <span className={`${anyFalsePos ? "col-span-2" : "col-span-3"} text-right`}>Actions</span>
          </div>

          {groups.map(([tenantId, tenantRules]) => {
            const isCollapsed = collapsed.has(tenantId);
            return (
              <section key={tenantId} className="overflow-hidden rounded-lg border border-border bg-surface shadow-card">
                <button
                  type="button"
                  onClick={() => toggleCollapse(tenantId)}
                  className="flex w-full items-center gap-2 border-b border-border bg-surface-2 px-3 py-2 text-left text-sm font-medium text-ink hover:bg-surface-2"
                >
                  {isCollapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
                  <span className="flex-1">{tenantName(tenantId)}</span>
                  <span className="tnum text-xs text-muted">{tenantRules.length} rule{tenantRules.length === 1 ? "" : "s"}</span>
                </button>
                {!isCollapsed && (
                  <ul className="divide-y divide-border">
                    {tenantRules.map((r) => (
                      <li
                        key={r.rule_id}
                        className="grid grid-cols-12 items-center gap-2 px-3 py-2.5 text-sm hover:bg-surface-2"
                      >
                        <span className="col-span-2">
                          <span className="block font-medium text-ink">{r.alert_type_name}</span>
                          <span className="block text-xs text-muted">{r.trigger_labels.map(labelText).join(", ")}</span>
                        </span>
                        <span className="col-span-3 text-muted" title={r.house_id ?? ""}>
                          {r.scope === "tenant_default"
                            ? "Tenant default"
                            : `House ${short(r.house_id ?? "")}${r.room_id ? ` · room ${short(r.room_id)}` : " · whole house"}`}
                        </span>
                        <span className="col-span-2"><ConfidenceMini value={r.min_confidence} /></span>
                        <span className="col-span-2 inline-flex items-center gap-1">
                          <SeverityBadge severity={r.effective_severity} />
                          {r.severity === null && <span className="text-xs text-muted">default</span>}
                        </span>
                        {anyFalsePos && <span className="col-span-1 tnum text-muted">{r.false_positive_count_30d}</span>}
                        <span
                          className={`${anyFalsePos ? "col-span-2" : "col-span-3"} flex items-center justify-end gap-2`}
                        >
                          <Button variant="ghost" size="sm" onClick={() => setEditing({ mode: "edit", rule: r })}>
                            Edit
                          </Button>
                          <Switch
                            checked={r.is_enabled}
                            disabled={toggle.isPending}
                            onCheckedChange={() => (r.is_enabled ? setDisabling(r) : toggle.mutate(r))}
                            aria-label={r.is_enabled ? "Disable rule" : "Enable rule"}
                          />
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </section>
            );
          })}

          <Pagination
            page={rules.data!.meta.page}
            pageSize={rules.data!.meta.page_size}
            total={rules.data!.meta.total}
            onChange={(p) => setFilter("page", String(p))}
          />
        </div>
      )}

      <ConfirmDialog
        open={disabling !== null}
        title="Disable this rule?"
        message={
          disabling?.scope === "house"
            ? "Detections in this house stop raising this alert from this rule; the tenant default applies again."
            : "Houses without their own rule stop raising this alert."
        }
        confirmLabel="Disable"
        destructive
        onConfirm={() => disabling && toggle.mutate(disabling)}
        onCancel={() => setDisabling(null)}
      />
    </div>
  );
}
