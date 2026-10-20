/** MM-020-P0: POST /refresh — poll + rebuild on server. */

export type PostRefreshResult =
  | { status: "queued" }
  | { status: "rate_limited"; retryAfterS: number }
  | { status: "forbidden" }
  | { status: "error"; httpStatus: number };

export async function postRefresh(
  fetchImpl: typeof fetch = fetch,
): Promise<PostRefreshResult> {
  let res: Response;
  try {
    res = await fetchImpl("/refresh", { method: "POST" });
  } catch {
    return { status: "error", httpStatus: 0 };
  }
  if (res.status === 202) {
    return { status: "queued" };
  }
  if (res.status === 429) {
    let retryAfterS = 5;
    try {
      const body = (await res.json()) as { retry_after_s?: number };
      if (typeof body.retry_after_s === "number" && body.retry_after_s > 0) {
        retryAfterS = body.retry_after_s;
      }
    } catch {
      /* use default */
    }
    return { status: "rate_limited", retryAfterS };
  }
  if (res.status === 403) {
    return { status: "forbidden" };
  }
  return { status: "error", httpStatus: res.status };
}
