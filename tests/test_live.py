"""MM-011: live daemon + localhost server."""

from __future__ import annotations

import http.client
import io
import json
import platform
import shutil
import socket
import stat
import subprocess
import sys
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
    MAX_SSE_CONNECTIONS,
    LiveDaemon,
    ProcessSingletonLock,
    SSE_RETRY_AFTER_SEC,
    SingletonLockError,
    create_http_server,
    ensure_python_version,
    host_header_allowed,
    origin_header_allowed,
    process_lock_path,
    refuse_public_bind,
    resolve_live_ledger,
)
from tests.test_events_fetch import EventsMockGh, _contents_body as events_contents_body
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
    daemon = _daemon(live_env, events_source="off")
    daemon.run_poll_cycle()
    httpd = create_http_server(daemon, port=0, sse_heartbeat_sec=0.15)
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


def _sample_network_event(eid: str) -> dict:
    return {
        "id": eid,
        "ts": "2026-10-20T12:00:00+00:00",
        "sender": "dev-1",
        "group": "build",
        "type": "message",
        "summary": "hello from sse test",
        "provenance": "agent-reported",
    }


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


def test_ensure_python_version_rejects_below_312() -> None:
    assert ensure_python_version((3, 9, 6), stderr=io.StringIO()) == 1


def test_ensure_python_version_accepts_312() -> None:
    assert ensure_python_version((3, 12, 0), stderr=io.StringIO()) == 0


def test_plist_uses_start_mac_wrapper() -> None:
    text = PLIST.read_text(encoding="utf-8")
    assert "/bin/bash" in text
    assert "REPLACE_WITH_AGENT_MINDMAP_REPO_ROOT/scripts/start-mac.sh" in text
    assert "/usr/bin/python3" not in text
    assert "REPLACE_WITH_ABSOLUTE_LOG_DIR" in text
    assert "SuccessfulExit" in text


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


# SEC-MM011-1
def test_host_and_origin_helpers() -> None:
    assert host_header_allowed("127.0.0.1:8787")
    assert host_header_allowed("localhost")
    assert not host_header_allowed("evil.example")
    assert origin_header_allowed(None)
    assert origin_header_allowed("http://127.0.0.1:8787")
    assert not origin_header_allowed("https://evil.example")
    assert not origin_header_allowed("null")


def test_sec_mm011_forged_host_and_origin_rejected(
    live_http: tuple[LiveDaemon, str, int],
) -> None:
    _, host, port = live_http
    base = f"http://{host}:{port}"
    status, _, _ = _http_get(
        f"{base}/healthz",
        {"Host": "attacker.example", "Origin": "http://127.0.0.1:8787"},
    )
    assert status == HTTPStatus.FORBIDDEN

    status2, _, _ = _http_get(
        f"{base}/activity.json",
        {"Host": f"{host}:{port}", "Origin": "https://evil.example"},
    )
    assert status2 == HTTPStatus.FORBIDDEN

    status3, _, _ = _http_get(
        f"{base}/events",
        {"Host": f"{host}:{port}", "Origin": "https://evil.example"},
    )
    assert status3 == HTTPStatus.FORBIDDEN


def test_sec_mm020d_2_origin_null_rejected(live_http: tuple[LiveDaemon, str, int]) -> None:
    _, host, port = live_http
    headers = {"Host": f"{host}:{port}", "Origin": "null"}
    for path in ("/healthz", "/activity.json", "/events"):
        status, _, _ = _http_get(f"http://{host}:{port}{path}", headers)
        assert status == HTTPStatus.FORBIDDEN


def test_sec_mm020d_2_sse_garbage_client_bytes_no_cpu_spin(
    live_http: tuple[LiveDaemon, str, int],
) -> None:
    """Unexpected post-request bytes must not busy-spin; slot frees promptly."""
    daemon, host, port = live_http
    sock = socket.create_connection((host, port), timeout=5)
    try:
        request = (
            f"GET /events HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            f"Accept: text/event-stream\r\n"
            f"Connection: keep-alive\r\n\r\n"
        ).encode("ascii")
        sock.sendall(request)
        buf = b""
        while b"\r\n\r\n" not in buf:
            chunk = sock.recv(4096)
            assert chunk, "server closed before headers"
            buf += chunk
        assert b" 200 " in buf.split(b"\r\n", 1)[0]
        assert daemon.sse_limiter.active_count() == 1

        cpu_before = time.process_time()
        wall_before = time.monotonic()
        sock.sendall(b"GARBAGE_BYTES_NOT_HTTP\r\n" * 20)
        assert daemon.sse_limiter.wait_until_active_at_most(0, timeout=1.0)

        # Handler must exit quickly; sampling window should not burn CPU.
        while time.monotonic() - wall_before < 0.4:
            time.sleep(0.05)
        cpu_delta = time.process_time() - cpu_before
        assert cpu_delta < 0.25, f"process_time grew by {cpu_delta:.3f}s"
    finally:
        sock.close()


