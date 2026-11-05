/** Alert Rules (/ops/alert-rules, cloud_staff): tenant defaults and house rules, email sync. */

import { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  Button,
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorState,
  FilterBar,
  Pagination,
  SeverityBadge,
  useToasts,
  type Column,
} from "../../shared";
import { labelText, percent } from "./format";
import { RuleForm, UUID } from "./RuleForm";

const PAGE_SIZE = 50;
const selectClass = "rounded border border-slate-300 bg-white px-2 py-1 text-sm text-slate-700";

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

  const columns: Column<AlertRule>[] = [
    {
      key: "type",
      header: "Alert type",
      render: (r) => <span className="font-medium text-slate-800">{r.alert_type_name}</span>,
      sortValue: (r) => r.alert_type_name,
    },
    {
      key: "scope",
      header: "Applies to",
      render: (r) =>
        r.scope === "tenant_default" ? (
          <span>Tenant default · {tenantName(r.tenant_id)}</span>
        ) : (
          <span title={r.house_id ?? ""}>
            House {short(r.house_id ?? "")}
            {r.room_id ? ` · room ${short(r.room_id)}` : " · whole house"}
          </span>
        ),
    },
    { key: "labels", header: "Labels", render: (r) => r.trigger_labels.map(labelText).join(", ") },
    {
      key: "conf",
      header: "Min conf.",
      render: (r) => percent(r.min_confidence),
      sortValue: (r) => r.min_confidence,
    },
    {
      key: "severity",
      header: "Severity",
      render: (r) => (
        <span className="inline-flex items-center gap-1">
          <SeverityBadge severity={r.effective_severity} />
          {r.severity === null && <span className="text-xs text-slate-400">default</span>}
        </span>
      ),
    },
    {
      key: "enabled",
      header: "Enabled",
      render: (r) =>
        r.is_enabled ? (
          <span className="text-emerald-700">✓ On</span>
        ) : (
          <span className="text-slate-500">✕ Off</span>
        ),
    },
    {
      key: "fp",
      header: "False pos. 30 d",
      render: (r) => r.false_positive_count_30d,
      sortValue: (r) => r.false_positive_count_30d,
    },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <span className="flex gap-1">
          <Button variant="ghost" onClick={() => setEditing({ mode: "edit", rule: r })}>
            Edit
          </Button>
          <Button
            variant="ghost"
            disabled={toggle.isPending}
            onClick={() => (r.is_enabled ? setDisabling(r) : toggle.mutate(r))}
          >
            {r.is_enabled ? "Disable" : "Enable"}
          </Button>
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-2xl font-semibold text-slate-900">Alert Rules</h1>
        <div className="flex gap-2">
          <Button variant="secondary" disabled={sync.isPending} onClick={() => sync.mutate()}>
            {sync.isPending ? "Syncing…" : "Sync email subscriptions"}
          </Button>
          <Button
            variant="secondary"
            disabled={!filters.tenantId || defaults.isPending}
            onClick={() => defaults.mutate()}
          >
            Create tenant defaults
          </Button>
          <Button onClick={() => setEditing({ mode: "create" })}>New rule</Button>
        </div>
      </div>
      {!filters.tenantId && (
        <p className="text-xs text-slate-500">Choose a tenant to create its default rules.</p>
      )}
      {lastSync && (
        <p role="status" className="rounded border border-slate-200 bg-white px-3 py-2 text-sm text-slate-700">
          {syncSummary(lastSync)}
          {lastSync.pending > 0 && " — contacts must click the confirmation link SNS emailed them."}
        </p>
      )}

      {editing && types.data && (
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
      )}

      <FilterBar
        onReset={() => {
          setHouseText("");
          setParams(new URLSearchParams(), { replace: true });
        }}
      >
        <label className="text-xs text-slate-500">
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
        <label className="text-xs text-slate-500">
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
        <label className="text-xs text-slate-500">
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
        <label className="text-xs text-slate-500">
          Enabled{" "}
          <select className={selectClass} value={params.get("enabled") ?? ""} onChange={(e) => setFilter("enabled", e.target.value)}>
            <option value="">All</option>
            <option value="true">Enabled</option>
            <option value="false">Disabled</option>
          </select>
        </label>
      </FilterBar>

      {rules.isPending ? (
        <div className="py-8 text-center text-sm text-slate-500">Loading rules…</div>
      ) : rules.isError ? (
        <ErrorState message={`Could not load rules: ${rules.error.message}`} onRetry={() => rules.refetch()} />
      ) : rules.data.data.length === 0 ? (
        <EmptyState
          title="No rules"
          description={
            filters.tenantId
              ? "This tenant has no matching rules. Create its defaults, or add a house rule."
              : "No rules match these filters."
          }
        />
      ) : (
        <>
          <DataTable columns={columns} rows={rules.data.data} rowKey={(r) => r.rule_id} />
          <Pagination
            page={rules.data.meta.page}
            pageSize={rules.data.meta.page_size}
            total={rules.data.meta.total}
            onChange={(p) => setFilter("page", String(p))}
          />
        </>
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
