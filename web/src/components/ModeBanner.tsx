export type ServerMode = "live" | "demo";

interface ModeBannerProps {
  mode: ServerMode;
}

/**
 * Plain LIVE/DEMO indicator (MM-020i). Styled minimally; UX will restyle later.
 */
export function ModeBanner({ mode }: ModeBannerProps) {
  const isDemo = mode === "demo";
  return (
    <div
      role="status"
      aria-live="polite"
      data-mode={mode}
      className={
        isDemo
          ? "w-full border-b border-amber-500/60 bg-amber-950/90 px-4 py-2 text-center text-sm font-semibold tracking-wide text-amber-100"
          : "w-full border-b border-emerald-600/50 bg-emerald-950/90 px-4 py-2 text-center text-sm font-semibold tracking-wide text-emerald-100"
      }
    >
      {isDemo ? "DEMO MODE — fixture data only" : "LIVE MODE — ingested data"}
    </div>
  );
}
