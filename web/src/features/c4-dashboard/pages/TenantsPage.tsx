/**
 * Tenants & Users admin (C4-14). Cloud-staff only.
 * List view with house counts; rows open the tenant detail page.
 * House counts use seed house IDs until C1 GET /houses ships (REPLACE_WHEN_C1).
 */

import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { createTenant, fetchTenants, type Tenant } from "../../../api/c4";
import { ApiError } from "../../../api/http";
import { DataTable, EmptyState, ErrorState, useToasts, type Column } from "../../../shared";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Field } from "../../../shared";
import { SEED_HOUSES } from "../houseOptions";

const inputCls =
  "w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted";

export default function TenantsPage() {
  const toasts = useToasts();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const tenantsQ = useQuery({ queryKey: ["c4", "tenants"], queryFn: fetchTenants });
  const [showCreateTenant, setShowCreateTenant] = useState(false);
  const [tenantForm, setTenantForm] = useState({ name: "", timezone: "America/Los_Angeles" });

  const createTenantM = useMutation({
    mutationFn: () => createTenant(tenantForm),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["c4", "tenants"] });
      setShowCreateTenant(false);
      setTenantForm({ name: "", timezone: "America/Los_Angeles" });
      navigate(`/ops/tenants/${t.tenant_id}`);
      toasts.push({ tone: "success", message: `Tenant ${t.name} created` });
    },
    onError: (e: unknown) => {
      toasts.push({
        tone: "error",
        message: e instanceof ApiError ? e.message : "Create tenant failed",
      });
    },
  });

  const tenantCols: Column<Tenant>[] = [
    { key: "name", header: "Name", render: (r) => <span className="font-medium text-ink">{r.name}</span>, sortValue: (r) => r.name },
    {
      key: "houses",
      header: "Houses",
      render: (r) => {
        const alias =
          r.name.toLowerCase().includes("sunrise") ? "sunrise" : r.name.toLowerCase().includes("acme") ? "acme" : null;
        const count = alias ? SEED_HOUSES.filter((h) => h.tenant_alias === alias).length : "—";
        return <span className="tnum text-muted">{count}</span>;
      },
    },
    { key: "tz", header: "Timezone", render: (r) => <span className="text-muted">{r.timezone}</span> },
    { key: "status", header: "Status", render: (r) => <span className="text-muted capitalize">{r.status}</span> },
    {
      key: "created",
      header: "Created",
      render: (r) => (r.created_at ? new Date(r.created_at).toLocaleDateString() : "—"),
    },
  ];

  if (tenantsQ.isError) {
    return (
      <ErrorState
        message={`Could not load tenants: ${tenantsQ.error instanceof ApiError ? tenantsQ.error.message : "Error"}`}
        onRetry={() => tenantsQ.refetch()}
      />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Tenants & users</h1>
          <p className="mt-1 text-sm text-muted">Manage tenants and the people who belong to them.</p>
        </div>
        <Button onClick={() => setShowCreateTenant(true)}>New tenant</Button>
      </div>

      <DataTable
        columns={tenantCols}
        rows={tenantsQ.data ?? []}
        rowKey={(r) => r.tenant_id}
        onRowClick={(r) => navigate(`/ops/tenants/${r.tenant_id}`)}
        empty={<EmptyState title="No tenants" description="Create the first tenant to get started." />}
      />

      <Dialog open={showCreateTenant} onOpenChange={setShowCreateTenant}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Create tenant</DialogTitle>
            <DialogDescription>A tenant groups houses and the people who manage them.</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              createTenantM.mutate();
            }}
          >
            <Field label="Name" name="t-name">
              <input id="t-name" required className={inputCls} value={tenantForm.name} onChange={(e) => setTenantForm({ ...tenantForm, name: e.target.value })} />
            </Field>
            <Field label="Timezone" name="t-tz">
              <input id="t-tz" required className={inputCls} value={tenantForm.timezone} onChange={(e) => setTenantForm({ ...tenantForm, timezone: e.target.value })} />
            </Field>
            <div className="flex justify-end gap-2 pt-1">
              <Button type="button" variant="secondary" onClick={() => setShowCreateTenant(false)}>Cancel</Button>
              <Button type="submit" disabled={createTenantM.isPending}>
                {createTenantM.isPending ? "Creating…" : "Create"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
    </div>
  );
}
