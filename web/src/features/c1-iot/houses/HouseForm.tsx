/** Add / edit house form. cloud_staff must pick the tenant when adding (C1 §3.1). */

import { useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { createHouse, updateHouse, type House } from "../../../api/c1";
import { fetchTenants } from "../../../api/c4";
import { Button, Field, FormPanel } from "../../../shared";
import { inputClass } from "../components";
import { errorText, serverFieldErrors } from "../format";

const FALLBACK_ZONES = [
  "America/Los_Angeles",
  "America/Denver",
  "America/Chicago",
  "America/New_York",
  "America/Phoenix",
  "Pacific/Honolulu",
  "America/Anchorage",
  "Europe/London",
  "Asia/Kolkata",
  "UTC",
];

function timeZones(): string[] {
  const intl = Intl as unknown as { supportedValuesOf?: (key: string) => string[] };
  try {
    return intl.supportedValuesOf?.("timeZone") ?? FALLBACK_ZONES;
  } catch {
    return FALLBACK_ZONES;
  }
}

function browserZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "America/Los_Angeles";
  } catch {
    return "America/Los_Angeles";
  }
}

export interface HouseFormProps {
  house?: House;
  needsTenant: boolean;
  onSaved: (house: House) => void;
  onCancel: () => void;
}

export function HouseForm({ house, needsTenant, onSaved, onCancel }: HouseFormProps) {
  const editing = !!house;
  const [name, setName] = useState(house?.name ?? "");
  const [address, setAddress] = useState(house?.address ?? "");
  const [timezone, setTimezone] = useState(house?.timezone ?? browserZone());
  const [tenantId, setTenantId] = useState("");
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});

  const tenants = useQuery({
    queryKey: ["c4", "tenants"],
    queryFn: fetchTenants,
    enabled: needsTenant && !editing,
  });

  const save = useMutation({
    mutationFn: () =>
      editing
        ? updateHouse(house.house_id, { name: name.trim(), address: address.trim() || null, timezone: timezone.trim() })
        : createHouse({
            name: name.trim(),
            timezone: timezone.trim(),
            ...(address.trim() ? { address: address.trim() } : {}),
            ...(needsTenant && tenantId ? { tenant_id: tenantId } : {}),
          }),
    onSuccess: onSaved,
  });

  const server = serverFieldErrors(save.error);
  const errors = { ...server, ...clientErrors };
  const generalError = save.error && Object.keys(server).length === 0 ? errorText(save.error) : null;

  function submit() {
    const errs: Record<string, string> = {};
    if (!name.trim()) errs.name = "Name is required.";
    if (!timezone.trim()) errs.timezone = "Timezone is required.";
    if (needsTenant && !editing && !tenantId) errs.tenant_id = "Choose a tenant.";
    setClientErrors(errs);
    if (!Object.keys(errs).length) save.mutate();
  }

  return (
    <FormPanel
      title={editing ? `Edit ${house.name}` : "Add house"}
      onSubmit={submit}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending}>
            {save.isPending ? "Saving…" : editing ? "Save" : "Add house"}
          </Button>
        </>
      }
    >
      <div className="grid gap-3 sm:grid-cols-2">
        {needsTenant && !editing && (
          <Field label="Tenant" name="house-tenant" error={errors.tenant_id}>
            <select id="house-tenant" className={inputClass} value={tenantId} onChange={(e) => setTenantId(e.target.value)}>
              <option value="">Choose…</option>
              {tenants.data?.map((t) => (
                <option key={t.tenant_id} value={t.tenant_id}>
                  {t.name}
                </option>
              ))}
            </select>
          </Field>
        )}
        <Field label="Name" name="house-name" error={errors.name}>
          <input id="house-name" className={inputClass} value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Timezone (IANA)" name="house-timezone" error={errors.timezone}>
          <input
            id="house-timezone"
            className={inputClass}
            list="c1-timezones"
            value={timezone}
            maxLength={40}
            onChange={(e) => setTimezone(e.target.value)}
          />
          <datalist id="c1-timezones">
            {timeZones().map((z) => (
              <option key={z} value={z} />
            ))}
          </datalist>
        </Field>
        <Field label="Address (optional)" name="house-address" error={errors.address}>
          <input
            id="house-address"
            className={inputClass}
            value={address}
            maxLength={200}
            onChange={(e) => setAddress(e.target.value)}
          />
        </Field>
      </div>
      {generalError && (
        <p role="alert" className="text-sm text-danger">
          {generalError}
        </p>
      )}
    </FormPanel>
  );
}
