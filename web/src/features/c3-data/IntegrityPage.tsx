/** Integrity (/ops/integrity): run a check (poll to done), browse reports + findings. */

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type IntegrityFinding,
  type IntegrityReport,
  c3Keys,
  getIntegrityReport,
  listIntegrityReports,
  runIntegrityCheck,
} from "../../api/c3";
import { ApiError } from "../../api/http";
import { Button, EmptyState, ErrorState, useToasts } from "../../shared";
import { labelText, relativeTime } from "./format";
import { ShieldCheck } from "lucide-react";

const POLL_MS = 5_000;

const SEVERITY_TONE: Record<string, string> = {
  high: "bg-danger-soft text-danger border-danger/30",
  medium: "bg-warning-soft text-warning border-warning/30",
  low: "border-border-strong text-muted",
};

function SeverityBadge({ severity }: { severity: string }) {
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${SEVERITY_TONE[severity] ?? SEVERITY_TONE.low}`}>
      {labelText(severity)}
    </span>
  );
}

export default function IntegrityPage() {
  const qc = useQueryClient();
  const toasts = useToasts();
  const [activeReportId, setActiveReportId] = useState<string | null>(null);

  const reports = useQuery({ queryKey: c3Keys.integrityReports(), queryFn: () => listIntegrityReports() });

  // Poll the selected report until it leaves "running".
  const report = useQuery({
    queryKey: c3Keys.integrityReport(activeReportId ?? ""),
    queryFn: () => getIntegrityReport(activeReportId!),
    enabled: Boolean(activeReportId),
    refetchInterval: (q) => (q.state.data?.status === "running" ? POLL_MS : false),
  });

  const run = useMutation({
    mutationFn: () => runIntegrityCheck(),
    onSuccess: (r) => {
      setActiveReportId(r.report_id);
      qc.invalidateQueries({ queryKey: c3Keys.integrityReports() });
      toasts.push({ tone: "info", message: "Integrity check started" });
    },
    onError: (e) => {
      const msg =
        e instanceof ApiError && e.code === "check_running"
          ? "A check is already running — try again shortly."
          : e instanceof ApiError
            ? e.message
            : "Could not start the check.";
      toasts.push({ tone: "error", message: msg });
    },
  });

  return (
    <div className="space-y-5">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Integrity</h1>
        <Button onClick={() => run.mutate()} disabled={run.isPending}>
          {run.isPending ? "Starting…" : "Run check"}
        </Button>
      </div>

      {report.data && <ReportPanel report={report.data} isPolling={report.data.status === "running"} />}

      <div>
        <h2 className="mb-2 text-sm font-semibold text-ink">Recent checks</h2>
        {reports.isPending ? (
          <div className="py-6 text-center text-sm text-muted">Loading reports…</div>
        ) : reports.isError ? (
          <ErrorState
            message={
              reports.error instanceof ApiError && reports.error.status === 403
                ? "You don't have access to integrity reports."
                : `Could not load reports: ${reports.error.message}`
            }
            onRetry={() => reports.refetch()}
          />
        ) : reports.data.length === 0 ? (
          <EmptyState
            title="No checks yet"
            description="Run a check to scan for data faults across tenants."
            icon={<ShieldCheck className="h-8 w-8" />}
            action={
              <Button onClick={() => run.mutate()} disabled={run.isPending}>
                {run.isPending ? "Starting…" : "Run first check"}
              </Button>
            }
          />
        ) : (
          <ul className="divide-y divide-border rounded-xl border border-border bg-surface shadow-card">
            {reports.data.map((r) => (
              <li key={r.report_id}>
                <button
                  type="button"
                  className={`flex w-full items-center justify-between px-4 py-3 text-left text-sm hover:bg-surface-2 ${activeReportId === r.report_id ? "bg-surface-2" : ""}`}
                  onClick={() => setActiveReportId(r.report_id)}
                >
                  <span>
                    <span className="font-medium text-ink">{r.status === "running" ? "Running…" : `${r.findings.length} finding(s)`}</span>
                    <span className="ml-2 text-muted">{(r.scope?.tenant_id as string) ?? "all tenants"}</span>
                  </span>
                  <time className="text-xs text-muted" dateTime={r.started_at}>
                    {relativeTime(r.started_at)}
                  </time>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

function ReportPanel({ report, isPolling }: { report: IntegrityReport; isPolling: boolean }) {
  const bySeverity = report.findings.reduce<Record<string, number>>((acc, f) => {
    acc[f.severity] = (acc[f.severity] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
      <div className="flex items-center justify-between">
        <div className="text-sm font-semibold text-ink">
          {isPolling ? "Check running…" : "Check complete"}
          {!isPolling && (
            <span className="ml-2 text-xs font-normal text-muted">
              {report.findings.length} finding(s)
              {Object.entries(bySeverity).length > 0 && ` · ${Object.entries(bySeverity).map(([s, n]) => `${n} ${s}`).join(", ")}`}
            </span>
          )}
        </div>
        {isPolling && (
          <span className="text-xs text-muted" aria-live="polite">
            polling…
          </span>
        )}
      </div>

      {!isPolling && report.findings.length === 0 && (
        <p className="mt-3 text-sm text-success">No faults found — the stores are consistent.</p>
      )}

      {report.findings.length > 0 && (
        <ul className="mt-3 space-y-2">
          {report.findings.map((f, i) => (
            <FindingRow key={`${f.entity_id}-${i}`} finding={f} />
          ))}
        </ul>
      )}
    </div>
  );
}

function FindingRow({ finding }: { finding: IntegrityFinding }) {
  const qc = useQueryClient();
  const toasts = useToasts();
  // Requeue is offered for faults whose entity is a failed clip (media_id). The integrity scan
  // flags stuck_processing / analyzed_no_detection on media_events; a requeue applies to a
  // failed clip only (409 not_failed otherwise), so offer it and surface the server's answer.
  const requeuable = finding.kind === "stuck_processing" || finding.kind === "analyzed_no_detection";
  const requeue = useMutation({
    mutationFn: async () => {
      const { requeueClip } = await import("../../api/c3");
      return requeueClip(finding.entity_id);
    },
    onSuccess: () => {
      toasts.push({ tone: "success", message: `Requeued ${finding.entity_id}` });
      qc.invalidateQueries({ queryKey: ["c3", "integrity-reports"] });
    },
    onError: (e) => {
      const msg =
        e instanceof ApiError && e.code === "not_failed"
          ? "That clip is not in a failed state."
          : e instanceof ApiError
            ? e.message
            : "Could not requeue.";
      toasts.push({ tone: "error", message: msg });
    },
  });

  return (
    <li className="flex items-center justify-between rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm">
      <span className="flex items-center gap-2">
        <SeverityBadge severity={finding.severity} />
        <span className="font-medium text-ink">{labelText(finding.kind)}</span>
        <code className="text-xs text-muted">{finding.entity_id}</code>
      </span>
      {requeuable && (
        <Button variant="secondary" onClick={() => requeue.mutate()} disabled={requeue.isPending}>
          {requeue.isPending ? "Requeuing…" : "Requeue"}
        </Button>
      )}
    </li>
  );
}
