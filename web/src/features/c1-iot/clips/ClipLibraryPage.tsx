/** Clip Library (/iot/clips for staff, /home/clips for owners — the API scopes owners to their houses). */

import { useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import {
  CLIP_STATUSES,
  c1Keys,
  listClips,
  listFeeds,
  listHouses,
  type ClipFilters,
  type ClipStatus,
  type ClipSummary,
} from "../../../api/c1";
import { ApiError } from "../../../api/http";
import { DataTable, EmptyState, ErrorState, FilterBar, Pagination, type Column } from "../../../shared";
import { CLIP_STATUS_LABEL, ClipPlayback, ClipStatusChip, KindLabel, TopLabel, selectClass } from "../components";
import { dayEndIso, dayStartIso, errorText, formatBytes, formatWhen } from "../format";

const PAGE_SIZE = 25;

function filtersFrom(params: URLSearchParams): ClipFilters {
  const from = params.get("from");
  const to = params.get("to");
  return {
    houseId: params.get("house") ?? undefined,
    feedId: params.get("feed") ?? undefined,
    status: (params.get("status") as ClipStatus | null) ?? undefined,
    from: from ? dayStartIso(from) : undefined,
    to: to ? dayEndIso(to) : undefined,
    page: Number(params.get("page") ?? 1) || 1,
    pageSize: PAGE_SIZE,
  };
}

export default function ClipLibraryPage() {
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => filtersFrom(params), [params]);

  const houses = useQuery({ queryKey: c1Keys.houses(), queryFn: () => listHouses() });
  const feedFilters = { houseId: filters.houseId, includeArchived: true, pageSize: 100 };
  const feeds = useQuery({ queryKey: c1Keys.feeds(feedFilters), queryFn: () => listFeeds(feedFilters) });
  const clips = useQuery({
    queryKey: c1Keys.clips(filters),
    queryFn: () => listClips(filters),
    placeholderData: keepPreviousData,
    refetchInterval: 15_000,
  });

  function setFilter(name: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(name, value);
    else next.delete(name);
    if (name === "house") next.delete("feed");
    if (name !== "page") next.delete("page");
    setParams(next, { replace: true });
  }

  const columns: Column<ClipSummary>[] = [
    {
      key: "time",
      header: "Captured",
      render: (c) => <time dateTime={c.captured_at}>{formatWhen(c.captured_at)}</time>,
      sortValue: (c) => c.captured_at,
    },
    { key: "house", header: "House", render: (c) => c.house_name ?? "—", sortValue: (c) => c.house_name ?? "" },
    { key: "feed", header: "Feed", render: (c) => c.feed_name ?? "—", sortValue: (c) => c.feed_name ?? "" },
    { key: "room", header: "Room", render: (c) => c.room_name ?? "—", sortValue: (c) => c.room_name ?? "" },
    { key: "kind", header: "Kind", render: (c) => <KindLabel kind={c.media_kind} /> },
    { key: "size", header: "Size", render: (c) => formatBytes(c.size), sortValue: (c) => c.size },
    {
      key: "status",
      header: "Status",
      render: (c) => <ClipStatusChip status={c.status} />,
      sortValue: (c) => CLIP_STATUSES.indexOf(c.status),
    },
    { key: "label", header: "Top label", render: (c) => <TopLabel clip={c} /> },
    { key: "play", header: "", render: (c) => <ClipPlayback mediaId={c.media_id} kind={c.media_kind} /> },
  ];

  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">Clip Library</h1>

      <FilterBar onReset={() => setParams(new URLSearchParams(), { replace: true })}>
        <label className="text-xs text-muted">
          House{" "}
          <select className={selectClass} value={params.get("house") ?? ""} onChange={(e) => setFilter("house", e.target.value)}>
            <option value="">All</option>
            {houses.data?.data.map((h) => (
              <option key={h.house_id} value={h.house_id}>
                {h.name}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-muted">
          Feed{" "}
          <select className={selectClass} value={params.get("feed") ?? ""} onChange={(e) => setFilter("feed", e.target.value)}>
            <option value="">All</option>
            {feeds.data?.data.map((f) => (
              <option key={f.feed_id} value={f.feed_id}>
                {f.name}
                {!filters.houseId && f.house_name ? ` · ${f.house_name}` : ""}
                {f.archived_at ? " (archived)" : ""}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-muted">
          Status{" "}
          <select className={selectClass} value={params.get("status") ?? ""} onChange={(e) => setFilter("status", e.target.value)}>
            <option value="">All</option>
            {CLIP_STATUSES.map((s) => (
              <option key={s} value={s}>
                {CLIP_STATUS_LABEL[s]}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs text-muted">
          From{" "}
          <input type="date" className={selectClass} value={params.get("from") ?? ""} onChange={(e) => setFilter("from", e.target.value)} />
        </label>
        <label className="text-xs text-muted">
          To{" "}
          <input type="date" className={selectClass} value={params.get("to") ?? ""} onChange={(e) => setFilter("to", e.target.value)} />
        </label>
      </FilterBar>

      {clips.isPending ? (
        <div className="space-y-2" aria-label="Loading clips">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-10 animate-pulse rounded bg-surface-2" />
          ))}
        </div>
      ) : clips.isError ? (
        <ErrorState
          message={
            clips.error instanceof ApiError && clips.error.status === 403
              ? "You don't have access to these clips."
              : `Could not load clips: ${errorText(clips.error)}`
          }
          onRetry={() => clips.refetch()}
        />
      ) : clips.data.data.length === 0 ? (
        <EmptyState title="No clips" description="Nothing matches these filters. Uploaded clips appear here." />
      ) : (
        <>
          <DataTable columns={columns} rows={clips.data.data} rowKey={(c) => c.media_id} />
          <Pagination
            page={clips.data.meta.page}
            pageSize={clips.data.meta.page_size}
            total={clips.data.meta.total}
            onChange={(p) => setFilter("page", String(p))}
          />
        </>
      )}
    </div>
  );
}
