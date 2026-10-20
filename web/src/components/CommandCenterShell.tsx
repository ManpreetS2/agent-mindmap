import type { ReactNode } from "react";
import { AnimatedGridPattern } from "./magic/animated-grid-pattern";

interface CommandCenterShellProps {
  children: ReactNode;
}

/** Dark glass / neon command-center chrome (MM-012 phase 1 — no motion lib yet). */
export function CommandCenterShell({ children }: CommandCenterShellProps) {
  return (
    <div className="dark relative flex min-h-dvh flex-col overflow-x-hidden bg-background text-foreground">
      <div
        className="pointer-events-none absolute inset-0 overflow-hidden"
        aria-hidden="true"
      >
        <AnimatedGridPattern className="h-full w-full opacity-[0.45] motion-reduce:opacity-30" />
        <div className="absolute inset-0 bg-gradient-to-b from-neon-violet/10 via-transparent to-neon-cyan/5" />
      </div>
      <div className="relative z-[1] flex min-h-0 flex-1 flex-col pt-0">{children}</div>
    </div>
  );
}
