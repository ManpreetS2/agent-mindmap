import { useMemo, useState } from "react";
import { LedgerLoadError } from "./data/loadActivity";
import { createSseTransport } from "./data/activityTransport";
import { LedgerErrorView } from "./components/LedgerErrorView";
import { MindmapLoadingView } from "./components/MindmapLoadingView";
import { SkipLink } from "./components/SkipLink";
import { CommandCenterShell } from "./components/CommandCenterShell";
import { ModeBanner } from "./components/ModeBanner";
import { MindmapView } from "./views/MindmapView";
import { useActivityFeed } from "./hooks/useActivityFeed";
import { useMindmapRefresh } from "./hooks/useMindmapRefresh";
import { useServerMode } from "./hooks/useServerMode";
import {
  type SseConnectionState,
  buildMindmapStatusBar,
} from "./utils/refreshFlow";

const POLL_MS = Number(
  (import.meta as ImportMeta & { env?: { VITE_ACTIVITY_POLL_MS?: string } }).env
    ?.VITE_ACTIVITY_POLL_MS ?? 10_000,
);

export function App() {
  const { bannerState } = useServerMode();
  const banner = <ModeBanner state={bannerState} />;
  const [sseConnection, setSseConnection] =
    useState<SseConnectionState>("connecting");
  const transport = useMemo(
    () =>
      createSseTransport({
        intervalMs: Number.isFinite(POLL_MS) ? POLL_MS : 10_000,
        onSseConnectionChange: (connected) => {
          setSseConnection(connected ? "connected" : "disconnected");
        },
      }),
    [],
  );
  const { activity, error, statusPulseNodeIds, reload } =
    useActivityFeed(transport);
  const activityKey = activity
    ? `${activity.generated_at}:${activity.meta.github}:${activity.events.length}`
    : "";
  const { handleRefresh, refreshError, rateLimitSeconds } =
    useMindmapRefresh(activityKey);

  if (!activity && error instanceof LedgerLoadError) {
    return (
      <CommandCenterShell>
        {banner}
        <SkipLink />
        <LedgerErrorView onRetry={reload} />
      </CommandCenterShell>
    );
  }

  if (!activity && error) {
    return (
      <CommandCenterShell>
        {banner}
        <SkipLink />
        <div className="app-error" role="alert">
          {error.message}
          <button type="button" onClick={reload}>
            Retry
          </button>
        </div>
      </CommandCenterShell>
    );
  }

  if (!activity) {
    return (
      <CommandCenterShell>
        {banner}
        <SkipLink />
        <MindmapLoadingView />
      </CommandCenterShell>
    );
  }

  const statusBar = buildMindmapStatusBar({
    meta: activity.meta,
    sse: sseConnection,
    refreshError,
    rateLimitSeconds,
  });

  return (
    <CommandCenterShell>
      {banner}
      <SkipLink />
      <MindmapView
        activity={activity}
        onRefresh={handleRefresh}
        statusPulseNodeIds={statusPulseNodeIds}
        statusBar={statusBar}
      />
    </CommandCenterShell>
  );
}
