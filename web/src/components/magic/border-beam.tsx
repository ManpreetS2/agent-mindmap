/**
 * MIT — adapted from Magic UI (https://magicui.design)
 * Copyright (c) Magic UI contributors
 */
import type { CSSProperties } from "react";
import { cn } from "../../lib/utils";

interface BorderBeamProps {
  className?: string;
  size?: number;
  duration?: number;
  borderWidth?: number;
  colorFrom?: string;
  colorTo?: string;
}

export function BorderBeam({
  className,
  size = 120,
  duration = 8,
  borderWidth = 1.5,
  colorFrom = "hsl(var(--neon-cyan))",
  colorTo = "hsl(var(--neon-violet))",
}: BorderBeamProps) {
  return (
    <div
      className={cn(
        "pointer-events-none absolute inset-0 rounded-[inherit] motion-reduce:hidden",
        className,
      )}
      aria-hidden="true"
    >
      <div
        className="absolute inset-0 rounded-[inherit] border-beam-mask"
        style={
          {
            "--beam-size": `${size}px`,
            "--beam-duration": `${duration}s`,
            "--beam-width": `${borderWidth}px`,
            "--beam-from": colorFrom,
            "--beam-to": colorTo,
          } as CSSProperties
        }
      />
    </div>
  );
}
