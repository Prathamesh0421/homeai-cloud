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
