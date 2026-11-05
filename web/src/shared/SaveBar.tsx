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
    <div className="sticky bottom-0 flex items-center justify-end gap-2 border-t border-slate-200 bg-white px-4 py-2">
      {onDiscard && (
        <button
          type="button"
          onClick={onDiscard}
          disabled={saving}
          className="rounded border border-slate-300 px-3 py-1.5 text-sm text-slate-600 hover:bg-slate-50 disabled:opacity-50"
        >
          Discard
        </button>
      )}
      <button
        type="button"
        onClick={onSave}
        disabled={saving}
        className="rounded bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
      >
        {saving ? "Saving…" : saveLabel}
      </button>
    </div>
  );
}
