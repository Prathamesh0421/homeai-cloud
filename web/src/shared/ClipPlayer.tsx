/** ClipPlayer: thin stub — full audio/video player lands in C4-12. */

export function ClipPlayer({ clipId }: { clipId: string }) {
  return (
    <div
      className="flex items-center justify-center rounded-lg border border-dashed border-slate-300 bg-slate-50 py-12 text-sm text-slate-400"
      data-clip-id={clipId}
    >
      Clip player (clip {clipId}) — available in C4-12
    </div>
  );
}
