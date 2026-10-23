import asyncio
import copy
import json
from types import SimpleNamespace as NS

import pytest

from ingest.build import validate_activity
from ingest.t3 import READ_TOOLS, T3Projection, collect, read_demo, safe_text
from ingest.t3_live import T3Daemon
from ingest.t3_mcp import TokenStore, validate_url

NOW = 1792699200


def test_two_providers_and_real_delegation():
    activity = T3Projection("local", demo=True).snapshot(read_demo(), NOW)
    validate_activity(activity)
    assert {n["session"]["provider"] for n in activity["nodes"]} == {
        "Codex",
        "Claude Code",
    }
    assert len(activity["nodes"]) == 5
    assert len(activity["edges"]) == 1
    assert activity["edges"][0]["type"] == "delegation"
    assert activity["meta"]["t3"]["mode"] == "demo"


@pytest.mark.parametrize(
    "status,expected",
    [
        ("running", "IN_PROGRESS"),
        ("idle", "IDLE"),
        ("completed", "DONE"),
        ("failed", "FAILED"),
        ("waiting", "BLOCKED"),
        ("queued", "BLOCKED"),
        ("interrupted", "UNKNOWN"),
        ("cancelled", "UNKNOWN"),
    ],
)
def test_states(status, expected):
    raw = read_demo()
    raw["threads"] = [{**raw["threads"][0], "status": status}]
    result = T3Projection("local").snapshot(raw, NOW)
    assert result["nodes"][0]["status"] == expected


def test_unknown_fields_are_not_inferred_from_names():
    raw = read_demo()
    raw["providers"] = []
    raw["threads"] = [{**raw["threads"][0], "title": "Claude Codex GPT", "model": None}]
    node = T3Projection("local").snapshot(raw, NOW)["nodes"][0]
    assert node["session"]["provider"] is None
    assert node["session"]["model"] is None


def test_disconnect_staleness_recovery_and_stable_layout():
    raw = read_demo()
    adapter = T3Projection("local")
    first = adapter.snapshot(raw, NOW)
    down = adapter.snapshot(None, NOW + 30)
    assert down["nodes"] and all(n["status"] == "STALE" for n in down["nodes"])
    stale = adapter.snapshot(raw, NOW + 301)
    assert (
        next(n for n in stale["nodes"] if n["session"]["thread_id"] == "demo-codex")[
            "status"
        ]
        == "STALE"
    )
    raw["threads"][0]["updatedAt"] = "2026-10-22T20:06:00Z"
    recovered = adapter.snapshot(raw, NOW + 360)
    assert (
        next(
            n for n in recovered["nodes"] if n["session"]["thread_id"] == "demo-codex"
        )["status"]
        == "IN_PROGRESS"
    )
    assert [(n["id"], n["layout"]) for n in first["nodes"]] == [
        (n["id"], n["layout"]) for n in recovered["nodes"]
    ]


def test_unavailable_start_and_duplicate_delivery():
    adapter = T3Projection("local")
    assert adapter.snapshot(None, NOW)["nodes"] == []
    raw = read_demo()
    raw["threads"] += copy.deepcopy(raw["threads"])
    result = adapter.snapshot(raw, NOW)
    assert len(result["nodes"]) == 5
    assert len(result["edges"]) == 1
    assert result == adapter.snapshot(raw, NOW)


def test_forks_not_delegation_and_no_fabricated_links():
    raw = read_demo()
    raw["threads"][1]["relationshipToParent"] = "fork"
    raw["threads"][0]["linkedPullRequest"] = {"url": "https://evil.example/token"}
    result = T3Projection("local").snapshot(raw, NOW)
    assert result["edges"] == []
    assert all(not n["session"]["source_links"] for n in result["nodes"])


def test_safe_projection_and_missing_time():
    raw = read_demo()
    raw["threads"] = [
        {
            **raw["threads"][0],
            "updatedAt": None,
            "title": "API_KEY=private sk-secretvalue",
            "prompt": "never publish",
            "env": {"secret": "private"},
        }
    ]
    result = T3Projection("local").snapshot(raw, NOW)
    assert result["nodes"][0]["status"] == "STALE"
    assert "private" not in json.dumps(result)
    assert "never publish" not in json.dumps(result)
    assert safe_text("Bearer abc") == "[redacted]"


class Session:
    def __init__(self):
        self.calls = []
        self.raw = read_demo()

    async def list_tools(self, cursor=None):
        return NS(
            tools=[
                NS(name=n, inputSchema={"properties": {"includeSubagents": {}}})
                for n in READ_TOOLS
            ],
            nextCursor=None,
        )

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        if name == "t3_environment_read":
            data = {
                "serverVersion": "tested-contract",
                "preferences": {"secret": "never publish"},
            }
        elif name == "orchestrator_capabilities":
            data = {"providers": self.raw["providers"]}
        elif name == "t3_project_list":
            data = {"projects": [{"id": "p", "title": "Test"}], "nextCursor": None}
        elif name == "t3_thread_list":
            data = {"threads": self.raw["threads"], "nextCursor": None}
        else:
            thread = next(
                t for t in self.raw["threads"] if t["threadId"] == args["threadId"]
            )
            data = {
                "thread": {**thread, "latestRunId": "r"},
                "recentRuns": [
                    {
                        "runId": "r",
                        "model": thread["model"],
                        "providerInstanceId": thread["providerInstanceId"],
                    }
                ],
                "items": [{"text": "never publish"}],
            }
        return NS(isError=False, structuredContent=data, content=[])


