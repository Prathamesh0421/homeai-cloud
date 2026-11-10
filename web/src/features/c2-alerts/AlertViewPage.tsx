/**
 * Public Alert View (/alert-view/:token): what an emergency contact sees from the email link.
 * No login and no app shell; mobile-first. Shows no owner or contact details (the API sends none).
 */

import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { c2Keys, getAlertView } from "../../api/c2";
import { ApiError } from "../../api/http";
import { ConfidenceBars, SeverityBadge, StatusChip } from "../../shared";
import { formatWhen, labelText, percent, isAudioClip } from "./format";

export const VIEW_REFRESH_MS = 30_000; // status changes (acknowledged / resolved) show up

const STATUS_NOTE: Record<string, string> = {
  open: "No one has responded yet.",
  acknowledged: "The household or care team has seen this alert.",
  resolved: "This alert has been resolved.",
  false_positive: "This alert was marked as a false alarm.",
};

function Notice({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <main className="mx-auto max-w-md px-4 py-10 text-center">
      <h1 className="text-xl font-semibold tracking-tight text-ink">{title}</h1>
      <div className="mt-2 text-sm text-muted">{children}</div>
      <p className="mt-6 text-sm font-medium text-danger">If someone is in danger, call 911.</p>
    </main>
  );
}

export default function AlertViewPage() {
  const { token = "" } = useParams();
  const view = useQuery({
    queryKey: c2Keys.alertView(token),
    queryFn: () => getAlertView(token),
    refetchInterval: (q) => (q.state.error ? false : VIEW_REFRESH_MS),
    retry: false,
  });

  if (view.isPending) {
    return <Notice title="Loading alert…">One moment.</Notice>;
  }
  if (view.isError) {
    const e = view.error;
    if (e instanceof ApiError && e.status === 401) {
      return (
        <Notice title="This link has expired">
          Alert links work for 24 hours. Contact the household or their care provider for an update.
        </Notice>
      );
    }
    if (e instanceof ApiError && e.status === 404) {
      return (
        <Notice title="This link is not valid">
          Check that the whole link from the email was opened, or ask for a new one.
        </Notice>
      );
    }
    if (e instanceof ApiError && e.status === 429) {
      const wait = (e.details as { retryAfter?: number } | undefined)?.retryAfter;
      return (
        <Notice title="Too many requests">
          Please try again {wait ? `in ${wait} seconds` : "in a minute"}.
        </Notice>
      );
    }
    return (
      <Notice title="Could not load the alert">
        <button type="button" className="underline" onClick={() => view.refetch()}>
          Try again
        </button>
      </Notice>
    );
  }

  const a = view.data;
  const where = [a.room_name, a.house_name].filter(Boolean).join(", ");
  return (
    <main className="mx-auto max-w-md space-y-4 px-4 py-6">
      <p className="text-xs font-semibold uppercase tracking-wide text-muted">HomeAI Cloud alert</p>
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={a.severity} />
        <StatusChip status={a.status} />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight text-ink">{a.alert_type_name}</h1>
      <p className="text-sm text-ink">
        {where || "Location unavailable"} · <time dateTime={a.triggered_at}>{formatWhen(a.triggered_at)}</time>
      </p>
      <p className="text-sm text-muted">{STATUS_NOTE[a.status]}</p>

      <div
        role="note"
        className="rounded-lg border border-danger/30 bg-danger-soft px-4 py-3 text-base font-semibold text-danger"
      >
        If someone is in danger, call 911.
      </div>

      <section className="rounded-xl border border-border bg-surface p-4 shadow-card">
        <h2 className="mb-2 text-sm font-semibold text-ink">What was heard</h2>
        {a.labels.length > 0 && (
          <p className="mb-2 text-sm text-ink">
            {labelText(a.labels[0].label)} ({percent(a.labels[0].confidence)} confidence)
          </p>
        )}
        <ConfidenceBars scores={a.labels.map((l) => ({ label: labelText(l.label), score: l.confidence }))} />
      </section>

      <section className="rounded-xl border border-border bg-surface p-4 shadow-card">
        <h2 className="mb-2 text-sm font-semibold text-ink">Recording</h2>
        {a.clip_url ? (
          isAudioClip(a.clip_url) ? (
            <audio controls preload="none" src={a.clip_url} className="w-full" aria-label="Alert recording" />
          ) : (
            <video controls preload="none" src={a.clip_url} className="w-full" aria-label="Alert recording" />
          )
        ) : (
          <p className="text-sm text-muted">The recording is not available.</p>
        )}
      </section>

      <p className="text-xs text-muted">
        This link is valid until <time dateTime={a.expires_at}>{formatWhen(a.expires_at)}</time>. It
        updates on its own while open.
      </p>
    </main>
  );
}
