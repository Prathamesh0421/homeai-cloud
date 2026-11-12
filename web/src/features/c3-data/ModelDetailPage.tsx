/** Model Detail (/ops/models/:modelId): label-map editor, metrics, evaluation, and activation. */

import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import {
  type EvaluationMetrics,
  type LabelMap,
  type LabelMapEntry,
  type ModelEvaluation,
  type ModelSummary,
  activateModel,
  c3Keys,
  evaluateModel,
  getModel,
  listClasses,
  listModels,
  updateLabelMap,
} from "../../api/c3";
import { ApiError } from "../../api/http";
import { Button, ConfirmDialog, EmptyState, ErrorState, KpiTile, useToasts } from "../../shared";
import { labelText, percent, relativeTime } from "./format";

const RULES: LabelMapEntry["rule"][] = ["max", "mean", "consec2"];
const REEVALUATE_HINT = "Label map saved. Re-evaluate this model so its metrics reflect the changes.";

function cloneLabelMap(labelMap: LabelMap): LabelMap {
  return {
    ...labelMap,
    entries: labelMap.entries.map((entry) => ({
      ...entry,
      source_classes: [...entry.source_classes],
    })),
  };
}

function evaluationTime(evaluation: ModelEvaluation): number {
  return new Date(evaluation.finished_at ?? evaluation.started_at).getTime();
}

function metricValue(metrics: Record<string, unknown> | EvaluationMetrics | null, key: string): number | null {
  const value = metrics && key in metrics ? (metrics as Record<string, unknown>)[key] : undefined;
  return typeof value === "number" ? value : null;
}

function errorDetails(error: ApiError): string[] {
  if (Array.isArray(error.details)) {
    return error.details.map((detail) =>
      typeof detail === "string"
        ? detail
        : typeof detail === "object" && detail && "msg" in detail
          ? String(detail.msg)
          : typeof detail === "object" && detail && "issue" in detail
            ? String(detail.issue)
          : JSON.stringify(detail),
    );
  }
  if (error.details && typeof error.details === "object" && "issues" in error.details) {
    const issues = error.details.issues;
    if (Array.isArray(issues)) return issues.map(String);
  }
  return [];
}

function activationMessage(candidate: ModelSummary, active?: ModelSummary): string {
  const candidateAccuracy = metricValue(candidate.metrics, "accuracy");
  const activeAccuracy = metricValue(active?.metrics ?? null, "accuracy");
  const candidateF1 = metricValue(candidate.metrics, "macro_f1");
  const activeF1 = metricValue(active?.metrics ?? null, "macro_f1");
  const candidateValues = `accuracy ${percent(candidateAccuracy, 1)}, macro F1 ${percent(candidateF1, 1)}`;
  const comparison = active
    ? `Active ${active.version}: accuracy ${percent(activeAccuracy, 1)}, macro F1 ${percent(activeF1, 1)}. Candidate ${candidate.version}: ${candidateValues}.`
    : `There is no active model. Candidate ${candidate.version}: ${candidateValues}.`;
  const prefix = candidate.status === "retired" ? "This retired version will be rolled back into service. " : "";
  return `${prefix}Activate ${candidate.name} ${candidate.version}? ${comparison}`;
}

