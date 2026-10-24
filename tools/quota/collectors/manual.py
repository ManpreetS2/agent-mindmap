"""Manual readings: strict validation, explicit source and observation time, 24h TTL."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .. import normalize as N
from .. import store
from ..models import FUTURE_SKEW, POOL_ORDER, QuotaError

DEFAULT_MINUTES = {"session": 300, "weekly": 10080}


def set_window(pool: str, wtype: str, used_pct, resets_at: str | None, source: str, observed_at: str,
               *, plan: str | None = None, window_minutes: int | None = None, state_dir: Path | None = None,
               now: datetime | None = None) -> dict:
    now = now or N.now_utc()
    if pool not in POOL_ORDER:
        raise QuotaError("unknown pool")
    src = N.clean_text(source, 100)
    if source and source.strip() and src.startswith("["):
        raise QuotaError("--source looks like a path, email or credential; describe the source in plain words "
                         "(for example 'claude.ai usage page'). Nothing was stored")
    if not src:
        raise QuotaError("--source is required and must describe where the number came from")
    observed = N.parse_ts(observed_at)
    if observed is None:
        raise QuotaError("--observed-at must be an ISO timestamp with a timezone")
    if observed - now > FUTURE_SKEW:
        raise QuotaError("--observed-at is in the future")
    if wtype not in ("session", "weekly", "monthly", "other"):
        raise QuotaError("--window must be session, weekly, monthly or other")
    resets = None
    if resets_at is not None:
        resets = N.parse_ts(resets_at)
        if resets is None:
            raise QuotaError("--resets-at must be an ISO timestamp with a timezone")
        if resets <= now:
            raise QuotaError("--resets-at has already passed; that window is no longer current")
    mins = window_minutes if window_minutes is not None else DEFAULT_MINUTES.get(wtype)
    if mins is not None and N.minutes(mins) is None:
        raise QuotaError("bad --window-minutes")
    _, label = N.classify_window(mins, wtype)
    if wtype == "monthly":
        label = "monthly"
    window = N.make_window(wtype, label, mins, _num(used_pct), resets, observed)
    prior = store.read(pool, "manual", state_dir)
    keep = []
    if prior and prior.get("outcome") == "ok":
        keep = [w for w in prior.get("windows", []) if isinstance(w, dict) and w.get("type") != wtype]
    reading = N.make_reading(pool, "manual", f"manual: {src}", observed, "ok",
                             plan=plan if plan is not None else (prior or {}).get("plan"), windows=[*keep, window])
    store.write(pool, reading, "manual", state_dir)
    return reading


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        raise QuotaError("--used-pct must be a number") from None


def clear(pool: str, state_dir: Path | None = None) -> bool:
    if pool not in POOL_ORDER:
        raise QuotaError("unknown pool")
    return store.clear(pool, "manual", state_dir)
