/** C2 Alert Tracking API client (docs/components/C2_ALERT_TRACKING.md §3). */

import { http, type Page } from "./http";

export type AlertStatus = "open" | "acknowledged" | "resolved" | "false_positive";
export type Severity = "critical" | "high" | "medium" | "low";
export type AlertAction = "acknowledge" | "resolve" | "false_positive";

export const ALERT_STATUSES: AlertStatus[] = ["open", "acknowledged", "resolved", "false_positive"];
export const SEVERITIES: Severity[] = ["critical", "high", "medium", "low"];

export interface AlertSummary {
  alert_id: string;
  tenant_id: string;
  house_id: string;
  house_name: string | null; // null while C1 is unavailable
  room_id: string | null;
  room_name: string | null;
  alert_type_code: string;
  alert_type_name: string;
  category: string;
  severity: Severity;
  status: AlertStatus;
  top_label: string;
  top_confidence: number;
  triggered_at: string;
}

export interface EvidenceLabel {
  label: string;
  confidence: number;
  source_class?: string | null;
  start_s?: number | null;
  end_s?: number | null;
}

export interface Evidence {
  detection_id: string;
  media_id: string;
  labels: EvidenceLabel[];
  model: { model_id: string; name: string; version: string } | null;
  detection_available: boolean; // false: C3 unreachable, labels hold only the top label
  threshold: number | null;
}

export interface TimelineEntry {
  from_status: AlertStatus | null;
  to_status: AlertStatus;
  actor_id: string;
  actor_role: string;
  note: string | null;
  changed_at: string;
}

export interface AlertNotification {
  notification_id: string;
  channel: "in_app" | "email";
  contact_id: string | null;
  recipient: string | null;
  priority: number | null;
  status: "queued" | "sent" | "failed";
  attempt_count: number;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
  view_link?: string | null; // DEMO_MODE only
}

export interface AlertDetail extends AlertSummary {
  rule_id: string;
  detection_id: string;
  media_id: string;
  acknowledged_at: string | null;
  resolved_at: string | null;
  updated_at: string;
  allowed_actions: AlertAction[];
  evidence: Evidence;
  timeline: TimelineEntry[];
  notifications: AlertNotification[];
}

export interface AlertType {
  code: string;
  name: string;
  category: string;
  service_code: string;
  trigger_label: string;
  default_severity: Severity;
  default_min_confidence: number;
}

export interface AlertFilters {
  status?: AlertStatus[];
  severity?: Severity;
  alertTypeCode?: string;
  houseId?: string;
  from?: string; // ISO-8601 UTC, inclusive
  to?: string; // ISO-8601 UTC, exclusive
  page?: number;
  pageSize?: number;
}

export function alertsQuery(f: AlertFilters): string {
  const q = new URLSearchParams();
  if (f.status?.length) q.set("status", f.status.join(","));
  if (f.severity) q.set("severity", f.severity);
  if (f.alertTypeCode) q.set("alert_type_code", f.alertTypeCode);
  if (f.houseId) q.set("house_id", f.houseId);
  if (f.from) q.set("from", f.from);
  if (f.to) q.set("to", f.to);
  q.set("page", String(f.page ?? 1));
  q.set("page_size", String(f.pageSize ?? 25));
  return q.toString();
}

export function listAlerts(f: AlertFilters): Promise<Page<AlertSummary>> {
  return http.getPage<AlertSummary>(`/api/v1/alerts?${alertsQuery(f)}`);
}

export function getAlert(alertId: string): Promise<AlertDetail> {
  return http.get<AlertDetail>(`/api/v1/alerts/${encodeURIComponent(alertId)}`);
}

export async function listAlertTypes(): Promise<AlertType[]> {
  const page = await http.getPage<AlertType>("/api/v1/alert-types?page_size=100");
  return page.data;
}

const ACTION_PATH: Record<AlertAction, string> = {
  acknowledge: "acknowledge",
  resolve: "resolve",
  false_positive: "false-positive",
};

/** Acknowledge / resolve take an optional note; false positive requires a reason (1-500). */
export function alertAction(
  alertId: string,
  action: AlertAction,
  text?: string,
): Promise<AlertDetail> {
  const trimmed = text?.trim();
  const body =
    action === "false_positive" ? { reason: trimmed ?? "" } : trimmed ? { note: trimmed } : undefined;
  return http.post<AlertDetail>(
    `/api/v1/alerts/${encodeURIComponent(alertId)}/${ACTION_PATH[action]}`,
    body,
  );
}

export const c2Keys = {
  alerts: (f: AlertFilters) => ["c2", "alerts", f] as const,
  alert: (alertId: string) => ["c2", "alert", alertId] as const,
  alertTypes: () => ["c2", "alert-types"] as const,
};
