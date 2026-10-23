"""Regression tests: credential boundary, startup ordering/paths, token-store concurrency."""

from __future__ import annotations

import copy
import json
import os
import socket
import threading
import urllib.request
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import pytest

from ingest import live
from ingest.live import DEFAULT_ACTIVITY, DEFAULT_T3_STATE, create_http_server, main
from ingest.t3 import T3Projection, read_demo, safe_ident, safe_text
from ingest.t3_live import T3Daemon
from ingest.t3_mcp import TokenStore

NOW = 1792699200
ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "tests" / "fixtures" / "ledger-sample.md"

# Synthetic examples only; none of these are real credentials.
SECRETS = [
    "Authorization: Basic dXNlcjpwYXNzd29yZA==",
    "authorization:Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.c2lnbmF0dXJl",
    "please use Bearer abcdef123456 for the call",
    "Basic dXNlcjpwYXNzd29yZA==",
    "rotate xoxb-123456789012-1234567890123-AbCdEfGhIjKlMnOpQrStUvWx",
    "xapp-1-A0123456789-0123456789-abcdef0123456789",
    "key sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv",
    "sk-proj-abcdefghijklmnopqrstuvwx",
    "ghp_abcdefghijklmnopqrstuvwxyz0123456789",
    "github_pat_11ABCDEFG0abcdefghijkl_mnopqrstuvwxyz",
    "glpat-abcdefghijklmnopqrst",
    "AKIAIOSHFODNN7EXAMPLE",
    "AIzaSyA-abcdefghijklmnopqrstuvwxyz01234",
    "password=hunter2",
    "API_KEY: abcd1234",
    "client_secret = notarealsecret",
    "https://user:pw@example.com/repo",
    "https://example.com/hook?token=abc123",
    "-----BEGIN RSA PRIVATE KEY-----",
    "aB3dE5gH7jK9mN1pQ3sT5vW7yZ",
    "0123456789abcdef0123456789abcdef01234567",
    "x\u200bo\u200bx\u200bb-123456789012-abcdefghij",  # zero-width obfuscation
    "ｘｏｘｂ-123456789012-abcdefghij",  # fullwidth (NFKC)
]
REAL_LOOKING = SECRETS

BENIGN = [
    "Check System Architecture and Claude Command",
    "Basic functionality check",
    "Add token handling to parser",
    "MM-020k fix SSE",
    "feature/t3-readonly-activity",
    # Real thread titles observed against a live T3 server.
    "Check T3 Environment Details",
    "Continue T3 Integration Work",
    "Independent review of T3 integration",
    "Read-only status-mapping inspection",
]


@pytest.mark.parametrize("secret", REAL_LOOKING)
def test_safe_text_fails_closed(secret):
    assert safe_text(secret) == "[redacted]"
    assert safe_text("prefix " + secret + " suffix") == "[redacted]"


@pytest.mark.parametrize("text", BENIGN)
def test_safe_text_keeps_ordinary_titles(text):
    assert safe_text(text) == text


def test_safe_text_strips_control_characters_and_truncates():
    assert safe_text("a\x00b\x1b[31m  c\n d") == "ab[31m c d"
    assert len(safe_text("word " * 100)) <= 160
    assert safe_text("   ") is None


def test_safe_ident_is_strict():
    assert safe_ident("claude-sonnet-5-5") == "claude-sonnet-5-5"
    assert safe_ident("0.1.2") == "0.1.2"
    assert safe_ident("has space") is None
    assert safe_ident("sk-ant-api03-AbCdEfGhIjKlMnOpQrStUv") is None
    assert safe_ident(None) is None


def _raw_with_secret(secret: str) -> dict:
    raw = copy.deepcopy(read_demo())
    t = raw["threads"][0]
    t["title"] = secret
    t["projectTitle"] = secret
    t["branch"] = secret
    t["model"] = secret
    t["status"] = secret
    raw["environment"]["serverVersion"] = secret
    raw["providers"][0]["driverKind"] = secret
    return raw


