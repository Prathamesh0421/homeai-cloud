/**
 * Login page: email + password, error states for 401 (invalid_credentials)
 * and 423 (account_locked with countdown), then redirect to the role landing.
 */

import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth, landingForRole } from "../../auth/AuthProvider";
import { ApiError } from "../../api/http";

export default function Login() {
  const { session, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [lockedFor, setLockedFor] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);

  // If already signed in, go to landing.
  useEffect(() => {
    if (session) navigate(landingForRole(session.role), { replace: true });
  }, [session, navigate]);

  // Countdown for account_locked.
  useEffect(() => {
    if (lockedFor === null) return;
    if (lockedFor <= 0) {
      setLockedFor(null);
      return;
    }
    const t = setTimeout(() => setLockedFor((s) => (s ?? 0) - 1), 1000);
    return () => clearTimeout(t);
  }, [lockedFor]);

  const from = (location.state as { from?: string } | null)?.from;

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const next = await login({ email, password });
      navigate(from ?? landingForRole(next.role), { replace: true });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 423) {
          const retry = (err.details as { retry_after?: number } | undefined)?.retry_after ?? 60;
          setLockedFor(retry);
          setError("Account is locked. Try again shortly.");
        } else if (err.code === "invalid_credentials") {
          setError("Invalid email or password.");
        } else {
          setError(err.message);
        }
      } else {
        setError("Unable to sign in. Try again.");
      }
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-50">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm space-y-4 rounded-lg border border-slate-200 bg-white p-8 shadow-sm"
      >
        <h1 className="text-xl font-semibold text-slate-900">Sign in to HomeAI Cloud</h1>
        <label className="block text-sm">
          <span className="text-slate-700">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 px-3 py-2"
            autoComplete="email"
          />
        </label>
        <label className="block text-sm">
          <span className="text-slate-700">Password</span>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1 block w-full rounded border border-slate-300 px-3 py-2"
            autoComplete="current-password"
          />
        </label>
        {error && (
          <div className="rounded bg-red-50 px-3 py-2 text-sm text-red-700" role="alert">
            {error}
            {lockedFor !== null && lockedFor > 0 ? ` (${lockedFor}s)` : ""}
          </div>
        )}
        <button
          type="submit"
          disabled={submitting || lockedFor !== null}
          className="w-full rounded bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
