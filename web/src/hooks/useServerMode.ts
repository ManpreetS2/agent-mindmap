import { useEffect, useState } from "react";
import type { ServerMode } from "../components/ModeBanner";

interface HealthzPayload {
  mode?: ServerMode;
}

export function useServerMode(healthzUrl = "/healthz"): {
  mode: ServerMode | null;
  error: Error | null;
} {
  const [mode, setMode] = useState<ServerMode | null>(null);
  const [error, setError] = useState<Error | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = () => {
      fetch(healthzUrl)
        .then((res) => {
          if (!res.ok) {
            throw new Error(`healthz ${res.status}`);
          }
          return res.json() as Promise<HealthzPayload>;
        })
        .then((body) => {
          if (cancelled) return;
          const next = body.mode === "demo" ? "demo" : "live";
          setMode(next);
          setError(null);
        })
        .catch((err: unknown) => {
          if (cancelled) return;
          setError(err instanceof Error ? err : new Error(String(err)));
        });
    };
    load();
    return () => {
      cancelled = true;
    };
  }, [healthzUrl]);

  return { mode, error };
}
