/**
 * Login page: email + password, error states for 401 (invalid_credentials)
 * and 423 (account_locked with countdown), then redirect to the role landing.
 * Split layout: problem/solution story on the left, sign-in on the right.
 */

import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useAuth, landingForRole } from "../../auth/AuthProvider";
import { ApiError } from "../../api/http";

const FLOW = [
  { step: "01", title: "Ingest", body: "Clips upload from home feeds to cloud storage." },
  { step: "02", title: "Classify", body: "YAMNet labels sounds like smoke, glass, or a fall." },
  { step: "03", title: "Alert", body: "Rules open alerts and email emergency contacts." },
] as const;

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
    <div className="relative min-h-screen bg-canvas lg:grid lg:grid-cols-2">
      {/* Left: problem + solution */}
      <aside className="relative flex flex-col justify-between overflow-hidden bg-primary px-8 py-10 text-white sm:px-12 lg:px-14 lg:py-14">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 opacity-90"
          style={{
            background:
              "radial-gradient(90% 70% at 0% 0%, rgba(96,165,250,0.28), transparent 55%)," +
              "radial-gradient(80% 60% at 100% 100%, rgba(15,23,42,0.45), transparent 50%)",
          }}
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -right-16 top-24 h-64 w-64 rounded-full border border-white/10"
        />
        <div
          aria-hidden="true"
          className="pointer-events-none absolute -right-8 top-40 h-40 w-40 rounded-full border border-white/10"
        />

        <div className="relative animate-[fadeSlide_500ms_ease-out]">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-blue-200">
            HomeAI Cloud
          </p>
          <h1 className="mt-4 max-w-md text-3xl font-semibold tracking-tight sm:text-4xl">
            Know when a home needs help — without watching every camera.
          </h1>
          <p className="mt-4 max-w-md text-sm leading-relaxed text-blue-100/90 sm:text-base">
            Operators and caregivers get ranked safety alerts from short audio/video clips,
            not a wall of raw feeds.
          </p>
        </div>

        <div className="relative mt-10 max-w-md animate-[fadeSlide_700ms_ease-out]">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-blue-200/80">
            The problem
          </p>
          <ul className="mt-3 space-y-2 text-sm leading-relaxed text-blue-50/90">
            <li>Many homes and tenants must stay isolated from each other.</li>
            <li>Raw clips are not actionable for emergency contacts.</li>
            <li>Auth, AI, rules, and email escalation have to work as one product.</li>
          </ul>

          <p className="mt-8 text-xs font-semibold uppercase tracking-[0.18em] text-blue-200/80">
            How HomeAI solves it
          </p>
          <ol className="mt-4 space-y-4">
            {FLOW.map((item, i) => (
              <li
                key={item.step}
                className="flex gap-4 animate-[fadeSlide_600ms_ease-out]"
                style={{ animationDelay: `${120 + i * 90}ms`, animationFillMode: "both" }}
              >
                <span className="mt-0.5 font-mono text-xs text-blue-200/70">{item.step}</span>
                <div>
                  <p className="text-sm font-semibold text-white">{item.title}</p>
                  <p className="mt-0.5 text-sm text-blue-100/85">{item.body}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>

        <p className="relative mt-10 text-xs text-blue-200/70 lg:mt-0">
          CMPE 281 · multi-tenant smart-home platform on AWS
        </p>
      </aside>

      {/* Right: sign-in */}
      <main className="relative flex items-center justify-center px-6 py-12 sm:px-10">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(100% 70% at 100% 0%, rgba(37,99,235,0.08), transparent 55%)," +
              "radial-gradient(90% 60% at 0% 100%, rgba(30,58,138,0.06), transparent 50%)",
          }}
        />
        <form
          onSubmit={onSubmit}
          className="relative w-full max-w-md animate-[fadeSlide_550ms_ease-out] space-y-5 rounded-xl border border-border bg-surface p-8 shadow-pop"
        >
          <div>
            <h2 className="text-2xl font-semibold tracking-tight text-ink">Sign in</h2>
            <p className="mt-1 text-sm text-muted">Access your HomeAI console.</p>
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
      </main>

      <style>{`
        @keyframes fadeSlide {
          from { opacity: 0; transform: translateY(10px); }
          to { opacity: 1; transform: translateY(0); }
        }
      `}</style>
    </div>
  );
}
