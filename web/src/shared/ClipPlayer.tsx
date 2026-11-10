/** ClipPlayer: thin stub until C1-07 / C2-11 playback URL is wired. */

export function ClipPlayer({ clipId }: { clipId: string }) {
  return (
    <div
      className="flex items-center justify-center rounded-xl border border-dashed border-border-strong bg-canvas py-12 text-sm text-muted"
      data-clip-id={clipId}
    >
      Clip playback is not available yet.
    </div>
  );
}
