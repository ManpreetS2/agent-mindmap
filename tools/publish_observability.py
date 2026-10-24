"""Publish a T3 read-only snapshot atomically to a dedicated *private* GitHub repository.

Run locally with the user's standard gh authentication. This script never uses Agent
Control tokens, never writes into the public dashboard repo, and does not run an agent.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from tools.export_observability import ROOT, make_feed

DESTINATION = "ManpreetS2/agent-observability-private"
HEARTBEAT_SEC = 30 * 60


def secure_env() -> dict[str, str]:
    """Do not let a worker's overriding gh token/config silently select bot credentials."""
    env = dict(os.environ)
    for key in ("GH_TOKEN", "GITHUB_TOKEN", "GH_CONFIG_DIR", "GH_ENTERPRISE_TOKEN"):
        env.pop(key, None)
    env["GIT_TERMINAL_PROMPT"] = "0"
    return env


def cmd(args: list[str], *, env: dict[str, str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        args, cwd=cwd, env=env, capture_output=True, text=True, check=False, timeout=90,
    )
    if result.returncode != 0:
        # Commands or upstream output may include sensitive metadata; never echo either.
        raise RuntimeError("GitHub operation failed; confirm standard gh login, destination access and network")
    return result.stdout.strip()


def verified_destination(repo: str, info: dict) -> bool:
    """Dedicated private feed only; publishing to the public mind-map always fails."""
    return (
        repo == DESTINATION
        and info.get("nameWithOwner") == DESTINATION
        and info.get("visibility") == "PRIVATE"
    )


def unchanged_except_export_time(previous: dict, current: dict) -> bool:
    a, b = dict(previous), dict(current)
    a.pop("exported_at", None)
    b.pop("exported_at", None)
    return a == b


def should_publish(previous: dict | None, current: dict, *, now: datetime) -> bool:
    if previous is None or not unchanged_except_export_time(previous, current):
        return True
    old = previous.get("exported_at")
    if not isinstance(old, str):
        return True
    try:
        prev = datetime.fromisoformat(old)
        if prev.utcoffset() is None:
            return True
        return (now - prev).total_seconds() >= HEARTBEAT_SEC
    except ValueError:
        return True


def publish(input_path: Path, repo: str, *, for_real: bool) -> str:
    # A missing/unavailable collector must fail, never substitute synthetic demo.
    if input_path.is_symlink() or not input_path.is_file():
        raise ValueError("Expected a regular local T3 activity snapshot file")
    source = json.loads(input_path.read_text(encoding="utf-8"))
    now = datetime.now(UTC)
    feed, summary = make_feed(source, now=now)
    if feed["source"] != "T3 read-only metadata" or not feed["sessions"]:
        raise ValueError("No real T3 session metadata available; refusing to publish an empty feed")

    if not for_real:
        return f"LOCAL CHECK OK: {len(feed['sessions'])} sessions; {feed['freshness']}; nothing uploaded"

    env = secure_env()
    info = json.loads(cmd(
        ["gh", "repo", "view", repo, "--json", "nameWithOwner,visibility"], env=env,
    ))
    if not verified_destination(repo, info):
        raise ValueError("Refusing to publish: destination is not the approved PRIVATE repository")

    # Clone into a fresh 0700 temp directory. Atomic git commit holds both files together.
    original_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix="agent-observability-") as tmp:
            checkout = Path(tmp) / "feed"
            cmd(["gh", "repo", "clone", repo, str(checkout), "--", "--depth", "1"], env=env)
            previous_path = checkout / "latest.json"
            previous = None
            if previous_path.exists():
                if previous_path.is_symlink():
                    raise ValueError("Refusing a symlinked remote feed file")
                try:
                    previous = json.loads(previous_path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeError):
                    raise ValueError("Remote feed is malformed: investigate before writing") from None
            if not should_publish(previous, feed, now=now):
                return "NO CHANGE: previous data is equivalent, heartbeat not due; nothing pushed"
            # Only the two allowlisted root-level output files are touched.
            for name, content in (
                ("latest.json", json.dumps(feed, indent=2, ensure_ascii=False) + "\n"),
                ("summary.md", summary),
            ):
                target = checkout / name
                if target.is_symlink():
                    raise ValueError("Refusing to overwrite a symlink")
                target.write_text(content, encoding="utf-8")
                target.chmod(0o600)
            cmd(["git", "add", "--", "latest.json", "summary.md"], cwd=checkout, env=env)
            cmd([
                "git", "-c", "user.name=Agent Mindmap",
                "-c", "user.email=agent-mindmap@users.noreply.github.com",
                "-c", "core.hooksPath=/dev/null", "commit", "-m",
                "chore: update private read-only T3 activity snapshot",
            ], cwd=checkout, env=env)
            cmd(["git", "-c", "core.hooksPath=/dev/null", "push", "origin", "HEAD"],
                cwd=checkout, env=env)
        return f"PUBLISHED to private feed: {len(feed['sessions'])} sessions; freshness={feed['freshness']}"
    finally:
        os.umask(original_umask)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True,
                        help="Absolute local activity.json produced by the read-only T3 daemon")
    parser.add_argument("--repo", default=DESTINATION,
                        help="Dedicated private repo; any other destination is refused")
    parser.add_argument("--for-real", action="store_true",
                        help="Explicitly allow GitHub writes (default is local validation only)")
    args = parser.parse_args()
    if args.repo != DESTINATION:
        parser.error("Only ManpreetS2/agent-observability-private is allowed")
    if ROOT == args.input.resolve() or ROOT in args.input.resolve().parents:
        parser.error("Refusing an input file under the PUBLIC dashboard repository")
    try:
        print(publish(args.input, args.repo, for_real=args.for_real))
        return 0
    except (ValueError, OSError, RuntimeError, json.JSONDecodeError) as exc:
        # make_feed's exceptions are intentional generic validation errors.
        print(f"Private publisher stopped: {str(exc)[:180]}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
