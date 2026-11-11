/** Model Management (/ops/models): registered versions, deployment status, create a version. */

import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  type ModelSummary,
  c3Keys,
  createModel,
  getDeployment,
  listModels,
} from "../../api/c3";
import { ApiError } from "../../api/http";
import {
  Button,
  DataTable,
  EmptyState,
  ErrorState,
  KpiTile,
  useToasts,
  type Column,
} from "../../shared";
import { labelText, percent, relativeTime, workerIsStale } from "./format";

const DEPLOY_POLL_MS = 10_000;

const STATUS_TONE: Record<string, string> = {
  active: "bg-success-soft text-success border-success/30",
  evaluated: "bg-accent-soft text-accent border-accent/30",
  registered: "border-border-strong text-muted",
  retired: "bg-surface-2 text-muted border-border",
};

function StatusBadge({ status }: { status: string }) {
  const tone = STATUS_TONE[status] ?? STATUS_TONE.registered;
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${tone}`}>
      {labelText(status)}
    </span>
  );
}

export default function ModelsPage() {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toasts = useToasts();
  const [showCreate, setShowCreate] = useState(false);

  const models = useQuery({ queryKey: c3Keys.models(), queryFn: listModels });
  const deploy = useQuery({
    queryKey: c3Keys.deployment(),
    queryFn: getDeployment,
    refetchInterval: DEPLOY_POLL_MS,
  });

  const columns: Column<ModelSummary>[] = [
    {
      key: "version",
      header: "Version",
      render: (m) => (
        <button
          type="button"
          className="font-medium text-ink hover:underline"
          onClick={() => navigate(`/ops/models/${m.model_id}`)}
        >
          {m.name} {m.version}
        </button>
      ),
      sortValue: (m) => m.version,
    },
    { key: "status", header: "Status", render: (m) => <StatusBadge status={m.status} />, sortValue: (m) => m.status },
    { key: "source", header: "Source", render: (m) => <span className="text-muted">{m.source}</span> },
    {
      key: "accuracy",
      header: "Accuracy",
      render: (m) => (
        <span className="tnum text-muted">
          {typeof m.metrics?.accuracy === "number" ? percent(m.metrics.accuracy as number, 1) : "—"}
        </span>
      ),
    },
    {
      key: "created",
      header: "Registered",
      render: (m) => (
        <time dateTime={m.created_at} title={new Date(m.created_at).toLocaleString()}>
          {relativeTime(m.created_at)}
        </time>
      ),
      sortValue: (m) => m.created_at,
    },
  ];

  const liveWorkers = useMemo(
    () => (deploy.data?.workers ?? []).filter((w) => !workerIsStale(w.last_heartbeat)),
    [deploy.data],
  );

  return (
    <div className="space-y-5">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Models</h1>
        <Button onClick={() => setShowCreate(true)}>New version</Button>
      </div>

      {/* Deployment status KPIs */}
      {deploy.data && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          <KpiTile
            label="Active model"
            value={
              deploy.data.active_model
                ? `${(deploy.data.active_model as Record<string, unknown>).version ?? "—"}`
                : "none"
            }
            hint={deploy.data.active_model ? String((deploy.data.active_model as Record<string, unknown>).name ?? "") : "no active model"}
          />
          <KpiTile
            label="Live workers"
            value={liveWorkers.length}
            hint={deploy.data.workers.length !== liveWorkers.length ? `${deploy.data.workers.length - liveWorkers.length} stale` : "all healthy"}
          />
          <KpiTile label="Queue" value={deploy.data.queue.queued} hint={`${deploy.data.queue.processing} processing · ${deploy.data.queue.failed} failed`} />
          <KpiTile label="p95 latency" value={`${deploy.data.p95_latency_ms} ms`} hint={`${deploy.data.throughput_per_min.toFixed(1)}/min`} />
        </div>
      )}

      {models.isPending ? (
        <div className="py-8 text-center text-sm text-muted">Loading models…</div>
      ) : models.isError ? (
        <ErrorState
          message={
            models.error instanceof ApiError && models.error.status === 403
              ? "You don't have access to model management."
              : `Could not load models: ${models.error.message}`
          }
          onRetry={() => models.refetch()}
        />
      ) : models.data.length === 0 ? (
        <EmptyState title="No models registered" description="Register a version to get started." />
      ) : (
        <DataTable columns={columns} rows={models.data} rowKey={(m) => m.model_id} onRowClick={(m) => navigate(`/ops/models/${m.model_id}`)} />
      )}

      {showCreate && (
        <CreateVersionDialog
          onClose={() => setShowCreate(false)}
          onCreated={(detail) => {
            toasts.push({ tone: "success", message: `Registered ${detail.name} ${detail.version}` });
            qc.invalidateQueries({ queryKey: c3Keys.models() });
            setShowCreate(false);
            navigate(`/ops/models/${detail.model_id}`);
          }}
        />
      )}
    </div>
  );
}

function CreateVersionDialog({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (d: { model_id: string; name: string; version: string }) => void;
}) {
  const [version, setVersion] = useState("");
  const [notes, setNotes] = useState("");
  const mutation = useMutation({
    mutationFn: () => createModel({ version: version.trim(), notes: notes.trim() || undefined }),
    onSuccess: onCreated,
  });

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-black/30 p-4" role="dialog" aria-label="New model version">
      <div className="w-full max-w-md rounded-xl border border-border bg-surface p-5 shadow-lg">
        <h2 className="text-lg font-semibold text-ink">New model version</h2>
        <p className="mt-1 text-xs text-muted">Registers a new version from the bundled base model.</p>
        <label className="mt-4 block text-sm">
          <span className="text-muted">Version</span>
          <input
            className="mt-1 w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-ink"
            placeholder="e.g. 1.1.0"
            value={version}
            onChange={(e) => setVersion(e.target.value)}
          />
        </label>
        <label className="mt-3 block text-sm">
          <span className="text-muted">Notes (optional)</span>
          <input
            className="mt-1 w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-ink"
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
          />
        </label>
        {mutation.isError && (
          <p className="mt-2 text-sm text-danger">
            {mutation.error instanceof ApiError ? mutation.error.message : "Could not create the version."}
          </p>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => mutation.mutate()} disabled={!version.trim() || mutation.isPending}>
            {mutation.isPending ? "Creating…" : "Create"}
          </Button>
        </div>
      </div>
    </div>
  );
}
