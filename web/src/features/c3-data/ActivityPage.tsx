/** Activity (/ops/activity): per-house/room 24-hour chart vs baseline, with an anomaly band.
 *
 * Time is UTC end to end: the API returns ``hours`` indexed by UTC hour and ``date`` as a UTC
 * day, so the axis is labelled UTC (no local-time conversion). Before the baseline job has run
 * the API returns null baselines and band ``insufficient_data`` — the page shows a "collecting
 * data" state, never a crash or a zero band.
 *
 * House and room are chosen from name selects (C1 list APIs) instead of pasting UUIDs.
 */

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { type ActivityPattern, c3Keys, listActivity } from "../../api/c3";
import { listHouses, listRooms, c1Keys } from "../../api/c1";
import { ApiError } from "../../api/http";
import { EmptyState, ErrorState, FilterSelect } from "../../shared";
import { BAND_LABEL, BAND_TONE, relativeTime, utcHourLabel } from "./format";

// Radix Select forbids value=""; use a sentinel for "all rooms".
const ALL_ROOMS = "__all__";

export default function ActivityPage() {
  const [houseId, setHouseId] = useState("");
  const [roomId, setRoomId] = useState(ALL_ROOMS);
  const [submitted, setSubmitted] = useState<{ houseId: string; roomId?: string } | null>(null);

  const housesQ = useQuery({
    queryKey: c1Keys.houses({ pageSize: 100 }),
    queryFn: () => listHouses({ pageSize: 100 }),
  });
  const houseOptions = useMemo(
    () => (housesQ.data?.data ?? []).map((h) => ({ value: h.house_id, label: h.name })),
    [housesQ.data],
  );

  const roomsQ = useQuery({
    queryKey: c1Keys.rooms(houseId),
    queryFn: () => listRooms(houseId),
    enabled: Boolean(houseId),
  });
  const roomOptions = useMemo(
    () => [
      { value: ALL_ROOMS, label: "All rooms" },
      ...(roomsQ.data ?? []).map((r) => ({ value: r.room_id, label: r.name })),
    ],
    [roomsQ.data],
  );

  const q = useQuery({
    queryKey: c3Keys.activity({ houseId: submitted?.houseId, roomId: submitted?.roomId }),
    queryFn: () => listActivity({ houseId: submitted!.houseId, roomId: submitted?.roomId }),
    enabled: Boolean(submitted?.houseId),
  });

  const today = q.data?.[0];

  return (
    <div className="space-y-5">
      <h1 className="text-2xl font-semibold tracking-tight text-ink">Activity</h1>

      <form
        className="flex flex-wrap items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (houseId) {
            setSubmitted({
              houseId,
              roomId: roomId && roomId !== ALL_ROOMS ? roomId : undefined,
            });
          }
        }}
      >
        <div className="text-sm">
          <span className="text-muted">House</span>
          <div className="mt-1.5">
            {housesQ.isError ? (
              <p className="text-xs text-danger">Could not load houses.</p>
            ) : (
              <FilterSelect
                label="House"
                value={houseId}
                onValueChange={(v) => {
                  setHouseId(v);
                  setRoomId(ALL_ROOMS);
                }}
                options={houseOptions}
                placeholder={housesQ.isPending ? "Loading houses…" : "Select a house"}
                className="w-[14rem]"
              />
            )}
          </div>
        </div>
        <div className="text-sm">
          <span className="text-muted">Room</span>
          <div className="mt-1.5">
            <FilterSelect
              label="Room"
              value={roomId || ALL_ROOMS}
              onValueChange={setRoomId}
              options={roomOptions}
              placeholder="All rooms"
              className="w-[14rem]"
            />
          </div>
        </div>
        <button
          type="submit"
          className="rounded-md bg-primary px-3.5 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
          disabled={!houseId}
        >
          Load
        </button>
      </form>

      {!submitted ? (
        <EmptyState title="Pick a house" description="Choose a house (and optionally a room) to see its activity pattern." />
      ) : q.isPending ? (
        <div className="py-8 text-center text-sm text-muted">Loading activity…</div>
      ) : q.isError ? (
        <ErrorState
          message={
            q.error instanceof ApiError && q.error.status === 403
              ? "You don't have access to this house's activity."
              : `Could not load activity: ${q.error.message}`
          }
          onRetry={() => q.refetch()}
        />
      ) : !today ? (
        <EmptyState title="No activity yet" description="No detections have been recorded for this house/room today (UTC)." />
      ) : (
        <ActivityChart pattern={today} />
      )}
    </div>
  );
}

function ActivityChart({ pattern }: { pattern: ActivityPattern }) {
  const hasBaseline = pattern.band !== "insufficient_data" && pattern.baseline_mean !== null;
  const maxCount = Math.max(1, ...pattern.hours, ...(pattern.baseline_mean ?? []));

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-surface p-4 shadow-card">
        <div>
          <div className="text-sm font-semibold text-ink">{pattern.date} (UTC)</div>
          <div className="text-xs text-muted">
            Last activity {relativeTime(pattern.last_activity_at)}
          </div>
        </div>
        <div className="text-right">
          <div className={`text-sm font-semibold ${BAND_TONE[pattern.band]}`}>{BAND_LABEL[pattern.band]}</div>
          <div className="text-xs text-muted">
            {hasBaseline && pattern.anomaly_score !== null
              ? `anomaly score ${(pattern.anomaly_score * 100).toFixed(0)}%`
              : "baseline not ready — run the baseline job"}
          </div>
        </div>
      </div>

      {/* 24-hour bars, UTC. Baseline (if present) shown as a faint overlay line per hour. */}
      <div className="rounded-xl border border-border bg-surface p-4 shadow-card">
        <div className="mb-2 text-xs font-semibold text-ink">Detections per hour (UTC)</div>
        <div className="flex items-end gap-0.5" style={{ height: 140 }}>
          {pattern.hours.map((count, hour) => {
            const h = Math.round((count / maxCount) * 120);
            const base = hasBaseline && pattern.baseline_mean ? Math.round((pattern.baseline_mean[hour] / maxCount) * 120) : null;
            return (
              <div
                key={hour}
                className="relative flex-1"
                style={{ height: 120 }}
                title={`${utcHourLabel(hour)}: ${count}${base !== null ? ` (baseline ${pattern.baseline_mean![hour].toFixed(1)})` : ""}`}
                aria-label={`${utcHourLabel(hour)}: ${count} detections`}
              >
                <div className="absolute bottom-0 w-full rounded-t bg-accent" style={{ height: h }} />
                {base !== null && (
                  <div className="absolute w-full border-t border-dashed border-warning" style={{ bottom: base }} aria-hidden="true" />
                )}
              </div>
            );
          })}
        </div>
        <div className="mt-1 flex justify-between text-[10px] text-muted">
          <span>00 UTC</span>
          <span>06</span>
          <span>12</span>
          <span>18</span>
          <span>23</span>
        </div>
      </div>

      {!hasBaseline && (
        <div className="rounded-lg border border-border bg-surface-2 px-4 py-3 text-sm text-muted">
          Collecting data: the baseline needs at least 14 active days. Run <code>make baseline-run</code> after
          seeding history to populate the band and anomaly score.
        </div>
      )}
    </div>
  );
}
