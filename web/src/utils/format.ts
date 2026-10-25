const LA_TZ = "America/Los_Angeles";

export function formatSourceTime(iso: string): string {
  if (!iso) return iso;
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString("en-US", {
      timeZone: LA_TZ,
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    });
  } catch {
    return iso;
  }
}

export function formatRelativeAgo(iso: string, now = new Date()): string {
  const then = new Date(iso).getTime();
  const diffMs = now.getTime() - then;
  if (Number.isNaN(diffMs)) return "unknown time";
  const mins = Math.round(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

export function attributionLabel(method: string): string {
  switch (method) {
    case "signature":
      return "signature";
    case "ledger_owner":
      return "ledger / task owner";
    case "unknown":
      return "unknown";
    default:
      return method;
  }
}

export function sourceKindFromUrl(url: string): string {
  if (url.startsWith("https://github.com")) return "GitHub";
  if (url.includes("task-ledger")) return "ledger";
  if (url.includes("build/tasks/")) return "task file";
  return "source";
}
