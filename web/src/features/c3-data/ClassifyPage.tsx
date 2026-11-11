/** Test Classify (/ops/classify): upload a clip, see labels, raw YAMNet top-10, latency. */

import { useRef, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { type TestClassifyResult, testClassify } from "../../api/c3";
import { ApiError } from "../../api/http";
import { Button, ConfidenceBars, ErrorState } from "../../shared";
import { labelText, percent } from "./format";

export default function ClassifyPage() {
  const inputRef = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);

  const classify = useMutation({
    mutationFn: (f: File) => testClassify(f),
  });

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">Test Classify</h1>
      <p className="text-sm text-muted">Upload an audio clip to run it through the active model without storing a detection.</p>

      <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface p-4 shadow-card">
        <input
          ref={inputRef}
          type="file"
          accept="audio/*,.wav,.mp3,.ogg,.flac"
          className="text-sm text-ink"
          aria-label="Clip file"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <Button onClick={() => file && classify.mutate(file)} disabled={!file || classify.isPending}>
          {classify.isPending ? "Classifying…" : "Classify"}
        </Button>
        {file && <span className="text-xs text-muted">{file.name}</span>}
      </div>

      {classify.isError && (
        <ErrorState
          message={
            classify.error instanceof ApiError && classify.error.status === 403
              ? "You don't have access to test classification."
              : classify.error instanceof ApiError
                ? `Classification failed: ${classify.error.message}`
                : "Classification failed."
          }
          onRetry={() => file && classify.mutate(file)}
        />
      )}

      {classify.data && <Result result={classify.data} />}
    </div>
  );
}

function Result({ result }: { result: TestClassifyResult }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Metric label="Top label" value={labelText(result.top_label)} />
        <Metric label="Confidence" value={percent(result.top_confidence)} />
        <Metric label="Duration" value={`${result.duration_s.toFixed(1)} s`} />
        <Metric label="Latency" value={`${result.latency_ms} ms`} />
      </div>

      <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
        <h3 className="mb-2 text-sm font-semibold text-ink">Home labels</h3>
        {result.labels.length === 0 ? (
          <p className="text-sm text-muted">No home labels above threshold (classified as “none”).</p>
        ) : (
          <ConfidenceBars scores={result.labels.map((l) => ({ label: labelText(l.label), score: l.confidence }))} />
        )}
      </div>

      <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
        <h3 className="mb-2 text-sm font-semibold text-ink">
          Raw YAMNet top {result.raw_top10.length} · model {result.model.name} {result.model.version}
        </h3>
        <ConfidenceBars scores={result.raw_top10.map((r) => ({ label: r.class_name, score: r.score }))} />
      </div>
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      <div className="mt-1 text-xl font-semibold text-ink">{value}</div>
    </div>
  );
}
