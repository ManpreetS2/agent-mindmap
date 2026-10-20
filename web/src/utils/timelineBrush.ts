export interface TimeDomain {
  minMs: number;
  maxMs: number;
}

export function clampDomain(
  domain: TimeDomain,
  full: TimeDomain,
): TimeDomain {
  const span = Math.max(1, domain.maxMs - domain.minMs);
  let minMs = Math.max(full.minMs, Math.min(domain.minMs, full.maxMs - span));
  let maxMs = minMs + span;
  if (maxMs > full.maxMs) {
    maxMs = full.maxMs;
    minMs = Math.max(full.minMs, maxMs - span);
  }
  return { minMs, maxMs };
}

export function zoomDomain(
  domain: TimeDomain,
  full: TimeDomain,
  factor: number,
  centerMs?: number,
): TimeDomain {
  const fullSpan = Math.max(1, full.maxMs - full.minMs);
  const span = Math.max(1, domain.maxMs - domain.minMs);
  const floor = Math.min(fullSpan, Math.max(1_000, fullSpan * 0.02));
  const nextSpan = Math.min(fullSpan, Math.max(floor, span * factor));
  const center = centerMs ?? (domain.minMs + domain.maxMs) / 2;
  return clampDomain(
    { minMs: center - nextSpan / 2, maxMs: center + nextSpan / 2 },
    full,
  );
}

export function brushDomainFromRatio(
  full: TimeDomain,
  startRatio: number,
  endRatio: number,
): TimeDomain {
  const span = full.maxMs - full.minMs;
  const a = Math.min(startRatio, endRatio);
  const b = Math.max(startRatio, endRatio);
  return clampDomain(
    {
      minMs: full.minMs + a * span,
      maxMs: full.minMs + Math.max(a + 0.02, b) * span,
    },
    full,
  );
}
