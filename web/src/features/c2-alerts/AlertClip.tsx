/** The alert's recording from C1 (C2-11): a fresh 15-minute presigned URL when Play is pressed. */

import { useEffect, useRef, useState } from "react";
import { getClipUrl } from "../../api/c2";
import { ApiError } from "../../api/http";
import { Button } from "@/components/ui/button";
import { isAudioClip } from "./format";

type State =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; url: string }
  | { kind: "missing" }
  | { kind: "failed" };

export function AlertClip({ mediaId }: { mediaId: string }) {
  const [state, setState] = useState<State>({ kind: "idle" });
  const player = useRef<HTMLMediaElement | null>(null);

  useEffect(() => setState({ kind: "idle" }), [mediaId]); // another alert in the drawer
  // The player replaces the Play button, so it takes over the keyboard focus.
  useEffect(() => {
    if (state.kind === "ready") player.current?.focus();
  }, [state.kind]);

  async function play() {
    setState({ kind: "loading" });
    try {
      setState({ kind: "ready", url: await getClipUrl(mediaId) });
    } catch (e) {
      // 404: C1 has no such clip (e.g. a faked detection); 403: not this user's house.
      const missing = e instanceof ApiError && (e.status === 404 || e.status === 403);
      setState({ kind: missing ? "missing" : "failed" });
    }
  }

  if (state.kind === "ready") {
    const Player = isAudioClip(state.url) ? "audio" : "video"; // C1 stores audio or video clips
    return (
      <Player
        ref={(el: HTMLMediaElement | null) => {
          player.current = el;
        }}
        tabIndex={0}
        src={state.url}
        controls
        autoPlay
        className="w-full rounded-md"
        aria-label="Alert recording"
        onError={() => setState({ kind: "failed" })}
      />
    );
  }
  if (state.kind === "missing") {
    return <p className="text-sm text-muted">The recording is not available.</p>;
  }
  return (
    <div className="flex items-center gap-3">
      <Button variant="secondary" size="sm" disabled={state.kind === "loading"} onClick={play}>
        {state.kind === "loading" ? "Loading…" : "Play recording"}
      </Button>
      {state.kind === "failed" && (
        <span role="alert" className="text-sm text-muted">
          Could not load the recording. Try again.
        </span>
      )}
    </div>
  );
}