@pytest.mark.parametrize("secret", REAL_LOOKING)
def test_secrets_never_reach_snapshot_or_served_response(tmp_path, secret, monkeypatch):
    monkeypatch.setattr("ingest.t3_live.read_demo", lambda: _raw_with_secret(secret))
    daemon = T3Daemon(
        activity_path=tmp_path / "activity.json",
        static_dir=tmp_path,
        cache_dir=tmp_path,
        bots=[],
        demo=True,
        clock=lambda: NOW,
    )
    daemon.run_poll_cycle()
    on_disk = (tmp_path / "activity.json").read_text()
    server = create_http_server(daemon, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        served = urllib.request.urlopen(f"http://127.0.0.1:{port}/activity.json").read().decode()
    finally:
        server.shutdown()
        server.server_close()
    # Distinctive fragments of each example must not appear anywhere browser-visible.
    fragments = [f for f in secret.replace("=", " ").replace(":", " ").split() if len(f) >= 8]
    for body in (on_disk, served):
        json.loads(body)
        for fragment in fragments:
            assert fragment not in body
        assert "[redacted]" in body or "Unknown" in body or "unknown" in body


def test_invalid_thread_ids_are_dropped():
    raw = copy.deepcopy(read_demo())
    raw["threads"][0]["threadId"] = "Authorization: Bearer abc/../../x"
    snap = T3Projection("local").snapshot(raw, NOW)
    assert "Authorization" not in json.dumps(snap)
    assert len(snap["nodes"]) == len(read_demo()["threads"]) - 1


# ---- startup ordering, default paths, cleanup --------------------------------


@pytest.fixture
def busy_port():
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(1)
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


def test_port_conflict_does_not_touch_existing_t3_activity(tmp_path, busy_port, capsys):
    existing = tmp_path / "activity.json"
    existing.write_text('{"keep":"me"}\n')
    before = (existing.read_bytes(), existing.stat().st_mtime_ns)
    rc = main(
        ["--source", "t3-demo", "--port", str(busy_port), "--activity-out", str(existing),
         "--cache-dir", str(tmp_path / "cache")]
    )
    assert rc == 2
    assert (existing.read_bytes(), existing.stat().st_mtime_ns) == before
    assert not (tmp_path / "cache").exists()
    assert "cannot start server" in capsys.readouterr().err


def test_port_conflict_does_not_touch_legacy_activity(tmp_path, busy_port):
    existing = tmp_path / "activity.json"
    existing.write_text('{"legacy":"data"}\n')
    before = (existing.read_bytes(), existing.stat().st_mtime_ns)
    rc = main(
        ["--ledger", str(LEDGER), "--port", str(busy_port), "--activity-out", str(existing),
         "--static-dir", str(tmp_path), "--cache-dir", str(tmp_path / "cache")]
    )
    assert rc == 2
    assert (existing.read_bytes(), existing.stat().st_mtime_ns) == before


def _capture_daemon(monkeypatch):
    captured = {}

    def fake_create(daemon, **_kwargs):
        captured["daemon"] = daemon
        raise OSError("stop before polling")

    monkeypatch.setattr(live, "create_http_server", fake_create)
    return captured


@pytest.mark.parametrize("source", ["t3", "t3-demo"])
def test_t3_sources_default_to_separate_paths(monkeypatch, source):
    captured = _capture_daemon(monkeypatch)
    assert main(["--source", source]) == 2
    daemon = captured["daemon"]
    assert daemon.activity_path == DEFAULT_T3_STATE / source / "activity.json"
    assert daemon.cache_dir == DEFAULT_T3_STATE / source / "cache"
    assert daemon.activity_path != DEFAULT_ACTIVITY


def test_legacy_defaults_and_explicit_overrides_preserved(monkeypatch, tmp_path):
    captured = _capture_daemon(monkeypatch)
    assert main(["--ledger", str(LEDGER)]) == 2
    assert captured["daemon"].activity_path == DEFAULT_ACTIVITY
    assert captured["daemon"].cache_dir == live.DEFAULT_CACHE
    out = tmp_path / "x" / "a.json"
    assert main(["--source", "t3-demo", "--activity-out", str(out), "--cache-dir", str(tmp_path / "c")]) == 2
    assert captured["daemon"].activity_path == out
    assert captured["daemon"].cache_dir == tmp_path / "c"


def test_start_stop_restart_releases_port_and_writes_only_after_bind(tmp_path, monkeypatch):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    order: list[str] = []
    servers = []
    real_create = create_http_server

    def tracking_create(daemon, **kwargs):
        order.append("bind")
        if not servers:
            assert not daemon.activity_path.exists()  # nothing written before bind
        server = real_create(daemon, **kwargs)
        server.serve_forever = lambda poll_interval=0.5: order.append("serve")  # return at once
        servers.append(server)
        return server

    monkeypatch.setattr(live, "create_http_server", tracking_create)
    out = tmp_path / "activity.json"
    args = ["--source", "t3-demo", "--port", str(port), "--activity-out", str(out),
            "--cache-dir", str(tmp_path / "cache")]
    assert main(args) == 0
    assert order == ["bind", "serve"] and out.is_file()
    assert servers[0].socket.fileno() == -1  # closed on exit
    assert main(args) == 0  # restart on the same port works
    assert len(servers) == 2


def test_poll_failure_after_bind_closes_server(tmp_path, monkeypatch):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    servers = []
    real_create = create_http_server

    def tracking_create(daemon, **kwargs):
        server = real_create(daemon, **kwargs)
        servers.append(server)
        return server

    def boom(self):
        raise RuntimeError("poll failed")

    monkeypatch.setattr(live, "create_http_server", tracking_create)
    monkeypatch.setattr(T3Daemon, "run_poll_cycle", boom)
    with pytest.raises(RuntimeError):
        main(["--source", "t3-demo", "--port", str(port), "--activity-out", str(tmp_path / "a.json")])
    assert servers[0].socket.fileno() == -1
    probe = socket.socket()
    probe.bind(("127.0.0.1", port))  # port is free again
    probe.close()


# ---- token store concurrency ---------------------------------------------------


class _Value:
    def __init__(self, payload):
        self.payload = payload

    def model_dump(self, **_kwargs):
        return {"value": self.payload}


def _writer(path: str, key: str) -> str:
    store = TokenStore("https://example.com/mcp")
    store.path = Path(path)
    store.save(key, _Value(key))
    return key


def test_concurrent_saves_keep_all_keys_private_and_clean(tmp_path, monkeypatch):
    path = tmp_path / "cfg" / "tokens.json"
    monkeypatch.setattr("ingest.t3_mcp.credential_path", lambda _: path)
    store = TokenStore("https://example.com/mcp")
    store.save("existing", _Value("keep"))
    keys = [f"k{i}" for i in range(24)]
    errors: list[BaseException] = []

    def run(key):
        try:
            _writer(str(path), key)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=run, args=(k,)) for k in keys]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    data = json.loads(path.read_text())
    assert set(data) == {"existing", *keys}
    assert data["existing"] == {"value": "keep"}
    assert path.stat().st_mode & 0o777 == 0o600
    assert [p.name for p in path.parent.iterdir() if p.suffix == ".tmp"] == []
    assert (path.parent / (path.name + ".lock")).stat().st_mode & 0o777 == 0o600
    TokenStore("https://example.com/mcp").read()  # still accepted as private


