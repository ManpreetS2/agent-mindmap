/** MM-020-P0: server-triggered poll + rebuild (POST /refresh). */

export async function postRefresh(fetchImpl: typeof fetch = fetch): Promise<void> {
  const res = await fetchImpl("/refresh", { method: "POST" });
  if (res.status === 429) {
    throw new Error("Refresh rate limited (max 1 per 5s)");
  }
  if (!res.ok) {
    throw new Error(`Refresh failed (${res.status})`);
  }
}
