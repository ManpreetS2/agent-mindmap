/**
 * MIT — adapted from Magic UI (https://magicui.design)
 * Copyright (c) Magic UI contributors
 */
import { useId } from "react";
import { cn } from "../../lib/utils";

interface AnimatedGridPatternProps {
  className?: string;
  width?: number;
  height?: number;
  numSquares?: number;
}

export function AnimatedGridPattern({
  className,
  width = 48,
  height = 48,
}: AnimatedGridPatternProps) {
  const id = useId();
  return (
    <svg
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute inset-0 h-full w-full fill-none stroke-border/30 motion-reduce:opacity-40",
        className,
      )}
    >
      <defs>
        <pattern
          id={id}
          width={width}
          height={height}
          patternUnits="userSpaceOnUse"
        >
          <path
            d={`M ${width} 0 L 0 0 0 ${height}`}
            fill="none"
            strokeWidth="1"
          />
        </pattern>
      </defs>
      <rect width="100%" height="100%" fill={`url(#${id})`} />
    </svg>
  );
}
