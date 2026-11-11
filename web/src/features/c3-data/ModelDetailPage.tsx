/** Model Detail (/ops/models/:modelId): label map, metrics, evaluate + activate. */

import { useMemo } from "react";
import { useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { type LabelMapEntry, c3Keys, activateModel, evaluateModel, getModel } from "../../api/c3";
import { ApiError } from "../../api/http";
import { Button, EmptyState, ErrorState, KpiTile, useToasts } from "../../shared";
import { labelText, percent, relativeTime } from "./format";

export default function ModelDetailPage() {
  const { modelId = "" } = useParams();
  const qc = useQueryClient();
  const toasts = useToasts();

  const model = useQuery({ queryKey: c3Keys.model(modelId), queryFn: () => getModel(modelId), enabled: Boolean(modelId) });

  const evaluate = useMutation({
    mutationFn: () => evaluateModel(modelId),
    onSuccess: () => {
      toasts.push({ tone: "success", message: "Evaluation complete" });
      qc.invalidateQueries({ queryKey: c3Keys.model(modelId) });
    },
    onError: (e) => toasts.push({ tone: "error", message: e instanceof ApiError ? e.message : "Evaluation failed." }),
  });

  const activate = useMutation({
    mutationFn: () => activateModel(modelId),
    onSuccess: () => {
      toasts.push({ tone: "success", message: "Model activated" });
      qc.invalidateQueries({ queryKey: c3Keys.model(modelId) });
      qc.invalidateQueries({ queryKey: c3Keys.models() });
      qc.invalidateQueries({ queryKey: c3Keys.deployment() });
    },
    onError: (e) => toasts.push({ tone: "error", message: e instanceof ApiError ? e.message : "Activation failed." }),
  });

  const entries = useMemo<LabelMapEntry[]>(() => {
    const lm = model.data?.label_map as { entries?: LabelMapEntry[] } | undefined;
    return lm?.entries ?? [];
  }, [model.data]);

  if (model.isPending) return <div className="py-8 text-center text-sm text-muted">Loading model…</div>;
  if (model.isError) {
    return (
      <ErrorState
        message={
          model.error instanceof ApiError && model.error.status === 404
            ? "This model does not exist."
            : `Could not load the model: ${model.error.message}`
        }
        onRetry={() => model.refetch()}
      />
    );
  }

  const m = model.data;
  const acc = typeof m.metrics?.accuracy === "number" ? (m.metrics.accuracy as number) : null;
  const isActive = m.status === "active";

  return (
    <div className="space-y-5">
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            {m.name} {m.version}
          </h1>
          <p className="text-xs text-muted">
            {labelText(m.status)} · registered {relativeTime(m.created_at)}
            {m.activated_at ? ` · activated ${relativeTime(m.activated_at)}` : ""}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => evaluate.mutate()} disabled={evaluate.isPending}>
            {evaluate.isPending ? "Evaluating…" : "Evaluate"}
          </Button>
          <Button onClick={() => activate.mutate()} disabled={isActive || activate.isPending}>
            {isActive ? "Active" : activate.isPending ? "Activating…" : "Activate"}
          </Button>
        </div>
      </div>

      {/* Metrics */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KpiTile label="Accuracy" value={acc !== null ? percent(acc, 1) : "—"} />
        <KpiTile label="Source" value={m.source} />
        <KpiTile label="Status" value={labelText(m.status)} />
        <KpiTile label="Evaluations" value={m.evaluations.length} />
      </div>

      {/* Label map */}
      <section>
        <h2 className="mb-2 text-sm font-semibold text-ink">Label map</h2>
        {entries.length === 0 ? (
          <EmptyState title="No label map" description="This version has no home-label mapping." />
        ) : (
          <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-card">
            <table className="w-full text-sm">
              <thead className="border-b border-border bg-surface-2 text-left text-xs uppercase tracking-wide text-muted">
                <tr>
                  <th className="px-4 py-2 font-medium">Home label</th>
                  <th className="px-4 py-2 font-medium">Source classes</th>
                  <th className="px-4 py-2 font-medium">Min confidence</th>
                  <th className="px-4 py-2 font-medium">Rule</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.home_label} className="border-b border-border/50 last:border-0">
                    <td className="px-4 py-2 font-medium text-ink">{labelText(e.home_label)}</td>
                    <td className="px-4 py-2 text-xs text-muted">{e.source_classes.join(", ")}</td>
                    <td className="px-4 py-2 tnum text-muted">{percent(e.min_confidence)}</td>
                    <td className="px-4 py-2 text-xs text-muted">{e.rule}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {isActive && <p className="mt-2 text-xs text-muted">The active model's label map is read-only; register a new version to change it.</p>}
      </section>
    </div>
  );
}
