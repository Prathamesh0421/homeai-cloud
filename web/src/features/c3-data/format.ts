/** Display helpers for the C3 pages. Time is UTC: the backend owns one frame of reference. */

export function labelText(label: string | null | undefined): string {
  if (!label) return "—";
  const s = label.replace(/_/g, " ");
  return s.charAt(0).toUpperCase() + s.slice(1);
}

export function percent(v: number | null | undefined, digits = 0): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

export function relativeTime(iso: string | null | undefined, now: Date = new Date()): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  const secs = Math.round((now.getTime() - then) / 1000);
  if (secs < 20) return "just now";
  if (secs < 90) return `${Math.round(secs / 60) || 1} m ago`;
  const mins = Math.round(secs / 60);
  if (mins < 90) return `${mins} m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 36) return `${hrs} h ago`;
  return `${Math.round(hrs / 24)} d ago`;
}

/** Label a UTC hour index (0..23) as "HH:00 UTC". The chart axis is UTC, not local. */
export function utcHourLabel(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00 UTC`;
}

/** A worker is live if its last heartbeat is within ~2 heartbeat intervals (stale past that). */
export function workerIsStale(lastHeartbeat: string | null, now: Date = new Date()): boolean {
  if (!lastHeartbeat) return true;
  const ageMs = now.getTime() - new Date(lastHeartbeat).getTime();
  return ageMs > 2 * 60 * 1000; // > 2 minutes (worker beats every ~10 s; TTL 600 s)
}

export const BAND_LABEL: Record<string, string> = {
  normal: "Normal",
  unusual: "Unusual",
  anomalous: "Anomalous",
  insufficient_data: "Collecting data",
};

export const BAND_TONE: Record<string, string> = {
  normal: "text-muted",
  unusual: "text-warning",
  anomalous: "text-danger",
  insufficient_data: "text-muted",
};
