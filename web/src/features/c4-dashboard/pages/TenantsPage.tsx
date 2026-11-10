/**
 * Tenants & Users admin (C4-14). Cloud-staff only.
 * House multi-select uses seed house IDs until C1 GET /houses ships (REPLACE_WHEN_C1).
 */

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createTenant,
  createTenantUser,
  fetchTenantUsers,
  fetchTenants,
  patchUser,
  type AdminRole,
  type AdminUser,
  type Tenant,
} from "../../../api/c4";
import { ApiError } from "../../../api/http";
import {
  ConfirmDialog,
  DataTable,
  EmptyState,
  ErrorState,
  useToasts,
  type Column,
} from "../../../shared";
import { SEED_HOUSES, houseLabel } from "../houseOptions";

const ROLES: AdminRole[] = ["house_owner", "iot_staff", "cloud_staff"];

export default function TenantsPage() {
  const toasts = useToasts();
  const qc = useQueryClient();
  const tenantsQ = useQuery({ queryKey: ["c4", "tenants"], queryFn: fetchTenants });
  const [selected, setSelected] = useState<Tenant | null>(null);
  const [showCreateTenant, setShowCreateTenant] = useState(false);
  const [tenantForm, setTenantForm] = useState({ name: "", timezone: "America/Los_Angeles" });
  const [showCreateUser, setShowCreateUser] = useState(false);
  const [userForm, setUserForm] = useState({
    email: "",
    password: "",
    role: "house_owner" as AdminRole,
    display_name: "",
    house_ids: [] as string[],
  });
  const [confirm, setConfirm] = useState<{
    user: AdminUser;
    action: "deactivate" | "unlock";
  } | null>(null);

  const usersQ = useQuery({
    queryKey: ["c4", "tenant-users", selected?.tenant_id],
    queryFn: () => fetchTenantUsers(selected!.tenant_id),
    enabled: Boolean(selected),
  });

  const housesForTenant = useMemo(() => {
    if (!selected) return [];
    // REPLACE_WHEN_C1: filter seed by tenant name alias heuristic
    const alias =
      selected.name.toLowerCase().includes("sunrise")
        ? "sunrise"
        : selected.name.toLowerCase().includes("acme")
          ? "acme"
          : null;
    if (!alias) return SEED_HOUSES; // new tenants: show all seed until C1
    return SEED_HOUSES.filter((h) => h.tenant_alias === alias);
  }, [selected]);

  const createTenantM = useMutation({
    mutationFn: () => createTenant(tenantForm),
    onSuccess: (t) => {
      qc.invalidateQueries({ queryKey: ["c4", "tenants"] });
      setShowCreateTenant(false);
      setTenantForm({ name: "", timezone: "America/Los_Angeles" });
      setSelected(t);
      toasts.push({ tone: "success", message: `Tenant ${t.name} created` });
    },
    onError: (e: unknown) => {
      toasts.push({
        tone: "error",
        message: e instanceof ApiError ? e.message : "Create tenant failed",
      });
    },
  });

  const createUserM = useMutation({
    mutationFn: () =>
      createTenantUser(selected!.tenant_id, {
        email: userForm.email.trim(),
        password: userForm.password,
        role: userForm.role,
        display_name: userForm.display_name.trim() || undefined,
        house_ids: userForm.house_ids,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["c4", "tenant-users", selected?.tenant_id] });
      setShowCreateUser(false);
      setUserForm({
        email: "",
        password: "",
        role: "house_owner",
        display_name: "",
        house_ids: [],
      });
      toasts.push({ tone: "success", message: "User created" });
    },
    onError: (e: unknown) => {
      toasts.push({
        tone: "error",
        message: e instanceof ApiError ? e.message : "Create user failed",
      });
    },
  });

  const patchM = useMutation({
    mutationFn: ({ user, action }: { user: AdminUser; action: "deactivate" | "unlock" }) =>
      patchUser(user.user_id, action === "deactivate" ? { is_active: false } : { unlock: true }),
    onSuccess: (_d, vars) => {
      qc.invalidateQueries({ queryKey: ["c4", "tenant-users", selected?.tenant_id] });
      setConfirm(null);
      toasts.push({
        tone: "success",
        message: vars.action === "deactivate" ? "User deactivated" : "User unlocked",
      });
    },
    onError: (e: unknown) => {
      toasts.push({
        tone: "error",
        message: e instanceof ApiError ? e.message : "Update failed",
      });
    },
  });

  const tenantCols: Column<Tenant>[] = [
    { key: "name", header: "Name", render: (r) => r.name, sortValue: (r) => r.name },
    { key: "tz", header: "Timezone", render: (r) => r.timezone },
    { key: "status", header: "Status", render: (r) => r.status },
    {
      key: "created",
      header: "Created",
      render: (r) => (r.created_at ? new Date(r.created_at).toLocaleDateString() : "—"),
    },
  ];

  const userCols: Column<AdminUser>[] = [
    { key: "email", header: "Email", render: (r) => r.email, sortValue: (r) => r.email },
    { key: "role", header: "Role", render: (r) => r.role },
    {
      key: "houses",
      header: "Houses",
      render: (r) =>
        r.house_ids.length ? r.house_ids.map(houseLabel).join(", ") : "—",
    },
    {
      key: "active",
      header: "Active",
      render: (r) => (r.is_active ? "yes" : "no"),
    },
    {
      key: "actions",
      header: "",
      render: (r) => (
        <div className="flex justify-end gap-2">
          <button
            type="button"
            className="text-xs text-slate-600 hover:underline"
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
              className="text-xs text-red-600 hover:underline"
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

  if (tenantsQ.isError) {
    return (
      <ErrorState message={`Could not load tenants: ${tenantsQ.error instanceof ApiError ? tenantsQ.error.message : "Error"}`} onRetry={() => tenantsQ.refetch()} />
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Tenants & Users</h1>
          <p className="mt-1 text-sm text-slate-500">
            Cloud-staff admin. House options use seed IDs until C1 houses API.
          </p>
        </div>
        <button
          type="button"
          className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700"
          onClick={() => setShowCreateTenant(true)}
        >
          New tenant
        </button>
      </div>

      <DataTable
        columns={tenantCols}
        rows={tenantsQ.data ?? []}
        rowKey={(r) => r.tenant_id}
        onRowClick={(r) => setSelected(r)}
        empty={<EmptyState title="No tenants" description="Create the first tenant to get started." />}
      />

      {selected && (
        <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="text-sm font-semibold text-slate-800">
              Users · {selected.name}
            </h2>
            <button
              type="button"
              className="rounded border border-slate-300 px-2 py-1 text-xs hover:bg-slate-50"
              onClick={() => setShowCreateUser(true)}
            >
              Add user
            </button>
          </div>
          {usersQ.isError && (
            <ErrorState message={`Could not load users: ${usersQ.error instanceof ApiError ? usersQ.error.message : "Error"}`} onRetry={() => usersQ.refetch()} />
          )}
          <DataTable
            columns={userCols}
            rows={usersQ.data ?? []}
            rowKey={(r) => r.user_id}
            empty={<EmptyState title="No users" description="Add a user for this tenant." />}
          />
        </section>
      )}

      {showCreateTenant && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30">
          <form
            className="w-full max-w-md space-y-3 rounded-lg bg-white p-4 shadow-lg"
            onSubmit={(e) => {
              e.preventDefault();
              createTenantM.mutate();
            }}
          >
            <h3 className="text-sm font-semibold">Create tenant</h3>
            <input
              required
              placeholder="Name"
              className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={tenantForm.name}
              onChange={(e) => setTenantForm({ ...tenantForm, name: e.target.value })}
            />
            <input
              required
              placeholder="Timezone"
              className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={tenantForm.timezone}
              onChange={(e) => setTenantForm({ ...tenantForm, timezone: e.target.value })}
            />
            <div className="flex justify-end gap-2">
              <button type="button" className="text-sm" onClick={() => setShowCreateTenant(false)}>
                Cancel
              </button>
              <button
                type="submit"
                disabled={createTenantM.isPending}
                className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white"
              >
                Create
              </button>
            </div>
          </form>
        </div>
      )}

      {showCreateUser && selected && (
        <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30">
          <form
            className="w-full max-w-md space-y-3 rounded-lg bg-white p-4 shadow-lg"
            onSubmit={(e) => {
              e.preventDefault();
              createUserM.mutate();
            }}
          >
            <h3 className="text-sm font-semibold">Add user · {selected.name}</h3>
            <input
              required
              type="email"
              placeholder="Email"
              className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={userForm.email}
              onChange={(e) => setUserForm({ ...userForm, email: e.target.value })}
            />
            <input
              required
              type="password"
              minLength={10}
              placeholder="Password (≥10, letters+digits)"
              className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={userForm.password}
              onChange={(e) => setUserForm({ ...userForm, password: e.target.value })}
            />
            <input
              placeholder="Display name"
              className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={userForm.display_name}
              onChange={(e) => setUserForm({ ...userForm, display_name: e.target.value })}
            />
            <select
              className="w-full rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={userForm.role}
              onChange={(e) => setUserForm({ ...userForm, role: e.target.value as AdminRole })}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
            <fieldset className="text-sm">
              <legend className="mb-1 text-slate-600">Houses (seed until C1)</legend>
              <div className="max-h-32 space-y-1 overflow-y-auto rounded border border-slate-200 p-2">
                {housesForTenant.map((h) => (
                  <label key={h.house_id} className="flex items-center gap-2">
                    <input
                      type="checkbox"
                      checked={userForm.house_ids.includes(h.house_id)}
                      onChange={() => {
                        const on = userForm.house_ids.includes(h.house_id);
                        setUserForm({
                          ...userForm,
                          house_ids: on
                            ? userForm.house_ids.filter((id) => id !== h.house_id)
                            : [...userForm.house_ids, h.house_id],
                        });
                      }}
                    />
                    {h.name}
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="flex justify-end gap-2">
              <button type="button" className="text-sm" onClick={() => setShowCreateUser(false)}>
                Cancel
              </button>
              <button
                type="submit"
                disabled={createUserM.isPending}
                className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white"
              >
                Create
              </button>
            </div>
          </form>
        </div>
      )}

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