def test_concurrent_saves_across_processes(tmp_path):
    path = tmp_path / "tokens.json"
    keys = [f"p{i}" for i in range(16)]
    with ProcessPoolExecutor(max_workers=4) as pool:
        assert sorted(pool.map(_writer, [str(path)] * len(keys), keys)) == sorted(keys)
    assert set(json.loads(path.read_text())) == set(keys)
    assert path.stat().st_mode & 0o777 == 0o600
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]


def test_save_rejects_symlinked_lock_and_failed_save_keeps_existing(tmp_path):
    path = tmp_path / "tokens.json"
    store = TokenStore("https://example.com/mcp")
    store.path = path
    store.save("a", _Value(1))
    original = path.read_text()

    class Bad:
        def model_dump(self, **_kwargs):
            raise RuntimeError("dump failed")

    with pytest.raises(RuntimeError):
        store.save("b", Bad())
    assert path.read_text() == original
    assert not [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    os.remove(tmp_path / "tokens.json.lock")
    (tmp_path / "elsewhere").write_text("x")
    (tmp_path / "tokens.json.lock").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(OSError):
        store.save("c", _Value(3))
    assert (tmp_path / "elsewhere").read_text() == "x"
    assert path.read_text() == original


# ---- second review round -----------------------------------------------------


@pytest.mark.parametrize(
    "thread_id",
    ["ghp_abcdefghijklmnopqrstuvwxyz0123456789", "xoxb-123456789012-abcdefghij", "password%3Dhunter2"],
)
def test_credential_shaped_thread_ids_are_dropped(thread_id):
    raw = copy.deepcopy(read_demo())
    raw["threads"][0]["threadId"] = thread_id
    snap = T3Projection("local").snapshot(raw, NOW)
    assert thread_id not in json.dumps(snap)
    assert len(snap["nodes"]) == len(read_demo()["threads"]) - 1


@pytest.mark.parametrize(
    "thread_id",
    [
        "1558cabe-7e29-4358-8547-081eab7c1ab6",
        "thread:delegated-task:command%3Amcp%3A6e496b21-1c90-4a4d-a0f5-2b26a88e4809%3Adelegate-task%3Amm-fix-review-4",
    ],
)
def test_real_thread_id_shapes_are_kept(thread_id):
    raw = copy.deepcopy(read_demo())
    raw["threads"][0]["threadId"] = thread_id
    snap = T3Projection("local").snapshot(raw, NOW)
    assert len(snap["nodes"]) == len(read_demo()["threads"])


@pytest.mark.parametrize(
    "encoded",
    [
        "password%3Dhunter2",
        "https://example.com/y?access_token%3dabc123",
        "Authorization%3A%20Bearer%20abc123",
        "api_key&#61;abcd1234",
        "password%253Dhunter2",  # double-encoded
    ],
)
def test_encoded_secrets_are_redacted(encoded):
    assert safe_text(encoded) == "[redacted]"


def test_authorization_word_alone_is_not_redacted():
    assert safe_text("Review authorization flow") == "Review authorization flow"
    assert safe_text("Authorization: anything") == "[redacted]"


def test_unsafe_credential_directory_and_symlink_rejected(tmp_path):
    store = TokenStore("https://example.com/mcp")
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o777)
    store.path = shared / "tokens.json"
    with pytest.raises(ValueError):
        store.save("a", _Value(1))
    target = tmp_path / "real.json"
    target.write_text("{}")
    target.chmod(0o600)
    link = tmp_path / "link.json"
    link.symlink_to(target)
    store.path = link
    with pytest.raises(ValueError):
        store.read()


