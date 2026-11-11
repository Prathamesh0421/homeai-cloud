/** Alert Detail (/alerts/:alertId): evidence, timeline, contacts notified, lifecycle actions. */

import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { alertAction, c2Keys, getAlert, type AlertAction, type AlertDetail } from "../../api/c2";
import { ApiError } from "../../api/http";
import {
  ActionBar,
  Button,
  ConfidenceBars,
  ErrorState,
  SeverityBadge,
  StatusChip,
  Timeline,
  useToasts,
} from "../../shared";
import { AlertClip } from "./AlertClip";
import { FalsePositiveDialog } from "./FalsePositiveDialog";
import { deliveryStatus, formatWhen, labelText, percent, timelineLabel, type DeliveryTone } from "./format";

const NOTE_MAX = 500;

const TONE_CLASS: Record<DeliveryTone, string> = {
  ok: "text-success",
  pending: "text-warning",
  retry: "text-orange-700",
  failed: "text-danger",
};

const TONE_ICON: Record<DeliveryTone, string> = { ok: "✓", pending: "…", retry: "↻", failed: "✕" };

const ACTION_DONE: Record<AlertAction, string> = {
  acknowledge: "Alert acknowledged",
  resolve: "Alert resolved",
  false_positive: "Marked as false positive",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-surface p-4 shadow-card">
      <h2 className="mb-3 text-sm font-semibold text-ink">{title}</h2>
      {children}
    </section>
  );
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 404) return "This alert does not exist (or was removed).";
    if (error.status === 403) return "You don't have access to this alert.";
    return `Could not load the alert: ${error.message}`;
  }
  return "Could not load the alert.";
}

