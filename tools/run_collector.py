"""The persistent, read-only T3 collector entry point (run by launchd; never takes a port argument).

Fixed on purpose: loopback only, port 8799, the local T3 MCP URL, state under ~/.local/state. One instance at a
time (flock). If something already answers on the port as a collector it exits cleanly instead of fighting it;
if anything else holds the port it exits with a retryable error. Never touches 8882, Agent Control or T3 itself.
"""
from __future__ import annotations

import fcntl
import json
import os
import socket
import sys
import urllib.request
from pathlib import Path

PORT = 8799
T3_URL = "http://127.0.0.1:3773/mcp"
STATE = Path(os.environ.get("AGENT_MINDMAP_COLLECTOR_STATE") or Path.home() / ".local" / "state" / "agent-mindmap-collector")
EX_RETRY = 75           # EX_TEMPFAIL: launchd retries after ThrottleInterval
LOG_LIMIT = 5_000_000


def port_in_use(port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(1)
        return s.connect_ex(("127.0.0.1", port)) == 0


def is_collector(port: int) -> bool:
    """True only if the listener answers /healthz with this project's health document."""
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(f"http://127.0.0.1:{port}/healthz", timeout=3) as r:
            doc = json.loads(r.read(65536).decode())
        return isinstance(doc, dict) and "last_build" in doc and "errors" in doc
    except (OSError, ValueError):
        return False


def rotate_log(path: Path) -> None:
    try:
        if path.stat().st_size > LOG_LIMIT:
            path.replace(path.with_suffix(".log.1"))
    except OSError:
        pass


def lock(state: Path):
    state.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(state, 0o700)
    fd = os.open(state / "collector.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(fd)
        return None
    return fd


def collector_argv(state: Path, port: int = PORT) -> list[str]:
    return ["--source", "t3", "--t3-url", T3_URL, "--port", str(port),
            "--activity-out", str(state / "activity.json"), "--cache-dir", str(state / "cache")]


def run(state: Path = STATE, port: int = PORT) -> int:
    fd = lock(state)
    if fd is None:
        print("another collector instance holds the lock; exiting", file=sys.stderr)
        return 0
    if port_in_use(port):
        if is_collector(port):
            print(f"a collector already answers on {port}; exiting without starting a second", file=sys.stderr)
            return 0
        print(f"port {port} is held by something that is not a collector; will retry", file=sys.stderr)
        return EX_RETRY
    rotate_log(state / "collector.log")
    from ingest.live import main as live_main
    return live_main(collector_argv(state, port))


if __name__ == "__main__":
    raise SystemExit(run())
