/** Camera Feed Manager (/iot/feeds): filters, add feed, feeds table; row click opens Feed Detail. */

import { useMemo, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  FEED_STATUSES,
  MEDIA_KINDS,
  c1Keys,
  listFeeds,
  listHouses,
  listRooms,
  type Feed,
  type FeedFilters,
  type FeedStatus,
  type MediaKind,
} from "../../../api/c1";
import { ApiError } from "../../../api/http";
import { Button, DataTable, EmptyState, ErrorState, FilterBar, Pagination, useToasts, type Column } from "../../../shared";
import {
  ConnectivityBadge,
  EnabledChip,
  FEED_STATUS_LABEL,
  FeedStatusChip,
  KindLabel,
  selectClass,
} from "../components";
import { AddFeedPanel } from "./AddFeedPanel";

const PAGE_SIZE = 25;
/** Connectivity changes when clips arrive or the monitor runs (every 60 s). */
const POLL_MS = 15_000;

function filtersFrom(params: URLSearchParams): FeedFilters {
  return {
    houseId: params.get("house") ?? undefined,
    roomId: params.get("room") ?? undefined,
    mediaKind: (params.get("kind") as MediaKind | null) ?? undefined,
    status: (params.get("status") as FeedStatus | null) ?? undefined,
    page: Number(params.get("page") ?? 1) || 1,
    pageSize: PAGE_SIZE,
  };
}

export default function FeedManagerPage() {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const toasts = useToasts();
  const [adding, setAdding] = useState(false);
  const filters = useMemo(() => filtersFrom(params), [params]);

  const houses = useQuery({ queryKey: c1Keys.houses(), queryFn: () => listHouses() });
  const rooms = useQuery({
    queryKey: c1Keys.rooms(filters.houseId ?? ""),
    queryFn: () => listRooms(filters.houseId!),
    enabled: !!filters.houseId,
  });
  const feeds = useQuery({
    queryKey: c1Keys.feeds(filters),
    queryFn: () => listFeeds(filters),
    placeholderData: keepPreviousData,
    refetchInterval: POLL_MS,
  });

  function setFilter(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    if (name === "house") next.delete("room");
    if (name !== "page") next.delete("page");
    setParams(next, { replace: true });
  }

  const columns: Column<Feed>[] = [
    {
      key: "name",
      header: "Name",
      render: (f) => (
        <Link
          to={`/iot/feeds/${f.feed_id}`}
          className="font-medium text-ink hover:underline"
          onClick={(e) => e.stopPropagation()}
        >
          {f.name}
        </Link>
      ),
      sortValue: (f) => f.name.toLowerCase(),
    },
    {
      key: "room",
      header: "Room",
      render: (f) => (
        <div>
          <div className={f.room_name ? "text-ink" : "italic text-muted"}>{f.room_name ?? "No room"}</div>
          <div className="text-xs text-muted">{f.house_name ?? ""}</div>
        </div>
      ),
      sortValue: (f) => `${f.house_name ?? ""} ${f.room_name ?? ""}`,
    },
    { key: "kind", header: "Kind", render: (f) => <KindLabel kind={f.media_kind} />, sortValue: (f) => f.media_kind },
    {
      key: "status",
      header: "Status",
      render: (f) => <FeedStatusChip status={f.status} />,
      sortValue: (f) => FEED_STATUSES.indexOf(f.status),
    },
    {
      key: "connectivity",
      header: "Connectivity",
      render: (f) => <ConnectivityBadge status={f.connectivity_status} lastClipAt={f.last_clip_at} />,
      sortValue: (f) => f.last_clip_at ?? "",
    },
    {
      key: "enabled",
      header: "Enabled",
      render: (f) => <EnabledChip enabled={f.is_enabled} />,
      sortValue: (f) => (f.is_enabled ? 1 : 0),
    },
  ];

  const houseList = houses.data?.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">Camera Feed Manager</h1>
        {!adding && <Button onClick={() => setAdding(true)}>+ Add feed</Button>}
      </div>

      {adding && (
        <AddFeedPanel
          houses={houseList}
          defaultHouseId={filters.houseId}
          onCancel={() => setAdding(false)}
          onCreated={(feed) => {
            setAdding(false);
            toasts.push({ tone: "success", message: `Feed “${feed.name}” added (provisioned, disabled).` });
            void queryClient.invalidateQueries({ queryKey: ["c1", "feeds"] });
          }}
        />
      )}

      <FilterBar onReset={() => setParams(new URLSearchParams(), { replace: true })}>
        <label className="text-xs text-muted">
          House{" "}
          <select className={selectClass} value={params.get("house") ?? ""} onChange={(e) => setFilter("house", e.target.value)}>
            <option value="">All</option>
            {houseList.map((h) => (
              <option key={h.house_id} value={h.house_id}>
                {h.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-muted">
          Room{" "}
          <select
            className={selectClass}
            value={params.get("room") ?? ""}
            disabled={!filters.houseId}
            title={filters.houseId ? undefined : "Choose a house first"}
            onChange={(e) => setFilter("room", e.target.value)}
          >
            <option value="">All</option>
            {rooms.data?.map((r) => (
              <option key={r.room_id} value={r.room_id}>
                {r.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-muted">
          Kind{" "}
          <select className={selectClass} value={params.get("kind") ?? ""} onChange={(e) => setFilter("kind", e.target.value)}>
            <option value="">All</option>
            {MEDIA_KINDS.map((k) => (
              <option key={k} value={k}>
                {k === "audio" ? "Audio" : "Video"}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-muted">
          Status{" "}
          <select className={selectClass} value={params.get("status") ?? ""} onChange={(e) => setFilter("status", e.target.value)}>
            <option value="">All</option>
            {FEED_STATUSES.map((s) => (
              <option key={s} value={s}>
                {FEED_STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
      </FilterBar>

      {feeds.isPending ? (
        <div className="space-y-2" aria-label="Loading feeds">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-10 animate-pulse rounded bg-surface-2" />
          ))}
        </div>
      ) : feeds.isError ? (
        <ErrorState
          message={
            feeds.error instanceof ApiError && feeds.error.status === 403
              ? "You don't have access to these feeds."
              : `Could not load feeds: ${feeds.error.message}`
          }
          onRetry={() => feeds.refetch()}
        />
      ) : feeds.data.data.length === 0 ? (
        <EmptyState
          title="No feeds yet"
          description="Register a camera or microphone feed for a house."
          action={!adding ? <Button onClick={() => setAdding(true)}>+ Add feed</Button> : undefined}
        />
      ) : (
        <>
          <DataTable
            columns={columns}
            rows={feeds.data.data}
            rowKey={(f) => f.feed_id}
            onRowClick={(f) => navigate(`/iot/feeds/${f.feed_id}`)}
          />
          <Pagination
            page={feeds.data.meta.page}
            pageSize={feeds.data.meta.page_size}
            total={feeds.data.meta.total}
            onChange={(p) => setFilter("page", String(p))}
          />
        </>
      )}
    </div>
  );
}
