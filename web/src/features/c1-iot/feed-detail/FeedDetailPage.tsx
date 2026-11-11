/** Feed Detail (/iot/feeds/:feedId): status, room, enable/disable, config + versions, upload, recent clips. */

import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  archiveFeed,
  c1Keys,
  getFeed,
  listClips,
  listRooms,
  setFeedEnabled,
  updateFeed,
  type ClipSummary,
  type FeedDetail,
} from "../../../api/c1";
import { ApiError } from "../../../api/http";
import { ActionBar, Button, ConfirmDialog, DataTable, ErrorState, useToasts, type Column } from "../../../shared";
import {
  Card,
  ClipPlayback,
  ClipStatusChip,
  ConnectivityBadge,
  EnabledChip,
  FeedStatusChip,
  KindLabel,
  TopLabel,
  selectClass,
} from "../components";
import { errorText, formatBytes, formatWhen } from "../format";
import { ConfigCard } from "./ConfigCard";
import { UploadClipCard } from "./UploadClipCard";

export const NO_ROOM_TOOLTIP = "Assign a room before enabling this feed.";

export default function FeedDetailPage() {
  const { feedId = "" } = useParams();
  const feed = useQuery({ queryKey: c1Keys.feed(feedId), queryFn: () => getFeed(feedId), refetchInterval: 15_000 });

  if (feed.isPending) return <div className="py-8 text-center text-sm text-muted">Loading feed…</div>;
  if (feed.isError) {
    const e = feed.error;
    return (
      <div className="space-y-4">
        <BackLink />
        <ErrorState
          message={
            e instanceof ApiError && e.status === 404
              ? "Feed not found (it may be in another tenant or was removed)."
              : `Could not load feed: ${errorText(e)}`
          }
          onRetry={() => feed.refetch()}
        />
      </div>
    );
  }
  return <FeedDetailView feed={feed.data} />;
}

function BackLink() {
  return (
    <Link to="/iot/feeds" className="text-sm text-muted hover:underline">
      ← Camera Feed Manager
    </Link>
  );
}

