"""
Attribute GitHub activity to bots via ~Bot signatures in body text.

GitHub login is always the shared owner account, so authorship is ignored.
MM-003: method is `signature` when a config alias matches, else `unknown`.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_bots(path: Path | None = None) -> list[dict[str, Any]]:
    cfg = path or (_repo_root() / "config" / "bots.json")
    with cfg.open(encoding="utf-8") as f:
        return list(json.load(f)["bots"])


def _signature_patterns(bots: list[dict[str, Any]]) -> list[tuple[re.Pattern[str], str]]:
    """Longest signature/alias first → bot id."""
    pairs: list[tuple[str, str]] = []
    for bot in bots:
        if bot.get("id") == "manpreet":
            continue
        for alias in bot.get("aliases", []):
            a = alias.strip()
            if not a:
                continue
            # Prefer explicit ~ signatures and emoji markers from config.
            if a.startswith("~") or (len(a) <= 4 and not a.isascii()):
                pairs.append((a, bot["id"]))
            elif a == bot.get("display_name"):
                pairs.append((f"~{a}", bot["id"]))
    # Deduplicate by pattern text, keep first (we'll sort by length).
    seen: set[str] = set()
    uniq: list[tuple[str, str]] = []
    for text, bot_id in pairs:
        if text in seen:
            continue
        seen.add(text)
        uniq.append((text, bot_id))
    uniq.sort(key=lambda p: len(p[0]), reverse=True)
    out: list[tuple[re.Pattern[str], str]] = []
    for text, bot_id in uniq:
        out.append((re.compile(re.escape(text)), bot_id))
    return out


def attribute_from_body(
    body: str | None,
    bots: list[dict[str, Any]] | None = None,
) -> tuple[str | None, str]:
    """
    Return (bot_id | None, attribution method).

    method is always `signature` or `unknown` for GitHub bodies in MM-003.
    """
    if not body:
        return None, "unknown"
    bot_list = bots if bots is not None else load_bots()
    for pattern, bot_id in _signature_patterns(bot_list):
        if pattern.search(body):
            return bot_id, "signature"
    return None, "unknown"


def owner_to_bot_id(owner: str, bots: list[dict[str, Any]] | None = None) -> str | None:
    """Map ledger owner cell text to a single bot id (no multi-owner cells)."""
    key = owner.strip().lower()
    bot_list = bots if bots is not None else load_bots()
    for bot in bot_list:
        names = {
            bot["display_name"].lower(),
            bot["id"].lower(),
            *(a.lstrip("~").lower() for a in bot.get("aliases", [])),
        }
        if key in names or any(
            key.startswith(n + ",") or key.startswith(n + " ") for n in names
        ):
            return str(bot["id"])
    return None


def map_github_login(
    login: str | None,
    bots: list[dict[str, Any]] | None = None,
) -> str | None:
    """
    Map a GitHub login to a bot id via the owner/attribution roster.

    The shared GitHub account is the owner bot (`manpreet`); aliases and the
    login `ManpreetS2` resolve there. Other logins are unmatched.
    """
    if not login:
        return None
    key = login.strip().lower()
    if not key:
        return None
    bot_list = bots if bots is not None else load_bots()
    # Common owner account login used by all bots.
    if key in {"manpreets2", "manpreet"}:
        return "manpreet"
    for bot in bot_list:
        names = {
            str(bot.get("id", "")).lower(),
            str(bot.get("display_name", "")).lower(),
            *(str(a).lstrip("~").lower() for a in bot.get("aliases", [])),
        }
        if key in names:
            return str(bot["id"])
    return None


# Longer (hyphen-numeric suffix) alternatives come first. A trailing word
# boundary used to succeed on the hyphen and return MM-020 for MM-020-1a.
_TASK_ID_BODY = (
    r"[A-Z]{2,}-[0-9]{3}[A-Za-z0-9]*-[0-9]+"
    r"|[A-Z]{2,}-[A-Z]{2}[0-9]{3}-[0-9]+"
    r"|[A-Z]{2,}-[0-9]{3}[A-Za-z0-9]*(?!-[0-9])"
    r"|[A-Z]{2,}-[A-Z]{2}[0-9]{3}(?!-[0-9])"
)
TASK_ID_RE = re.compile(
    rf"(?<![A-Za-z0-9])({_TASK_ID_BODY})(?![A-Za-z0-9])"
)


def extract_task_id(*texts: str | None) -> str | None:
    for text in texts:
        if not text:
            continue
        m = TASK_ID_RE.search(text)
        if m:
            return m.group(1)
    return None


# QA-MM004-2: signed review/comment verdicts include these tokens.
VERDICT_RE = re.compile(
    r"\b(PASS|FAIL|CHANGES|CONDITIONAL|BLOCKED|INCONCLUSIVE)\b",
    re.IGNORECASE,
)
VERDICT_TOKENS = frozenset(
    {"PASS", "FAIL", "CHANGES", "CONDITIONAL", "BLOCKED", "INCONCLUSIVE"}
)


def extract_verdict(body: str | None) -> str | None:
    if not body:
        return None
    m = VERDICT_RE.search(body)
    return m.group(1).upper() if m else None
