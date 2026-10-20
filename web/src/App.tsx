import { useCallback, useEffect, useState } from "react";
import type { Activity } from "@shared/types";
import { LedgerLoadError, loadActivity } from "./data/loadActivity";
import { LedgerErrorView } from "./components/LedgerErrorView";
import { MindmapLoadingView } from "./components/MindmapLoadingView";
import { SkipLink } from "./components/SkipLink";
import { CommandCenterShell } from "./components/CommandCenterShell";
import { MindmapView } from "./views/MindmapView";

export function App() {
  const [activity, setActivity] = useState<Activity | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [retryToken, setRetryToken] = useState(0);

  const reload = useCallback(() => {
    setError(null);
    setActivity(null);
    setRetryToken((t) => t + 1);
  }, []);

  useEffect(() => {
    let cancelled = false;
    loadActivity()
      .then((data) => {
        if (!cancelled) setActivity(data);
      })
      .catch((e: unknown) => {
        if (!cancelled) {
          setError(e instanceof Error ? e : new Error("Failed to load data"));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [retryToken]);

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
        <div className="app-error" role="alert">
          {error.message}
          <button type="button" onClick={reload}>Retry</button>
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
      <MindmapView activity={activity} onRefresh={reload} />
    </CommandCenterShell>
  );
}
