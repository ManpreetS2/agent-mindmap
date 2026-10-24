"""Public interface: pools() returns exactly the five QuotaPool dicts, staleness computed at call time."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from . import normalize as N
from . import store
from .models import POOL_ORDER, T3_UI_SOURCE

_RANK = {"VERIFIED": 0, "MANUAL": 1, "ERROR": 2, "UNSUPPORTED": 3, "STALE": 4, "UNKNOWN": 5}


def _resolve(pool_id: str, state_dir: Path | None, now: datetime) -> dict:
    cands = []
    for channel in store.CHANNELS:
        reading = store.read(pool_id, channel, state_dir)
        if reading:
            cands.append(N.evaluate(pool_id, reading, now))
    if not cands:
        return N.placeholder(pool_id)
    cands.sort(key=lambda p: (_RANK[p["status"]], p["observed_at"] is None, -(N.parse_ts(p["observed_at"]).timestamp() if p["observed_at"] else 0)))
    best = dict(cands[0])
    if best["plan"] is None:
        best["plan"] = next((c["plan"] for c in cands if c["plan"]), None)
    return best


def pools(now: datetime | None = None, state_dir: Path | None = None) -> list[dict]:
    current = now or N.now_utc()
    return [_resolve(pid, state_dir, current) for pid in POOL_ORDER]


def to_feed_pools(pool_list: list[dict]) -> dict:
    """Backward-compatible `quota.pools` for the private feed: old keys kept, `windows` added."""
    out = {}
    for p in pool_list:
        entry = {"status": p["status"], "source": p["source"]["method"], "observed_at": p["observed_at"],
                 "note": p["reason"] or ("Collected from a supported source" if p["status"] == "VERIFIED"
                                         else "Manually entered; not a live provider reading" if p["status"] == "MANUAL"
                                         else "No sourced, timestamped snapshot available"),
                 "windows": p["windows"]}
        for w in p["windows"]:
            if w["type"] == "session":
                entry["five_hour_used_pct"] = w["used_pct"]
            elif w["type"] == "weekly":
                entry["weekly_used_pct"] = w["used_pct"]
        out[p["id"]] = entry
    return out


def t3_ui_source() -> dict:
    return dict(T3_UI_SOURCE)
