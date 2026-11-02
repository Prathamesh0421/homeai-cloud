/**
 * RouteGuard: wraps a route element and enforces role-based access.
 *
 * - If no session, redirect to /login (preserving the intended destination).
 * - If the session role is not allowed, redirect to the user's landing page.
 *   Opening another role's route redirects to your own landing (contracts §2).
 */

import type { ReactNode } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { landingForRole, useAuth, type Role } from "./AuthProvider";

interface RouteGuardProps {
  allow: Role[];
  children: ReactNode;
}

export function RouteGuard({ allow, children }: RouteGuardProps) {
  const { session, loading } = useAuth();
  const location = useLocation();

  if (loading) {
    return <div className="p-8 text-slate-500">Loading…</div>;
  }
  if (!session) {
    return <Navigate to="/login" state={{ from: location.pathname }} replace />;
  }
  if (!allow.includes(session.role)) {
    return <Navigate to={landingForRole(session.role)} replace />;
  }
  return <>{children}</>;
}
