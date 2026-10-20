#!/usr/bin/env python3
"""
Shared secret / sensitive-pattern scanner (DEV 2 / MM-020c).

Single owner of the denylist used by ledger_mirror (SEC-MM010-1) and
events_mirror (QA-MM020b-2 / SEC-MM020c-*). DEV 1's event_emit should import
from here rather than keeping a parallel regex.

Public API
----------
looks_like_secret(text: str) -> bool
    True if *any* denylist pattern matches. Safe for flush gating.
    Never logs or returns matched secret text.

find_secrets(text: str) -> list[str]
    Ordered unique **kind labels** for matches (not the matched substrings).
    Kinds: github_token | github_pat | bearer | authorization | sk | akia |
    jwt | private_key | email.
    Callers must not treat these labels as secret material; they are enum-like
    ids for tests and diagnostics only.

Patterns (summary)
------------------
- SEC-MM010-1: ghp_/gho_/ghu_/ghs_/ghr_, github_pat_, Bearer …, Authorization: …
- QA-MM020b-2 / SEC-MM020c-1: case-sensitive ``\\bsk-[A-Za-z0-9_-]{20,}``
- AKIA…, JWT (eyJ…), BEGIN PRIVATE KEY blocks, emails

Stdlib only. No network. Matched secret *text* is never returned.
"""

from __future__ import annotations

import re
from typing import Iterable

# (kind, pattern, flags) — sk- is intentionally case-sensitive (SEC-MM020c-1).
_RULES: tuple[tuple[str, str, int], ...] = (
    ("github_token", r"\b(?:ghp_|gho_|ghu_|ghs_|ghr_)[A-Za-z0-9_]+", re.IGNORECASE),
    ("github_pat", r"\bgithub_pat_[A-Za-z0-9_]+", re.IGNORECASE),
    ("bearer", r"Bearer\s+[A-Za-z0-9._\-]+", re.IGNORECASE),
    ("authorization", r"Authorization:\s*\S+", re.IGNORECASE),
    # SEC-MM020c-1: case-sensitive, word-boundary, ≥20 chars after sk-
    ("sk", r"\bsk-[A-Za-z0-9_-]{20,}", 0),
    ("akia", r"\bAKIA[0-9A-Z]{16}\b", 0),
    ("jwt", r"\beyJ[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+){2}", 0),
    ("private_key", r"-----BEGIN(?:\s+\w+)?\s+PRIVATE KEY-----", re.IGNORECASE),
    (
        "email",
        r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b",
        re.IGNORECASE,
    ),
)

_COMPILED: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (kind, re.compile(pat, flags)) for kind, pat, flags in _RULES
)


def find_secrets(text: str) -> list[str]:
    """
    Return unique kind labels for denylist hits in ``text`` (stable rule order).

    Does **not** return matched secret substrings.
    """
    if not text:
        return []
    found: list[str] = []
    seen: set[str] = set()
    for kind, cre in _COMPILED:
        if cre.search(text) and kind not in seen:
            seen.add(kind)
            found.append(kind)
    return found


def looks_like_secret(text: str) -> bool:
    """True if any denylist pattern matches ``text``."""
    if not text:
        return False
    for _, cre in _COMPILED:
        if cre.search(text):
            return True
    return False


def secret_kinds() -> tuple[str, ...]:
    """Stable tuple of all kind labels (for tests / docs)."""
    return tuple(kind for kind, _, _ in _RULES)


# Back-compat alias used by older call sites / docs.
def iter_secret_kinds() -> Iterable[str]:
    return secret_kinds()
