/**
 * Fetch wrapper for the HomeAI Cloud API.
 *
 * - Base path is relative ("/api/v1") so the same build works behind Caddy
 *   locally and on EC2. The Vite dev server proxies "/api" to the gateway.
 * - Adds the bearer token from AuthProvider.
 * - Maps the contract error envelope {"error": {code, message, details}} to
 *   an ApiError. A 401 clears the token and notifies the auth layer via a
 *   window event.
 */

export class ApiError extends Error {
  status: number;
  code: string;
  details: unknown;

  constructor(status: number, code: string, message: string, details: unknown) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const TOKEN_KEY = "homeai.token";

export function getToken(): string | null {
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
  window.dispatchEvent(new Event("homeai:token"));
}

export function clearToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
  window.dispatchEvent(new Event("homeai:token"));
}

export interface Envelope<T> {
  data: T;
  meta?: Record<string, unknown>;
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const resp = await fetch(path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (resp.status === 204) return undefined as T;

  const text = await resp.text();
  const parsed = text ? JSON.parse(text) : undefined;

  if (!resp.ok) {
    const err = parsed?.error ?? { code: "unknown", message: resp.statusText };
    if (resp.status === 401) {
      clearToken();
    }
    throw new ApiError(resp.status, err.code ?? "unknown", err.message ?? "error", err.details);
  }

  // Endpoints return {"data": ...}; unwrap. JWKS returns the object directly.
  if (parsed && typeof parsed === "object" && "data" in parsed) {
    return parsed.data as T;
  }
  return parsed as T;
}

export const http = {
  get: <T>(path: string) => request<T>("GET", path),
  post: <T>(path: string, body?: unknown) => request<T>("POST", path, body),
  put: <T>(path: string, body?: unknown) => request<T>("PUT", path, body),
  patch: <T>(path: string, body?: unknown) => request<T>("PATCH", path, body),
  delete: <T>(path: string) => request<T>("DELETE", path),
};
