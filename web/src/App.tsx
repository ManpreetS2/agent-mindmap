import { useMemo } from "react";
import { LedgerLoadError } from "./data/loadActivity";
import { createPollTransport } from "./data/activityTransport";
import { LedgerErrorView } from "./components/LedgerErrorView";
import { MindmapLoadingView } from "./components/MindmapLoadingView";
import { SkipLink } from "./components/SkipLink";
import { CommandCenterShell } from "./components/CommandCenterShell";
import { MindmapView } from "./views/MindmapView";
import { useActivityFeed } from "./hooks/useActivityFeed";
import { useObservability } from "./hooks/useObservability";

const POLL_MS = Number(
  (import.meta as ImportMeta & { env?: { VITE_ACTIVITY_POLL_MS?: string } }).env
    ?.VITE_ACTIVITY_POLL_MS ?? 10_000,
);

export function App() {
  const transport = useMemo(
    () => createPollTransport({ intervalMs: Number.isFinite(POLL_MS) ? POLL_MS : 10_000 }),
    [],
  );
  const { activity, error, statusPulseNodeIds, reload } =
    useActivityFeed(transport);
  const observability = useObservability();

  if (error instanceof LedgerLoadError) {
    return (
      <CommandCenterShell>
        <SkipLink />
        <LedgerErrorView onRetry={reload} />
      </CommandCenterShell>
    );
  }

  if (error) {
    return (
      <CommandCenterShell>
        <SkipLink />
        <div className="app-error state-panel state-panel--error" role="alert">
          <span className="state-icon" aria-hidden="true">!</span>
          <h1>Couldn&apos;t load activity</h1>
          <p className="state-sub">{error.message}</p>
          <button type="button" className="state-button" onClick={reload}>
            Retry
          </button>
        </div>
      </CommandCenterShell>
    );
  }

  if (!activity) {
    return (
      <CommandCenterShell>
        <SkipLink />
        <MindmapLoadingView />
      </CommandCenterShell>
    );
  }

  return (
    <CommandCenterShell>
      <SkipLink />
      <MindmapView
        activity={activity}
        onRefresh={reload}
        statusPulseNodeIds={statusPulseNodeIds}
        observability={observability}
      />
    </CommandCenterShell>
  );
}
