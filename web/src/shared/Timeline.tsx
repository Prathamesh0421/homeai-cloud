/** Timeline: thin stub — alert/clip timeline lands in C4-12. */

export interface TimelineProps {
  events: { id: string; label: string; at: string }[];
}

export function Timeline({ events }: TimelineProps) {
  return (
    <ol className="space-y-2">
      {events.map((e) => (
        <li key={e.id} className="flex items-center gap-2 text-sm text-slate-600">
          <span className="h-2 w-2 rounded-full bg-slate-400" />
          <span>{e.label}</span>
          <span className="ml-auto text-xs text-slate-400">{e.at}</span>
        </li>
      ))}
    </ol>
  );
}
