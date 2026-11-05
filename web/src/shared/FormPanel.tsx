/** FormPanel: titled card wrapping a form. Maps 422 field errors to inputs.
 *
 * The contract error envelope is `{"error": {code, message, details}}` where
 * `details` may be `{"fields": {field: [messages]}}` (FastAPI validation) or
 * our service-level `details` dict. FormPanel extracts field-level messages
 * so each input can show its own error.
 */

import type { ReactNode } from "react";

export interface FormPanelProps {
  title?: string;
  children: ReactNode;
  onSubmit?: () => void;
  footer?: ReactNode;
}

export function FormPanel({ title, children, onSubmit, footer }: FormPanelProps) {
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit?.();
      }}
      className="rounded-lg border border-slate-200 bg-white p-4"
    >
      {title && <h3 className="mb-3 text-sm font-semibold text-slate-800">{title}</h3>}
      <div className="space-y-3">{children}</div>
      {footer && <div className="mt-4 flex justify-end gap-2">{footer}</div>}
    </form>
  );
}

/** Extract per-field error messages from a contract error envelope. */
export function fieldErrors(details: unknown): Record<string, string[]> {
  if (!details || typeof details !== "object") return {};
  // Contract envelope (homeai_common.errors): details = [{field, issue}], field like
  // "trigger_labels.0" -> grouped under its top-level name.
  if (Array.isArray(details)) {
    const out: Record<string, string[]> = {};
    for (const item of details as Array<Record<string, unknown>>) {
      if (typeof item?.field === "string" && item.field && typeof item.issue === "string") {
        (out[item.field.split(".")[0]] ??= []).push(item.issue);
      }
    }
    return out;
  }
  const d = details as Record<string, unknown>;
  // FastAPI validation: {"details": [{"loc": ["body","field"], "msg": "..."}]}
  // Our service errors: {"fields": {"field": ["msg"]}} or {"field": "msg"}
  const out: Record<string, string[]> = {};
  if (Array.isArray(d.details)) {
    for (const item of d.details as Array<Record<string, unknown>>) {
      const loc = item.loc as unknown[] | undefined;
      const msg = item.msg as string | undefined;
      if (loc && msg && loc.length >= 2 && loc[0] === "body") {
        const field = String(loc[1]);
        (out[field] ??= []).push(msg);
      }
    }
    return out;
  }
  if (d.fields && typeof d.fields === "object") {
    for (const [field, val] of Object.entries(d.fields as Record<string, unknown>)) {
      out[field] = Array.isArray(val) ? (val as string[]) : [String(val)];
    }
    return out;
  }
  return out;
}

export interface FieldProps {
  label: string;
  name: string;
  error?: string;
  children: ReactNode;
}

export function Field({ label, name, error, children }: FieldProps) {
  return (
    <div>
      <label htmlFor={name} className="block text-xs font-medium text-slate-600">
        {label}
      </label>
      <div className="mt-1">{children}</div>
      {error && <p className="mt-1 text-xs text-red-600">{error}</p>}
    </div>
  );
}
