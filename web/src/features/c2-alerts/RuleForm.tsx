/** Create / edit an alert rule (cloud_staff). Inline 422 errors, 409 duplicate, 412 stale version. */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  HOME_LABELS,
  SEVERITIES,
  createRule,
  getRule,
  updateRule,
  type AlertRule,
  type AlertType,
  type RuleCreate,
  type RuleUpdate,
  type Severity,
} from "../../api/c2";
import type { Tenant } from "../../api/c4";
import { ApiError } from "../../api/http";
import { Button, Field, FormPanel, fieldErrors, SEVERITY_LABEL, useToasts } from "../../shared";
import { labelText } from "./format";

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const inputClass = "w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-sm text-ink";

export interface FormState {
  scope: "tenant_default" | "house";
  tenantId: string;
  houseId: string;
  roomId: string;
  alertTypeCode: string;
  labels: string[];
  minConfidence: string; // "" -> the alert type's default
  severity: Severity | "";
  isEnabled: boolean;
}

function fromRule(rule: AlertRule): FormState {
  return {
    scope: rule.scope,
    tenantId: rule.tenant_id,
    houseId: rule.house_id ?? "",
    roomId: rule.room_id ?? "",
    alertTypeCode: rule.alert_type_code,
    labels: rule.trigger_labels,
    minConfidence: String(rule.min_confidence),
    severity: rule.severity ?? "",
    isEnabled: rule.is_enabled,
  };
}

/** Client-side checks the server would also make; it stays the authority (422 details). */
export function validate(f: FormState, editing: boolean): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!editing) {
    if (!f.alertTypeCode) errors.alert_type_code = "Choose an alert type";
    if (f.scope === "tenant_default" && !f.tenantId) errors.tenant_id = "Choose a tenant";
    if (f.scope === "house" && !UUID.test(f.houseId.trim())) errors.house_id = "Enter the house id (UUID)";
  }
  if (f.roomId.trim() && !UUID.test(f.roomId.trim())) errors.room_id = "Enter a room id (UUID) or leave empty";
  if (f.scope === "tenant_default" && f.roomId.trim()) errors.room_id = "Only a house rule can have a room";
  if (f.labels.length === 0) errors.trigger_labels = "Pick at least one label";
  if (f.minConfidence.trim()) {
    const n = Number(f.minConfidence);
    if (!(n >= 0 && n <= 1) || Math.round(n * 100) / 100 !== n) {
      errors.min_confidence = "A number from 0 to 1 with at most 2 decimals";
    }
  }
  return errors;
}

/**
 * Only what the user changed. The server re-checks a room through C1 whenever ``room_id`` is in
 * the body, so sending it unchanged would make every edit of a room rule depend on C1.
 */
export function changedFields(rule: AlertRule, f: FormState, minConfidence: number | undefined): RuleUpdate {
  const body: RuleUpdate = {};
  const sameLabels =
    f.labels.length === rule.trigger_labels.length && f.labels.every((l) => rule.trigger_labels.includes(l));
  if (!sameLabels) body.trigger_labels = f.labels;
  if (minConfidence !== undefined && minConfidence !== rule.min_confidence) body.min_confidence = minConfidence;
  const room = f.roomId.trim() || null;
  if (room !== rule.room_id) body.room_id = room;
  const severity = f.severity || null;
  if (severity !== rule.severity) body.severity = severity;
  if (f.isEnabled !== rule.is_enabled) body.is_enabled = f.isEnabled;
  return body;
}

export interface RuleFormProps {
  rule?: AlertRule; // edit when set
  tenants: Tenant[];
  types: AlertType[];
  defaultTenantId?: string;
  onSaved: (rule: AlertRule) => void;
  onCancel: () => void;
  /** Called after a 409 duplicate or 412 stale version so the list reloads. */
  onConflict: () => void;
}

