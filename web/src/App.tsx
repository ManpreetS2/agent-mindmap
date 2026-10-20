import { useCallback, useMemo, useState } from "react";
import { LedgerLoadError } from "./data/loadActivity";
import { createSseTransport } from "./data/activityTransport";
import { postRefresh } from "./data/postRefresh";
import { LedgerErrorView } from "./components/LedgerErrorView";
import { MindmapLoadingView } from "./components/MindmapLoadingView";
import { SkipLink } from "./components/SkipLink";
import { CommandCenterShell } from "./components/CommandCenterShell";
import { ModeBanner } from "./components/ModeBanner";
import { MindmapView } from "./views/MindmapView";
import { useActivityFeed } from "./hooks/useActivityFeed";
import { useServerMode } from "./hooks/useServerMode";
import {
  REFRESH_FORBIDDEN_MESSAGE,
  refreshRateLimitMessage,
} from "./utils/viewState";

const POLL_MS = Number(
  (import.meta as ImportMeta & { env?: { VITE_ACTIVITY_POLL_MS?: string } }).env
    ?.VITE_ACTIVITY_POLL_MS ?? 10_000,
);

export function App() {
  const { bannerState } = useServerMode();
  const banner = <ModeBanner state={bannerState} />;
  const [sseConnected, setSseConnected] = useState(true);
  const [refreshRateLimit, setRefreshRateLimit] = useState<string | null>(null);
  const [refreshForbidden, setRefreshForbidden] = useState<string | null>(null);
  const transport = useMemo(
    () =>
      createSseTransport({
        intervalMs: Number.isFinite(POLL_MS) ? POLL_MS : 10_000,
        onSseConnectionChange: setSseConnected,
      }),
    [],
  );
  const { activity, error, statusPulseNodeIds, reload } =
    useActivityFeed(transport);

  const handleRefresh = useCallback(async () => {
    setRefreshForbidden(null);
    setRefreshRateLimit(null);
    const result = await postRefresh();
    if (result.status === "queued") {
      reload();
      return;
    }
    if (result.status === "rate_limited") {
      setRefreshRateLimit(refreshRateLimitMessage(result.retryAfterS));
      return;
    }
    if (result.status === "forbidden") {
      setRefreshForbidden(REFRESH_FORBIDDEN_MESSAGE);
      return;
    }
    setRefreshForbidden(`Refresh failed (${result.httpStatus}).`);
  }, [reload]);

  if (error instanceof LedgerLoadError) {
    return (
      <CommandCenterShell>
        {banner}
        <SkipLink />
        <LedgerErrorView onRetry={reload} />
      </CommandCenterShell>
    );
  }

  if (error) {
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

  return (
    <CommandCenterShell>
      {banner}
      <SkipLink />
      <MindmapView
        activity={activity}
        onRefresh={handleRefresh}
        statusPulseNodeIds={statusPulseNodeIds}
        sseDisconnected={!sseConnected}
        refreshRateLimitMessage={refreshRateLimit}
        refreshForbiddenMessage={refreshForbidden}
      />
    </CommandCenterShell>
  );
}
