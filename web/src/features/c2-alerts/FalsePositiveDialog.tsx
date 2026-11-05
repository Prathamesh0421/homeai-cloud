/** Confirm dialog for "Mark false positive": a reason (1-500 characters) is required. */

import { useEffect, useId, useRef, useState } from "react";

export const REASON_MAX = 500;

export interface FalsePositiveDialogProps {
  open: boolean;
  busy?: boolean;
  onConfirm: (reason: string) => void;
  onCancel: () => void;
}

export function FalsePositiveDialog({ open, busy, onConfirm, onCancel }: FalsePositiveDialogProps) {
  const [reason, setReason] = useState("");
  const fieldId = useId();
  const box = useRef<HTMLTextAreaElement>(null);

  const cancel = useRef(onCancel);
  cancel.current = onCancel;

  // Only when the dialog opens: start empty and focus the box. (Keyed on `open` alone, so a
  // parent re-render, e.g. a toast going away, never clears what is being typed.)
  useEffect(() => {
    if (!open) return;
    setReason("");
    box.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") cancel.current();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  if (!open) return null;
  const trimmed = reason.trim();
  const valid = trimmed.length >= 1 && trimmed.length <= REASON_MAX;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/30"
      role="dialog"
      aria-modal="true"
      aria-labelledby={`${fieldId}-title`}
    >
      <form
        className="w-full max-w-md rounded-lg border border-slate-200 bg-white p-4 shadow-lg"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid && !busy) onConfirm(trimmed);
        }}
      >
        <h3 id={`${fieldId}-title`} className="text-sm font-semibold text-slate-800">
          Mark as false positive?
        </h3>
        <p className="mt-1 text-sm text-slate-600">
          The alert closes and no more emails go out for it. The reason is kept in its timeline and
          counts toward the rule's false-positive total.
        </p>
        <label htmlFor={fieldId} className="mt-3 block text-xs font-medium text-slate-600">
          Reason (required)
        </label>
        <textarea
          id={fieldId}
          ref={box}
          rows={3}
          maxLength={REASON_MAX}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="mt-1 w-full rounded border border-slate-300 p-2 text-sm"
          placeholder="e.g. Dropped a glass in the kitchen while cooking"
        />
        <div className="text-right text-xs text-slate-400">
          {reason.length}/{REASON_MAX}
        </div>
        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!valid || busy}
            className="rounded bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-500 disabled:opacity-50"
          >
            Mark false positive
          </button>
        </div>
      </form>
    </div>
  );
}
