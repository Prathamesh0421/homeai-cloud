/**
 * Login page: split layout.
 *  - Left: brand, one-line problem, the pipeline scene as hero, 01/02/03 legend.
 *  - Right: sign-in form (flush on the panel, password toggle, fixed-width
 *    spinner, shake on failure, aria-live error, VITE_DEMO role chips).
 *
 * Mobile: form first with a two-line pitch, story + scene below.
 */

import { useEffect, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { motion, useReducedMotion } from "motion/react";
import { Eye, EyeOff, Loader2 } from "lucide-react";
import { useAuth, landingForRole } from "../../auth/AuthProvider";
import { ApiError } from "../../api/http";
import { PipelineScene, type Step } from "./PipelineScene";

const DEMO = import.meta.env.VITE_DEMO === "true";

const DEMO_USERS: { label: string; email: string; password: string }[] = DEMO
  ? [
      { label: "Cloud staff", email: "ops@homeai.test", password: "Demo!2026" },
      { label: "House owner", email: "owner.maple@acme.test", password: "Demo!2026" },
      { label: "IoT staff", email: "iot@acme.test", password: "Demo!2026" },
    ]
  : [];

const LEGEND: { step: Step; n: string; label: string }[] = [
  { step: "ingest", n: "01", label: "Ingest" },
  { step: "classify", n: "02", label: "Classify" },
  { step: "alert", n: "03", label: "Alert" },
];

export default function Login() {
  const { session, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const reduce = useReducedMotion();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lockedFor, setLockedFor] = useState<number | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [shake, setShake] = useState(0);
  const [activeStep, setActiveStep] = useState<Step>("ingest");

  useEffect(() => {
    if (session) navigate(landingForRole(session.role), { replace: true });
  }, [session, navigate]);

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
      setShake((s) => s + 1);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="relative min-h-screen bg-canvas lg:grid lg:grid-cols-[1.05fr_0.95fr]">
      {/* Right: sign-in (rendered first in DOM so mobile shows it first) */}
      <main className="relative order-1 flex items-center justify-center px-6 py-10 sm:px-10 lg:order-2">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0"
          style={{
            background:
              "radial-gradient(100% 70% at 100% 0%, rgba(37,99,235,0.08), transparent 55%)," +
              "radial-gradient(90% 60% at 0% 100%, rgba(30,58,138,0.06), transparent 50%)",
          }}
        />
        <motion.form
          onSubmit={onSubmit}
          animate={shake ? (reduce ? undefined : { x: [0, -6, 6, -4, 4, 0] }) : undefined}
          transition={shake ? { duration: 0.2 } : undefined}
          className="relative w-full max-w-md space-y-5"
        >
          {/* Mobile pitch (two lines) */}
          <div className="lg:hidden">
            <h1 className="text-2xl font-semibold tracking-tight text-ink">
              Know when a home needs help.
            </h1>
            <p className="mt-1 text-sm text-muted">
              Clips become ranked alerts your contacts can act on.
            </p>
          </div>

          {/* Desktop heading */}
          <div className="hidden lg:block">
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
              className="mt-1.5 block w-full rounded-md border border-border-strong bg-surface px-3 py-2.5 text-sm text-ink placeholder:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
              autoComplete="email"
              placeholder="you@example.com"
            />
          </label>

          <label className="block text-sm">
            <span className="font-medium text-ink">Password</span>
            <div className="relative mt-1.5">
              <input
                type={showPw ? "text" : "password"}
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="block w-full rounded-md border border-border-strong bg-surface px-3 py-2.5 pr-10 text-sm text-ink placeholder:text-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
                autoComplete="current-password"
                placeholder="••••••••••"
              />
              <button
                type="button"
                onClick={() => setShowPw((s) => !s)}
                className="absolute inset-y-0 right-0 flex w-10 items-center justify-center text-muted hover:text-ink"
                aria-label={showPw ? "Hide password" : "Show password"}
                tabIndex={-1}
              >
                {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </label>

          {error && (
            <div
              className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger"
              role="alert"
              aria-live="assertive"
            >
              {error}
              {lockedFor !== null && lockedFor > 0 ? ` (${lockedFor}s)` : ""}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || lockedFor !== null}
            className="inline-flex w-[7.5rem] items-center justify-center gap-2 rounded-md bg-primary px-3 py-2.5 text-sm font-medium text-white shadow-card transition-colors hover:bg-primary-hover disabled:opacity-50"
          >
            {submitting ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin" />
                <span>Signing in…</span>
              </>
            ) : (
              <span>Sign in</span>
            )}
          </button>

          {DEMO && (
            <div className="space-y-2">
              <p className="text-xs font-medium text-muted">Demo accounts</p>
              <div className="flex flex-wrap gap-2">
                {DEMO_USERS.map((u) => (
                  <button
                    key={u.label}
                    type="button"
                    onClick={() => {
                      setEmail(u.email);
                      setPassword(u.password);
                      setError(null);
                    }}
                    className="rounded-full border border-border-strong bg-surface px-3 py-1 text-xs text-ink transition-colors hover:bg-surface-2"
                  >
                    {u.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </motion.form>
      </main>

      {/* Left: brand + story + scene */}
      <aside className="relative order-2 flex flex-col justify-between overflow-hidden bg-primary px-8 py-10 text-white sm:px-12 lg:order-1 lg:px-14 lg:py-14">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 opacity-90"
          style={{
            background:
              "radial-gradient(90% 70% at 0% 0%, rgba(96,165,250,0.28), transparent 55%)," +
              "radial-gradient(80% 60% at 100% 100%, rgba(15,23,42,0.45), transparent 50%)",
          }}
        />

        {/* Brand: small logo mark + sentence-case wordmark */}
        <div className="relative flex items-center gap-2">
          <span
            aria-hidden="true"
            className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-white/10 text-sm font-semibold text-white ring-1 ring-white/15"
          >
            H
          </span>
          <span className="text-sm font-medium tracking-tight text-white">HomeAI Cloud</span>
        </div>

        {/* Headline + one-line problem */}
        <div className="relative mt-10 max-w-md">
          <h2 className="text-3xl font-semibold tracking-tight sm:text-4xl">
            Know when a home needs help, without watching every camera.
          </h2>
          <p className="mt-4 text-sm leading-relaxed text-blue-100/90 sm:text-base">
            Clips alone are a wall of media. HomeAI turns them into ranked alerts your contacts can act on.
          </p>
        </div>

        {/* Scene hero */}
        <div className="relative mt-8 max-w-md">
          <PipelineScene onStep={setActiveStep} />

          {/* Legend: 01/02/03 highlights in sync */}
          <ol className="mt-8 grid grid-cols-3 gap-3 border-t border-white/10 pt-5">
            {LEGEND.map((item) => {
              const isActive = activeStep === item.step;
              return (
                <li
                  key={item.step}
                  className={
                    "flex items-center gap-2 text-sm transition-colors " +
                    (isActive ? "text-white" : "text-blue-200/50")
                  }
                >
                  <span className="font-mono text-xs">{item.n}</span>
                  <span className="font-medium">{item.label}</span>
                </li>
              );
            })}
          </ol>
        </div>

        <p className="relative mt-10 text-xs text-blue-200/70 lg:mt-0">
          CMPE 281 · multi-tenant smart-home platform on AWS
        </p>
      </aside>
    </div>
  );
}
