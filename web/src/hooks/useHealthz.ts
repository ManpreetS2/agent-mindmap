import { useCallback, useEffect, useState } from "react";

export interface HealthSnapshot {
  ledger_status?: string;
  github_status?: string;
  errors: string[];
}

export function useHealthz(pollMs = 10_000): HealthSnapshot {
  const [snap, setSnap] = useState<HealthSnapshot>({ errors: [] });

  const load = useCallback(() => {
    void fetch("/healthz")
      .then((r) => (r.ok ? r.json() : null))
      .then((body) => {
        if (!body || typeof body !== "object") return;
        const errors = Array.isArray(body.errors)
          ? body.errors.filter((e: unknown) => typeof e === "string")
          : [];
        setSnap({
          ledger_status:
            typeof body.ledger_status === "string"
              ? body.ledger_status
              : undefined,
          github_status:
            typeof body.github_status === "string"
              ? body.github_status
              : undefined,
          errors,
        });
      })
      .catch(() => {
        /* keep last snapshot */
      });
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(load, pollMs);
    return () => window.clearInterval(t);
  }, [load, pollMs]);

  return snap;
}
