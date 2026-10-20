import type { ReactNode } from "react";
import type { FactSource } from "../utils/detailPanelFacts";
import { UnsourcedTag } from "./UnsourcedTag";

interface FactSourceLinkProps {
  source: FactSource;
  children: ReactNode;
  className?: string;
}

export function FactSourceLink({
  source,
  children,
  className,
}: FactSourceLinkProps) {
  if (source.kind === "linked") {
    return (
      <a href={source.href} className={className}>
        {children}
      </a>
    );
  }
  return (
    <span className={className}>
      {children}
      {" "}
      <UnsourcedTag />
    </span>
  );
}
