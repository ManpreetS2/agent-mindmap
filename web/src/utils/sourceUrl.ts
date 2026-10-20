import type { FactSource } from "./detailPanelFacts";

export function isHttpSourceUrl(url: string | undefined | null): boolean {
  if (!url) return false;
  return /^https?:\/\//i.test(url.trim());
}

export function factSourceFromUrl(url: string | undefined | null): FactSource {
  if (isHttpSourceUrl(url)) {
    return { kind: "linked", href: url!.trim() };
  }
  return { kind: "unsourced" };
}
