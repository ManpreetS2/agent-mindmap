"""MM-011: live daemon + localhost server."""

from __future__ import annotations

import json
import platform
import shutil
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path
from typing import Iterator

import pytest

from ingest.live import (
    BIND_HOST,
    LiveDaemon,
    create_http_server,
    refuse_public_bind,
    resolve_live_ledger,
)
from tests.test_github_poller import MockGh
from tests.test_ledger_fetch import LedgerMockGh, _contents_body

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "tests" / "fixtures" / "ledger-sample.md"
BOTS_PATH = ROOT / "config" / "bots.json"
PLIST = ROOT / "ops" / "com.manpreet.mindmap.plist"


@pytest.fixture
def bots() -> list[dict]:
    with BOTS_PATH.open(encoding="utf-8") as f:
        return json.load(f)["bots"]


@pytest.fixture
def live_env(tmp_path: Path, bots: list[dict]) -> dict:
    ledger = tmp_path / "task-ledger.md"
    shutil.copy(LEDGER, ledger)
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    activity = static / "activity.json"
    return {
        "ledger": ledger,
        "static": static,
        "activity": activity,
        "cache": tmp_path / "cache",
        "bots": bots,
    }


def _daemon(env: dict, **kwargs) -> LiveDaemon:
    return LiveDaemon(
        ledger_source="path",
        ledger_path=env["ledger"],
        activity_path=env["activity"],
        static_dir=env["static"],
        cache_dir=env["cache"],
        bots=env["bots"],
        github_runner=kwargs.pop("github_runner", MockGh()),
        **kwargs,
    )


def _wait_for_port(host: str, port: int, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise TimeoutError(f"server did not listen on {host}:{port}")


@pytest.fixture
def live_http(live_env: dict) -> Iterator[tuple[LiveDaemon, str, int]]:
    daemon = _daemon(live_env)
    daemon.run_poll_cycle()
    httpd = create_http_server(daemon, port=0)
    thread = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.2}, daemon=True)
    thread.start()
    host, port = httpd.server_address
    _wait_for_port(host, port)
    try:
        yield daemon, host, port
    finally:
        httpd.shutdown()
        thread.join(timeout=3)
        httpd.server_close()


def _http_get(url: str, headers: dict[str, str] | None = None) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


# AC1
def test_refuse_bind_all_interfaces() -> None:
    with pytest.raises(ValueError, match="refusing"):
        refuse_public_bind("0.0.0.0")
    with pytest.raises(ValueError, match="refusing"):
        refuse_public_bind("::")
    daemon = LiveDaemon(
        ledger_path=LEDGER,
        activity_path=Path("/tmp/activity.json"),
        static_dir=ROOT,
        cache_dir=ROOT,
        bots=[],
    )
    with pytest.raises(ValueError):
        create_http_server(daemon, host="0.0.0.0", port=0)


def test_server_binds_loopback_only(live_http: tuple[LiveDaemon, str, int]) -> None:
    _, host, port = live_http
    assert host == BIND_HOST
    status, _, _ = _http_get(f"http://{host}:{port}/healthz")
    assert status == HTTPStatus.OK


# AC2
def test_activity_json_etag_and_304(live_http: tuple[LiveDaemon, str, int]) -> None:
    _, host, port = live_http
    url = f"http://{host}:{port}/activity.json"
    status, headers, body = _http_get(url)
    assert status == HTTPStatus.OK
    etag = headers.get("ETag")
    assert etag
    assert headers.get("Cache-Control") == "no-cache"
    assert json.loads(body.decode())

    status2, headers2, body2 = _http_get(url, {"If-None-Match": etag})
    assert status2 == HTTPStatus.NOT_MODIFIED
    assert body2 == b""
    assert headers2.get("ETag") == etag


