/**
 * AuthProvider: holds the session token in memory + sessionStorage, decodes
 * the claims for UI use, and exposes login/logout. A 401 anywhere clears the
 * token (http.ts dispatches "homeai:token") and we re-render.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { clearToken, getToken, setToken } from "../api/http";
import { fetchMe, login as apiLogin, logout as apiLogout, type LoginRequest } from "../api/c4";

export type Role = "house_owner" | "iot_staff" | "cloud_staff";

export interface Session {
  token: string;
  role: Role;
  tenantId: string;
  houseIds: string[];
  email: string;
  userId: string;
}

interface AuthContextValue {
  session: Session | null;
  loading: boolean;
  login: (req: LoginRequest) => Promise<Session>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function decodeClaims(token: string): Omit<Session, "token"> | null {
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    return {
      role: payload.role,
      tenantId: payload.tenant_id,
      houseIds: payload.house_ids ?? [],
      email: payload.email,
      userId: payload.sub,
    };
  } catch {
    return null;
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);

  // Restore session from sessionStorage on mount.
  useEffect(() => {
    const token = getToken();
    if (token) {
      const claims = decodeClaims(token);
      if (claims) setSession({ token, ...claims });
    }
    setLoading(false);
  }, []);

  // Listen for token clears (e.g. 401 from http.ts).
  useEffect(() => {
    const handler = () => {
      const token = getToken();
      if (!token) setSession(null);
    };
    window.addEventListener("homeai:token", handler);
    return () => window.removeEventListener("homeai:token", handler);
  }, []);

  const login = useCallback(async (req: LoginRequest) => {
    const result = await apiLogin(req);
    setToken(result.token);
    const claims = decodeClaims(result.token);
    const next: Session = {
      token: result.token,
      role: claims?.role ?? result.claims.role,
      tenantId: claims?.tenantId ?? result.claims.tenant_id,
      houseIds: claims?.houseIds ?? result.claims.house_ids,
      email: claims?.email ?? result.claims.email,
      userId: claims?.userId ?? result.claims.sub,
    };
    setSession(next);
    return next;
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // Even if the server call fails, drop the local token.
    }
    clearToken();
    setSession(null);
  }, []);

  const value = useMemo<AuthContextValue>(
    () => ({ session, loading, login, logout }),
    [session, loading, login, logout],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider");
  return ctx;
}

export function landingForRole(role: Role): string {
  switch (role) {
    case "house_owner":
      return "/home/overview";
    case "iot_staff":
      return "/iot/feeds";
    case "cloud_staff":
      return "/ops/dashboard";
  }
}

// Re-export so callers don't need fetchMe import path.
export { fetchMe };