export default function ModelDetailPage() {
  const { modelId = "" } = useParams();
  const queryClient = useQueryClient();
  const toasts = useToasts();
  const [draft, setDraft] = useState<LabelMap | null>(null);
  const [savedDraft, setSavedDraft] = useState("");
  const [editorError, setEditorError] = useState<string[]>([]);
  const [confirmSave, setConfirmSave] = useState(false);
  const [confirmActivate, setConfirmActivate] = useState(false);

  const model = useQuery({
    queryKey: c3Keys.model(modelId),
    queryFn: () => getModel(modelId),
    enabled: Boolean(modelId),
  });
  const models = useQuery({ queryKey: c3Keys.models(), queryFn: listModels });
  const classes = useQuery({
    queryKey: [...c3Keys.models(), "classes"],
    queryFn: listClasses,
    enabled: (model.data?.status ?? "active") !== "active",
    staleTime: Number.POSITIVE_INFINITY,
  });

  useEffect(() => {
    if (!model.data) return;
    const next = cloneLabelMap(model.data.label_map);
    setDraft(next);
    setSavedDraft(JSON.stringify(next));
    setEditorError([]);
  }, [model.data]);

  const dirty = Boolean(draft && JSON.stringify(draft) !== savedDraft);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  const evaluations = useMemo(
    () => [...(model.data?.evaluations ?? [])].sort((a, b) => evaluationTime(b) - evaluationTime(a)),
    [model.data?.evaluations],
  );
  const latestMetrics = evaluations[0]?.metrics;

  const evaluate = useMutation({
    mutationFn: () => evaluateModel(modelId),
    onSuccess: async () => {
      await model.refetch();
      await queryClient.invalidateQueries({ queryKey: c3Keys.models() });
      toasts.push({ tone: "success", message: "Evaluation complete" });
    },
    onError: (error) =>
      toasts.push({ tone: "error", message: error instanceof ApiError ? error.message : "Evaluation failed." }),
  });

  const save = useMutation({
    mutationFn: async () => {
      if (!draft) throw new Error("No label map to save.");
      return updateLabelMap(modelId, draft);
    },
    onSuccess: async () => {
      setConfirmSave(false);
      setEditorError([]);
      await model.refetch();
      await queryClient.invalidateQueries({ queryKey: c3Keys.models() });
      toasts.push({ tone: "success", message: REEVALUATE_HINT });
    },
    onError: (error) => {
      setConfirmSave(false);
      const messages =
        error instanceof ApiError && error.status === 409
          ? [error.message || "The active model cannot be edited."]
          : error instanceof ApiError && error.status === 422
            ? errorDetails(error).length > 0
              ? errorDetails(error)
              : [error.message]
            : [error instanceof Error ? error.message : "Could not save the label map."];
      setEditorError(messages);
      toasts.push({ tone: "error", message: messages[0] });
    },
  });

  const activate = useMutation({
    mutationFn: () => activateModel(modelId),
    onSuccess: async () => {
      setConfirmActivate(false);
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: c3Keys.model(modelId) }),
        queryClient.invalidateQueries({ queryKey: c3Keys.models() }),
        queryClient.invalidateQueries({ queryKey: c3Keys.deployment() }),
      ]);
      toasts.push({ tone: "success", message: "Model activated" });
    },
    onError: (error) => {
      setConfirmActivate(false);
      toasts.push({ tone: "error", message: error instanceof ApiError ? error.message : "Activation failed." });
    },
  });

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

  const current = model.data;
  const isActive = current.status === "active";
  const activeModel = models.data?.find((item) => item.status === "active" && item.model_id !== current.model_id);
  const summaryMetrics = latestMetrics ?? current.metrics;
  const accuracy = metricValue(summaryMetrics, "accuracy");
  const macroF1 = metricValue(summaryMetrics, "macro_f1");
  const latency = metricValue(summaryMetrics, "p95_latency_ms");
  const clips = metricValue(summaryMetrics, "n_clips");

  function requestSave() {
    const emptyLabels = draft?.entries.filter((entry) => entry.source_classes.length === 0).map((entry) => labelText(entry.home_label)) ?? [];
    if (emptyLabels.length > 0) {
      setEditorError([`Choose at least one source class for: ${emptyLabels.join(", ")}.`]);
      return;
    }
    if (current.status === "evaluated" || current.status === "retired") setConfirmSave(true);
    else save.mutate();
  }

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">
            {current.name} {current.version}
          </h1>
          <p className="text-xs text-muted">
            {labelText(current.status)} · registered {relativeTime(current.created_at)}
            {current.activated_at ? ` · activated ${relativeTime(current.activated_at)}` : ""}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" onClick={() => evaluate.mutate()} disabled={evaluate.isPending}>
            {evaluate.isPending ? "Evaluating…" : "Evaluate"}
          </Button>
          <Button onClick={() => setConfirmActivate(true)} disabled={isActive || activate.isPending}>
            {isActive ? "Active" : current.status === "retired" ? "Roll back to this version" : "Activate"}
          </Button>
        </div>
      </header>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <KpiTile label="Accuracy" value={accuracy === null ? "—" : percent(accuracy, 1)} />
        <KpiTile label="Macro F1" value={macroF1 === null ? "—" : percent(macroF1, 1)} />
        <KpiTile label="P95 latency" value={latency === null ? "—" : `${latency.toFixed(0)} ms`} />
        <KpiTile label="Evaluation clips" value={clips === null ? "—" : clips.toLocaleString()} />
      </div>

      <section aria-labelledby="label-map-heading" className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <div>
            <h2 id="label-map-heading" className="text-sm font-semibold text-ink">Label map</h2>
            <p className="text-xs text-muted">
              {isActive ? "The active model's label map is read-only; create a new version to change it." : "Map model classes to each home alert label."}
            </p>
          </div>
          {!isActive && draft && (
            <div className="flex gap-2">
              <Button
                variant="secondary"
                disabled={!dirty || save.isPending}
                onClick={() => {
                  const reset = cloneLabelMap(current.label_map);
                  setDraft(reset);
                  setSavedDraft(JSON.stringify(reset));
                  setEditorError([]);
                }}
              >
                Reset
              </Button>
              <Button disabled={!dirty || save.isPending} onClick={requestSave}>
                {save.isPending ? "Saving…" : "Save label map"}
              </Button>
            </div>
          )}
        </div>

        {editorError.length > 0 && (
          <div role="alert" className="rounded-lg border border-danger/30 bg-danger/5 px-4 py-3 text-sm text-danger">
            <p className="font-medium">The label map could not be saved.</p>
            <ul className="mt-1 list-disc pl-5">
              {editorError.map((message, index) => <li key={`${message}-${index}`}>{message}</li>)}
            </ul>
          </div>
        )}

        {!draft || draft.entries.length === 0 ? (
          <EmptyState title="No label map" description="This version has no home-label mapping." />
        ) : (
          <div className="space-y-3">
            {draft.entries.map((entry, index) => (
              <LabelMapRow
                key={entry.home_label}
                entry={entry}
                disabled={isActive}
                availableClasses={classes.data ?? []}
                onChange={(next) => setDraft((value) => value && ({ ...value, entries: value.entries.map((item, itemIndex) => itemIndex === index ? next : item) }))}
              />
            ))}
          </div>
        )}
      </section>

      <section aria-labelledby="latest-metrics-heading" className="space-y-3">
        <h2 id="latest-metrics-heading" className="text-sm font-semibold text-ink">Latest evaluation metrics</h2>
        {!latestMetrics ? (
          <EmptyState title="Not evaluated yet. Click Evaluate." description="Evaluation results will include per-label metrics and a confusion matrix." />
        ) : (
          <>
            <LatestEvaluationSummary metrics={latestMetrics} />
            <PerLabelTable metrics={latestMetrics} />
            <ConfusionMatrix metrics={latestMetrics} />
          </>
        )}
      </section>

      <EvaluationHistory evaluations={evaluations} />

      <ConfirmDialog
        open={confirmSave}
        title="Save label-map changes?"
        message="Saving resets this version to registered. You must Evaluate again before activating."
        confirmLabel="Save changes"
        onConfirm={() => save.mutate()}
        onCancel={() => setConfirmSave(false)}
      />
      <ConfirmDialog
        open={confirmActivate}
        title={current.status === "retired" ? "Roll back this model?" : "Activate this model?"}
        message={activationMessage(current, activeModel)}
        confirmLabel={current.status === "retired" ? "Roll back to this version" : "Activate"}
        onConfirm={() => activate.mutate()}
        onCancel={() => setConfirmActivate(false)}
      />
    </div>
  );
}

