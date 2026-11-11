/** EmptyState: friendly placeholder for empty lists. */

import type { ReactNode } from "react";

export interface EmptyStateProps {
  title: string;
  description?: string;
  /** Optional icon shown above the title (lucide icon element). */
  icon?: ReactNode;
  /** Optional primary action (a Button or link). */
  action?: ReactNode;
}

export function EmptyState({ title, description, icon, action }: EmptyStateProps) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border-strong bg-surface py-12 text-center">
      {icon && <div className="mb-3 text-muted">{icon}</div>}
      <h3 className="text-sm font-semibold text-ink">{title}</h3>
      {description && <p className="mt-1 max-w-sm text-xs text-muted">{description}</p>}
      {action && <div className="mt-3">{action}</div>}
    </div>
  );
}
