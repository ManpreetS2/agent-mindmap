import type { ReactNode } from "react";
import { AnimatedGridPattern } from "./magic/animated-grid-pattern";

interface CommandCenterShellProps {
  children: ReactNode;
}

/** Dark glass / neon command-center chrome (MM-012 phase 1 — no motion lib yet). */
export function CommandCenterShell({ children }: CommandCenterShellProps) {
  return (
    <div className="dark relative min-h-full bg-background text-foreground">
      <AnimatedGridPattern className="opacity-[0.45] motion-reduce:opacity-30" />
      <div
        className="pointer-events-none absolute inset-0 bg-gradient-to-b from-neon-violet/10 via-transparent to-neon-cyan/5"
        aria-hidden="true"
      />
      <div className="relative z-[1] flex min-h-full flex-col">{children}</div>
      <div
        className="pointer-events-none fixed inset-x-0 top-0 z-[2] h-px bg-gradient-to-r from-transparent via-neon-cyan/60 to-transparent"
        aria-hidden="true"
      />
    </div>
  );
}