export function RuleForm({ rule, tenants, types, defaultTenantId, onSaved, onCancel, onConflict }: RuleFormProps) {
  const editing = rule !== undefined;
  const { push } = useToasts();
  const [form, setForm] = useState<FormState>(() =>
    rule
      ? fromRule(rule)
      : {
          scope: "house",
          tenantId: defaultTenantId ?? "",
          houseId: "",
          roomId: "",
          alertTypeCode: "",
          labels: [],
          minConfidence: "",
          severity: "",
          isEnabled: true,
        },
  );
  const [version, setVersion] = useState(rule?.version ?? 0);
  const [clientErrors, setClientErrors] = useState<Record<string, string>>({});
  const [serverErrors, setServerErrors] = useState<Record<string, string[]>>({});

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((cur) => ({ ...cur, [key]: value }));

  function chooseType(code: string) {
    const type = types.find((t) => t.code === code);
    // A new rule starts from the type's label and threshold; the user can change both.
    setForm((cur) => ({
      ...cur,
      alertTypeCode: code,
      labels: type ? [type.trigger_label] : cur.labels,
      minConfidence: "",
    }));
  }

  const save = useMutation({
    mutationFn: async (f: FormState) => {
      const minConfidence = f.minConfidence.trim() ? Number(f.minConfidence) : undefined;
      if (rule) {
        const body = changedFields(rule, f, minConfidence);
        if (Object.keys(body).length === 0) return null; // nothing to save
        return updateRule(rule.rule_id, version, body);
      }
      const body: RuleCreate = {
        alert_type_code: f.alertTypeCode,
        trigger_labels: f.labels,
        is_enabled: f.isEnabled,
        ...(f.scope === "tenant_default" ? { tenant_id: f.tenantId } : { house_id: f.houseId.trim() }),
        ...(f.roomId.trim() ? { room_id: f.roomId.trim() } : {}),
        ...(f.severity ? { severity: f.severity } : {}),
        ...(minConfidence !== undefined ? { min_confidence: minConfidence } : {}),
      };
      return createRule(body);
    },
    onSuccess: (saved) => {
      if (saved === null) {
        onCancel(); // edit form closed with no changes
        return;
      }
      push({ tone: "success", message: editing ? "Rule saved" : "Rule created" });
      onSaved(saved);
    },
    onError: async (error) => {
      if (!(error instanceof ApiError)) {
        push({ tone: "error", message: "Could not save the rule" });
        return;
      }
      if (error.status === 422) {
        setServerErrors(fieldErrors(error.details));
        return;
      }
      if (error.status === 409) {
        push({ tone: "warning", message: error.message });
        onConflict();
        return;
      }
      if (error.status === 412 && rule) {
        // Someone saved this rule meanwhile: load their version; the user re-applies changes.
        onConflict();
        try {
          const fresh = await getRule(rule.rule_id);
          setForm(fromRule(fresh));
          setVersion(fresh.version);
          push({ tone: "warning", message: "This rule was changed by someone else. Reloaded the latest version." });
        } catch {
          push({ tone: "warning", message: "This rule was changed by someone else. Close the form and open it again." });
        }
        return;
      }
      push({ tone: "error", message: error.message });
    },
  });

  function submit() {
    const errors = validate(form, editing);
    setClientErrors(errors);
    setServerErrors({});
    if (Object.keys(errors).length === 0) save.mutate(form);
  }

  const error = (field: string) => clientErrors[field] ?? serverErrors[field]?.join("; ");
  const typeDefault = types.find((t) => t.code === form.alertTypeCode)?.default_min_confidence;

  return (
    <FormPanel
      title={editing ? `Edit rule: ${rule.alert_type_name}` : "New alert rule"}
      onSubmit={submit}
      footer={
        <>
          <Button variant="secondary" onClick={onCancel}>
            Cancel
          </Button>
          <Button type="submit" disabled={save.isPending}>
            {editing ? "Save" : "Create rule"}
          </Button>
        </>
      }
    >
      {!editing && (
        <fieldset>
          <legend className="text-xs font-medium text-muted">Applies to</legend>
          <div className="mt-1 flex gap-4 text-sm">
            <label>
              <input
                type="radio"
                name="scope"
                checked={form.scope === "house"}
                onChange={() => set("scope", "house")}
              />{" "}
              One house
            </label>
            <label>
              <input
                type="radio"
                name="scope"
                checked={form.scope === "tenant_default"}
                onChange={() => set("scope", "tenant_default")}
              />{" "}
              Tenant default (every house without its own rule)
            </label>
          </div>
        </fieldset>
      )}

      {!editing && form.scope === "tenant_default" && (
        <Field label="Tenant" name="rule-tenant" error={error("tenant_id")}>
          <select
            id="rule-tenant"
            className={inputClass}
            value={form.tenantId}
            onChange={(e) => set("tenantId", e.target.value)}
          >
            <option value="">Choose…</option>
            {tenants.map((t) => (
              <option key={t.tenant_id} value={t.tenant_id}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
      )}

      {/* STANDIN(C1 houses API): house and room are typed as ids until C1 lists houses/rooms. */}
      {!editing && form.scope === "house" && (
        <Field label="House id" name="rule-house" error={error("house_id")}>
          <input
            id="rule-house"
            className={inputClass}
            value={form.houseId}
            onChange={(e) => set("houseId", e.target.value)}
            placeholder="22222222-0000-0000-0000-0000000000a1"
          />
        </Field>
      )}
      {editing && (
        <p className="text-sm text-muted">
          {rule.scope === "house" ? `House ${rule.house_id}` : "Tenant default"} · {rule.alert_type_name}
        </p>
      )}

      {!editing && (
        <Field label="Alert type" name="rule-type" error={error("alert_type_code")}>
          <select
            id="rule-type"
            className={inputClass}
            value={form.alertTypeCode}
            onChange={(e) => chooseType(e.target.value)}
          >
            <option value="">Choose…</option>
            {types.map((t) => (
              <option key={t.code} value={t.code}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
      )}

      <Field label="Trigger labels" name="rule-labels" error={error("trigger_labels")}>
        <div id="rule-labels" className="flex flex-wrap gap-3 text-sm">
          {HOME_LABELS.map((label) => (
            <label key={label}>
              <input
                type="checkbox"
                checked={form.labels.includes(label)}
                onChange={(e) =>
                  set(
                    "labels",
                    e.target.checked ? [...form.labels, label] : form.labels.filter((l) => l !== label),
                  )
                }
              />{" "}
              {labelText(label)}
            </label>
          ))}
        </div>
      </Field>

      <Field label="Minimum confidence (0–1)" name="rule-confidence" error={error("min_confidence")}>
        <input
          id="rule-confidence"
          className={inputClass}
          inputMode="decimal"
          value={form.minConfidence}
          onChange={(e) => set("minConfidence", e.target.value)}
          placeholder={typeDefault !== undefined ? `Type default ${typeDefault}` : "Type default"}
        />
      </Field>

      {form.scope === "house" && (
        <Field label="Room id (optional: only this room)" name="rule-room" error={error("room_id")}>
          <input
            id="rule-room"
            className={inputClass}
            value={form.roomId}
            onChange={(e) => set("roomId", e.target.value)}
            placeholder="Whole house"
          />
        </Field>
      )}

      <Field label="Severity" name="rule-severity" error={error("severity")}>
        <select
          id="rule-severity"
          className={inputClass}
          value={form.severity}
          onChange={(e) => set("severity", e.target.value as Severity | "")}
        >
          <option value="">Alert type default</option>
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {SEVERITY_LABEL[s]}
            </option>
          ))}
        </select>
      </Field>

      <label className="flex items-center gap-2 text-sm text-ink">
        <input type="checkbox" checked={form.isEnabled} onChange={(e) => set("isEnabled", e.target.checked)} />
        Enabled
      </label>
    </FormPanel>
  );
}