def test_mcp_contract_readonly_and_payload_allowlist():
    session = Session()
    raw = asyncio.run(collect(session))
    assert {name for name, _ in session.calls} <= READ_TOOLS
    assert any(args.get("includeSubagents") is True for _, args in session.calls)
    assert "never publish" not in json.dumps(raw)
    result = T3Projection("local").snapshot(raw, NOW)
    validate_activity(result)
    assert {n["session"]["provider"] for n in result["nodes"]} == {
        "Claude Code",
        "Codex",
    }


def test_incompatible_server():
    session = Session()

    async def missing(cursor=None):
        return NS(tools=[], nextCursor=None)

    session.list_tools = missing
    with pytest.raises(ValueError, match="unsupported"):
        asyncio.run(collect(session))


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/mcp",
        "http://user:secret@localhost/mcp",
        "https://example.com/mcp?token=secret",
        "https://example.com/other",
    ],
)
def test_unsafe_urls_rejected(url):
    with pytest.raises(ValueError):
        validate_url(url)


def test_token_permissions(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ingest.t3_mcp.credential_path", lambda _: tmp_path / "tokens.json"
    )
    store = TokenStore("https://example.com/mcp")
    store.save("tokens", NS(model_dump=lambda **_: {"access_token": "private"}))
    assert store.path.stat().st_mode & 0o777 == 0o600
    store.path.chmod(0o644)
    with pytest.raises(ValueError):
        store.read()


def test_daemon_change_detection_and_local_server(tmp_path):
    from ingest.live import create_http_server

    daemon = T3Daemon(
        activity_path=tmp_path / "activity.json",
        static_dir=tmp_path,
        cache_dir=tmp_path,
        bots=[],
        demo=True,
    )
    daemon.run_poll_cycle()
    before = daemon.activity_etag()
    daemon.run_poll_cycle()
    assert daemon.activity_etag() == before
    with pytest.raises(ValueError):
        create_http_server(daemon, host="0.0.0.0")
    server = create_http_server(daemon, port=0)
    assert server.server_address[0] == "127.0.0.1"
    server.server_close()


def test_pagination_and_repeated_cursor_rejected():
    session = Session()
    original = session.call_tool

    async def paged(name, args):
        if name == "t3_project_list":
            return NS(
                isError=False,
                structuredContent={"projects": [], "nextCursor": 0},
                content=[],
            )
        return await original(name, args)

    session.call_tool = paged
    with pytest.raises(ValueError, match="repeated cursor"):
        asyncio.run(collect(session))


def test_malformed_snapshot_preserves_last_verified_state():
    projection = T3Projection("local")
    first = projection.snapshot(read_demo(), NOW)
    with pytest.raises((KeyError, TypeError)):
        projection.snapshot({"threads": [None], "providers": []}, NOW)
    recovered = projection.snapshot(None, NOW + 30)
    assert [n["id"] for n in recovered["nodes"]] == [n["id"] for n in first["nodes"]]


def test_daemon_retains_snapshot_on_mcp_error(tmp_path, monkeypatch):
    raw = read_demo()

    async def good(_url, **_kwargs):
        return raw

    async def bad(_url, **_kwargs):
        raise RuntimeError("secret upstream body must never be logged")

    monkeypatch.setattr("ingest.t3_live.connect", good)
    daemon = T3Daemon(
        activity_path=tmp_path / "activity.json",
        static_dir=tmp_path,
        cache_dir=tmp_path,
        bots=[],
        clock=lambda: NOW,
    )
    daemon.run_poll_cycle()
    first = json.loads(daemon.activity_body())
    monkeypatch.setattr("ingest.t3_live.connect", bad)
    daemon.run_poll_cycle()
    failed = json.loads(daemon.activity_body())
    assert [n["id"] for n in failed["nodes"]] == [n["id"] for n in first["nodes"]]
    assert failed["meta"]["t3"]["connection"] == "unavailable"
    assert "secret" not in json.dumps(daemon.health().to_json())
    monkeypatch.setattr("ingest.t3_live.connect", good)
    daemon.run_poll_cycle()
    assert json.loads(daemon.activity_body())["meta"]["t3"]["connection"] == "connected"


def test_http_demo_snapshot_etag_health_and_readonly(tmp_path):
    import threading
    import urllib.error
    import urllib.request

    from ingest.live import create_http_server

    daemon = T3Daemon(
        activity_path=tmp_path / "activity.json",
        static_dir=tmp_path,
        cache_dir=tmp_path,
        bots=[],
        demo=True,
    )
    daemon.run_poll_cycle()
    server = create_http_server(daemon, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}"
    try:
        with urllib.request.urlopen(url + "/activity.json") as response:
            assert json.load(response)["meta"]["t3"]["mode"] == "demo"
            etag = response.headers["ETag"]
        with pytest.raises(urllib.error.HTTPError) as unchanged:
            urllib.request.urlopen(
                urllib.request.Request(
                    url + "/activity.json", headers={"If-None-Match": etag}
                )
            )
        assert unchanged.value.code == 304
        with pytest.raises(urllib.error.HTTPError) as write:
            urllib.request.urlopen(
                urllib.request.Request(url + "/activity.json", method="POST")
            )
        assert write.value.code == 405
        with urllib.request.urlopen(url + "/healthz") as response:
            assert json.load(response)["errors"] == []
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_unchanged_thread_reads_are_cached():
    session = Session()
    cache = {}
    first = asyncio.run(collect(session, cache))
    session.calls.clear()
    second = asyncio.run(collect(session, cache))
    assert first == second
    assert not any(name == "t3_thread_read" for name, _ in session.calls)
    session.raw["threads"][0]["status"] = "completed"
    session.calls.clear()
    asyncio.run(collect(session, cache))
    assert sum(name == "t3_thread_read" for name, _ in session.calls) == 1