interface LabelMapRowProps {
  entry: LabelMapEntry;
  disabled: boolean;
  availableClasses: string[];
  onChange: (entry: LabelMapEntry) => void;
}

function LabelMapRow({ entry, disabled, availableClasses, onChange }: LabelMapRowProps) {
  const [search, setSearch] = useState("");
  const suggestions = search.trim()
    ? availableClasses.filter((item) => !entry.source_classes.includes(item) && item.toLowerCase().includes(search.trim().toLowerCase())).slice(0, 10)
    : [];
  const inputId = `class-search-${entry.home_label}`;
  const thresholdId = `threshold-${entry.home_label}`;

  function setThreshold(raw: string) {
    const parsed = Number(raw);
    if (!Number.isFinite(parsed)) return;
    onChange({ ...entry, min_confidence: Math.min(1, Math.max(0, parsed)) });
  }

  return (
    <fieldset disabled={disabled} className="rounded-xl border border-border bg-surface p-4 shadow-card disabled:opacity-75">
      <legend className="px-1 text-sm font-semibold text-ink">{labelText(entry.home_label)}</legend>
      {entry.category && <p className="mb-3 text-xs text-muted">Category: {entry.category}</p>}
      <div className="grid gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(15rem,1fr)_10rem]">
        <div>
          <label htmlFor={inputId} className="text-xs font-medium text-muted">Source classes</label>
          <div className="mt-1 flex flex-wrap gap-1.5" aria-label={`${labelText(entry.home_label)} selected source classes`}>
            {entry.source_classes.map((sourceClass) => (
              <span key={sourceClass} className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-1 text-xs text-primary">
                {sourceClass}
                {!disabled && (
                  <button
                    type="button"
                    aria-label={`Remove ${sourceClass} from ${labelText(entry.home_label)}`}
                    className="rounded px-1 hover:bg-primary/10 focus:outline-none focus:ring-2 focus:ring-primary"
                    onClick={() => onChange({ ...entry, source_classes: entry.source_classes.filter((item) => item !== sourceClass) })}
                  >
                    ×
                  </button>
                )}
              </span>
            ))}
          </div>
          {!disabled && (
            <div className="relative mt-2">
              <input
                id={inputId}
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder="Search model classes"
                autoComplete="off"
                aria-controls={`${inputId}-suggestions`}
                className="w-full rounded-md border border-border-strong bg-surface px-3 py-2 text-sm text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
              />
              {suggestions.length > 0 && (
                <ul id={`${inputId}-suggestions`} className="absolute z-10 mt-1 max-h-48 w-full overflow-auto rounded-md border border-border bg-surface p-1 shadow-pop">
                  {suggestions.map((suggestion) => (
                    <li key={suggestion}>
                      <button
                        type="button"
                        className="w-full rounded px-2 py-1.5 text-left text-sm text-ink hover:bg-surface-2 focus:bg-surface-2 focus:outline-none"
                        onClick={() => {
                          onChange({ ...entry, source_classes: [...entry.source_classes, suggestion] });
                          setSearch("");
                        }}
                      >
                        {suggestion}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
        <div>
          <label htmlFor={thresholdId} className="text-xs font-medium text-muted">Minimum confidence</label>
          <div className="mt-2 flex items-center gap-2">
            <input
              id={thresholdId}
              type="range"
              min="0"
              max="1"
              step="0.01"
              value={entry.min_confidence}
              onChange={(event) => setThreshold(event.target.value)}
              className="min-w-0 flex-1 accent-primary"
            />
            <input
              aria-label={`${labelText(entry.home_label)} minimum confidence value`}
              type="number"
              min="0"
              max="1"
              step="0.01"
              value={entry.min_confidence}
              onChange={(event) => setThreshold(event.target.value)}
              className="w-20 rounded-md border border-border-strong bg-surface px-2 py-1.5 text-sm tnum text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
            />
          </div>
        </div>
        <div>
          <label htmlFor={`rule-${entry.home_label}`} className="text-xs font-medium text-muted">Frame rule</label>
          <select
            id={`rule-${entry.home_label}`}
            value={entry.rule}
            onChange={(event) => onChange({ ...entry, rule: event.target.value as LabelMapEntry["rule"] })}
            className="mt-1 w-full rounded-md border border-border-strong bg-surface px-2 py-2 text-sm text-ink focus:border-primary focus:outline-none focus:ring-2 focus:ring-primary/20"
          >
            {RULES.map((rule) => <option key={rule} value={rule}>{rule}</option>)}
          </select>
        </div>
      </div>
    </fieldset>
  );
}

function LatestEvaluationSummary({ metrics }: { metrics: EvaluationMetrics }) {
  const values = [
    ["Dataset", metrics.dataset],
    ["Clips", metrics.n_clips?.toLocaleString() ?? "—"],
    ["Accuracy", percent(metrics.accuracy, 1)],
    ["Macro F1", percent(metrics.macro_f1, 1)],
    ["Average latency", metrics.avg_latency_ms === undefined ? "—" : `${metrics.avg_latency_ms.toFixed(0)} ms`],
    ["P95 latency", metrics.p95_latency_ms === undefined ? "—" : `${metrics.p95_latency_ms.toFixed(0)} ms`],
  ];
  return (
    <dl className="grid grid-cols-2 gap-3 rounded-xl border border-border bg-surface p-4 shadow-card sm:grid-cols-3 lg:grid-cols-6">
      {values.map(([label, value]) => (
        <div key={label}>
          <dt className="text-xs font-medium uppercase tracking-wide text-muted">{label}</dt>
          <dd className="mt-1 text-sm font-semibold tnum text-ink">{value}</dd>
        </div>
      ))}
    </dl>
  );
}

function PerLabelTable({ metrics }: { metrics: EvaluationMetrics }) {
  const rows = Object.entries(metrics.per_label ?? {});
  if (rows.length === 0) return <p className="text-xs text-muted">No per-label metrics were returned.</p>;
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface shadow-card">
      <table className="w-full text-sm">
        <caption className="sr-only">Per-label metrics for the latest evaluation</caption>
        <thead className="border-b border-border bg-surface-2 text-left text-xs uppercase tracking-wide text-muted">
          <tr><th className="px-4 py-2">Label</th><th className="px-4 py-2">Precision</th><th className="px-4 py-2">Recall</th><th className="px-4 py-2">F1</th><th className="px-4 py-2">Support</th></tr>
        </thead>
        <tbody>
          {rows.map(([label, values]) => (
            <tr key={label} className="border-b border-border/50 last:border-0">
              <th scope="row" className="px-4 py-2 text-left font-medium text-ink">{labelText(label)}</th>
              <td className="px-4 py-2 tnum text-muted">{percent(values.precision, 1)}</td>
              <td className="px-4 py-2 tnum text-muted">{percent(values.recall, 1)}</td>
              <td className="px-4 py-2 tnum text-muted">{percent(values.f1, 1)}</td>
              <td className="px-4 py-2 tnum text-muted">{values.support}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ConfusionMatrix({ metrics }: { metrics: EvaluationMetrics }) {
  const labels = metrics.labels ?? [];
  const confusion = metrics.confusion ?? [];
  if (labels.length === 0 || confusion.length === 0) return <p className="text-xs text-muted">No confusion matrix was returned.</p>;
  const max = Math.max(1, ...confusion.flat());
  return (
    <div className="overflow-x-auto rounded-xl border border-border bg-surface p-4 shadow-card">
      <table className="mx-auto text-center text-xs">
        <caption className="mb-3 text-left text-sm font-semibold text-ink">Confusion matrix — rows are actual, columns are predicted</caption>
        <thead><tr><th scope="col" className="p-2 text-muted">Actual ↓ / Predicted →</th>{labels.map((label) => <th scope="col" key={label} className="p-2 font-medium text-muted">{labelText(label)}</th>)}</tr></thead>
        <tbody>
          {labels.map((label, rowIndex) => (
            <tr key={label}>
              <th scope="row" className="p-2 text-right font-medium text-muted">{labelText(label)}</th>
              {labels.map((columnLabel, columnIndex) => {
                const count = confusion[rowIndex]?.[columnIndex] ?? 0;
                const opacity = 0.08 + (count / max) * 0.45;
                return (
                  <td
                    key={columnLabel}
                    aria-label={`Actual ${labelText(label)}, predicted ${labelText(columnLabel)}: ${count}`}
                    className={`min-w-12 border border-surface p-2 tnum ${rowIndex === columnIndex ? "font-semibold text-ink ring-1 ring-inset ring-primary" : "text-ink"}`}
                    style={{ backgroundColor: `rgb(37 99 235 / ${opacity})` }}
                  >
                    {count}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EvaluationHistory({ evaluations }: { evaluations: ModelEvaluation[] }) {
  return (
    <section aria-labelledby="evaluation-history-heading" className="space-y-2">
      <h2 id="evaluation-history-heading" className="text-sm font-semibold text-ink">Evaluation history</h2>
      {evaluations.length === 0 ? (
        <EmptyState title="No evaluation history" description="This model has not been evaluated yet." />
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface shadow-card">
          <table className="w-full text-sm">
            <thead className="border-b border-border bg-surface-2 text-left text-xs uppercase tracking-wide text-muted">
              <tr><th className="px-4 py-2">Dataset</th><th className="px-4 py-2">Finished</th><th className="px-4 py-2">Accuracy</th><th className="px-4 py-2">Macro F1</th><th className="px-4 py-2">Clips</th></tr>
            </thead>
            <tbody>
              {evaluations.map((evaluation) => (
                <tr key={evaluation.evaluation_id} className="border-b border-border/50 last:border-0">
                  <td className="px-4 py-2 font-medium text-ink">{evaluation.dataset}</td>
                  <td className="px-4 py-2 text-muted">{relativeTime(evaluation.finished_at ?? evaluation.started_at)}</td>
                  <td className="px-4 py-2 tnum text-muted">{percent(evaluation.metrics.accuracy, 1)}</td>
                  <td className="px-4 py-2 tnum text-muted">{percent(evaluation.metrics.macro_f1, 1)}</td>
                  <td className="px-4 py-2 tnum text-muted">{evaluation.metrics.n_clips ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
