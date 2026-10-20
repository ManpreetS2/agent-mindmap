import { useEffect, useRef, useState } from "react";
import type { ModeBannerState } from "../components/ModeBanner";

interface HealthzPayload {
  mode?: string;
}

const INITIAL_BACKOFF_MS = 500;
const MAX_BACKOFF_MS = 15_000;

function parseHealthzMode(raw: unknown): ModeBannerState {
  if (raw === "demo") return "demo";
  if (raw === "live") return "live";
  return "unknown";
}

export function useServerMode(healthzUrl = "/healthz"): {
  bannerState: ModeBannerState;
  error: Error | null;
} {
  const [bannerState, setBannerState] = useState<ModeBannerState>("loading");
  const [error, setError] = useState<Error | null>(null);
  const attemptRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const schedule = (delayMs: number) => {
      timer = setTimeout(() => {
        void load();
      }, delayMs);
    };

    const load = async () => {
      try {
        const res = await fetch(healthzUrl);
        if (!res.ok) {
          throw new Error(`healthz ${res.status}`);
        }
        const body = (await res.json()) as HealthzPayload;
        if (cancelled) return;
        setBannerState(parseHealthzMode(body.mode));
        setError(null);
        attemptRef.current = 0;
        schedule(5000);
      } catch (err: unknown) {
        if (cancelled) return;
        const nextErr = err instanceof Error ? err : new Error(String(err));
        setError(nextErr);
        setBannerState("unknown");
        attemptRef.current += 1;
        const backoff = Math.min(
          MAX_BACKOFF_MS,
          INITIAL_BACKOFF_MS * 2 ** (attemptRef.current - 1),
        );
        schedule(backoff);
      }
    };

    void load();

    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [healthzUrl]);

  return { bannerState, error };
}
