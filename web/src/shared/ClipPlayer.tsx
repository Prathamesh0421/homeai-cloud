/** ClipPlayer: thin stub — full audio/video player lands in C4-12. */

export function ClipPlayer({ clipId }: { clipId: string }) {
  return (
    <div
      className="flex items-center justify-center rounded-xl border border-dashed border-border-strong bg-canvas py-12 text-sm text-muted"
      data-clip-id={clipId}
    >
      Clip player (clip {clipId}) — available in C4-12
    </div>
  );
}
