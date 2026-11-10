/** Upload a clip to this feed (POST /ingest/clip) — used in the live demo instead of a device. */

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { CLIP_ACCEPT, MAX_CLIP_BYTES, uploadClip, type Feed, type IngestResult } from "../../../api/c1";
import { Button, Field } from "../../../shared";
import { Card, ClipStatusChip, inputClass } from "../components";
import { errorText, formatBytes, localInputToIso, serverFieldErrors, toLocalInput } from "../format";

export function UploadClipCard({ feed, onUploaded }: { feed: Feed; onUploaded: (res: IngestResult) => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [capturedAt, setCapturedAt] = useState(() => toLocalInput(new Date()));
  const [clientClipId, setClientClipId] = useState("");
  const [clientError, setClientError] = useState<string | null>(null);

  const upload = useMutation({
    mutationFn: () =>
      uploadClip({
        feedId: feed.feed_id,
        mediaKind: feed.media_kind,
        capturedAt: localInputToIso(capturedAt),
        clientClipId: clientClipId.trim() || undefined,
        file: file!,
      }),
    onSuccess: onUploaded,
  });

  const fieldErrs = serverFieldErrors(upload.error);

  function submit() {
    setClientError(null);
    upload.reset();
    if (!file) return setClientError("Choose a file.");
    if (file.size > MAX_CLIP_BYTES) return setClientError(`File is ${formatBytes(file.size)}; the limit is 50 MB.`);
    if (!capturedAt) return setClientError("Set the capture time.");
    upload.mutate();
  }

  const result = upload.data;
  return (
    <Card title="Upload clip">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
        className="space-y-3"
      >
        <Field label={`File (${feed.media_kind === "audio" ? "wav or mp3" : "mp4"}, ≤ 50 MB)`} name="clip-file" error={fieldErrs.file}>
          <input
            id="clip-file"
            type="file"
            accept={CLIP_ACCEPT}
            className="block w-full text-sm text-ink"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
        </Field>
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Captured at" name="clip-captured" error={fieldErrs.captured_at}>
            <input
              id="clip-captured"
              type="datetime-local"
              className={inputClass}
              value={capturedAt}
              onChange={(e) => setCapturedAt(e.target.value)}
            />
          </Field>
          <Field label="Client clip id (optional)" name="clip-client-id" error={fieldErrs.client_clip_id}>
            <input
              id="clip-client-id"
              className={inputClass}
              value={clientClipId}
              placeholder="e.g. hall-1840"
              onChange={(e) => setClientClipId(e.target.value)}
            />
          </Field>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted">
            Sent as a <strong>{feed.media_kind}</strong> clip. The same client clip id twice returns the stored clip.
          </span>
          <Button type="submit" disabled={upload.isPending}>
            {upload.isPending ? "Uploading…" : "Upload"}
          </Button>
        </div>
        {clientError && (
          <p role="alert" className="text-sm text-danger">
            {clientError}
          </p>
        )}
        {upload.isError && Object.keys(fieldErrs).length === 0 && (
          <p role="alert" className="rounded-md border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
            {errorText(upload.error)}
          </p>
        )}
        {result && (
          <div
            role="status"
            className={`rounded-md border px-3 py-2 text-sm ${
              result.duplicate ? "border-warning/30 bg-warning-soft text-warning" : "border-success/30 bg-success-soft text-success"
            }`}
          >
            <div className="flex items-center gap-2">
              {result.duplicate ? "Duplicate: this clip id was already stored (duplicate: true)." : "Uploaded."}
              <ClipStatusChip status={result.status} />
            </div>
            <div className="mt-1 break-all font-mono text-xs">media_id {result.media_id}</div>
            <div className="break-all font-mono text-xs">s3 {result.s3_key}</div>
          </div>
        )}
      </form>
    </Card>
  );
}
