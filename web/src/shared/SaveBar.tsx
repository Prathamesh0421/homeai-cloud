/** SaveBar: sticky footer shown when a form has unsaved changes. */

export interface SaveBarProps {
  dirty: boolean;
  saving?: boolean;
  onSave?: () => void;
  onDiscard?: () => void;
  saveLabel?: string;
}

export function SaveBar({ dirty, saving, onSave, onDiscard, saveLabel = "Save" }: SaveBarProps) {
  if (!dirty) return null;
  return (
    <div className="sticky bottom-0 flex items-center justify-end gap-2 rounded-xl border border-border bg-surface/95 px-4 py-3 shadow-pop backdrop-blur">
      {onDiscard && (
        <button
          type="button"
          onClick={onDiscard}
          disabled={saving}
          className="rounded-md border border-border-strong px-3.5 py-2 text-sm text-muted hover:bg-surface-2 disabled:opacity-50"
        >
          Discard
        </button>
      )}
      <button
        type="button"
        onClick={onSave}
        disabled={saving}
        className="rounded-md bg-primary px-3.5 py-2 text-sm font-medium text-white shadow-card hover:bg-primary-hover disabled:opacity-50"
      >
        {saving ? "Saving…" : saveLabel}
      </button>
    </div>
  );
}
