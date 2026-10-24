"""python -m tools.quota collect|show|manual|claude-statusline|claude-statusline-snippet|install-claude-statusline"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import api, normalize as N, store
from .collectors import claude_statusline, codex_app_server, cursor_cli, manual
from .models import POOL_ORDER, QuotaError


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="python -m tools.quota")
    p.add_argument("--state-dir", type=Path, default=None)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("collect", help="run the Codex and Cursor collectors (no model calls)")
    s = sub.add_parser("show")
    s.add_argument("--json", action="store_true")
    m = sub.add_parser("manual")
    msub = m.add_subparsers(dest="action", required=True)
    ms = msub.add_parser("set")
    ms.add_argument("--pool", required=True, choices=POOL_ORDER)
    ms.add_argument("--window", required=True, choices=("session", "weekly", "monthly", "other"))
    ms.add_argument("--used-pct", required=True)
    ms.add_argument("--resets-at")
    ms.add_argument("--source", required=True)
    ms.add_argument("--observed-at", required=True)
    ms.add_argument("--plan")
    ms.add_argument("--window-minutes", type=int)
    mc = msub.add_parser("clear")
    mc.add_argument("--pool", required=True, choices=POOL_ORDER)
    c = sub.add_parser("claude-statusline")
    c.add_argument("--alias", required=True, choices=claude_statusline.CLAUDE_ALIASES)
    c.add_argument("--expect-config-dir")
    for name in ("claude-statusline-snippet", "install-claude-statusline"):
        x = sub.add_parser(name)
        x.add_argument("--alias", required=True, choices=claude_statusline.CLAUDE_ALIASES)
        x.add_argument("--config-dir", required=True)
        if name.startswith("install"):
            x.add_argument("--apply", action="store_true")
            x.add_argument("--yes-i-approved-settings-change", action="store_true")
    return p


def _collect(state_dir) -> int:
    for pid, fn in (("codex", codex_app_server.collect), ("cursor-premium", cursor_cli.collect)):
        reading = fn()
        store.write(pid, reading, "live", state_dir)
        print(f"{pid}: {reading['outcome']}" + (f" ({reading['reason']})" if reading.get("reason") else ""))
    return 0


def _show(state_dir, as_json: bool) -> int:
    pools = api.pools(state_dir=state_dir)
    if as_json:
        print(json.dumps(pools, indent=2))
        return 0
    for p in pools:
        wins = ", ".join(f"{w['label']} {w['used_pct']:g}% used (resets {w['resets_at'] or '?'})" for w in p["windows"])
        print(f"{p['id']:<15} {p['status']:<12} plan={p['plan'] or '-':<8} {wins or p['reason'] or ''}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    sd = args.state_dir
    try:
        if args.cmd == "claude-statusline":
            text = sys.stdin.read(claude_statusline.MAX_STDIN) if not sys.stdin.isatty() else ""
            print(claude_statusline.run(args.alias, text, state_dir=sd, expect_config_dir=args.expect_config_dir))
            return 0
        if args.cmd == "collect":
            return _collect(sd)
        if args.cmd == "show":
            return _show(sd, args.json)
        if args.cmd == "manual":
            if args.action == "clear":
                print("cleared" if manual.clear(args.pool, sd) else "nothing to clear")
                return 0
            manual.set_window(args.pool, args.window, args.used_pct, args.resets_at, args.source, args.observed_at,
                              plan=args.plan, window_minutes=args.window_minutes, state_dir=sd)
            print(f"stored manual {args.window} reading for {args.pool}")
            return 0
        if args.cmd == "claude-statusline-snippet":
            print(json.dumps(claude_statusline.snippet(args.alias, args.config_dir), indent=2))
            return 0
        if args.cmd == "install-claude-statusline":
            code, msg = claude_statusline.install(args.alias, args.config_dir, apply=args.apply,
                                                  approved=args.yes_i_approved_settings_change)
            print(msg)
            return code
    except QuotaError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 1
