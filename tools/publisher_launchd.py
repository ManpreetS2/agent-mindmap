"""Opt-in macOS launchd job that runs the private publisher every few minutes. Nothing here runs a model.

  python -m tools.publisher_launchd render    print the plist (changes nothing)
  python -m tools.publisher_launchd install   write the plist to ~/Library/LaunchAgents (does NOT load it)
  python -m tools.publisher_launchd enable    load it: publishing starts (needs --yes-i-approved-live-publishing)
  python -m tools.publisher_launchd disable   unload it
  python -m tools.publisher_launchd status    loaded?, last success, last error (non-sensitive)

The publisher itself rate-limits (>= 3 min between uploads), skips unchanged snapshots, backs off after
failures and holds a lock, so the 240 s interval, sleep/wake catch-up and overlapping runs are all safe.
"""
from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from tools.export_observability import ROOT
from tools.publish_observability import STATE_DIR

LABEL = "com.manpreets2.agent-mindmap-publisher"
PLIST = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
INTERVAL_SEC = 240
COLLECTOR_URL = "http://127.0.0.1:8799/activity.json"


SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
HOMEBREW_DIRS = ("/opt/homebrew/bin", "/usr/local/bin")
MIN_PYTHON = (3, 12)


def find_tool(name: str, env: dict | None = None, which: Callable = shutil.which) -> str | None:
    env = os.environ if env is None else env
    return which(name, path=env.get("PATH"))


def derive_path(tools: tuple[str, ...] = ("gh", "git", "node", "npm"), env: dict | None = None,
                which: Callable = shutil.which, extra: tuple[str, ...] = ()) -> str:
    """PATH for a LaunchAgent, built from where the tools it needs were actually found (not guessed), then the
    system directories. Paths may contain spaces."""
    dirs: list[str] = []
    for name in tools:
        found = find_tool(name, env, which)
        if found:
            dirs.append(str(Path(found).parent))
    ordered: list[str] = []
    for d in (*extra, *dirs, *SYSTEM_PATH):
        if d and d not in ordered:
            ordered.append(d)
    return ":".join(ordered)


def python_version(python: str, run: Callable | None = None) -> tuple[int, int] | None:
    runner = run or (lambda a: subprocess.run(a, capture_output=True, text=True, check=False, timeout=20))
    try:
        r = runner([python, "-c", "import sys;print(sys.version_info[0],sys.version_info[1])"])
        major, minor = r.stdout.split()[:2]
        return (int(major), int(minor)) if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None


def discover_python(env: dict | None = None, which: Callable = shutil.which, run: Callable | None = None,
                    home: Path | None = None) -> str | None:
    """First interpreter >= 3.12: env AGENT_MINDMAP_PYTHON, this interpreter, PATH, Homebrew/python.org/user locations."""
    env = os.environ if env is None else env
    home = home or Path.home()
    candidates: list[str] = []
    if env.get("AGENT_MINDMAP_PYTHON"):
        candidates.append(env["AGENT_MINDMAP_PYTHON"])
    candidates.append(sys.executable)
    for name in ("python3.14", "python3.13", "python3.12", "python3"):
        found = find_tool(name, env, which)
        if found:
            candidates.append(found)
    for d in (*HOMEBREW_DIRS, str(home / ".local" / "bin")):
        candidates += [str(Path(d) / n) for n in ("python3.14", "python3.13", "python3.12", "python3")]
    seen: set[str] = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        if (Path(c).exists() or run is not None) and (python_version(c, run) or (0, 0)) >= MIN_PYTHON:
            return c
    return None


def plist_data(python: str = sys.executable, repo: Path = ROOT, state_dir: Path = STATE_DIR,
               path_env: str | None = None) -> dict:
    return {
        "Label": LABEL,
        "ProgramArguments": [python, "-m", "tools.publish_observability", "--collector-url", COLLECTOR_URL,
                             "--for-real"],
        "WorkingDirectory": str(repo),
        "StartInterval": INTERVAL_SEC,
        "RunAtLoad": True,
        "ProcessType": "Background",
        "LowPriorityIO": True,
        "Nice": 10,
        "ThrottleInterval": 60,
        "EnvironmentVariables": {
            # launchd's default PATH would not find gh/git; derived from where they really are. No tokens here.
            "PATH": path_env or derive_path(),
            "PYTHONPATH": str(repo),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        "StandardOutPath": str(state_dir / "publisher.log"),
        "StandardErrorPath": str(state_dir / "publisher.log"),
    }


def render() -> bytes:
    return plistlib.dumps(plist_data())


def install() -> str:
    STATE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_bytes(render())
    PLIST.chmod(0o644)
    return f"wrote {PLIST} (not loaded; run 'enable' only after approval)"


def launchctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["launchctl", *args], capture_output=True, text=True, check=False)


def status() -> str:
    state = {}
    try:
        state = json.loads((STATE_DIR / "state.json").read_text())
    except (OSError, ValueError):
        pass
    loaded = launchctl("print", f"gui/{os.getuid()}/{LABEL}").returncode == 0
    return json.dumps({
        "plist_installed": PLIST.exists(), "loaded": loaded,
        "last_success_at": state.get("last_success_at"), "last_error": state.get("last_error"),
        "consecutive_failures": state.get("consecutive_failures", 0),
    }, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["render", "install", "enable", "disable", "status"])
    parser.add_argument("--yes-i-approved-live-publishing", action="store_true")
    args = parser.parse_args()
    if args.action == "render":
        sys.stdout.write(render().decode())
    elif args.action == "install":
        print(install())
    elif args.action == "enable":
        if not args.yes_i_approved_live_publishing:
            parser.error("refusing to start live publishing without --yes-i-approved-live-publishing")
        if not PLIST.exists():
            parser.error("run 'install' first")
        r = launchctl("bootstrap", f"gui/{os.getuid()}", str(PLIST))
        print("loaded" if r.returncode == 0 else f"launchctl bootstrap failed ({r.returncode}); already loaded?")
    elif args.action == "disable":
        r = launchctl("bootout", f"gui/{os.getuid()}/{LABEL}")
        print("unloaded" if r.returncode == 0 else "was not loaded")
    else:
        print(status())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
