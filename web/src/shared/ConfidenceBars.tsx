/** ConfidenceBars: thin stub — top-N class confidence bars land in C4-12. */

export interface ConfidenceBarsProps {
  scores: { label: string; score: number }[];
}

export function ConfidenceBars({ scores }: ConfidenceBarsProps) {
  return (
    <div className="space-y-1">
      {scores.map((s) => (
        <div key={s.label} className="flex items-center gap-2 text-xs">
          <span className="w-24 truncate text-slate-600">{s.label}</span>
          <div className="h-2 flex-1 overflow-hidden rounded bg-slate-100">
            <div className="h-full bg-slate-700" style={{ width: `${Math.round(s.score * 100)}%` }} />
          </div>
          <span className="w-10 text-right text-slate-500">{(s.score * 100).toFixed(0)}%</span>
        </div>
      ))}
    </div>
  );
}
