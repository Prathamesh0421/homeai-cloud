/** Toasts: a tiny context-based notification system.
 *
 * Pages call `useToasts().push({tone, message})`; the provider renders the
 * stack in a fixed container and auto-dismisses after `ttl` ms.
 */

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";

export type ToastTone = "info" | "success" | "warning" | "error";

export interface Toast {
  id: number;
  tone: ToastTone;
  message: string;
}

interface ToastContextValue {
  toasts: Toast[];
  push: (t: { tone: ToastTone; message: string; ttl?: number }) => void;
  dismiss: (id: number) => void;
}

const ToastContext = createContext<ToastContextValue | null>(null);

let _id = 0;

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const dismiss = useCallback((id: number) => {
    setToasts((cur) => cur.filter((t) => t.id !== id));
  }, []);

  const push = useCallback(
    ({ tone, message, ttl = 4000 }: { tone: ToastTone; message: string; ttl?: number }) => {
      const id = ++_id;
      setToasts((cur) => [...cur, { id, tone, message }]);
      if (ttl > 0) window.setTimeout(() => dismiss(id), ttl);
    },
    [dismiss],
  );

  const value = useMemo(() => ({ toasts, push, dismiss }), [toasts, push, dismiss]);
  return <ToastContext.Provider value={value}>{children}</ToastContext.Provider>;
}

export function useToasts(): ToastContextValue {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error("useToasts must be used within ToastProvider");
  return ctx;
}

const TONE_CLASSES: Record<ToastTone, string> = {
  info: "border-slate-200 bg-white text-slate-700",
  success: "border-emerald-200 bg-emerald-50 text-emerald-800",
  warning: "border-amber-200 bg-amber-50 text-amber-800",
  error: "border-red-200 bg-red-50 text-red-800",
};

export function ToastViewport() {
  const { toasts, dismiss } = useToasts();
  return (
    <div className="fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2">
      {toasts.map((t) => (
        <div
          key={t.id}
          className={`flex items-start justify-between rounded border px-3 py-2 text-sm shadow-sm ${TONE_CLASSES[t.tone]}`}
          role="status"
        >
          <span>{t.message}</span>
          <button
            type="button"
            onClick={() => dismiss(t.id)}
            aria-label="Dismiss"
            className="ml-2 text-xs opacity-60 hover:opacity-100"
          >
            ✕
          </button>
        </div>
      ))}
    </div>
  );
}
