/** ConfidenceBars: thin stub — top-N class confidence bars land in C4-12. */

export interface ConfidenceBarsProps {
  scores: { label: string; score: number }[];
}

export function ConfidenceBars({ scores }: ConfidenceBarsProps) {
  return (
    <div className="space-y-1">
      {scores.map((s) => (
        <div key={s.label} className="flex items-center gap-2 text-xs">
          <span className="w-24 truncate text-muted">{s.label}</span>
          <div className="h-2 flex-1 overflow-hidden rounded bg-canvas">
            <div className="h-full bg-accent" style={{ width: `${Math.round(s.score * 100)}%` }} />
          </div>
          <span className="w-10 text-right text-muted">{(s.score * 100).toFixed(0)}%</span>
        </div>
      ))}
    </div>
  );
}
