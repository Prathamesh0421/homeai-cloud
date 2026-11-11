/** Timestamp — one component for every timestamp in the app.
 *
 * Shows relative text ("4s ago") with the absolute time in a tooltip, so we
 * stop mixing "10 Nov, 21:31", "08/11/2026", and ISO UTC across pages. Times
 * are UTC end to end on the backend; the tooltip shows the local equivalent
 * and a UTC tag.
 */

import { useEffect, useState } from "react";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

export interface TimestampProps {
  /** ISO-8601 string (UTC with Z). */
  iso: string | null | undefined;
  /** Tick interval for the relative text. Defaults to 1s for live pages. */
  tickMs?: number;
  /** Hide the relative text and show only the absolute time. */
  absolute?: boolean;
  className?: string;
}

function relativeNow(iso: string, now: number): string {
  const then = new Date(iso).getTime();
  const secs = Math.max(0, Math.round((now - then) / 1000));
  if (secs < 5) return "just now";
  if (secs < 60) return `${secs}s ago`;
  const mins = Math.round(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.round(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.round(hrs / 24)}d ago`;
}

function absoluteLocal(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function absoluteUtc(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function Timestamp({ iso, tickMs = 1000, absolute = false, className }: TimestampProps) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (absolute) return;
    const t = window.setInterval(() => setNow(Date.now()), tickMs);
    return () => window.clearInterval(t);
  }, [absolute, tickMs]);

  if (!iso) return <span className={className ?? "text-muted"}>—</span>;

  const rel = relativeNow(iso, now);
  const local = absoluteLocal(iso);
  const utc = `${absoluteUtc(iso)} UTC`;

  if (absolute) {
    return (
      <TooltipProvider>
        <Tooltip>
          <TooltipTrigger asChild>
            <time dateTime={iso} className={className ?? "tnum text-ink"} title={`${local} (${utc})`}>
              {local}
            </time>
          </TooltipTrigger>
          <TooltipContent>{utc}</TooltipContent>
        </Tooltip>
      </TooltipProvider>
    );
  }

  return (
    <TooltipProvider>
      <Tooltip>
        <TooltipTrigger asChild>
          <time dateTime={iso} className={className ?? "tnum text-muted"} title={`${local} (${utc})`}>
            {rel}
          </time>
        </TooltipTrigger>
        <TooltipContent>
          {local}
          <br />
          {utc}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
