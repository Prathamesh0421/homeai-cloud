/** KpiTile: single metric with label and optional delta. */

export interface KpiTileProps {
  label: string;
  value: string | number;
  hint?: string;
  delta?: { value: string; positive?: boolean };
}

export function KpiTile({ label, value, hint, delta }: KpiTileProps) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-ink">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-muted">{hint}</div>}
      {delta && (
        <div
          className={`mt-1 text-xs font-medium ${
            delta.positive ? "text-success" : "text-danger"
          }`}
        >
          {delta.value}
        </div>
      )}
    </div>
  );
}
