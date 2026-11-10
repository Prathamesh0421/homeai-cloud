/** Display and error helpers for the C1 pages (pure). */

import { ApiError } from "../../api/http";

/** "just now", "2 m ago", "3 h ago", "4 d ago". */
export function relativeTime(iso: string, now: Date = new Date()): string {
  const seconds = Math.max(0, Math.round((now.getTime() - new Date(iso).getTime()) / 1000));
  if (seconds < 45) return "just now";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes} m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  return `${Math.round(hours / 24)} d ago`;
}

/** Local date and time, e.g. "Nov 10, 3:12 PM". */
export function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** 320044 -> "312.5 KB". */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/** "glass_break" -> "Glass break". */
export function labelText(label: string): string {
  const words = label.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

/** Value for a ``datetime-local`` input (local time, minutes precision). */
export function toLocalInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** ``datetime-local`` value -> ISO-8601 UTC with ``Z`` and no milliseconds. */
export function localInputToIso(value: string): string {
  return new Date(value).toISOString().replace(/\.\d{3}Z$/, "Z");
}

/** Start of a local day (``yyyy-mm-dd``) as UTC ISO. */
export function dayStartIso(day: string): string {
  return new Date(`${day}T00:00:00`).toISOString();
}

/** Start of the next local day, so ``to`` is exclusive. */
export function dayEndIso(day: string): string {
  const d = new Date(`${day}T00:00:00`);
  d.setDate(d.getDate() + 1);
  return d.toISOString();
}

/** Friendly text for C1's 409/422 codes; falls back to the server message. */
const CODE_TEXT: Record<string, string> = {
  room_required: "Assign a room to this feed before enabling it.",
  feed_not_enabled: "This feed is not enabled (or has no room), so it cannot accept clips.",
  media_kind_mismatch: "The clip type does not match the feed (audio feeds take audio, video feeds take video).",
  house_not_empty: "This house still has enabled feeds. Disable or archive them first.",
  room_in_use: "A feed still uses this room. Move or archive that feed first.",
  storage_unavailable: "Clip storage is unavailable right now. Try again in a moment.",
  payload_too_large: "File is larger than 50 MB.",
  forbidden: "You don't have permission to do that.",
};

export function errorText(err: unknown): string {
  if (err instanceof ApiError) {
    const friendly = CODE_TEXT[err.code];
    if (friendly) return `${friendly} (${err.status} ${err.code})`;
    if (err.status === 413) return `${CODE_TEXT.payload_too_large} (413)`;
    return `${err.message} (${err.status} ${err.code})`;
  }
  return err instanceof Error ? err.message : String(err);
}

/**
 * 422 ``details: [{field, issue}]`` -> ``{field: issue}``. Nested fields such as
 * ``config.capture_interval_s`` are keyed by their last part as well, so form inputs can use
 * their own names.
 */
export function serverFieldErrors(err: unknown): Record<string, string> {
  if (!(err instanceof ApiError) || err.status !== 422 || !Array.isArray(err.details)) return {};
  const out: Record<string, string> = {};
  for (const item of err.details as Array<Record<string, unknown>>) {
    if (typeof item?.field !== "string" || typeof item.issue !== "string") continue;
    const parts = item.field.split(".").filter((p) => p && !/^\d+$/.test(p));
    for (const key of [item.field, parts[0], parts[parts.length - 1]]) {
      if (key && !(key in out)) out[key] = item.issue;
    }
  }
  return out;
}
