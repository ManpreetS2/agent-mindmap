/**
 * MIT — adapted from Magic UI (https://magicui.design)
 * Copyright (c) Magic UI contributors
 *
 * Static ticker (no framer-motion) for MM-012 phase 1; motion in follow-up.
 */
import { cn } from "../../lib/utils";

interface NumberTickerProps {
  value: number;
  className?: string;
  suffix?: string;
}

export function NumberTicker({ value, className, suffix }: NumberTickerProps) {
  return (
    <span
      className={cn(
        "inline-tabular-nums font-mono text-neon-cyan tracking-tight",
        className,
      )}
      aria-live="polite"
    >
      {value.toLocaleString("en-US")}
      {suffix}
    </span>
  );
}
