/** Confirm dialog for "Mark false positive": a reason (1-500 characters) is required. */

import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

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
  const panel = useRef<HTMLFormElement>(null);

  const cancel = useRef(onCancel);
  cancel.current = onCancel;

  // Only when the dialog opens: start empty and focus the box. (Keyed on `open` alone, so a
  // parent re-render, e.g. a toast going away, never clears what is being typed.) On close,
  // focus goes back to the button that opened it, if that button is still on the page.
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    setReason("");
    box.current?.focus();
    return () => {
      if (opener?.isConnected) opener.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") cancel.current();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  // Tab and Shift+Tab stay inside the dialog while it is open (aria-modal).
  function trapTab(e: ReactKeyboardEvent) {
    if (e.key !== "Tab" || !panel.current) return;
    const items = panel.current.querySelectorAll<HTMLElement>("textarea, button:not(:disabled)");
    const first = items[0];
    const last = items[items.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  if (!open) return null;
  const trimmed = reason.trim();
  const valid = trimmed.length >= 1 && trimmed.length <= REASON_MAX;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby={`${fieldId}-title`}
      aria-describedby={`${fieldId}-message`}
      onKeyDown={trapTab}
    >
      <form
        ref={panel}
        className="w-full max-w-md rounded-xl border border-border bg-surface p-5 shadow-pop"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid && !busy) onConfirm(trimmed);
        }}
      >
        <h3 id={`${fieldId}-title`} className="text-sm font-semibold text-ink">
          Mark as false positive?
        </h3>
        <p id={`${fieldId}-message`} className="mt-1 text-sm text-muted">
          The alert closes and no more emails go out for it. The reason is kept in its timeline and
          counts toward the rule's false-positive total.
        </p>
        <label htmlFor={fieldId} className="mt-3 block text-xs font-medium text-muted">
          Reason (required)
        </label>
        <textarea
          id={fieldId}
          ref={box}
          rows={3}
          maxLength={REASON_MAX}
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          className="mt-1 w-full rounded-md border border-border-strong bg-surface p-2 text-sm text-ink"
          placeholder="e.g. Dropped a glass in the kitchen while cooking"
        />
        <div className="text-right text-xs text-muted">
          {reason.length}/{REASON_MAX}
        </div>
        <div className="mt-3 flex justify-end gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-border-strong bg-surface px-3 py-1.5 text-sm text-ink hover:bg-canvas"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!valid || busy}
            className="rounded-md bg-danger px-3 py-1.5 text-sm font-medium text-white hover:bg-danger/90 disabled:opacity-50"
          >
            Mark false positive
          </button>
        </div>
      </form>
    </div>
  );
}
