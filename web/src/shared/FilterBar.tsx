/** FilterBar: renders a row of filter controls. */

import type { ReactNode } from "react";

export interface FilterBarProps {
  children: ReactNode;
  onReset?: () => void;
}

export function FilterBar({ children, onReset }: FilterBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-surface p-3 shadow-card">
      {children}
      {onReset && (
        <button
          type="button"
          onClick={onReset}
          className="ml-auto rounded-md border border-border-strong px-2.5 py-1.5 text-xs text-muted hover:bg-surface-2"
        >
          Reset
        </button>
      )}
    </div>
  );
}
