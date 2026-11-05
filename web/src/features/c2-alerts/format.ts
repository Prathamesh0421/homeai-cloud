/** Display helpers for the C2 alert pages (pure; unit-tested). */

import type { AlertNotification, AlertStatus, TimelineEntry } from "../../api/c2";

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

/** Local date and time, e.g. "Oct 24, 11:10 PM". */
export function formatWhen(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

/** "glass_break" -> "Glass break". */
export function labelText(label: string): string {
  const words = label.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function percent(confidence: number): string {
  return `${Math.round(confidence * 100)}%`;
}

const ROLE_TEXT: Record<string, string> = {
  house_owner: "house owner",
  cloud_staff: "cloud staff",
  iot_staff: "IoT staff",
  service: "system",
};

const STATUS_VERB: Record<AlertStatus, string> = {
  open: "Raised",
  acknowledged: "Acknowledged",
  resolved: "Resolved",
  false_positive: "Marked false positive",
};

export function timelineLabel(entry: TimelineEntry): string {
  const verb = STATUS_VERB[entry.to_status];
  const who = entry.from_status === null ? "" : ` by ${ROLE_TEXT[entry.actor_role] ?? entry.actor_role}`;
  const note = entry.note ? ` — “${entry.note}”` : "";
  return `${verb}${who}${note}`;
}

export const MAX_EMAIL_ATTEMPTS = 3;

export type DeliveryTone = "ok" | "pending" | "retry" | "failed";

/** What a contact's email row means for the person reading Alert Detail. */
export function deliveryStatus(n: AlertNotification): { text: string; tone: DeliveryTone } {
  if (n.channel === "in_app") return { text: "Shown in app", tone: "ok" };
  if (n.status === "sent") return { text: "Sent", tone: "ok" };
  if (n.status === "queued") return { text: "Sending…", tone: "pending" };
  if (n.last_error === "alert_closed") return { text: "Stopped: alert closed", tone: "failed" };
  if (n.last_error === "contact_removed") return { text: "Stopped: contact removed", tone: "failed" };
  const triesLeft = n.attempt_count < MAX_EMAIL_ATTEMPTS;
  if (n.last_error === "subscription_pending") {
    return triesLeft
      ? { text: `Pending confirmation (try ${n.attempt_count}/${MAX_EMAIL_ATTEMPTS})`, tone: "pending" }
      : { text: "Failed: email never confirmed", tone: "failed" };
  }
  return triesLeft
    ? { text: `Retry ${n.attempt_count}/${MAX_EMAIL_ATTEMPTS}`, tone: "retry" }
    : { text: `Failed after ${MAX_EMAIL_ATTEMPTS} tries`, tone: "failed" };
}

/** Start of a local calendar day as ISO UTC ("2026-11-05" -> local midnight). */
export function dayStartIso(day: string): string {
  return new Date(`${day}T00:00:00`).toISOString();
}

/** Start of the day after (``to`` is exclusive). */
export function dayEndIso(day: string): string {
  const d = new Date(`${day}T00:00:00`);
  d.setDate(d.getDate() + 1);
  return d.toISOString();
}
