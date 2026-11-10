/** Tenant detail (/ops/tenants/:tenantId): users table + add user.
 *  Reached from TenantsPage rows. Cloud-staff only.
 */

import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createTenantUser,
  fetchTenantUsers,
  fetchTenants,
  patchUser,
  type AdminRole,
  type AdminUser,
} from "../../../api/c4";
import { ApiError } from "../../../api/http";
import {
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorState,
  Field,
  useToasts,
  type Column,
} from "../../../shared";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { SEED_HOUSES, houseLabel } from "../houseOptions";

const ROLES: AdminRole[] = ["house_owner", "iot_staff", "cloud_staff"];
const inputCls =
  "w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted";

export default function TenantDetailPage() {
  const { tenantId = "" } = useParams();
  const toasts = useToasts();
  const qc = useQueryClient();
  const tenantsQ = useQuery({ queryKey: ["c4", "tenants"], queryFn: fetchTenants });
  const tenant = tenantsQ.data?.find((t) => t.tenant_id === tenantId);

  const [showCreateUser, setShowCreateUser] = useState(false);
  const [userForm, setUserForm] = useState({
    email: "",
    password: "",
    role: "house_owner" as AdminRole,
    display_name: "",
    house_ids: [] as string[],
  });
  const [confirm, setConfirm] = useState<{ user: AdminUser; action: "deactivate" | "unlock" } | null>(null);

  const usersQ = useQuery({
    queryKey: ["c4", "tenant-users", tenantId],
    queryFn: () => fetchTenantUsers(tenantId),
  });

  const housesForTenant = useMemo(() => {
    if (!tenant) return [];
    const alias =
      tenant.name.toLowerCase().includes("sunrise") ? "sunrise" : tenant.name.toLowerCase().includes("acme") ? "acme" : null;
    if (!alias) return SEED_HOUSES;
    return SEED_HOUSES.filter((h) => h.tenant_alias === alias);
  }, [tenant]);

  const createUserM = useMutation({
    mutationFn: () =>
      createTenantUser(tenantId, {
        email: userForm.email.trim(),
        password: userForm.password,
        role: userForm.role,
        display_name: userForm.display_name.trim() || undefined,
        house_ids: userForm.house_ids,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["c4", "tenant-users", tenantId] });
      setShowCreateUser(false);
      setUserForm({ email: "", password: "", role: "house_owner", display_name: "", house_ids: [] });
      toasts.push({ tone: "success", message: "User created" });
    },
    onError: (e: unknown) => {
      toasts.push({ tone: "error", message: e instanceof ApiError ? e.message : "Create user failed" });
    },
  });

  const patchM = useMutation({
    mutationFn: ({ user, action }: { user: AdminUser; action: "deactivate" | "unlock" }) =>
      patchUser(user.user_id, action === "deactivate" ? { is_active: false } : { unlock: true }),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ["c4", "tenant-users", tenantId] });
      setConfirm(null);
      toasts.push({ tone: "success", message: vars.action === "deactivate" ? "User deactivated" : "User unlocked" });
    },
    onError: (e: unknown) => {
      toasts.push({ tone: "error", message: e instanceof ApiError ? e.message : "Update failed" });
    },
  });

  const userCols: Column<AdminUser>[] = [
    { key: "email", header: "Email", render: (r) => <span className="font-medium text-ink">{r.email}</span>, sortValue: (r) => r.email },
    { key: "role", header: "Role", render: (r) => <span className="text-muted">{r.role}</span> },
    {
      key: "houses",
      header: "Houses",
      render: (r) =>
        r.house_ids.length ? <span className="text-muted">{r.house_ids.map(houseLabel).join(", ")}</span> : <span className="text-muted">—</span>,
    },
    {
      key: "active",
      header: "Active",
      render: (r) =>
        r.is_active ? (
          <span className="inline-flex items-center rounded-full border border-success/30 bg-success-soft px-2 py-0.5 text-xs font-medium text-success">
            Active
          </span>
        ) : (
          <span className="inline-flex items-center rounded-full border border-border bg-surface-2 px-2 py-0.5 text-xs font-medium text-muted">
            Inactive
          </span>
        ),
    },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <div className="flex justify-end gap-3">
          <button
            type="button"
            className="text-xs text-muted hover:text-ink hover:underline"
            onClick={(e) => {
              e.stopPropagation();
              setConfirm({ user: r, action: "unlock" });
            }}
          >
            Unlock
          </button>
          {r.is_active && (
            <button
              type="button"
              className="text-xs text-danger hover:underline"
              onClick={(e) => {
                e.stopPropagation();
                setConfirm({ user: r, action: "deactivate" });
              }}
            >
              Deactivate
            </button>
          )}
        </div>
      ),
    },
  ];

  if (tenantsQ.isError || (tenantsQ.data && !tenant)) {
    return (
      <div className="space-y-4">
        <Link to="/ops/tenants" className="text-sm text-muted hover:underline">← Tenants</Link>
        <ErrorState message="This tenant does not exist." />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <Link to="/ops/tenants" className="text-sm text-muted hover:underline">← Tenants</Link>

      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">{tenant?.name ?? "Tenant"}</h1>
          <p className="mt-1 text-sm text-muted">{tenant?.timezone}</p>
        </div>
        <Button onClick={() => setShowCreateUser(true)}>Add user</Button>
      </div>

      {usersQ.isError && (
        <ErrorState
          message={`Could not load users: ${usersQ.error instanceof ApiError ? usersQ.error.message : "Error"}`}
          onRetry={() => usersQ.refetch()}
        />
      )}

      <DataTable
        columns={userCols}
        rows={usersQ.data ?? []}
        rowKey={(r) => r.user_id}
        empty={<EmptyState title="No users" description="Add a user for this tenant." />}
      />

      <Dialog open={showCreateUser} onOpenChange={setShowCreateUser}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add user · {tenant?.name}</DialogTitle>
            <DialogDescription>They will be able to sign in with the role and houses you assign.</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-3"
            onSubmit={(e) => {
              e.preventDefault();
              createUserM.mutate();
            }}
          >
            <Field label="Email" name="u-email">
              <input id="u-email" required type="email" className={inputCls} value={userForm.email} onChange={(e) => setUserForm({ ...userForm, email: e.target.value })} />
            </Field>
            <Field label="Password" name="u-pw">
              <input id="u-pw" required type="password" minLength={10} className={inputCls} value={userForm.password} onChange={(e) => setUserForm({ ...userForm, password: e.target.value })} />
            </Field>
            <Field label="Display name" name="u-name">
              <input id="u-name" className={inputCls} value={userForm.display_name} onChange={(e) => setUserForm({ ...userForm, display_name: e.target.value })} />
            </Field>
            <Field label="Role" name="u-role">
              <select id="u-role" className={inputCls} value={userForm.role} onChange={(e) => setUserForm({ ...userForm, role: e.target.value as AdminRole })}>
                {ROLES.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
            </Field>
            <fieldset className="text-sm">
              <legend className="mb-1.5 text-muted">Houses</legend>
              <div className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-border bg-surface-2 p-2.5">
                {housesForTenant.map((h) => {
                  const on = userForm.house_ids.includes(h.house_id);
                  return (
                    <label key={h.house_id} className="flex cursor-pointer items-center gap-2 rounded px-1 py-1 hover:bg-surface">
                      <input
                        type="checkbox"
                        checked={on}
                        onChange={() => {
                          setUserForm({
                            ...userForm,
                            house_ids: on
                              ? userForm.house_ids.filter((id) => id !== h.house_id)
                              : [...userForm.house_ids, h.house_id],
                          });
                        }}
                      />
                      <span className="text-sm text-ink">{h.name}</span>
                    </label>
                  );
                })}
              </div>
            </fieldset>
            <div className="flex justify-end gap-2 pt-1">
              <Button type="button" variant="secondary" onClick={() => setShowCreateUser(false)}>Cancel</Button>
              <Button type="submit" disabled={createUserM.isPending}>
                {createUserM.isPending ? "Creating…" : "Create"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <ConfirmDialog
        open={Boolean(confirm)}
        title={confirm?.action === "deactivate" ? "Deactivate user?" : "Unlock user?"}
        message={
          confirm?.action === "deactivate"
            ? `${confirm.user.email} will no longer be able to sign in.`
            : `Clear lockout for ${confirm?.user.email ?? ""}.`
        }
        confirmLabel={confirm?.action === "deactivate" ? "Deactivate" : "Unlock"}
        destructive={confirm?.action === "deactivate"}
        onConfirm={() => confirm && patchM.mutate(confirm)}
        onCancel={() => setConfirm(null)}
      />
    </div>
  );
}
