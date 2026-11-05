/** KpiTile: single metric with label and optional delta. */

export interface KpiTileProps {
  label: string;
  value: string | number;
  hint?: string;
  delta?: { value: string; positive?: boolean };
}

export function KpiTile({ label, value, hint, delta }: KpiTileProps) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-slate-500">{hint}</div>}
      {delta && (
        <div
          className={`mt-1 text-xs font-medium ${
            delta.positive ? "text-emerald-600" : "text-red-600"
          }`}
        >
          {delta.value}
        </div>
      )}
    </div>
  );
}
