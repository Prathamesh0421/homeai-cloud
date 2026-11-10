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
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-canvas">
      {/* Atmosphere: layered soft gradients, not a flat slab. */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(120% 80% at 15% 0%, rgba(37,99,235,0.12), transparent 60%)," +
            "radial-gradient(120% 80% at 100% 100%, rgba(30,58,138,0.08), transparent 55%)",
        }}
      />
      <form
        onSubmit={onSubmit}
        className="relative w-full max-w-md space-y-5 rounded-xl border border-border bg-surface p-8 shadow-pop"
      >
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">HomeAI Cloud</h1>
          <p className="mt-1 text-sm text-muted">Sign in to monitor your home.</p>
        </div>
        <label className="block text-sm">
          <span className="font-medium text-ink">Email</span>
          <input
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="mt-1.5 block w-full rounded-md border border-border-strong bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-muted"
            autoComplete="email"
            placeholder="you@example.com"
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium text-ink">Password</span>
          <input
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className="mt-1.5 block w-full rounded-md border border-border-strong bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-muted"
            autoComplete="current-password"
            placeholder="••••••••••"
          />
        </label>
        {error && (
          <div
            className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger"
            role="alert"
          >
            {error}
            {lockedFor !== null && lockedFor > 0 ? ` (${lockedFor}s)` : ""}
          </div>
        )}
        <button
          type="submit"
          disabled={submitting || lockedFor !== null}
          className="w-full rounded-md bg-primary px-3 py-2.5 text-sm font-medium text-white shadow-card transition-colors hover:bg-primary-hover disabled:opacity-50"
        >
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
