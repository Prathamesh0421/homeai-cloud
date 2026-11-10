/** C4 API client functions. */

import { http } from "./http";

export interface LoginRequest {
  email: string;
  password: string;
}

export interface LoginResponse {
  token: string;
  expires_in: number;
  landing: string;
  claims: {
    sub: string;
    role: "house_owner" | "iot_staff" | "cloud_staff";
    tenant_id: string;
    house_ids: string[];
    email: string;
    jti: string;
  };
}

export interface HouseRef {
  house_id: string;
  name: string | null;
}

export interface AuthMeResponse {
  user: {
    user_id: string;
    tenant_id: string;
    email: string;
    role: "house_owner" | "iot_staff" | "cloud_staff";
    display_name: string | null;
    house_ids: string[];
    is_active: boolean;
    last_login_at: string | null;
  };
  houses: HouseRef[];
}

export function login(body: LoginRequest): Promise<LoginResponse> {
  return http.post<LoginResponse>("/api/v1/auth/login", body);
}

export function logout(): Promise<void> {
  return http.post<void>("/api/v1/auth/logout");
}

export function fetchMe(): Promise<AuthMeResponse> {
  return http.get<AuthMeResponse>("/api/v1/auth/me");
}

export function fetchJwks(): Promise<{ keys: unknown[] }> {
  return http.get<{ keys: unknown[] }>("/.well-known/jwks.json");
}

// --- Settings (C4-06) --------------------------------------------------------

export type ServiceCode =
  | "fire_safety" | "distress" | "intrusion" | "fall"
  | "wellness" | "presence" | "pet";
export type Sensitivity = "low" | "medium" | "high";

export interface HouseSettings {
  house_id: string;
  enabled_services: ServiceCode[];
  quiet_start: string | null;
  quiet_end: string | null;
  sensitivity: Sensitivity;
  is_default: boolean;
  updated_at: string | null;
}

export interface SettingsUpsert {
  enabled_services: ServiceCode[];
  quiet_start: string | null;
  quiet_end: string | null;
  sensitivity: Sensitivity;
}

export function fetchSettings(houseId: string): Promise<HouseSettings> {
  return http.get<HouseSettings>(`/api/v1/houses/${houseId}/settings`);
}

export function putSettings(houseId: string, body: SettingsUpsert): Promise<HouseSettings> {
  return http.put<HouseSettings>(`/api/v1/houses/${houseId}/settings`, body);
}

// --- Emergency contacts (C4-06) ---------------------------------------------

export type ContactType = "family" | "caregiver" | "neighbor" | "emergency_service";

export interface EmergencyContact {
  contact_id: string;
  house_id: string;
  name: string;
  email: string;
  phone: string | null;
  contact_type: ContactType;
  priority: number;
}

export interface ContactCreate {
  name: string;
  email: string;
  phone?: string;
  contact_type: ContactType;
  priority?: number;
}

export interface ContactPatch {
  name?: string;
  email?: string;
  phone?: string;
  contact_type?: ContactType;
  priority?: number;
}

export function fetchContacts(houseId: string): Promise<EmergencyContact[]> {
  return http.get<EmergencyContact[]>(`/api/v1/houses/${houseId}/emergency-contacts`);
}

export function createContact(houseId: string, body: ContactCreate): Promise<EmergencyContact> {
  return http.post<EmergencyContact>(`/api/v1/houses/${houseId}/emergency-contacts`, body);
}

export function patchContact(contactId: string, body: ContactPatch): Promise<EmergencyContact> {
  return http.patch<EmergencyContact>(`/api/v1/emergency-contacts/${contactId}`, body);
}

export function deleteContact(contactId: string): Promise<void> {
  return http.delete<void>(`/api/v1/emergency-contacts/${contactId}`);
}

export function reorderContacts(houseId: string, contactIds: string[]): Promise<void> {
  return http.put<void>(`/api/v1/houses/${houseId}/emergency-contacts/order`, { contact_ids: contactIds });
}

// --- Tenants + users admin (C4-07) ------------------------------------------

export type AdminRole = "house_owner" | "iot_staff" | "cloud_staff";

export interface Tenant {
  tenant_id: string;
  name: string;
  timezone: string;
  status: string;
  created_at: string;
}

export interface AdminUser {
  user_id: string;
  tenant_id: string | null;
  email: string;
  role: AdminRole;
  display_name: string | null;
  house_ids: string[];
  is_active: boolean;
  last_login_at: string | null;
}

export function fetchTenants(): Promise<Tenant[]> {
  return http.get<Tenant[]>("/api/v1/tenants");
}

export function createTenant(body: { name: string; timezone: string }): Promise<Tenant> {
  return http.post<Tenant>("/api/v1/tenants", body);
}

export function fetchTenantUsers(tenantId: string): Promise<AdminUser[]> {
  return http.get<AdminUser[]>(`/api/v1/tenants/${tenantId}/users`);
}

export function createTenantUser(
  tenantId: string,
  body: { email: string; password: string; role: AdminRole; display_name?: string; house_ids?: string[] },
): Promise<AdminUser> {
  return http.post<AdminUser>(`/api/v1/tenants/${tenantId}/users`, body);
}

export function patchUser(
  userId: string,
  body: { role?: AdminRole; house_ids?: string[]; is_active?: boolean; unlock?: boolean; password?: string },
): Promise<AdminUser> {
  return http.patch<AdminUser>(`/api/v1/users/${userId}`, body);
}

// --- Dashboard summary (C4-08) ----------------------------------------------

export type DashboardRange = "24h" | "7d" | "30d";

export interface DashboardKpis {
  houses: number;
  feeds_total: number;
  feeds_active: number;
  feeds_online: number;
  alerts: number;
  open_alerts: number;
  clips_classified: number;
}

export interface DashboardSummary {
  kpis: DashboardKpis;
  alerts_by_severity: { critical: number; high: number; medium: number; low: number };
  alerts_by_day: { date: string; count: number }[];
  detections_top: { label: string; count: number }[];
  recent_alerts: {
    alert_id: string;
    alert_type_code: string;
    severity: string;
    status: string;
    house_name: string | null;
    room_name: string | null;
    triggered_at: string | null;
  }[];
  activity: { house_id: string; room_id: string; anomaly_score: number; band: string }[];
}

export interface DashboardSummaryResult {
  data: DashboardSummary;
  meta: {
    range: DashboardRange;
    generated_at: string;
    live_since: string;
    unavailable: string[];
  };
}

export function fetchDashboardSummary(params: {
  range?: DashboardRange;
  houseId?: string;
  tenantId?: string;
}): Promise<DashboardSummaryResult> {
  const q = new URLSearchParams();
  if (params.range) q.set("range", params.range);
  if (params.houseId) q.set("house_id", params.houseId);
  if (params.tenantId) q.set("tenant_id", params.tenantId);
  const qs = q.toString();
  return http
    .getEnvelope<DashboardSummary>(`/api/v1/dashboard/summary${qs ? `?${qs}` : ""}`)
    .then((env) => ({
      data: env.data,
      meta: env.meta as DashboardSummaryResult["meta"],
    }));
}