# ---- third review round ------------------------------------------------------


@pytest.mark.parametrize(
    "encoded",
    [
        "password%EF%BC%9Dhunter2",  # decodes to a fullwidth "=", needs NFKC after decoding
        "password%25252525253Dhunter2",  # nesting beyond the decode limit fails closed
    ],
)
def test_decoded_forms_are_normalized_and_depth_fails_closed(encoded):
    assert safe_text(encoded) == "[redacted]"


@pytest.mark.parametrize(
    "thread_id",
    ["password%253Dhunter2", "aB3dE5gH7jK9mN1pQ3sT5vW7yZ", "thread:ghp_abcdefghijklmnopqrstuvwxyz0123456789"],
)
def test_thread_id_bypasses_are_dropped(thread_id):
    raw = copy.deepcopy(read_demo())
    raw["threads"][0]["threadId"] = thread_id
    snap = T3Projection("local").snapshot(raw, NOW)
    assert thread_id not in json.dumps(snap)
    assert len(snap["nodes"]) == len(read_demo()["threads"]) - 1


# ---- fourth review round -----------------------------------------------------


def test_long_titles_are_scanned_in_bounded_time():
    import time

    start = time.perf_counter()
    assert safe_text("word " * 100_000) == ("word " * 100_000).strip()[:160]
    assert time.perf_counter() - start < 2


@pytest.mark.parametrize(
    "encoded",
    [
        "cGFzc3dvcmQ9YWJjMTIz",  # base64("password=abc123")
        "Zm9vIEF1dGhvcml6YXRpb246IEJhc2ljIGFiYw==",  # base64("foo Authorization: Basic abc")
        r"password=abc123",
        r"api_key\x3dabcd1234",
        "+AHA-assword+AD0-x",  # UTF-7 "password=x"
    ],
)
def test_other_encoded_credentials_are_redacted(encoded):
    assert safe_text(encoded) == "[redacted]"


@pytest.mark.parametrize(
    "thread_id",
    ["thread:aB3dE5gH7jK9mN1pQ3sT5vW7yZ", None, 5, ["x"]],
)
def test_composite_and_malformed_thread_ids_never_abort_snapshot(thread_id):
    raw = copy.deepcopy(read_demo())
    raw["threads"][0]["threadId"] = thread_id
    snap = T3Projection("local").snapshot(raw, NOW)
    assert len(snap["nodes"]) == len(read_demo()["threads"]) - 1


def _delegated(rid: str) -> str:
    return (
        "thread:delegated-task:command%3Amcp%3A6e496b21-1c90-4a4d-a0f5-2b26a88e4809"
        f"%3Adelegate-task%3A{rid}"
    )


@pytest.mark.parametrize("rid", ["mm-fix-review-4", "ReviewFixes2026IterationTwo", "Mm_Real_Delegation_Run_0042_Final"])
def test_delegated_ids_with_long_mixed_case_request_ids_are_kept(rid):
    raw = copy.deepcopy(read_demo())
    raw["threads"][0]["threadId"] = _delegated(rid)
    assert len(T3Projection("local").snapshot(raw, NOW)["nodes"]) == len(read_demo()["threads"])


@pytest.mark.parametrize("rid", ["ghp_abcdefghijklmnopqrstuvwxyz0123456789", "xoxb-123456789012-abcdefghij", "cGFzc3dvcmQ9YWJjMTIz"])
def test_delegated_ids_embedding_credentials_are_dropped(rid):
    raw = copy.deepcopy(read_demo())
    raw["threads"][0]["threadId"] = _delegated(rid)
    snap = T3Projection("local").snapshot(raw, NOW)
    assert rid not in json.dumps(snap)
    assert len(snap["nodes"]) == len(read_demo()["threads"]) - 1
