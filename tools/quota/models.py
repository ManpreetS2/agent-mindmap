"""Pool metadata and constants. Output shape = schema/observability.schema.json `pool`."""
from __future__ import annotations

from datetime import timedelta

POOL_ORDER = ("claude-1", "claude-2", "cursor-premium", "devin-free", "codex")

POOL_META = {
    "claude-1": {"label": "Claude 1", "provider": "claude", "kind": "claude-statusline",
                 "method": "Claude Code status line rate_limits (awaiting first status line)", "programmatic": True},
    "claude-2": {"label": "Claude 2", "provider": "claude", "kind": "claude-statusline",
                 "method": "Claude Code status line rate_limits (awaiting first status line)", "programmatic": True},
    "cursor-premium": {"label": "Cursor Premium", "provider": "cursor", "kind": "cursor-cli",
                       "method": "cursor-agent about reports plan only", "programmatic": False},
    "devin-free": {"label": "Devin Free", "provider": "devin", "kind": "none",
                   "method": "no collector configured", "programmatic": False},
    "codex": {"label": "Codex", "provider": "codex", "kind": "codex-app-server",
              "method": "codex app-server account/rateLimits/read", "programmatic": True},
}

LIVE_TTL = timedelta(minutes=15)
MANUAL_TTL = timedelta(hours=24)
FUTURE_SKEW = timedelta(seconds=60)

SESSION_MINUTES = 300
WEEKLY_MINUTES = 10080
WINDOW_TYPES = ("session", "weekly", "monthly", "other")

# Source record for the T3 UI (documentation only; never a reading).
T3_UI_SOURCE = {
    "kind": "t3-ui",
    "method": "visible in T3 Usage->Limits UI, not exposed through the read-only MCP",
    "supported_programmatically": False,
    "status": "UNSUPPORTED",
}


class QuotaError(ValueError):
    """Malformed or unsafe quota data."""
