/**
 * Small C1 display pieces. The shared kit's StatusChip only knows alert statuses and its ClipPlayer
 * is a stub, so C1 keeps its own versions here (icon + word, never colour alone).
 */

import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { Mic, Play, Video } from "lucide-react";
import { INPUT } from "../../shared/tokens";
import {
  c1Keys,
  getClip,
  getPlaybackUrl,
  type ClipStatus,
  type ClipSummary,
  type Connectivity,
  type FeedStatus,
  type MediaKind,
} from "../../api/c1";
import { errorText, labelText, relativeTime } from "./format";

const chipBase = "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium";

const FEED_STATUS: Record<FeedStatus, { icon: string; label: string; cls: string }> = {
  provisioned: { icon: "○", label: "Provisioned", cls: "bg-surface-2 text-muted border-border" },
  active: { icon: "●", label: "Active", cls: "bg-success-soft text-success border-success/30" },
  inactive: { icon: "◌", label: "Inactive", cls: "bg-warning-soft text-warning border-warning/30" },
  error: { icon: "✕", label: "Error", cls: "bg-danger-soft text-danger border-danger/30" },
};

export function FeedStatusChip({ status }: { status: FeedStatus }) {
  const s = FEED_STATUS[status] ?? FEED_STATUS.provisioned;
  return (
    <span className={`${chipBase} ${s.cls}`}>
      <span aria-hidden="true">{s.icon}</span>
      {s.label}
    </span>
  );
}

export const FEED_STATUS_LABEL: Record<FeedStatus, string> = {
  provisioned: "Provisioned",
  active: "Active",
  inactive: "Inactive",
  error: "Error",
};

const CLIP_STATUS: Record<ClipStatus, { icon: string; label: string; cls: string }> = {
  queued: { icon: "⏳", label: "Queued", cls: "bg-surface-2 text-muted border-border" },
  processing: { icon: "↻", label: "Processing", cls: "bg-accent-soft text-accent border-accent/30" },
  analyzed: { icon: "✓", label: "Analyzed", cls: "bg-success-soft text-success border-success/30" },
  failed: { icon: "✕", label: "Failed", cls: "bg-danger-soft text-danger border-danger/30" },
};

export const CLIP_STATUS_LABEL: Record<ClipStatus, string> = {
  queued: "Queued",
  processing: "Processing",
  analyzed: "Analyzed",
  failed: "Failed",
};

export function ClipStatusChip({ status }: { status: ClipStatus }) {
  const s = CLIP_STATUS[status] ?? CLIP_STATUS.queued;
  return (
    <span className={`${chipBase} ${s.cls}`}>
      <span aria-hidden="true">{s.icon}</span>
      {s.label}
    </span>
  );
}

export function EnabledChip({ enabled }: { enabled: boolean }) {
  return enabled ? (
    <span className={`${chipBase} border-success/30 bg-success-soft text-success`}>
      <span aria-hidden="true">✓</span>Enabled
    </span>
  ) : (
    <span className={`${chipBase} border-border bg-surface-2 text-muted`}>
      <span aria-hidden="true">–</span>Disabled
    </span>
  );
}

const DOT: Record<Connectivity, { cls: string; label: string }> = {
  online: { cls: "bg-success", label: "Online" },
  offline: { cls: "bg-danger", label: "Offline" },
  unknown: { cls: "bg-border-strong", label: "Unknown" },
};

/** Dot + word + age of the last clip (connectivity is recorded from uploads, not measured). */
export function ConnectivityBadge({ status, lastClipAt }: { status: Connectivity; lastClipAt: string | null }) {
  const d = DOT[status] ?? DOT.unknown;
  return (
    <span className="inline-flex items-center gap-1.5 text-sm text-ink">
      <span aria-hidden="true" className={`inline-block h-2 w-2 rounded-full ${d.cls}`} />
      {d.label}
      <span className="text-xs text-muted">
        {lastClipAt ? (
          <time dateTime={lastClipAt} title={new Date(lastClipAt).toLocaleString()}>
            · last clip {relativeTime(lastClipAt)}
          </time>
        ) : (
          "· no clips yet"
        )}
      </span>
    </span>
  );
}

export function KindLabel({ kind }: { kind: MediaKind }) {
  return (
    <span className="inline-flex items-center gap-1 text-ink">
      {kind === "audio" ? (
        <Mic className="h-3.5 w-3.5 text-muted" aria-hidden="true" />
      ) : (
        <Video className="h-3.5 w-3.5 text-muted" aria-hidden="true" />
      )}
      {kind === "audio" ? "Audio" : "Video"}
    </span>
  );
}

/** Fetches a fresh presigned URL when the user presses Play, then shows the native player. */
export function ClipPlayback({ mediaId, kind }: { mediaId: string; kind: MediaKind }) {
  const [url, setUrl] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function play() {
    setLoading(true);
    setError(null);
    try {
      const res = await getPlaybackUrl(mediaId);
      setUrl(res.url);
    } catch (e) {
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  }

  if (url) {
    return kind === "video" ? (
      <video src={url} controls autoPlay className="max-h-48 w-full max-w-sm rounded" onError={() => setUrl(null)} />
    ) : (
      <audio src={url} controls autoPlay className="w-64" onError={() => setUrl(null)} />
    );
  }
  return (
    <span className="inline-flex items-center gap-2">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          void play();
        }}
        disabled={loading}
        className="inline-flex items-center gap-1 rounded-md border border-border-strong px-2 py-1 text-xs font-medium text-ink hover:bg-surface-2 disabled:opacity-50"
        aria-label="Play clip"
      >
        {loading ? (
          "Loading…"
        ) : (
          <>
            <Play className="h-3 w-3" aria-hidden="true" /> Play
          </>
        )}
      </button>
      {error && <span className="text-xs text-danger">{error}</span>}
    </span>
  );
}

export function Card({ title, children, actions }: { title: string; children: ReactNode; actions?: ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-surface p-5 shadow-card">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold text-ink">{title}</h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

/** The kit's INPUT baseline, full width (focus ring comes from index.css). */
export const inputClass = `w-full ${INPUT}`;
export const selectClass = "rounded-md border border-border-strong bg-surface px-2.5 py-1.5 text-sm text-ink";

/**
 * Top label of an analyzed clip. ``GET /clips`` does not promise ``top_label``, so when the row
 * lacks it the detail record is fetched (cached for a minute).
 */
export function TopLabel({ clip }: { clip: ClipSummary }) {
  const needsDetail = clip.status === "analyzed" && clip.top_label === undefined;
  const detail = useQuery({
    queryKey: c1Keys.clip(clip.media_id),
    queryFn: () => getClip(clip.media_id),
    enabled: needsDetail,
    staleTime: 60_000,
  });
  const label = clip.top_label ?? detail.data?.top_label;
  if (clip.status !== "analyzed") return <span className="text-muted">—</span>;
  if (needsDetail && detail.isPending) return <span className="text-xs text-muted">…</span>;
  if (!label || label === "none") return <span className="text-muted">No label</span>;
  return <span className="font-medium text-ink">{labelText(label)}</span>;
}