# AC3
def test_unchanged_ledger_skips_rewrite(live_env: dict) -> None:
    daemon = _daemon(live_env)
    daemon.run_poll_cycle()
    mtime = live_env["activity"].stat().st_mtime_ns
    assert daemon.poll_ledger_once() is False
    daemon.maybe_rebuild()
    assert live_env["activity"].stat().st_mtime_ns == mtime


def test_ledger_change_triggers_rebuild(live_env: dict) -> None:
    clock = {"t": 1_700_000_000.0}

    def fake_clock() -> float:
        return clock["t"]

    daemon = _daemon(live_env, clock=fake_clock)
    daemon.run_poll_cycle()
    first_gen = json.loads(live_env["activity"].read_text(encoding="utf-8"))["generated_at"]

    clock["t"] += 5.0
    live_env["ledger"].write_text(
        live_env["ledger"].read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    assert daemon.poll_ledger_once() is True
    assert daemon.maybe_rebuild()
    second = json.loads(live_env["activity"].read_text(encoding="utf-8"))
    assert second["generated_at"] != first_gen


# AC4
def test_github_failure_keeps_last_good_activity(live_env: dict) -> None:
    daemon = _daemon(live_env, github_runner=MockGh())
    daemon.run_poll_cycle()
    before = live_env["activity"].read_bytes()
    mtime = live_env["activity"].stat().st_mtime_ns

    daemon.github_runner = MockGh(fail=True)
    assert daemon.poll_github_once() is False
    daemon.maybe_rebuild()

    assert live_env["activity"].read_bytes() == before
    assert live_env["activity"].stat().st_mtime_ns == mtime
    health = daemon.health()
    assert health.errors


def test_process_survives_failed_poll(live_http: tuple[LiveDaemon, str, int]) -> None:
    daemon, host, port = live_http
    daemon.github_runner = MockGh(fail=True)
    daemon.poll_github_once()
    status, _, body = _http_get(f"http://{host}:{port}/healthz")
    assert status == HTTPStatus.OK
    payload = json.loads(body.decode())
    assert payload["errors"]


# AC5
def test_path_traversal_and_post_rejected(live_http: tuple[LiveDaemon, str, int]) -> None:
    _, host, port = live_http
    base = f"http://{host}:{port}"
    for bad in ("/../etc/passwd", "/%2e%2e/index.html", "/..%2findex.html"):
        status, _, _ = _http_get(base + bad)
        assert status in (HTTPStatus.NOT_FOUND, HTTPStatus.BAD_REQUEST)

    req = urllib.request.Request(
        base + "/activity.json",
        data=b"{}",
        method="POST",
    )
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(req, timeout=5)
    assert exc.value.code == HTTPStatus.METHOD_NOT_ALLOWED


def test_ledger_source_gh_uses_fetch(live_env: dict) -> None:
    text = LEDGER.read_text(encoding="utf-8")
    runner = LedgerMockGh(status=200, body=_contents_body(text))
    daemon = LiveDaemon(
        ledger_source="gh",
        ledger_path=None,
        activity_path=live_env["activity"],
        static_dir=live_env["static"],
        cache_dir=live_env["cache"],
        bots=live_env["bots"],
        github_runner=runner,
    )
    assert daemon.poll_ledger_once() is True
    assert daemon.maybe_rebuild()
    saved = json.loads(live_env["activity"].read_text(encoding="utf-8"))
    assert saved["meta"]["ledger"] == "ok"
    assert saved["tasks"]


def test_resolve_live_ledger_gh() -> None:
    source, path, url = resolve_live_ledger(ledger_source="gh", ledger_path=None)
    assert source == "gh"
    assert path is None
    assert "agent-mindmap" in url


# AC6
def test_launchd_plist_lint() -> None:
    if platform.system() != "Darwin":
        pytest.skip("plutil only on macOS")
    if not shutil.which("plutil"):
        pytest.skip("plutil not installed")
    proc = subprocess.run(
        ["plutil", "-lint", str(PLIST)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout


def test_makefile_live_target() -> None:
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "live:" in makefile
    assert "ingest.live" in makefile