export function FeedDetailView({ feed }: { feed: FeedDetail }) {
  const queryClient = useQueryClient();
  const toasts = useToasts();
  const navigate = useNavigate();
  const [editingConfig, setEditingConfig] = useState(false);
  const [confirmArchive, setConfirmArchive] = useState(false);
  const archived = !!feed.archived_at;

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: c1Keys.feed(feed.feed_id) });
    void queryClient.invalidateQueries({ queryKey: ["c1", "feeds"] });
  }

  function onMutationError(e: unknown) {
    toasts.push({ tone: "error", message: errorText(e), ttl: 7000 });
    if (e instanceof ApiError && e.status === 409) refresh();
  }

  const toggle = useMutation({
    mutationFn: (enable: boolean) => setFeedEnabled(feed.feed_id, enable),
    onSuccess: (f) => {
      toasts.push({ tone: "success", message: f.is_enabled ? "Feed enabled." : "Feed disabled." });
      refresh();
    },
    onError: onMutationError,
  });

  const archive = useMutation({
    mutationFn: () => archiveFeed(feed.feed_id),
    onSuccess: () => {
      toasts.push({ tone: "success", message: `Feed “${feed.name}” archived.` });
      void queryClient.invalidateQueries({ queryKey: ["c1", "feeds"] });
      navigate("/iot/feeds");
    },
    onError: onMutationError,
  });

  const noRoom = !feed.room_id;
  const enableDisabled = archived || toggle.isPending || (!feed.is_enabled && noRoom);

  return (
    <div className="space-y-4">
      <BackLink />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight text-ink">{feed.name}</h1>
          <div className="mt-1 text-sm text-muted">
            {feed.house_name ?? "House"} · {feed.room_name ?? <span className="italic">No room</span>} ·{" "}
            <KindLabel kind={feed.media_kind} />
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <FeedStatusChip status={feed.status} />
            <EnabledChip enabled={feed.is_enabled} />
            <ConnectivityBadge status={feed.connectivity_status} lastClipAt={feed.last_clip_at} />
            {archived && (
              <span className="rounded-full border border-border-strong bg-surface-2 px-2 py-0.5 text-xs text-muted">
                Archived {formatWhen(feed.archived_at!)}
              </span>
            )}
          </div>
        </div>
        {!archived && (
          <div className="flex flex-col items-end gap-1">
            <ActionBar>
              <span title={!feed.is_enabled && noRoom ? NO_ROOM_TOOLTIP : undefined}>
                <Button
                  variant={feed.is_enabled ? "secondary" : "primary"}
                  disabled={enableDisabled}
                  onClick={() => toggle.mutate(!feed.is_enabled)}
                >
                  {feed.is_enabled ? "Disable" : "Enable"}
                </Button>
              </span>
              <Button variant="secondary" onClick={() => setEditingConfig(true)} disabled={editingConfig}>
                Edit config
              </Button>
              <Button variant="danger" onClick={() => setConfirmArchive(true)} disabled={archive.isPending}>
                Archive
              </Button>
            </ActionBar>
            {!feed.is_enabled && noRoom && (
              <p className="text-xs text-warning">
                {NO_ROOM_TOOLTIP}
              </p>
            )}
          </div>
        )}
      </div>

      {archived && (
        <div className="rounded-md border border-border bg-surface-2 px-4 py-3 text-sm text-muted">
          This feed is archived: it is disabled and no longer accepts clips.
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        {!archived && <RoomCard key={feed.room_id ?? "none"} feed={feed} onSaved={refresh} onError={onMutationError} />}
        <ConfigCard
          key={feed.config_version}
          feed={feed}
          editing={editingConfig}
          onEditingChange={setEditingConfig}
          readOnly={archived}
        />
        {!archived && (
          <UploadClipCard
            feed={feed}
            onUploaded={(res) => {
              toasts.push(
                res.duplicate
                  ? { tone: "warning", message: "Duplicate clip id: returned the stored clip (duplicate: true)." }
                  : { tone: "success", message: "Clip uploaded and queued for analysis." },
              );
              refresh();
              void queryClient.invalidateQueries({ queryKey: ["c1", "clips"] });
            }}
          />
        )}
      </div>

      <RecentClips feedId={feed.feed_id} />

      <ConfirmDialog
        open={confirmArchive}
        title="Archive this feed?"
        message={`“${feed.name}” will be disabled and hidden from the feed list. Its clips stay in the Clip Library.`}
        confirmLabel="Archive"
        destructive
        onCancel={() => setConfirmArchive(false)}
        onConfirm={() => {
          setConfirmArchive(false);
          archive.mutate();
        }}
      />
    </div>
  );
}

function RoomCard({ feed, onSaved, onError }: { feed: FeedDetail; onSaved: () => void; onError: (e: unknown) => void }) {
  const toasts = useToasts();
  const [roomId, setRoomId] = useState(feed.room_id ?? "");
  const rooms = useQuery({ queryKey: c1Keys.rooms(feed.house_id), queryFn: () => listRooms(feed.house_id) });
  const save = useMutation({
    mutationFn: () => updateFeed(feed.feed_id, { room_id: roomId || null }),
    onSuccess: (f) => {
      toasts.push({ tone: "success", message: f.room_name ? `Room set to ${f.room_name}.` : "Room removed." });
      onSaved();
    },
    onError: (e) => {
      setRoomId(feed.room_id ?? "");
      onError(e);
    },
  });
  const changed = roomId !== (feed.room_id ?? "");

  return (
    <Card title="Room">
      <div className="flex flex-wrap items-center gap-2">
        <label htmlFor="feed-room-select" className="text-xs text-muted">
          Room
        </label>
        <select
          id="feed-room-select"
          className={selectClass}
          value={roomId}
          onChange={(e) => setRoomId(e.target.value)}
        >
          <option value="">No room</option>
          {rooms.data?.map((r) => (
            <option key={r.room_id} value={r.room_id}>
              {r.name}
            </option>
          ))}
        </select>
        <Button variant="secondary" disabled={!changed || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save room"}
        </Button>
      </div>
      {rooms.data && rooms.data.length === 0 && (
        <p className="mt-2 text-xs text-muted">
          This house has no rooms yet. <Link to="/iot/houses" className="underline">Add one in Houses and Rooms.</Link>
        </p>
      )}
      {feed.is_enabled && (
        <p className="mt-2 text-xs text-muted">An enabled feed needs a room; disable it before removing the room.</p>
      )}
    </Card>
  );
}

function RecentClips({ feedId }: { feedId: string }) {
  const filters = { feedId, pageSize: 10 };
  const clips = useQuery({
    queryKey: c1Keys.clips(filters),
    queryFn: () => listClips(filters),
    // Poll faster while a clip waits for C3 so "queued" turns into "analyzed" on screen.
    refetchInterval: (q) =>
      q.state.data?.data.some((c) => c.status === "queued" || c.status === "processing") ? 3_000 : 15_000,
  });

  const columns: Column<ClipSummary>[] = [
    { key: "time", header: "Captured", render: (c) => formatWhen(c.captured_at) },
    { key: "status", header: "Status", render: (c) => <ClipStatusChip status={c.status} /> },
    { key: "label", header: "Top label", render: (c) => <TopLabel clip={c} /> },
    { key: "size", header: "Size", render: (c) => formatBytes(c.size) },
    { key: "play", header: "", render: (c) => <ClipPlayback mediaId={c.media_id} kind={c.media_kind} /> },
  ];

  return (
    <Card title="Recent clips">
      {clips.isPending ? (
        <div className="text-sm text-muted">Loading clips…</div>
      ) : clips.isError ? (
        <div className="text-sm text-danger">Could not load clips: {errorText(clips.error)}</div>
      ) : (
        <DataTable
          columns={columns}
          rows={clips.data.data}
          rowKey={(c) => c.media_id}
          empty="No clips yet. Upload one above or start the device simulator."
        />
      )}
    </Card>
  );
}
