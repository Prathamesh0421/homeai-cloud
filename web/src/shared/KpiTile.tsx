/** KpiTile: single metric with label and optional delta. */

export interface KpiTileProps {
  label: string;
  value: string | number;
  hint?: string;
  delta?: { value: string; positive?: boolean };
  /** Visual tone; "warning" highlights the tile (e.g. feeds offline). */
  tone?: "default" | "warning";
}

export function KpiTile({ label, value, hint, delta, tone = "default" }: KpiTileProps) {
  const isWarning = tone === "warning";
  return (
    <div
      className={`rounded-xl border p-4 shadow-card ${
        isWarning ? "border-warning/40 bg-warning-soft" : "border-border bg-surface"
      }`}
    >
      <div className={`text-xs font-medium uppercase tracking-wide ${isWarning ? "text-warning" : "text-muted"}`}>
        {label}
      </div>
      <div className={`mt-1 text-2xl font-semibold tnum ${isWarning ? "text-warning" : "text-ink"}`}>{value}</div>
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