def test_sec_mm020d_2_missing_origin_allowed_for_get(
    live_http: tuple[LiveDaemon, str, int],
) -> None:
    """Same-origin GETs without an Origin header remain allowed (SEC-MM011-1)."""
    _, host, port = live_http
    headers = {"Host": f"{host}:{port}"}
    for path in ("/healthz", "/activity.json"):
        status, _, _ = _http_get(f"http://{host}:{port}{path}", headers)
        assert status == HTTPStatus.OK

    conn = http.client.HTTPConnection(host, port, timeout=5)
    conn.request("GET", "/events", headers=headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.OK
    conn.close()


def test_sec_mm011_localhost_allowed(live_http: tuple[LiveDaemon, str, int]) -> None:
    _, host, port = live_http
    headers = {"Host": f"{host}:{port}", "Origin": f"http://{host}:{port}"}
    for path in ("/healthz", "/activity.json", "/index.html"):
        status, _, _ = _http_get(f"http://{host}:{port}{path}", headers)
        assert status == HTTPStatus.OK


def test_network_events_dedupe_by_id(live_env: dict) -> None:
    daemon = _daemon(live_env, events_source="off")
    evt = _sample_network_event("evt-dedupe-1")
    daemon.ingest_network_events([evt, dict(evt)])
    assert daemon.health().network_event_count == 1


def test_pr_lane_events_ingested_into_sse_log(live_env: dict) -> None:
    """MM-020e: poll_github_once → build_pr_lane_events → NetworkEventLog / SSE."""
    daemon = _daemon(live_env, events_source="off", github_runner=MockGh())
    assert daemon.health().network_event_count == 0
    assert daemon.poll_github_once() is True
    count = daemon.health().network_event_count
    assert count > 0
    events = daemon.network_events_after(None)
    assert len(events) == count
    assert all(
        e.get("provenance") in {"github-verified", "agent-reported"} for e in events
    )
    assert any(e.get("provenance") == "github-verified" for e in events)
    assert all(isinstance(e.get("id"), str) and e["id"] for e in events)
    # Second poll dedupes by id — count must not grow.
    assert daemon.poll_github_once() is False
    assert daemon.health().network_event_count == count


def test_pr_lane_events_flow_through_sse_stream(
    live_http: tuple[LiveDaemon, str, int],
) -> None:
    """MM-020e wiring: GitHub PR-lane events appear on GET /events."""
    daemon, host, port = live_http
    before = daemon.health().network_event_count
    # live_http already ran one poll cycle with MockGh — lanes may already be in.
    if before == 0:
        daemon.github_runner = MockGh()
        assert daemon.poll_github_once() is True
    count = daemon.health().network_event_count
    assert count > 0
    got = _read_sse_events(host, port, max_events=min(count, 3), timeout=5.0)
    assert got
    assert all(e.get("provenance") == "github-verified" for e in got)


def test_poll_events_from_gh(live_env: dict) -> None:
    line = json.dumps(_sample_network_event("evt-gh-1"), separators=(",", ":"))
    body = events_contents_body(line + "\n")
    runner = EventsMockGh(status=200, body=body)
    daemon = _daemon(live_env, events_source="gh", github_runner=runner)
    assert daemon.poll_events_once() is True
    assert daemon.health().network_event_count == 1


def _read_sse_events(
    host: str,
    port: int,
    *,
    last_event_id: str | None = None,
    max_events: int = 1,
    timeout: float = 5.0,
) -> list[dict]:
    headers = {
        "Host": f"{host}:{port}",
        "Accept": "text/event-stream",
    }
    if last_event_id:
        headers["Last-Event-ID"] = last_event_id
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    conn.request("GET", "/events", headers=headers)
    resp = conn.getresponse()
    assert resp.status == HTTPStatus.OK
    assert "text/event-stream" in resp.getheader("Content-Type", "")
    deadline = time.monotonic() + timeout
    events: list[dict] = []
    buf = b""
    while len(events) < max_events and time.monotonic() < deadline:
        chunk = resp.read(1)
        if not chunk:
            break
        buf += chunk
        while b"\n\n" in buf:
            block, buf = buf.split(b"\n\n", 1)
            text = block.decode("utf-8", errors="replace")
            data_lines = [
                ln[6:]
                for ln in text.splitlines()
                if ln.startswith("data:")
            ]
            if not data_lines:
                continue
            payload = "\n".join(data_lines)
            events.append(json.loads(payload))
    conn.close()
    return events


def test_qa_mm011_2_singleton_lock_refused_and_released(live_env: dict) -> None:
    lock_path = process_lock_path(live_env["activity"])
    first = ProcessSingletonLock(lock_path)
    first.acquire()
    assert lock_path.is_file()
    assert stat.S_IMODE(lock_path.stat().st_mode) == 0o600

    second = ProcessSingletonLock(lock_path)
    with pytest.raises(SingletonLockError):
        second.acquire()

    first.release()
    third = ProcessSingletonLock(lock_path)
    third.acquire()
    third.release()


def test_qa_mm011_2_second_process_refused_across_ports(live_env: dict) -> None:
    """Lock is adjacent to activity.json — different --port cannot bypass it."""
    lock_path = process_lock_path(live_env["activity"])
    hold_script = """
import sys, time
from pathlib import Path
from ingest.live import ProcessSingletonLock
lock = ProcessSingletonLock(Path(sys.argv[1]))
lock.acquire()
print("held", flush=True)
time.sleep(float(sys.argv[2]))
"""
    try_script = """
import sys
from pathlib import Path
from ingest.live import ProcessSingletonLock, SingletonLockError
try:
    ProcessSingletonLock(Path(sys.argv[1])).acquire()
except SingletonLockError:
    sys.exit(1)
sys.exit(0)
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", hold_script, str(lock_path), "30"],
        cwd=str(ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None
        line = holder.stdout.readline().decode()
        assert line.strip() == "held"

        blocked = subprocess.run(
            [sys.executable, "-c", try_script, str(lock_path)],
            cwd=str(ROOT),
            capture_output=True,
            timeout=5,
        )
        assert blocked.returncode == 1

        holder.terminate()
        assert holder.wait(timeout=5) is not None

        allowed = subprocess.run(
            [sys.executable, "-c", try_script, str(lock_path)],
            cwd=str(ROOT),
            capture_output=True,
            timeout=5,
        )
        assert allowed.returncode == 0
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=3)


def test_sec_mm020d_1_sse_connection_cap(live_http: tuple[LiveDaemon, str, int]) -> None:
    daemon, host, port = live_http
    headers = {"Host": f"{host}:{port}"}
    connections: list[http.client.HTTPConnection] = []
    # Keep HTTPResponse objects alive so http.client does not close the SSE socket.
    responses: list[http.client.HTTPResponse] = []
    try:
        for _ in range(MAX_SSE_CONNECTIONS):
            conn = http.client.HTTPConnection(host, port, timeout=5)
            conn.request("GET", "/events", headers=headers)
            resp = conn.getresponse()
            assert resp.status == HTTPStatus.OK
            responses.append(resp)
            connections.append(conn)

        overflow = http.client.HTTPConnection(host, port, timeout=5)
        overflow.request("GET", "/events", headers=headers)
        resp9 = overflow.getresponse()
        assert resp9.status == HTTPStatus.SERVICE_UNAVAILABLE
        assert resp9.getheader("Retry-After") == str(SSE_RETRY_AFTER_SEC)
        overflow.close()

        responses[0].close()
        connections[0].close()
        assert daemon.sse_limiter.wait_until_active_at_most(MAX_SSE_CONNECTIONS - 1)

        replacement = http.client.HTTPConnection(host, port, timeout=5)
        replacement.request("GET", "/events", headers=headers)
        assert replacement.getresponse().status == HTTPStatus.OK
        replacement.close()
    finally:
        for conn in connections[1:]:
            conn.close()


def test_sse_replay_last_event_id_and_dedupe(
    live_http: tuple[LiveDaemon, str, int],
) -> None:
    daemon, host, port = live_http
    # MM-020e may have already seeded PR-lane events via poll_github_once.
    prior = daemon.network_events_after(None)
    prior_tail = prior[-1]["id"] if prior else None
    prior_count = len(prior)

    first = _sample_network_event("sse-evt-1")
    second = _sample_network_event("sse-evt-2")
    daemon.ingest_network_events([first])

    got = _read_sse_events(
        host,
        port,
        last_event_id=prior_tail,
        max_events=1,
        timeout=3.0,
    )
    assert len(got) == 1
    assert got[0]["id"] == "sse-evt-1"

    daemon.ingest_network_events([second, dict(first)])

    replay = _read_sse_events(
        host,
        port,
        last_event_id="sse-evt-1",
        max_events=1,
        timeout=3.0,
    )
    assert len(replay) == 1
    assert replay[0]["id"] == "sse-evt-2"
    assert daemon.health().network_event_count == prior_count + 2


def test_sec_mm020e3_healthz_reports_dropped_network_events(
    live_http: tuple[LiveDaemon, str, int],
) -> None:
    daemon, host, port = live_http
    before = daemon.health().dropped_network_events
    daemon.ingest_network_events([_sample_network_event("healthz-ok")])
    sk = "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF"
    daemon.ingest_network_events(
        [
            {
                "id": "healthz-secret",
                "ts": "2026-10-20T12:00:00+00:00",
                "sender": "dev-1",
                "group": "build",
                "type": "message",
                "summary": f"leak {sk}",
                "provenance": "agent-reported",
            }
        ]
    )
    health = daemon.health()
    assert health.dropped_network_events >= before + 1
    headers = {"Host": f"{host}:{port}"}
    status, _, body = _http_get(f"http://{host}:{port}/healthz", headers)
    assert status == HTTPStatus.OK
    payload = json.loads(body.decode())
    assert payload["dropped_network_events"] >= before + 1
    assert sk not in body.decode()


def test_qa_mm020e5_network_event_log_enforces_cap_and_secret(
    live_env: dict,
) -> None:
    from ingest.github_poller import SUMMARY_MAX_CHARS

    daemon = _daemon(live_env, events_source="off")
    dropped_before = daemon.health().dropped_network_events
    oversize = {
        "id": "oversize-summary",
        "ts": "2026-10-20T12:00:00+00:00",
        "sender": "dev-1",
        "group": "build",
        "type": "message",
        "summary": "x" * 500,
        "provenance": "agent-reported",
    }
    added_big = daemon.ingest_network_events([oversize])
    assert len(added_big) == 1
    assert len(added_big[0]["summary"]) == SUMMARY_MAX_CHARS
    added = daemon.ingest_network_events(
        [
            {
                "id": "capped-summary",
                "ts": "2026-10-20T12:00:00+00:00",
                "sender": "dev-1",
                "group": "build",
                "type": "message",
                "summary": "y" * (SUMMARY_MAX_CHARS + 50),
                "provenance": "agent-reported",
            }
        ]
    )
    assert len(added) == 1
    assert len(added[0]["summary"]) == SUMMARY_MAX_CHARS
    sk = "sk-proj-abcdefghijklmnopqrstuvwxyz1234567890ABCDEF"
    assert (
        daemon.ingest_network_events(
            [
                {
                    "id": "secret-summary",
                    "ts": "2026-10-20T12:00:00+00:00",
                    "sender": "dev-1",
                    "group": "build",
                    "type": "message",
                    "summary": sk,
                    "provenance": "agent-reported",
                }
            ]
        )
        == []
    )
    assert daemon.health().dropped_network_events >= dropped_before + 1


def test_qa_mm020e4_sse_slots_released_after_mid_push_abort(
    live_http: tuple[LiveDaemon, str, int],
) -> None:
    daemon, host, port = live_http
    for i in range(30):
        daemon.ingest_network_events([_sample_network_event(f"abort-seed-{i}")])
    headers = {"Host": f"{host}:{port}"}
    for _ in range(15):
        conn = http.client.HTTPConnection(host, port, timeout=3)
        conn.request("GET", "/events", headers=headers)
        resp = conn.getresponse()
        try:
            resp.read(32)
        except (ConnectionError, http.client.HTTPException, OSError):
            pass
        resp.close()
        if conn.sock is not None:
            try:
                conn.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        conn.close()
    deadline = time.monotonic() + 5.0
    while daemon.sse_limiter.active_count() > 0 and time.monotonic() < deadline:
        time.sleep(0.05)
    assert daemon.sse_limiter.active_count() == 0
