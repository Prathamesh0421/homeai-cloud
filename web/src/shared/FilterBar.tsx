/** FilterBar: renders a row of filter controls. */

import type { ReactNode } from "react";

export interface FilterBarProps {
  children: ReactNode;
  onReset?: () => void;
}

export function FilterBar({ children, onReset }: FilterBarProps) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-200 bg-white p-3">
      {children}
      {onReset && (
        <button
          type="button"
          onClick={onReset}
          className="ml-auto rounded border border-slate-200 px-2 py-1 text-xs text-slate-600 hover:bg-slate-50"
        >
          Reset
        </button>
      )}
    </div>
  );
}
