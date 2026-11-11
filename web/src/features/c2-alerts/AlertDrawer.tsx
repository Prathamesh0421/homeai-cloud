/** AlertDrawer: side Sheet showing an alert's clip, confidences, timeline, and actions.
 *  Reuses the same alertAction mutation as the full AlertDetailPage. */

import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { alertAction, c2Keys, getAlert, type AlertAction, type AlertDetail } from "../../api/c2";
import { ApiError } from "../../api/http";
import {
  ConfidenceBars,
  SeverityBadge,
  StatusChip,
  Timeline,
  useToasts,
} from "../../shared";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { AlertClip } from "./AlertClip";
import { FalsePositiveDialog } from "./FalsePositiveDialog";
import { formatWhen, labelText, percent, timelineLabel } from "./format";

const ACTION_DONE: Record<AlertAction, string> = {
  acknowledge: "Alert acknowledged",
  resolve: "Alert resolved",
  false_positive: "Marked as false positive",
};

export interface AlertDrawerProps {
  alertId: string | null;
  onOpenChange: (open: boolean) => void;
}

export function AlertDrawer({ alertId, onOpenChange }: AlertDrawerProps) {
  const queryClient = useQueryClient();
  const { push } = useToasts();
  const [note, setNote] = useState("");
  const [confirmFp, setConfirmFp] = useState(false);

  // Reset draft note / FP dialog when opening a different alert (or closing).
  useEffect(() => {
    setNote("");
    setConfirmFp(false);
  }, [alertId]);

  const alert = useQuery({
    queryKey: c2Keys.alert(alertId ?? ""),
    queryFn: () => getAlert(alertId!),
    enabled: Boolean(alertId),
  });

  const act = useMutation({
    mutationFn: ({ action, text }: { action: AlertAction; text?: string }) =>
      alertAction(alertId!, action, text),
    onSuccess: (updated, { action }) => {
      queryClient.setQueryData(c2Keys.alert(alertId!), updated);
      queryClient.invalidateQueries({ queryKey: ["c2", "alerts"] });
      setNote("");
      setConfirmFp(false);
      push({ tone: "success", message: ACTION_DONE[action] });
    },
    onError: (error) => {
      if (error instanceof ApiError && error.status === 409) {
        push({ tone: "warning", message: error.message });
        queryClient.invalidateQueries({ queryKey: c2Keys.alert(alertId!) });
      } else {
        push({ tone: "error", message: error instanceof Error ? error.message : "Action failed" });
      }
    },
  });

  const a: AlertDetail | undefined = alert.data;
  const can = (action: AlertAction) =>
    a?.allowed_actions.includes(action) && !act.isPending;

  return (
    <Sheet open={Boolean(alertId)} onOpenChange={onOpenChange}>
      <SheetContent className="w-full max-w-lg overflow-y-auto">
        {alert.isPending ? (
          <div className="py-8 text-center text-sm text-muted">Loading alert…</div>
        ) : alert.isError || !a ? (
          <div className="py-8 text-center text-sm text-muted">Could not load this alert.</div>
        ) : (
          <>
            <SheetHeader>
              <div className="flex flex-wrap items-center gap-2">
                <SeverityBadge severity={a.severity} />
                <StatusChip status={a.status} />
              </div>
              <SheetTitle>{a.alert_type_name}</SheetTitle>
              <SheetDescription>
                {a.house_name ?? "House unavailable"}
                {a.room_name ? ` · ${a.room_name}` : ""} ·{" "}
                <time dateTime={a.triggered_at}>{formatWhen(a.triggered_at)}</time>
              </SheetDescription>
            </SheetHeader>

            <div className="space-y-5 px-5 pb-6">
              <section>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                  Recording
                </h3>
                <AlertClip mediaId={a.evidence.media_id} />
              </section>

              {/* Confidence */}
              <section>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                  What was heard
                </h3>
                <p className="mb-2 text-sm text-ink">
                  Matched <strong>{labelText(a.top_label)}</strong> at {percent(a.top_confidence)}
                  {a.evidence.threshold !== null && (
                    <> (threshold {percent(a.evidence.threshold)})</>
                  )}
                </p>
                <ConfidenceBars
                  scores={a.evidence.labels.map((l) => ({ label: labelText(l.label), score: l.confidence }))}
                />
              </section>

              {/* Timeline */}
              <section>
                <h3 className="mb-2 text-xs font-medium uppercase tracking-wide text-muted">
                  Timeline
                </h3>
                <Timeline
                  events={a.timeline.map((t, i) => ({
                    id: `${i}-${t.changed_at}`,
                    label: timelineLabel(t),
                    at: formatWhen(t.changed_at),
                  }))}
                />
              </section>

              {/* Actions */}
              {a.allowed_actions.length > 0 && (
                <section className="space-y-3 border-t border-border pt-4">
                  <div>
                    <label htmlFor="drawer-note" className="block text-xs font-medium text-muted">
                      Note (optional, saved with Acknowledge or Resolve)
                    </label>
                    <textarea
                      id="drawer-note"
                      rows={2}
                      maxLength={500}
                      value={note}
                      onChange={(e) => setNote(e.target.value)}
                      className="mt-1 w-full rounded-md border border-border-strong bg-surface p-2 text-sm text-ink"
                    />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button disabled={!can("acknowledge")} onClick={() => act.mutate({ action: "acknowledge", text: note })}>
                      Acknowledge
                    </Button>
                    <Button variant="secondary" disabled={!can("resolve")} onClick={() => act.mutate({ action: "resolve", text: note })}>
                      Resolve
                    </Button>
                    <Button variant="danger" disabled={!can("false_positive")} onClick={() => setConfirmFp(true)}>
                      Mark false positive
                    </Button>
                  </div>
                </section>
              )}
            </div>

          </>
        )}
      </SheetContent>
      <FalsePositiveDialog
        open={confirmFp}
        busy={act.isPending}
        onCancel={() => setConfirmFp(false)}
        onConfirm={(reason) => act.mutate({ action: "false_positive", text: reason })}
      />
    </Sheet>
  );
}
