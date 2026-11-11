/** C2 Alert Tracking API client (docs/components/C2_ALERT_TRACKING.md §3). */

import { ApiError, getToken, http, type Page } from "./http";

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

// --- alert rules (cloud_staff) ----------------------------------------------------------------

/** Home labels a rule can trigger on (contract §3). */
export const HOME_LABELS = [
  "smoke_alarm",
  "distress_sound",
  "glass_break",
  "fall_indicator",
  "cough",
  "speech",
  "dog",
] as const;
export type HomeLabel = (typeof HOME_LABELS)[number];

export interface AlertRule {
  rule_id: string;
  tenant_id: string;
  house_id: string | null;
  scope: "tenant_default" | "house";
  alert_type_code: string;
  alert_type_name: string;
  trigger_labels: string[];
  min_confidence: number;
  room_id: string | null;
  severity: Severity | null; // null: the alert type's default (effective_severity)
  effective_severity: Severity;
  is_enabled: boolean;
  version: number;
  false_positive_count_30d: number;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface RuleFilters {
  tenantId?: string;
  houseId?: string;
  alertTypeCode?: string;
  isEnabled?: boolean;
  page?: number;
  pageSize?: number;
}

export interface RuleCreate {
  tenant_id?: string; // tenant-wide default (no house_id)
  house_id?: string;
  alert_type_code: string;
  trigger_labels: string[];
  min_confidence?: number;
  room_id?: string;
  severity?: Severity;
  is_enabled?: boolean;
}

/** Omitted fields keep their value; ``null`` clears room / severity. */
export interface RuleUpdate {
  trigger_labels?: string[];
  min_confidence?: number;
  room_id?: string | null;
  severity?: Severity | null;
  is_enabled?: boolean;
}

export interface SyncResult {
  topics: number;
  subscribed: number;
  pending: number;
  removed: number;
  failed: number;
}

export function rulesQuery(f: RuleFilters): string {
  const q = new URLSearchParams();
  if (f.tenantId) q.set("tenant_id", f.tenantId);
  if (f.houseId) q.set("house_id", f.houseId);
  if (f.alertTypeCode) q.set("alert_type_code", f.alertTypeCode);
  if (f.isEnabled !== undefined) q.set("is_enabled", String(f.isEnabled));
  q.set("page", String(f.page ?? 1));
  q.set("page_size", String(f.pageSize ?? 50));
  return q.toString();
}

export function listRules(f: RuleFilters): Promise<Page<AlertRule>> {
  return http.getPage<AlertRule>(`/api/v1/alert-rules?${rulesQuery(f)}`);
}

export function getRule(ruleId: string): Promise<AlertRule> {
  return http.get<AlertRule>(`/api/v1/alert-rules/${encodeURIComponent(ruleId)}`);
}

export function createRule(body: RuleCreate): Promise<AlertRule> {
  return http.post<AlertRule>("/api/v1/alert-rules", body);
}

/** ``version`` is the rule's current version; a stale one answers 412 version_mismatch. */
export function updateRule(ruleId: string, version: number, body: RuleUpdate): Promise<AlertRule> {
  return http.put<AlertRule>(`/api/v1/alert-rules/${encodeURIComponent(ruleId)}`, body, {
    headers: { "If-Match": `"${version}"` },
  });
}

export function createTenantDefaults(tenantId: string): Promise<{ created: number }> {
  return http.post<{ created: number }>("/api/v1/alert-rules/defaults", { tenant_id: tenantId });
}

export function syncSubscriptions(houseId?: string): Promise<SyncResult> {
  return http.post<SyncResult>("/api/v1/alert-rules/subscriptions/sync", houseId ? { house_id: houseId } : {});
}

// --- public alert view (no login) ---------------------------------------------------------------

export interface AlertView {
  alert_type_name: string;
  severity: Severity;
  status: AlertStatus;
  house_name: string | null;
  room_name: string | null;
  triggered_at: string;
  labels: { label: string; confidence: number }[];
  clip_url: string | null;
  expires_at: string;
}

/**
 * ``GET /alert-view/{token}`` for the emergency contact who opened an email link. Plain fetch on
 * purpose: no bearer token is sent, and a 401 here means "link expired", so it must not log out a
 * signed-in user the way ``http`` does. Errors are ApiErrors; 429 carries ``retryAfter`` seconds.
 */
export async function getAlertView(token: string): Promise<AlertView> {
  const resp = await fetch(`/api/v1/alert-view/${encodeURIComponent(token)}`);
  const text = await resp.text();
  let parsed: { data?: AlertView; error?: { code?: string; message?: string; details?: unknown } } | undefined;
  try {
    parsed = text ? JSON.parse(text) : undefined;
  } catch {
    parsed = undefined; // e.g. an HTML error page from the gateway
  }
  if (!resp.ok || !parsed?.data) {
    const err = parsed?.error ?? {};
    const retryAfter = Number(resp.headers.get("Retry-After") ?? "");
    throw new ApiError(
      resp.status,
      err.code ?? "unknown",
      err.message ?? resp.statusText,
      Number.isFinite(retryAfter) && retryAfter > 0 ? { retryAfter } : err.details,
    );
  }
  return parsed.data;
}

/**
 * C1's presigned playback URL for an alert's clip, with the signed-in user's own token (C2-11,
 * contract §4.4: owners and cloud staff in scope). Plain fetch, not ``http``: a 401 from C1 must
 * not sign the user out of C2's pages, the player just shows no recording.
 */
export async function getClipUrl(mediaId: string): Promise<string> {
  const token = getToken();
  const resp = await fetch(`/api/v1/clips/${encodeURIComponent(mediaId)}/playback-url`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  let parsed: { data?: { url?: string }; error?: { code?: string; message?: string } } | undefined;
  try {
    parsed = await resp.json();
  } catch {
    parsed = undefined; // e.g. an HTML error page from the gateway
  }
  if (!resp.ok || !parsed?.data?.url) {
    throw new ApiError(resp.status, parsed?.error?.code ?? "unknown", parsed?.error?.message ?? resp.statusText, undefined);
  }
  return parsed.data.url;
}

export const c2Keys = {
  alerts: (f: AlertFilters) => ["c2", "alerts", f] as const,
  alert: (alertId: string) => ["c2", "alert", alertId] as const,
  alertTypes: () => ["c2", "alert-types"] as const,
  rules: (f: RuleFilters) => ["c2", "rules", f] as const,
  alertView: (token: string) => ["c2", "alert-view", token] as const,
};
