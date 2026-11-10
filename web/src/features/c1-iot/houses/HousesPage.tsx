/** Houses and Rooms (/iot/houses): houses table with add/edit/delete; click a house to manage its rooms. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { c1Keys, deleteHouse, listHouses, type House } from "../../../api/c1";
import { useAuth } from "../../../auth/AuthProvider";
import { Button, ConfirmDialog, DataTable, EmptyState, ErrorState, useToasts, type Column } from "../../../shared";
import { errorText } from "../format";
import { HouseForm } from "./HouseForm";
import { RoomsPanel } from "./RoomsPanel";

export default function HousesPage() {
  const { session } = useAuth();
  const queryClient = useQueryClient();
  const toasts = useToasts();
  const houses = useQuery({ queryKey: c1Keys.houses(), queryFn: () => listHouses() });
  const [form, setForm] = useState<{ house?: House } | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<House | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["c1", "houses"] });
  }

  const remove = useMutation({
    mutationFn: (h: House) => deleteHouse(h.house_id),
    onSuccess: (_v, h) => {
      toasts.push({ tone: "success", message: `House “${h.name}” deleted.` });
      setDeleteError(null);
      if (expanded === h.house_id) setExpanded(null);
      refresh();
    },
    onError: (e) => {
      setDeleteError(errorText(e));
      toasts.push({ tone: "error", message: errorText(e), ttl: 7000 });
      refresh();
    },
  });

  const columns: Column<House>[] = [
    {
      key: "name",
      header: "House",
      render: (h) => (
        <button
          type="button"
          className="text-left font-medium text-ink hover:underline"
          aria-expanded={expanded === h.house_id}
          onClick={(e) => {
            e.stopPropagation();
            setExpanded((cur) => (cur === h.house_id ? null : h.house_id));
          }}
        >
          <span aria-hidden="true" className="mr-1 text-muted">
            {expanded === h.house_id ? "▾" : "▸"}
          </span>
          {h.name}
        </button>
      ),
      sortValue: (h) => h.name.toLowerCase(),
    },
    { key: "address", header: "Address", render: (h) => h.address || <span className="text-muted">—</span> },
    { key: "tz", header: "Timezone", render: (h) => h.timezone, sortValue: (h) => h.timezone },
    {
      key: "counts",
      header: "Rooms / feeds",
      render: (h) =>
        h.room_count === undefined && h.feed_count === undefined ? (
          <span className="text-muted">—</span>
        ) : (
          `${h.room_count ?? "—"} / ${h.feed_count ?? "—"}`
        ),
    },
    {
      key: "actions",
      header: "",
      className: "text-right",
      render: (h) => (
        <span className="inline-flex gap-1" onClick={(e) => e.stopPropagation()}>
          <Button variant="ghost" onClick={() => setForm({ house: h })}>
            Edit
          </Button>
          <Button variant="ghost" onClick={() => setDeleting(h)}>
            Delete
          </Button>
        </span>
      ),
    },
  ];

  const expandedHouse = houses.data?.data.find((h) => h.house_id === expanded);

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Houses and Rooms</h1>
        {!form && <Button onClick={() => setForm({})}>+ Add house</Button>}
      </div>

      {form && (
        <HouseForm
          key={form.house?.house_id ?? "new"}
          house={form.house}
          needsTenant={session?.role === "cloud_staff"}
          onCancel={() => setForm(null)}
          onSaved={(h) => {
            toasts.push({ tone: "success", message: form.house ? `House “${h.name}” saved.` : `House “${h.name}” added.` });
            setForm(null);
            if (!form.house) setExpanded(h.house_id);
            refresh();
          }}
        />
      )}

      {deleteError && (
        <p role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
          {deleteError}
        </p>
      )}

      {houses.isPending ? (
        <div className="space-y-2" aria-label="Loading houses">
          {[0, 1].map((i) => (
            <div key={i} className="h-10 animate-pulse rounded bg-surface-2" />
          ))}
        </div>
      ) : houses.isError ? (
        <ErrorState message={`Could not load houses: ${errorText(houses.error)}`} onRetry={() => houses.refetch()} />
      ) : houses.data.data.length === 0 ? (
        <EmptyState
          title="No houses yet"
          description="Add a house, then its rooms, before registering feeds."
          action={!form ? <Button onClick={() => setForm({})}>+ Add house</Button> : undefined}
        />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={houses.data.data}
            rowKey={(h) => h.house_id}
            onRowClick={(h) => setExpanded((cur) => (cur === h.house_id ? null : h.house_id))}
          />
          {expandedHouse ? (
            <RoomsPanel key={expandedHouse.house_id} house={expandedHouse} />
          ) : (
            <p className="text-xs text-muted">Click a house to see and manage its rooms.</p>
          )}
        </>
      )}

      <ConfirmDialog
        open={!!deleting}
        title="Delete house?"
        message={deleting ? `Delete “${deleting.name}”? A house with enabled feeds cannot be deleted.` : ""}
        confirmLabel="Delete"
        destructive
        onCancel={() => setDeleting(null)}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting);
          setDeleting(null);
        }}
      />
    </div>
  );
}
