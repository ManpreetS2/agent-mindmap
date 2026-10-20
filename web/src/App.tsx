import { useEffect, useState } from "react";
import type { Activity } from "@shared/types";
import { loadActivity } from "./data/loadActivity";
import { MindmapView } from "./views/MindmapView";

export function App() {
  const [activity, setActivity] = useState<Activity | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadActivity()
      .then(setActivity)
      .catch((e: unknown) => {
        setError(e instanceof Error ? e.message : "Failed to load data");
      });
  }, []);

  if (error) {
    return (
      <div className="app-error" role="alert">
        {error}
      </div>
    );
  }

  if (!activity) {
    return (
      <div className="app-loading" role="status" aria-live="polite">
        Reading activity snapshot…
      </div>
    );
  }

  return <MindmapView activity={activity} />;
}
