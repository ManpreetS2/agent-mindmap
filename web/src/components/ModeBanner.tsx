export type ServerMode = "live" | "demo";
export type ModeBannerState = "loading" | "unknown" | ServerMode;

interface ModeBannerProps {
  state: ModeBannerState;
}

/**
 * Plain LIVE/DEMO indicator (MM-020i). Styled minimally; UX will restyle later.
 */
export function ModeBanner({ state }: ModeBannerProps) {
  const label =
    state === "loading"
      ? "LOADING MODE…"
      : state === "unknown"
        ? "UNKNOWN MODE — server mode unavailable"
        : state === "demo"
          ? "DEMO MODE — fixture data only"
          : "LIVE MODE — ingested data";

  const dataMode = state === "loading" || state === "unknown" ? state : state;

  const className =
    state === "demo"
      ? "w-full border-b border-amber-500/60 bg-amber-950/90 px-4 py-2 text-center text-sm font-semibold tracking-wide text-amber-100"
      : state === "live"
        ? "w-full border-b border-emerald-600/50 bg-emerald-950/90 px-4 py-2 text-center text-sm font-semibold tracking-wide text-emerald-100"
        : "w-full border-b border-zinc-600/60 bg-zinc-900/95 px-4 py-2 text-center text-sm font-semibold tracking-wide text-zinc-200";

  return (
    <div role="status" aria-live="polite" data-mode={dataMode} className={className}>
      {label}
    </div>
  );
}
