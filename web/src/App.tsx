import { useCallback, useEffect, useState } from "react";
import type { Activity } from "@shared/types";
import { LedgerLoadError, loadActivity } from "./data/loadActivity";
import { LedgerErrorView } from "./components/LedgerErrorView";
import { MindmapLoadingView } from "./components/MindmapLoadingView";
import { SkipLink } from "./components/SkipLink";
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
      <>
        <SkipLink />
        <LedgerErrorView onRetry={reload} />
      </>
    );
  }

  if (error) {
    return (
      <>
        <SkipLink />
        <div className="app-error" role="alert">
          {error.message}
          <button type="button" onClick={reload}>Retry</button>
        </div>
      </>
    );
  }

  if (!activity) {
    return (
      <>
        <SkipLink />
        <MindmapLoadingView />
      </>
    );
  }

  return (
    <>
      <SkipLink />
      <MindmapView activity={activity} onRefresh={reload} />
    </>
  );
}
