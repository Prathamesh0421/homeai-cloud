/**
 * PipelineScene — the hero of the login left panel.
 *
 * Plays the real product loop once, then holds its final state:
 *   1. A waveform draws in and spikes (Ingest).
 *   2. A chip appears: glass_break · 0.80 (Classify).
 *   3. An alert row appears: High · Kitchen · Maple St (Alert).
 *   4. A line appears: Email sent to Alice Maple.
 *
 * The 01/02/03 legend highlights as the scene reaches each step. A Replay
 * button restarts the sequence; it does not loop forever (a loop competes with
 * the form). Honors prefers-reduced-motion.
 */

import { useCallback, useEffect, useState } from "react";
import { motion, useReducedMotion } from "motion/react";

// Flat, one sharp burst, flat. viewBox 0 0 400 80, baseline y=40.
const WAVE_PATH =
  "M0 40 L60 40 L80 40 L100 38 L120 42 L140 40 L160 40 L180 39 L196 41 " +
  "L208 14 L214 66 L220 30 L240 40 L260 40 L280 40 L300 40 L320 40 L340 40 L360 40 L400 40";

export type Step = "ingest" | "classify" | "alert" | "email";

export interface PipelineSceneProps {
  /** Called whenever the active step changes (legend highlights in sync). */
  onStep?: (step: Step) => void;
}

const STEP_DELAYS = {
  ingest: 0,
  classify: 1.8,
  alert: 2.4,
  email: 3.2,
} as const;

const TOTAL = 4.0; // seconds until the scene holds

export function PipelineScene({ onStep }: PipelineSceneProps) {
  const reduce = useReducedMotion();
  const [runKey, setRunKey] = useState(0);

  const step = (delay: number) => ({
    initial: { opacity: 0, y: reduce ? 0 : 8 },
    animate: { opacity: 1, y: 0 },
    transition: { delay: reduce ? 0 : delay, duration: reduce ? 0 : 0.35, ease: "easeOut" as const },
  });

  // Advance the active step as the timeline plays.
  useEffect(() => {
    if (reduce) {
      onStep?.("email");
      return;
    }
    const timers = (Object.keys(STEP_DELAYS) as Step[]).map((s) =>
      window.setTimeout(() => {
        onStep?.(s);
      }, STEP_DELAYS[s] * 1000),
    );
    return () => timers.forEach(clearTimeout);
    // onStep intentionally not in deps (parent passes a fresh fn each render)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runKey, reduce, onStep]);

  const replay = useCallback(() => {
    onStep?.("ingest");
    setRunKey((k) => k + 1);
  }, [onStep]);

  return (
    <div className="space-y-3 text-white">
      <div className="relative">
        <svg viewBox="0 0 400 80" className="w-full" role="img" aria-label="Audio waveform with a sharp burst">
          <motion.path
            key={runKey}
            d={WAVE_PATH}
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            initial={{ pathLength: reduce ? 1 : 0, opacity: reduce ? 1 : 0.5 }}
            animate={{ pathLength: 1, opacity: 1 }}
            transition={{ duration: reduce ? 0 : 1.8, ease: "linear" }}
          />
        </svg>
      </div>

      <motion.div
        {...step(STEP_DELAYS.classify)}
        className="inline-flex items-center gap-2 rounded-md border border-white/15 bg-white/10 px-2.5 py-1.5 text-sm"
      >
        <span className="font-mono text-blue-200">glass_break</span>
        <span className="text-white/40">·</span>
        <span className="tnum text-white">0.80</span>
      </motion.div>

      <motion.div
        {...step(STEP_DELAYS.alert)}
        className="flex items-center gap-2 rounded-md border border-sev-high/40 bg-sev-high/15 px-2.5 py-1.5 text-sm"
      >
        <span className="inline-flex items-center gap-1.5 font-semibold text-sev-high">
          <span className="h-1.5 w-1.5 rounded-full bg-sev-high" aria-hidden="true" />
          High
        </span>
        <span className="text-white/40">·</span>
        <span className="text-white">Kitchen</span>
        <span className="text-white/40">·</span>
        <span className="text-white">Maple St</span>
      </motion.div>

      <motion.div
        {...step(STEP_DELAYS.email)}
        className="flex items-center gap-2 text-sm text-blue-100/90"
      >
        <span className="text-blue-200/70">→</span>
        <span>Email sent to Alice Maple</span>
      </motion.div>

      <div className="pt-2">
        <button
          type="button"
          onClick={replay}
          className="rounded-md border border-white/15 px-2.5 py-1 text-xs text-blue-100/80 transition-colors hover:bg-white/10 hover:text-white"
        >
          Replay
        </button>
      </div>
    </div>
  );
}

export const PIPELINE_TOTAL_MS = TOTAL * 1000;
