/** FilterBar: renders a row of filter controls. Includes a Select-based
 * FilterSelect so every page uses the same filter primitive (shadcn Select
 * on Radix), instead of native <select> with varying heights.
 */

import type { ReactNode } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

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

export interface FilterSelectOption {
  value: string;
  label: string;
}

export interface FilterSelectProps {
  /** ARIA label / visible label for the trigger. */
  label: string;
  value: string;
  onValueChange: (value: string) => void;
  options: FilterSelectOption[];
  /** Placeholder when value is empty. Defaults to label. */
  placeholder?: string;
  /** Width override; defaults to a comfortable filter width. */
  className?: string;
}

export function FilterSelect({
  label,
  value,
  onValueChange,
  options,
  placeholder,
  className,
}: FilterSelectProps) {
  // Radix SelectItem forbids value=""; drop empty options so callers cannot crash the menu.
  const safeOptions = options.filter((o) => o.value !== "");
  return (
    <Select value={value || undefined} onValueChange={onValueChange}>
      <SelectTrigger aria-label={label} className={className ?? "w-[10rem]"} data-empty={value ? undefined : ""}>
        <SelectValue placeholder={placeholder ?? label} />
      </SelectTrigger>
      <SelectContent>
        {safeOptions.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
