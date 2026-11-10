/** My Feeds (/home/feeds): read-only feed cards for the owner's houses, with connectivity. */

import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { c1Keys, listFeeds, listHouses, type Feed } from "../../../api/c1";
import { EmptyState, ErrorState } from "../../../shared";
import { ConnectivityBadge, EnabledChip, FeedStatusChip, KindLabel } from "../components";
import { errorText } from "../format";

export default function MyFeedsPage() {
  const houses = useQuery({ queryKey: c1Keys.houses(), queryFn: () => listHouses() });
  const feedFilters = { pageSize: 100 };
  const feeds = useQuery({
    queryKey: c1Keys.feeds(feedFilters),
    queryFn: () => listFeeds(feedFilters),
    refetchInterval: 15_000,
  });

  if (feeds.isPending || houses.isPending) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">My Feeds</h1>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Loading feeds">
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-28 animate-pulse rounded-lg bg-surface-2" />
          ))}
        </div>
      </div>
    );
  }
  const error = feeds.error ?? houses.error;
  if (error) {
    return (
      <div className="space-y-4">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">My Feeds</h1>
        <ErrorState
          message={`Could not load your feeds: ${errorText(error)}`}
          onRetry={() => {
            void feeds.refetch();
            void houses.refetch();
          }}
        />
      </div>
    );
  }

  const byHouse = new Map<string, Feed[]>();
  for (const f of feeds.data?.data ?? []) {
    byHouse.set(f.house_id, [...(byHouse.get(f.house_id) ?? []), f]);
  }
  const houseList = houses.data?.data ?? [];

  return (
    <div className="space-y-6">
      <div className="flex items-baseline justify-between">
        <h1 className="text-2xl font-semibold tracking-tight text-ink">My Feeds</h1>
        <span className="text-xs text-muted">Read-only · updates every 15 s</span>
      </div>
      {houseList.length === 0 ? (
        <EmptyState title="No houses" description="No houses are assigned to your account yet." />
      ) : (
        houseList.map((h) => {
          const list = byHouse.get(h.house_id) ?? [];
          return (
            <section key={h.house_id} className="space-y-2">
              <h2 className="text-sm font-semibold text-ink">{h.name}</h2>
              {list.length === 0 ? (
                <p className="text-sm text-muted">No feeds in this house yet.</p>
              ) : (
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                  {list.map((f) => (
                    <article key={f.feed_id} className="rounded-xl border border-border bg-surface p-5 shadow-card">
                      <div className="flex items-start justify-between gap-2">
                        <div>
                          <h3 className="font-medium text-ink">{f.name}</h3>
                          <p className="text-xs text-muted">
                            {f.room_name ?? "No room"} · <KindLabel kind={f.media_kind} />
                          </p>
                        </div>
                        <FeedStatusChip status={f.status} />
                      </div>
                      <div className="mt-3">
                        <ConnectivityBadge status={f.connectivity_status} lastClipAt={f.last_clip_at} />
                      </div>
                      <div className="mt-3 flex items-center justify-between">
                        <EnabledChip enabled={f.is_enabled} />
                        <Link to={`/home/clips?house=${h.house_id}&feed=${f.feed_id}`} className="text-xs text-muted underline">
                          View clips
                        </Link>
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
          );
        })
      )}
    </div>
  );
}
