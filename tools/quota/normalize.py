"""Validation and normalisation of raw provider values into schema-shaped quota data."""
from __future__ import annotations

import math
import re
from datetime import UTC, datetime

from .models import (LIVE_TTL, MANUAL_TTL, FUTURE_SKEW, POOL_META, QuotaError,
                     SESSION_MINUTES, WEEKLY_MINUTES, WINDOW_TYPES)

_MAX_EPOCH = 4102444800  # 2100-01-01


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def parse_ts(value) -> datetime | None:
    """ISO-8601 with an explicit offset -> aware UTC datetime. Anything else -> None."""
    if not isinstance(value, str) or not 10 <= len(value) <= 40:
        return None
    text = value.strip()
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(UTC)


def epoch_to_dt(value) -> datetime | None:
    """Epoch SECONDS (int/float) -> aware UTC datetime; bools, NaN, inf, non-positive, absurd -> None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value <= 0 or value > _MAX_EPOCH:
        return None
    return datetime.fromtimestamp(value, UTC)


def pct(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or not 0 <= value <= 100:
        return None
    return float(value)


def minutes(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    if value < 1 or value != int(value) or value > 10_000_000:
        return None
    return int(value)


def classify_window(window_minutes: int | None, fallback_label: str = "other") -> tuple[str, str]:
    if window_minutes == SESSION_MINUTES:
        return "session", "5-hour"
    if window_minutes == WEEKLY_MINUTES:
        return "weekly", "7-day"
    if window_minutes and 40320 <= window_minutes <= 44640:
        return "monthly", "monthly"
    if window_minutes:
        return "other", f"{window_minutes}-min"[:40]
    return "other", fallback_label[:40]


def make_window(wtype: str, label: str, window_minutes: int | None, used_pct, resets_at: datetime | None,
                observed_at: datetime | None = None) -> dict:
    used = pct(used_pct)
    if used is None:
        raise QuotaError("used percentage must be a finite number in 0..100")
    if wtype not in WINDOW_TYPES:
        raise QuotaError("unknown window type")
    out = {"type": wtype, "label": label[:40], "window_minutes": window_minutes, "used_pct": used,
           "resets_at": iso(resets_at) if resets_at else None}
    if observed_at:
        out["observed_at"] = iso(observed_at)
    return out


def check_windows(windows) -> list[dict]:
    """Reject duplicates / malformed windows in a stored reading."""
    if not isinstance(windows, list) or len(windows) > 6:
        raise QuotaError("windows must be a list of at most 6")
    seen, clean = set(), []
    for w in windows:
        if not isinstance(w, dict):
            raise QuotaError("window must be an object")
        wtype = w.get("type")
        key = (wtype, w.get("window_minutes") if wtype == "other" else None)
        if key in seen:
            raise QuotaError(f"duplicate {wtype} window")
        seen.add(key)
        resets = parse_ts(w["resets_at"]) if w.get("resets_at") is not None else None
        if w.get("resets_at") is not None and resets is None:
            raise QuotaError("malformed resets_at")
        obs = parse_ts(w["observed_at"]) if w.get("observed_at") is not None else None
        if w.get("observed_at") is not None and obs is None:
            raise QuotaError("malformed window observed_at")
        wm = w.get("window_minutes")
        if wm is not None and minutes(wm) is None:
            raise QuotaError("bad window_minutes")
        clean.append(make_window(wtype, str(w.get("label") or wtype), wm, w.get("used_pct"), resets, obs))
    return clean


def public_window(w: dict) -> dict:
    used = w["used_pct"]
    return {"type": w["type"], "label": w["label"], "window_minutes": w["window_minutes"],
            "used_pct": used, "remaining_pct": round(100.0 - used, 4), "resets_at": w["resets_at"]}


_PLAN_RE = re.compile(r"[^a-z0-9 _.+-]")


def clean_plan(value) -> str | None:
    if not isinstance(value, str):
        return None
    text = _PLAN_RE.sub("", value.strip().lower())[:40].strip()
    return text or None


def clean_text(value, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join("".join(c if c.isprintable() else " " for c in value).split())[:limit]


def placeholder(pool_id: str, status: str = "UNKNOWN", reason: str | None = "No reading yet") -> dict:
    m = POOL_META[pool_id]
    return {"id": pool_id, "label": m["label"], "provider": m["provider"], "account_alias": pool_id,
            "plan": None, "status": status, "windows": [],
            "source": {"kind": m["kind"], "method": m["method"][:120], "supported_programmatically": m["programmatic"]},
            "observed_at": None, "expires_at": None, "reason": reason}


def evaluate(pool_id: str, reading: dict | None, now: datetime) -> dict:
    """Stored reading -> pool dict at time `now` (staleness computed here, never trusted from disk)."""
    base = placeholder(pool_id)
    if not reading:
        return base
    try:
        kind = reading["kind"]
        observed = parse_ts(reading.get("observed_at"))
        if observed is None:
            raise QuotaError("malformed observed_at")
        if observed - now > FUTURE_SKEW:
            return {**base, "reason": "Reading timestamp is in the future; ignored"}
        base["plan"] = clean_plan(reading.get("plan"))
        base["source"] = {"kind": kind, "method": clean_text(reading.get("method"), 120) or kind,
                          "supported_programmatically": kind != "manual" and POOL_META[pool_id]["programmatic"]}
        base["observed_at"] = iso(observed)
        outcome = reading.get("outcome")
        reason = clean_text(reading.get("reason"), 200) or None
        if outcome == "error":
            return {**base, "status": "ERROR", "reason": reason or "Collection failed"}
        if outcome == "unsupported":
            base["source"]["supported_programmatically"] = False
            return {**base, "status": "UNSUPPORTED", "reason": reason or "No supported programmatic source"}
        if outcome != "ok":
            raise QuotaError("unknown outcome")
        all_windows = check_windows(reading.get("windows", []))
        windows = [w for w in all_windows if not (w["resets_at"] and parse_ts(w["resets_at"]) <= now)]
        if not windows:
            if all_windows:  # every window rolled over: nothing current, nothing to show
                return {**base, "status": "STALE", "expires_at": iso(min(parse_ts(w["resets_at"]) for w in all_windows)),
                        "reason": "Every window in the last reading has reset; take a new reading"}
            return {**base, "reason": reason or "Reading has no current windows"}
        ttl = MANUAL_TTL if kind == "manual" else LIVE_TTL
        oldest = min((parse_ts(w["observed_at"]) for w in windows if w.get("observed_at")), default=observed)
        oldest = min(oldest, observed)
        expiry = oldest + ttl
        for w in windows:
            if w["resets_at"]:
                expiry = min(expiry, parse_ts(w["resets_at"]))
        base["windows"] = [public_window(w) for w in windows]
        base["expires_at"] = iso(expiry)
        if now < expiry:
            base["status"] = "MANUAL" if kind == "manual" else "VERIFIED"
            base["reason"] = reason
        else:
            base["status"] = "STALE"
            base["reason"] = "Reading expired; values are history, not current state"
        return base
    except (QuotaError, KeyError, TypeError, ValueError, AttributeError) as exc:
        return {**placeholder(pool_id), "reason": f"Stored reading rejected: {clean_text(str(exc), 100)}"}



def make_reading(alias: str, kind: str, method: str, observed_at: datetime, outcome: str = "ok", *,
                 plan: str | None = None, reason: str | None = None, windows: list[dict] | None = None,
                 ordinary_usage_allowed: bool | None = None) -> dict:
    """Build a storable reading (already validated: duplicates and bad values raise QuotaError)."""
    if alias not in POOL_META:
        raise QuotaError("unknown pool alias")
    reading = {"version": 1, "alias": alias, "kind": kind, "method": clean_text(method, 120),
               "observed_at": iso(observed_at), "plan": clean_plan(plan), "outcome": outcome,
               "reason": clean_text(reason, 200) or None, "windows": check_windows(windows or [])}
    if ordinary_usage_allowed is not None:
        reading["ordinary_usage_allowed"] = bool(ordinary_usage_allowed)
    return reading
