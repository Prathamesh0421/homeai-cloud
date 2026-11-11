/**
 * Services & Settings (C4-12): toggles, quiet hours, sensitivity, emergency contacts.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { MoreHorizontal, Plus } from "lucide-react";
import {
  createContact,
  deleteContact,
  fetchContacts,
  fetchSettings,
  putSettings,
  reorderContacts,
  type ContactType,
  type EmergencyContact,
  type Sensitivity,
  type ServiceCode,
  type SettingsUpsert,
} from "../../../api/c4";
import { ApiError } from "../../../api/http";
import { useAuth } from "../../../auth/AuthProvider";
import {
  ConfirmDialog,
  ErrorState,
  Field,
  SaveBar,
  SortableList,
  useToasts,
  type SortableItem,
} from "../../../shared";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { houseOptionsFor } from "../houseOptions";

function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "") + (parts[1]?.[0] ?? "")).toUpperCase() || "?";
}

const ALL_SERVICES: { code: ServiceCode; label: string; hint: string }[] = [
  { code: "fire_safety", label: "Fire safety", hint: "Smoke / fire alarms" },
  { code: "distress", label: "Distress", hint: "Calls for help, screaming" },
  { code: "intrusion", label: "Intrusion", hint: "Break-in, glass break" },
  { code: "fall", label: "Fall", hint: "Fall detection" },
  { code: "wellness", label: "Wellness", hint: "Cough, illness cues" },
  { code: "presence", label: "Presence", hint: "Occupancy / footsteps" },
  { code: "pet", label: "Pet", hint: "Animal sounds" },
];

const CONTACT_TYPES: ContactType[] = ["family", "caregiver", "neighbor", "emergency_service"];

const inputCls =
  "rounded-md border border-border-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-muted";

function toTimeInput(isoOrHm: string | null): string {
  if (!isoOrHm) return "";
  return isoOrHm.slice(0, 5);
}

function fromTimeInput(hm: string): string | null {
  if (!hm.trim()) return null;
  return hm.length === 5 ? `${hm}:00` : hm;
}

export default function SettingsPage() {
  const { session } = useAuth();
  const toasts = useToasts();
  const qc = useQueryClient();

  const houses = useMemo(
    () => houseOptionsFor(session?.role ?? "", session?.houseIds ?? []),
    [session?.role, session?.houseIds],
  );
  const [houseId, setHouseId] = useState(houses[0]?.house_id ?? "");

  useEffect(() => {
    if (!houseId && houses[0]) setHouseId(houses[0].house_id);
  }, [houses, houseId]);

  const settingsQ = useQuery({
    queryKey: ["c4", "settings", houseId],
    queryFn: () => fetchSettings(houseId),
    enabled: Boolean(houseId),
  });
  const contactsQ = useQuery({
    queryKey: ["c4", "contacts", houseId],
    queryFn: () => fetchContacts(houseId),
    enabled: Boolean(houseId),
  });

  const [draft, setDraft] = useState<SettingsUpsert | null>(null);
  useEffect(() => {
    if (!settingsQ.data) return;
    setDraft({
      enabled_services: [...settingsQ.data.enabled_services],
      quiet_start: settingsQ.data.quiet_start,
      quiet_end: settingsQ.data.quiet_end,
      sensitivity: settingsQ.data.sensitivity,
    });
  }, [settingsQ.data]);

  const dirty = useMemo(() => {
    if (!draft || !settingsQ.data) return false;
    const a = settingsQ.data;
    return (
      JSON.stringify([...draft.enabled_services].sort()) !==
        JSON.stringify([...a.enabled_services].sort()) ||
      draft.quiet_start !== a.quiet_start ||
      draft.quiet_end !== a.quiet_end ||
      draft.sensitivity !== a.sensitivity
    );
  }, [draft, settingsQ.data]);

  const saveSettings = useMutation({
    mutationFn: () => putSettings(houseId, draft!),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["c4", "settings", houseId] });
      toasts.push({ tone: "success", message: "Settings saved" });
    },
    onError: (e: unknown) => {
      const msg = e instanceof ApiError ? e.message : "Save failed";
      toasts.push({ tone: "error", message: msg });
    },
  });

  const [contactForm, setContactForm] = useState({
    name: "",
    email: "",
    phone: "",
    contact_type: "family" as ContactType,
  });
  const [deleteId, setDeleteId] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);

  const addContact = useMutation({
    mutationFn: () =>
      createContact(houseId, {
        name: contactForm.name.trim(),
        email: contactForm.email.trim(),
        phone: contactForm.phone.trim() || undefined,
        contact_type: contactForm.contact_type,
      }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["c4", "contacts", houseId] });
      setContactForm({ name: "", email: "", phone: "", contact_type: "family" });
      setAddOpen(false);
      toasts.push({ tone: "success", message: "Contact added" });
    },
    onError: (e: unknown) => {
      const msg = e instanceof ApiError ? e.message : "Could not add contact";
      toasts.push({ tone: "error", message: msg });
    },
  });

  const removeContact = useMutation({
    mutationFn: (id: string) => deleteContact(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["c4", "contacts", houseId] });
      setDeleteId(null);
      toasts.push({ tone: "success", message: "Contact removed" });
    },
    onError: (e: unknown) => {
      toasts.push({
        tone: "error",
        message: e instanceof ApiError ? e.message : "Delete failed",
      });
    },
  });

  const reorder = useMutation({
    mutationFn: (ids: string[]) => reorderContacts(houseId, ids),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["c4", "contacts", houseId] }),
    onError: (e: unknown) => {
      toasts.push({
        tone: "error",
        message: e instanceof ApiError ? e.message : "Reorder failed",
      });
      qc.invalidateQueries({ queryKey: ["c4", "contacts", houseId] });
    },
  });

  function toggleService(code: ServiceCode) {
    if (!draft) return;
    const on = draft.enabled_services.includes(code);
    setDraft({
      ...draft,
      enabled_services: on
        ? draft.enabled_services.filter((c) => c !== code)
        : [...draft.enabled_services, code],
    });
  }

  const sortable: SortableItem[] = (contactsQ.data ?? []).map((c: EmergencyContact) => ({
    id: c.contact_id,
    label: `${c.name} · ${c.email} (${c.contact_type})`,
  }));

  if (!houses.length) {
    return (
      <ErrorState message="Your account is not linked to a house yet. Ask cloud staff to assign one." />
    );
  }

  return (
    <div className="space-y-6 pb-20">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">Services & Settings</h1>
          <p className="mt-1 text-sm text-muted">
            Choose which sounds trigger alerts, set quiet hours, and manage who gets notified.
          </p>
        </div>
        <label className="text-sm text-muted">
          House{" "}
          <select
            className="ml-1.5 rounded-md border border-border-strong bg-surface px-2.5 py-1.5 text-sm text-ink"
            value={houseId}
            onChange={(e) => setHouseId(e.target.value)}
          >
            {houses.map((h) => (
              <option key={h.house_id} value={h.house_id}>
                {h.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {settingsQ.isError && (
        <ErrorState
          message={`Could not load settings: ${settingsQ.error instanceof ApiError ? settingsQ.error.message : "Error"}`}
          onRetry={() => settingsQ.refetch()}
        />
      )}

      {draft && (
        <section className="space-y-5 rounded-xl border border-border bg-surface p-5 shadow-card">
          <div>
            <h2 className="text-sm font-semibold text-ink">Enabled services</h2>
            <p className="mt-0.5 text-xs text-muted">Toggle which sounds trigger alerts for this house.</p>
          </div>
          <ul className="divide-y divide-border rounded-lg border border-border">
            {ALL_SERVICES.map((s) => {
              const on = draft.enabled_services.includes(s.code);
              return (
                <li key={s.code} className="flex items-center gap-3 px-3 py-2.5">
                  <div className="flex-1">
                    <div className="text-sm font-medium text-ink">{s.label}</div>
                    <div className="text-xs text-muted">{s.hint}</div>
                  </div>
                  <Switch
                    checked={on}
                    onCheckedChange={() => toggleService(s.code)}
                    aria-label={`Enable ${s.label}`}
                  />
                </li>
              );
            })}
          </ul>

          <div className="grid gap-4 sm:grid-cols-3">
            <label className="text-sm text-muted">
              Quiet start
              <input
                type="time"
                className={`mt-1.5 block w-full ${inputCls}`}
                value={toTimeInput(draft.quiet_start)}
                onChange={(e) =>
                  setDraft({ ...draft, quiet_start: fromTimeInput(e.target.value) })
                }
              />
            </label>
            <label className="text-sm text-muted">
              Quiet end
              <input
                type="time"
                className={`mt-1.5 block w-full ${inputCls}`}
                value={toTimeInput(draft.quiet_end)}
                onChange={(e) => setDraft({ ...draft, quiet_end: fromTimeInput(e.target.value) })}
              />
            </label>
            <fieldset className="text-sm text-muted">
              <legend className="mb-1.5">Sensitivity</legend>
              <div className="inline-flex rounded-md border border-border-strong p-0.5">
                {(["low", "medium", "high"] as Sensitivity[]).map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setDraft({ ...draft, sensitivity: s })}
                    className={`rounded px-3 py-1.5 text-sm capitalize transition-colors ${
                      draft.sensitivity === s
                        ? "bg-primary text-white"
                        : "text-muted hover:text-ink"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
              <p className="mt-1.5 text-xs text-muted">
                Low raises the confidence needed to alert (fewer alerts); high lowers it (more alerts).
                Critical and high alerts bypass quiet hours.
              </p>
            </fieldset>
          </div>
        </section>
      )}

      <section className="space-y-3 rounded-xl border border-border bg-surface p-5 shadow-card">
        <div className="flex items-center justify-between">
          <div>
            <h2 className="text-sm font-semibold text-ink">Emergency contacts</h2>
            <p className="mt-0.5 text-xs text-muted">Notified in order when an alert fires. Drag to reorder.</p>
          </div>
          {(contactsQ.data?.length ?? 0) < 5 && (
            <Button variant="secondary" size="sm" onClick={() => setAddOpen(true)}>
              <Plus className="h-4 w-4" /> Add contact
            </Button>
          )}
        </div>
        {contactsQ.isError && (
          <ErrorState
            message={`Could not load contacts: ${contactsQ.error instanceof ApiError ? contactsQ.error.message : "Error"}`}
            onRetry={() => contactsQ.refetch()}
          />
        )}
        {sortable.length > 0 && (
          <SortableList
            items={sortable}
            onChange={(items) => reorder.mutate(items.map((i) => i.id))}
            positionLabel={(i) => (i === 0 ? "Notified first" : `Then #${i + 1}`)}
            renderRow={(item) => {
              const c = (contactsQ.data ?? []).find((x) => x.contact_id === item.id);
              if (!c) return <span className="text-sm text-ink">{item.label}</span>;
              return (
                <div className="flex items-center gap-3">
                  <Avatar className="h-8 w-8">
                    <AvatarFallback>{initials(c.name)}</AvatarFallback>
                  </Avatar>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm font-medium text-ink">{c.name}</div>
                    <div className="truncate text-xs text-muted">{c.email}</div>
                  </div>
                  <Badge variant="neutral" className="capitalize">{c.contact_type.replace("_", " ")}</Badge>
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <button
                        type="button"
                        className="rounded-md p-1.5 text-muted hover:bg-surface-2 hover:text-ink focus-visible:outline-none"
                        aria-label={`Actions for ${c.name}`}
                      >
                        <MoreHorizontal className="h-4 w-4" aria-hidden="true" />
                      </button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                      <DropdownMenuItem onSelect={() => setDeleteId(c.contact_id)} className="text-danger">
                        Remove
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
                </div>
              );
            }}
          />
        )}
        {sortable.length === 0 && !contactsQ.isError && (
          <p className="text-sm text-muted">No contacts yet. Add one to start receiving alert emails.</p>
        )}
      </section>

      <Dialog open={addOpen} onOpenChange={setAddOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Add emergency contact</DialogTitle>
            <DialogDescription>They will be notified in order when an alert fires for this house.</DialogDescription>
          </DialogHeader>
          <form
            className="grid gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              addContact.mutate();
            }}
          >
            <Field label="Name" name="c-name">
              <input id="c-name" required className={inputCls} value={contactForm.name} onChange={(e) => setContactForm({ ...contactForm, name: e.target.value })} />
            </Field>
            <Field label="Email" name="c-email">
              <input id="c-email" required type="email" className={inputCls} value={contactForm.email} onChange={(e) => setContactForm({ ...contactForm, email: e.target.value })} />
            </Field>
            <Field label="Phone (optional)" name="c-phone">
              <input id="c-phone" className={inputCls} value={contactForm.phone} onChange={(e) => setContactForm({ ...contactForm, phone: e.target.value })} />
            </Field>
            <Field label="Role" name="c-type">
              <select id="c-type" className={inputCls} value={contactForm.contact_type} onChange={(e) => setContactForm({ ...contactForm, contact_type: e.target.value as ContactType })}>
                {CONTACT_TYPES.map((t) => (
                  <option key={t} value={t}>{t.replace("_", " ")}</option>
                ))}
              </select>
            </Field>
            <div className="flex justify-end gap-2 pt-1">
              <Button type="button" variant="secondary" onClick={() => setAddOpen(false)}>Cancel</Button>
              <Button type="submit" disabled={addContact.isPending}>
                {addContact.isPending ? "Adding…" : "Add contact"}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      <SaveBar
        dirty={dirty}
        saving={saveSettings.isPending}
        onSave={() => saveSettings.mutate()}
        onDiscard={() => {
          if (!settingsQ.data) return;
          setDraft({
            enabled_services: [...settingsQ.data.enabled_services],
            quiet_start: settingsQ.data.quiet_start,
            quiet_end: settingsQ.data.quiet_end,
            sensitivity: settingsQ.data.sensitivity,
          });
        }}
      />

      <ConfirmDialog
        open={Boolean(deleteId)}
        title="Remove contact?"
        message="They will stop receiving alert emails for this house."
        confirmLabel="Remove"
        destructive
        onConfirm={() => deleteId && removeContact.mutate(deleteId)}
        onCancel={() => setDeleteId(null)}
      />
    </div>
  );
}
