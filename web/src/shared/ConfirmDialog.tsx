/** ConfirmDialog: modal asking for confirmation before a destructive action. */

import { useEffect, useId, useRef, type KeyboardEvent as ReactKeyboardEvent } from "react";

export interface ConfirmDialogProps {
  open: boolean;
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  destructive?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const ids = useId();
  const panel = useRef<HTMLDivElement>(null);
  const cancelButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onCancel();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onCancel]);

  // Keyboard users: focus moves into the dialog (Cancel, the safe choice) and back to the
  // control that opened it when the dialog closes, if that control is still on the page.
  useEffect(() => {
    if (!open) return;
    const opener = document.activeElement as HTMLElement | null;
    cancelButton.current?.focus();
    return () => {
      if (opener?.isConnected) opener.focus();
    };
  }, [open]);

  // Tab and Shift+Tab stay inside the dialog while it is open (aria-modal).
  function trapTab(e: ReactKeyboardEvent) {
    if (e.key !== "Tab" || !panel.current) return;
    const buttons = panel.current.querySelectorAll<HTMLButtonElement>("button:not(:disabled)");
    const first = buttons[0];
    const last = buttons[buttons.length - 1];
    if (e.shiftKey && document.activeElement === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && document.activeElement === last) {
      e.preventDefault();
      first.focus();
    }
  }

  if (!open) return null;
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby={`${ids}-title`}
      aria-describedby={`${ids}-message`}
      onKeyDown={trapTab}
    >
      <div ref={panel} className="w-full max-w-sm rounded-xl border border-border bg-surface p-5 shadow-pop">
        <h3 id={`${ids}-title`} className="text-sm font-semibold text-ink">
          {title}
        </h3>
        <p id={`${ids}-message`} className="mt-1.5 text-sm text-muted">
          {message}
        </p>
        <div className="mt-5 flex justify-end gap-2">
          <button
            ref={cancelButton}
            type="button"
            onClick={onCancel}
            className="rounded-md border border-border-strong px-3.5 py-2 text-sm text-muted hover:bg-surface-2"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            onClick={onConfirm}
            className={`rounded-md px-3.5 py-2 text-sm font-medium text-white shadow-card ${
              destructive ? "bg-danger hover:bg-danger/90" : "bg-primary hover:bg-primary-hover"
            }`}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
