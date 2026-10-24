"""Claude Code status line tap. Keeps ONLY rate_limits.{five_hour,seven_day}.{used_percentage,resets_at}."""
from __future__ import annotations

import json
import os
import shlex
import sys
from datetime import datetime
from pathlib import Path

from .. import normalize as N
from .. import store
from ..models import SESSION_MINUTES, WEEKLY_MINUTES

CLAUDE_ALIASES = ("claude-1", "claude-2")
METHOD_FMT = "Claude Code status line rate_limits ({alias})"
_SLOTS = (("five_hour", "session", "5-hour", SESSION_MINUTES), ("seven_day", "weekly", "7-day", WEEKLY_MINUTES))
MAX_STDIN = 1 << 20


def extract(payload, alias: str, now: datetime) -> dict | None:
    """Status-line JSON -> reading, or None when no valid window is present. Everything else is discarded."""
    limits = payload.get("rate_limits") if isinstance(payload, dict) else None
    if not isinstance(limits, dict):
        return None
    windows = []
    for key, wtype, label, mins in _SLOTS:
        raw = limits.get(key)
        if not isinstance(raw, dict):
            continue
        used = N.pct(raw.get("used_percentage"))
        resets = N.epoch_to_dt(raw.get("resets_at"))
        invalid_reset = raw.get("resets_at") is not None and resets is None  # supplied but malformed
        if used is None or invalid_reset or (resets is not None and resets <= now):
            continue  # malformed or already rolled over: absent, never guessed
        windows.append(N.make_window(wtype, label, mins, used, resets))
    if not windows:
        return None
    return N.make_reading(alias, "claude-statusline", METHOD_FMT.format(alias=alias), now, "ok", windows=windows)


def format_status(reading: dict | None) -> str:
    if not reading:
        return "quota n/a"
    parts = []
    for w in reading["windows"]:
        tag = "5h" if w["type"] == "session" else "7d"
        parts.append(f"{tag} {w['used_pct']:.0f}%")
    return " · ".join(parts)


def _same_dir(a: str, b: str) -> bool:
    return os.path.realpath(os.path.expanduser(a)) == os.path.realpath(os.path.expanduser(b))


def run(alias: str, stdin_text: str, *, state_dir: Path | None = None, expect_config_dir: str | None = None,
        env: dict | None = None, now: datetime | None = None) -> str:
    """Never raises: a status line must not crash. Returns the string to print."""
    try:
        if alias not in CLAUDE_ALIASES:
            return "quota n/a"
        env = os.environ if env is None else env
        if expect_config_dir is not None:
            actual = env.get("CLAUDE_CONFIG_DIR") or "~/.claude"
            if not _same_dir(actual, expect_config_dir):
                return "quota n/a"  # cross-account guard: wrong config dir, write nothing
        payload = json.loads(stdin_text[:MAX_STDIN]) if stdin_text.strip() else {}
        reading = extract(payload, alias, now or N.now_utc())
        if reading:
            store.write(alias, reading, "live", state_dir)
        return format_status(reading)
    except Exception:  # noqa: BLE001 - the status line must never fail
        return "quota n/a"


def command_for(alias: str, config_dir: str, repo_root: Path | None = None, python: str | None = None) -> str:
    root = repo_root or Path(__file__).resolve().parents[3]
    return (f"cd {shlex.quote(str(root))} && {shlex.quote(python or sys.executable)} -m tools.quota "
            f"claude-statusline --alias {alias} --expect-config-dir {shlex.quote(config_dir)}")


def snippet(alias: str, config_dir: str, **kw) -> dict:
    return {"statusLine": {"type": "command", "command": command_for(alias, config_dir, **kw)}}


def install(alias: str, config_dir: str, *, apply: bool, approved: bool, now: datetime | None = None, **kw) -> tuple[int, str]:
    """Merge the snippet into <config_dir>/settings.json. Dry-run unless apply AND approved."""
    cdir = Path(config_dir).expanduser()
    target = cdir / "settings.json"
    want = snippet(alias, str(cdir), **kw)["statusLine"]
    if not cdir.is_dir():
        return 2, f"config dir {cdir} does not exist; nothing to do"
    settings: dict = {}
    if target.exists():
        try:
            settings = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return 2, f"{target} is not valid JSON; refusing to touch it"
        if not isinstance(settings, dict):
            return 2, f"{target} is not a JSON object; refusing to touch it"
    existing = settings.get("statusLine")
    if existing == want:
        return 0, f"{target} already has the quota status line; nothing to do"
    if existing is not None:
        return 2, (f"{target} already defines a statusLine; refusing to overwrite it. Chain manually: have your "
                   f"existing command's script also run:\n  {want['command']}  < the same stdin JSON")
    merged = {**settings, "statusLine": want}
    text = json.dumps(merged, indent=2) + "\n"
    if not (apply and approved):
        hint = "" if not apply else " (--apply needs --yes-i-approved-settings-change too)"
        return 0, f"DRY RUN{hint}: would add to {target}:\n{json.dumps({'statusLine': want}, indent=2)}"
    stamp = (now or N.now_utc()).strftime("%Y%m%dT%H%M%SZ")
    backup = None
    if target.exists():
        backup = target.with_name(f"settings.json.bak-{stamp}")
        backup.write_bytes(target.read_bytes())
        os.chmod(backup, 0o600)
    tmp = target.with_name(f".settings.json.{os.getpid()}.tmp")
    mode = target.stat().st_mode & 0o777 if target.exists() else 0o600
    tmp.write_text(text, encoding="utf-8")
    os.chmod(tmp, mode)
    os.replace(tmp, target)
    return 0, f"updated {target}" + (f" (backup {backup.name})" if backup else "")

