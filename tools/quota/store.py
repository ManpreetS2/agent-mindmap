"""Per-alias reading files. One file per alias and channel; a reading carries its alias and is rejected on mismatch."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from .models import POOL_ORDER, QuotaError

ENV_DIR = "AGENT_MINDMAP_QUOTA_DIR"
CHANNELS = ("live", "manual")
ALLOWED_KEYS = {"version", "alias", "kind", "method", "observed_at", "plan", "outcome", "reason", "windows",
                "ordinary_usage_allowed"}
ALLOWED_WINDOW_KEYS = {"type", "label", "window_minutes", "used_pct", "resets_at", "observed_at"}
MAX_BYTES = 64 * 1024


def default_dir() -> Path:
    env = os.environ.get(ENV_DIR)
    return Path(env).expanduser() if env else Path.home() / ".local" / "state" / "agent-mindmap-quota"


def _path(state_dir: Path | None, alias: str, channel: str) -> Path:
    if alias not in POOL_ORDER:
        raise QuotaError("unknown pool alias")
    if channel not in CHANNELS:
        raise QuotaError("unknown channel")
    suffix = "" if channel == "live" else ".manual"
    return Path(state_dir or default_dir()) / f"{alias}{suffix}.json"


def sanitize(reading: dict) -> dict:
    """Keep only allowlisted keys; account ids, emails and tokens can never reach disk."""
    out = {k: v for k, v in reading.items() if k in ALLOWED_KEYS}
    out["windows"] = [{k: v for k, v in w.items() if k in ALLOWED_WINDOW_KEYS} for w in reading.get("windows", [])]
    out["version"] = 1
    return out


def write(alias: str, reading: dict, channel: str = "live", state_dir: Path | None = None) -> Path:
    if reading.get("alias") != alias:
        raise QuotaError(f"alias mismatch: reading is for {reading.get('alias')!r}, refusing to store under {alias!r}")
    path = _path(state_dir, alias, channel)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    data = json.dumps(sanitize(reading), sort_keys=True, allow_nan=False).encode()
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path


def read(alias: str, channel: str = "live", state_dir: Path | None = None) -> dict | None:
    """Return the stored reading, or None when absent/unreadable/for another alias."""
    path = _path(state_dir, alias, channel)
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return None
    if not isinstance(data, dict) or data.get("alias") != alias:
        return None
    return data


def clear(alias: str, channel: str, state_dir: Path | None = None) -> bool:
    try:
        _path(state_dir, alias, channel).unlink()
        return True
    except FileNotFoundError:
        return False
