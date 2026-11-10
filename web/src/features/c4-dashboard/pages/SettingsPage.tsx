/**
 * Services & Settings (C4-12): toggles, quiet hours, sensitivity, emergency contacts.
 */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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
  SaveBar,
  SortableList,
  useToasts,
  type SortableItem,
} from "../../../shared";
import { houseOptionsFor } from "../houseOptions";

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

function toTimeInput(isoOrHm: string | null): string {
  if (!isoOrHm) return "";
  // API may return "22:00:00" or "22:00"
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
      <ErrorState message="No houses: Your account has no house_ids. Ask cloud staff to assign houses, or wait for C1 houses." />
    );
  }

  return (
    <div className="space-y-6 pb-16">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Services & Settings</h1>
          <p className="mt-1 text-sm text-slate-500">
            Quiet hours and contacts drive C2 alerts. House list uses seed IDs until C1 houses API.
          </p>
        </div>
        <label className="text-sm text-slate-600">
          House{" "}
          <select
            className="ml-1 rounded border border-slate-300 bg-white px-2 py-1.5 text-sm"
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
        <ErrorState message={`Could not load settings: ${settingsQ.error instanceof ApiError ? settingsQ.error.message : "Error"}`} onRetry={() => settingsQ.refetch()} />
      )}

      {draft && (
        <section className="space-y-4 rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="text-sm font-semibold text-slate-800">Enabled services</h2>
          <div className="grid gap-2 sm:grid-cols-2">
            {ALL_SERVICES.map((s) => (
              <label
                key={s.code}
                className="flex cursor-pointer items-start gap-2 rounded border border-slate-100 px-3 py-2 hover:bg-slate-50"
              >
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={draft.enabled_services.includes(s.code)}
                  onChange={() => toggleService(s.code)}
                />
                <span>
                  <span className="block text-sm font-medium text-slate-800">{s.label}</span>
                  <span className="text-xs text-slate-500">{s.hint}</span>
                </span>
              </label>
            ))}
          </div>

          <div className="grid gap-4 sm:grid-cols-3">
            <label className="text-sm text-slate-600">
              Quiet start
              <input
                type="time"
                className="mt-1 block w-full rounded border border-slate-300 px-2 py-1.5"
                value={toTimeInput(draft.quiet_start)}
                onChange={(e) =>
                  setDraft({ ...draft, quiet_start: fromTimeInput(e.target.value) })
                }
              />
            </label>
            <label className="text-sm text-slate-600">
              Quiet end
              <input
                type="time"
                className="mt-1 block w-full rounded border border-slate-300 px-2 py-1.5"
                value={toTimeInput(draft.quiet_end)}
                onChange={(e) =>
                  setDraft({ ...draft, quiet_end: fromTimeInput(e.target.value) })
                }
              />
            </label>
            <fieldset className="text-sm text-slate-600">
              <legend className="mb-1">Sensitivity</legend>
              <div className="flex gap-2">
                {(["low", "medium", "high"] as Sensitivity[]).map((s) => (
                  <button
                    key={s}
                    type="button"
                    onClick={() => setDraft({ ...draft, sensitivity: s })}
                    className={`rounded px-3 py-1.5 capitalize ${
                      draft.sensitivity === s
                        ? "bg-slate-900 text-white"
                        : "border border-slate-300 text-slate-700 hover:bg-slate-50"
                    }`}
                  >
                    {s}
                  </button>
                ))}
              </div>
            </fieldset>
          </div>
        </section>
      )}

      <section className="space-y-3 rounded-lg border border-slate-200 bg-white p-4">
        <h2 className="text-sm font-semibold text-slate-800">Emergency contacts</h2>
        {contactsQ.isError && (
          <ErrorState message={`Could not load contacts: ${contactsQ.error instanceof ApiError ? contactsQ.error.message : "Error"}`} onRetry={() => contactsQ.refetch()} />
        )}
        {sortable.length > 0 && (
          <div className="space-y-2">
            <SortableList
              items={sortable}
              onChange={(items) => reorder.mutate(items.map((i) => i.id))}
            />
            <ul className="space-y-1">
              {(contactsQ.data ?? []).map((c) => (
                <li key={c.contact_id} className="flex justify-end">
                  <button
                    type="button"
                    className="text-xs text-red-600 hover:underline"
                    onClick={() => setDeleteId(c.contact_id)}
                  >
                    Remove {c.name}
                  </button>
                </li>
              ))}
            </ul>
          </div>
        )}
        {(contactsQ.data?.length ?? 0) < 5 && (
          <form
            className="grid gap-2 border-t border-slate-100 pt-3 sm:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              addContact.mutate();
            }}
          >
            <input
              required
              placeholder="Name"
              className="rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={contactForm.name}
              onChange={(e) => setContactForm({ ...contactForm, name: e.target.value })}
            />
            <input
              required
              type="email"
              placeholder="Email"
              className="rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={contactForm.email}
              onChange={(e) => setContactForm({ ...contactForm, email: e.target.value })}
            />
            <input
              placeholder="Phone (optional)"
              className="rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={contactForm.phone}
              onChange={(e) => setContactForm({ ...contactForm, phone: e.target.value })}
            />
            <select
              className="rounded border border-slate-300 px-2 py-1.5 text-sm"
              value={contactForm.contact_type}
              onChange={(e) =>
                setContactForm({ ...contactForm, contact_type: e.target.value as ContactType })
              }
            >
              {CONTACT_TYPES.map((t) => (
                <option key={t} value={t}>
                  {t}
                </option>
              ))}
            </select>
            <button
              type="submit"
              disabled={addContact.isPending}
              className="rounded bg-slate-900 px-3 py-1.5 text-sm text-white hover:bg-slate-700 sm:col-span-2"
            >
              {addContact.isPending ? "Adding…" : "Add contact"}
            </button>
          </form>
        )}
      </section>

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
        message="They will stop receiving alert emails for this house after the next C2 subscription sync."
        confirmLabel="Remove"
        destructive
        onConfirm={() => deleteId && removeContact.mutate(deleteId)}
        onCancel={() => setDeleteId(null)}
      />
    </div>
  );
}
