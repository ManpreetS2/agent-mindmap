export type ProviderKey = "claude" | "codex" | "other" | "unknown";

export function providerKey(provider: string | null | undefined): ProviderKey {
  if (!provider) return "unknown";
  const p = provider.toLowerCase();
  if (p.includes("claude")) return "claude";
  if (p.includes("codex")) return "codex";
  return "other";
}

/** Short identity shown on nodes; unknown providers are shown as reported, never guessed. */
export function providerLabel(provider: string | null | undefined): string {
  switch (providerKey(provider)) {
    case "claude":
      return "Claude";
    case "codex":
      return "Codex";
    case "unknown":
      return "Unknown provider";
    default:
      return provider as string;
  }
}