export default function AlertDetailPage() {
  const { alertId = "" } = useParams();
  const queryClient = useQueryClient();
  const { push } = useToasts();
  const [note, setNote] = useState("");
  const [confirmFp, setConfirmFp] = useState(false);

  const alert = useQuery({ queryKey: c2Keys.alert(alertId), queryFn: () => getAlert(alertId) });

  const act = useMutation({
    mutationFn: ({ action, text }: { action: AlertAction; text?: string }) =>
      alertAction(alertId, action, text),
    onSuccess: (updated, { action }) => {
      queryClient.setQueryData(c2Keys.alert(alertId), updated);
      queryClient.invalidateQueries({ queryKey: ["c2", "alerts"] });
      setNote("");
      setConfirmFp(false);
      push({ tone: "success", message: ACTION_DONE[action] });
    },
    onError: (error) => {
      setConfirmFp(false);
      if (error instanceof ApiError && error.status === 409) {
        // Someone else changed it first: show the server's reason and the current state.
        push({ tone: "warning", message: error.message });
        queryClient.invalidateQueries({ queryKey: c2Keys.alert(alertId) });
      } else {
        push({ tone: "error", message: error instanceof Error ? error.message : "Action failed" });
      }
    },
  });

  if (alert.isPending) return <div className="py-8 text-center text-sm text-muted">Loading alert…</div>;
  if (alert.isError) {
    return (
      <div className="space-y-4">
        <Link to="/alerts" className="text-sm text-muted hover:underline">
          ← All alerts
        </Link>
        <ErrorState message={errorMessage(alert.error)} onRetry={() => alert.refetch()} />
      </div>
    );
  }

  const a: AlertDetail = alert.data;
  const can = (action: AlertAction) => a.allowed_actions.includes(action) && !act.isPending;
  const closed = a.allowed_actions.length === 0;

  return (
    <div className="space-y-4">
      <Link to="/alerts" className="text-sm text-muted hover:underline">
        ← All alerts
      </Link>

      <header className="flex flex-wrap items-center gap-3">
        <SeverityBadge severity={a.severity} />
        <h1 className="text-2xl font-semibold tracking-tight text-ink">{a.alert_type_name}</h1>
        <StatusChip status={a.status} />
        <div className="w-full text-sm text-muted">
          {a.house_name ?? "House unavailable"}
          {a.room_name ? ` · ${a.room_name}` : ""} ·{" "}
          <time dateTime={a.triggered_at}>{formatWhen(a.triggered_at)}</time>
        </div>
      </header>

      <div className="grid gap-4 lg:grid-cols-2">
        <Section title="Evidence">
          <div className="mb-4">
            <AlertClip mediaId={a.evidence.media_id} />
          </div>
          <p className="mb-2 text-sm text-ink">
            Matched <strong>{labelText(a.top_label)}</strong> at {percent(a.top_confidence)}
            {a.evidence.threshold !== null && (
              <> (alert threshold {percent(a.evidence.threshold)}, rule plus house sensitivity)</>
            )}
          </p>
          <ConfidenceBars
            scores={a.evidence.labels.map((l) => ({ label: labelText(l.label), score: l.confidence }))}
          />
          <p className="mt-3 text-xs text-muted">
            {a.evidence.detection_available
              ? a.evidence.model
                ? `Model ${a.evidence.model.name} ${a.evidence.model.version}`
                : null
              : "Detection details are unavailable right now; showing the top label only."}
          </p>
        </Section>

        <Section title="Timeline">
          <Timeline
            events={a.timeline.map((t, i) => ({
              id: `${i}-${t.changed_at}`,
              label: timelineLabel(t),
              at: formatWhen(t.changed_at),
            }))}
          />
        </Section>
      </div>

      <Section title="Contacts notified">
        <table className="w-full text-sm">
          <thead className="text-left text-xs uppercase tracking-wide text-muted">
            <tr>
              <th className="py-1">#</th>
              <th className="py-1">Recipient</th>
              <th className="py-1">Delivery</th>
              <th className="py-1">Sent</th>
            </tr>
          </thead>
          <tbody>
            {a.notifications.map((n) => {
              const delivery = deliveryStatus(n);
              return (
                <tr key={n.notification_id} className="border-t border-border">
                  <td className="py-1.5 text-muted">{n.priority ?? "—"}</td>
                  <td className="py-1.5 text-ink">
                    {n.channel === "in_app" ? "In-app alert list" : n.recipient}
                    {n.view_link && (
                      <a href={n.view_link} className="ml-2 text-xs text-accent underline" target="_blank" rel="noreferrer">
                        demo link
                      </a>
                    )}
                  </td>
                  <td className={`py-1.5 ${TONE_CLASS[delivery.tone]}`}>
                    <span aria-hidden="true">{TONE_ICON[delivery.tone]} </span>
                    {delivery.text}
                  </td>
                  <td className="py-1.5 text-muted">{n.sent_at ? formatWhen(n.sent_at) : "—"}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {a.severity !== "critical" && a.severity !== "high" && (
          <p className="mt-2 text-xs text-muted">
            Emails go out for critical and high alerts only.
          </p>
        )}
      </Section>

      <Section title="Actions">
        {closed ? (
          <p className="text-sm text-muted">This alert is closed; no further actions.</p>
        ) : (
          <div className="space-y-3">
            <div>
              <label htmlFor="alert-note" className="block text-xs font-medium text-muted">
                Note (optional, saved with Acknowledge or Resolve)
              </label>
              <textarea
                id="alert-note"
                rows={2}
                maxLength={NOTE_MAX}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                className="mt-1 w-full rounded-md border border-border-strong bg-surface p-2 text-sm text-ink"
              />
            </div>
            <ActionBar>
              <Button
                disabled={!can("acknowledge")}
                onClick={() => act.mutate({ action: "acknowledge", text: note })}
              >
                Acknowledge
              </Button>
              <Button
                variant="secondary"
                disabled={!can("resolve")}
                onClick={() => act.mutate({ action: "resolve", text: note })}
              >
                Resolve
              </Button>
              <Button variant="danger" disabled={!can("false_positive")} onClick={() => setConfirmFp(true)}>
                Mark false positive
              </Button>
            </ActionBar>
            {!a.allowed_actions.includes("resolve") && (
              <p className="text-xs text-muted">Acknowledge the alert before resolving it.</p>
            )}
          </div>
        )}
      </Section>

      <FalsePositiveDialog
        open={confirmFp}
        busy={act.isPending}
        onCancel={() => setConfirmFp(false)}
        onConfirm={(reason) => act.mutate({ action: "false_positive", text: reason })}
      />
    </div>
  );
}
