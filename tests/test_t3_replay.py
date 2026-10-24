"""Deterministic replay tests: no T3, model, GitHub or other external service."""

import json
from unittest.mock import Mock

import pytest

from ingest.build import validate_activity
from ingest.live import main
from ingest.t3 import DEMO_REPLAY_STAGES, demo_replay
from ingest.t3_live import T3Daemon

EXPECTED = [
    ("IDLE", "IDLE"),
    ("IDLE", "IDLE"),
    ("IN_PROGRESS", "IDLE"),
    ("IN_PROGRESS", "BLOCKED"),
    ("IN_PROGRESS", "IN_PROGRESS"),
    ("BLOCKED", "IN_PROGRESS"),
    ("BLOCKED", "FAILED"),
    ("IN_PROGRESS", "IN_PROGRESS"),
    ("DONE", "DONE"),
    ("IDLE", "IDLE"),
]


@pytest.fixture
def replay(tmp_path, monkeypatch):
    forbidden = Mock(side_effect=AssertionError("Replay tried an external source"))
    monkeypatch.setattr("ingest.t3_live.connect", forbidden)
    monkeypatch.setattr("ingest.t3_live.read_demo", forbidden)
    monkeypatch.setattr("ingest.live.poll_github", forbidden)
    clock = [1000.0]
    daemon = T3Daemon(
        activity_path=tmp_path / "activity.json",
        static_dir=tmp_path,
        cache_dir=tmp_path,
        bots=[],
        demo=True,
        replay=True,
        demo_step_sec=5,
        clock=lambda: clock[0],
    )
    return daemon, clock, forbidden


def snapshot(daemon):
    daemon.run_poll_cycle()
    data = json.loads(daemon.activity_body())
    validate_activity(data)
    return data


@pytest.mark.parametrize("stage", range(10))
def test_every_transition_and_synthetic_contract(replay, stage):
    daemon, clock, forbidden = replay
    clock[0] += stage * 5
    data = snapshot(daemon)
    states = {n["session"]["provider"]: n["status"] for n in data["nodes"]}
    assert (states["Codex"], states["Claude Code"]) == EXPECTED[stage]
    assert data["meta"]["t3"]["mode"] == "demo"
    assert data["meta"]["t3"]["replay"]["stage"] == stage
    assert len(data["nodes"]) == 2
    assert len(data["edges"]) == (1 if 3 <= stage <= 8 else 0)
    if data["edges"]:
        nodes = {n["session"]["provider"]: n["id"] for n in data["nodes"]}
        assert data["edges"][0]["source"] == nodes["Codex"]
        assert data["edges"][0]["target"] == nodes["Claude Code"]
    assert all("simulated" in n["session"]["model"] for n in data["nodes"])
    assert all("[SIMULATED]" in n["label"] for n in data["nodes"])
    assert all("SIMULATED replay" in e["raw"] for e in data["events"])
    assert all(not n["session"]["source_links"] for n in data["nodes"])
    forbidden.assert_not_called()


def test_stable_ids_etags_reset_and_no_accumulation(replay):
    daemon, clock, forbidden = replay
    first = snapshot(daemon)
    ids = [(n["id"], n["layout"]) for n in first["nodes"]]
    previous_etag = daemon.activity_etag()
    for tick in range(1, 41):
        clock[0] = 1000 + tick * 5
        data = snapshot(daemon)
        assert [(n["id"], n["layout"]) for n in data["nodes"]] == ids
        assert len({n["id"] for n in data["nodes"]}) == 2
        assert len({e["id"] for e in data["edges"]}) <= 1
        assert len(data["events"]) <= 3
        assert data["meta"]["t3"]["replay"]["cycle"] == tick // 10
        assert daemon.activity_etag() != previous_etag
        previous_etag = daemon.activity_etag()
        clock[0] += 0.25
        assert snapshot(daemon) == data
        assert daemon.activity_etag() == previous_etag
        if tick % 10 in {0, 9}:
            assert not data["edges"]
            assert all(n["status"] == "IDLE" for n in data["nodes"])
    assert len(daemon._projection.slots) == 2
    forbidden.assert_not_called()


def test_seekable_pure_function_and_process_restart(replay):
    daemon, clock, _ = replay
    first = snapshot(daemon)
    for elapsed in [0, 4.999, 5, 19.5, 49.999, 50, 50000]:
        assert demo_replay(elapsed) == demo_replay(elapsed)
    assert demo_replay(4.999)[1]["stage"] == 0
    assert demo_replay(5)[1]["stage"] == 1
    assert demo_replay(50)[1]["cycle"] == 1
    clock[0] += 500
    restarted = T3Daemon(
        activity_path=daemon.activity_path,
        static_dir=daemon.static_dir,
        cache_dir=daemon.cache_dir,
        bots=[],
        demo=True,
        replay=True,
        clock=lambda: clock[0],
    )
    assert snapshot(restarted) == first
    assert len(DEMO_REPLAY_STAGES) == 10


@pytest.mark.parametrize("step", [0, 1, -5, float("nan"), float("inf"), 301])
def test_invalid_replay_timing_fails_before_start(step):
    with pytest.raises(ValueError):
        demo_replay(0, step)


@pytest.mark.parametrize("source", ["legacy", "t3"])
def test_cli_cannot_enable_replay_in_real_sources(source):
    with pytest.raises(SystemExit) as error:
        main(["--source", source, "--demo-replay"])
    assert error.value.code == 2


def test_live_daemon_cannot_enable_replay(tmp_path):
    with pytest.raises(ValueError, match="t3-demo"):
        T3Daemon(
            activity_path=tmp_path / "activity.json",
            static_dir=tmp_path,
            cache_dir=tmp_path,
            bots=[],
            demo=False,
            replay=True,
        )


def test_static_demo_remains_static(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ingest.t3_live.connect", Mock(side_effect=AssertionError("network"))
    )
    clock = [1000]
    daemon = T3Daemon(
        activity_path=tmp_path / "activity.json",
        static_dir=tmp_path,
        cache_dir=tmp_path,
        bots=[],
        demo=True,
        clock=lambda: clock[0],
    )
    before = snapshot(daemon)
    clock[0] += 500
    assert snapshot(daemon) == before
    assert "replay" not in before["meta"]["t3"]
    assert len(before["nodes"]) == 5


def test_http_replay_changes_etags_without_page_reload(replay):
    import threading
    import urllib.error
    import urllib.request

    from ingest.live import create_http_server

    daemon, clock, _ = replay
    snapshot(daemon)
    server = create_http_server(daemon, port=0)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    url = f"http://127.0.0.1:{server.server_port}/activity.json"
    try:
        with urllib.request.urlopen(url) as response:
            etag = response.headers["ETag"]
            assert json.load(response)["meta"]["t3"]["replay"]["stage"] == 0
        with pytest.raises(urllib.error.HTTPError) as unchanged:
            urllib.request.urlopen(
                urllib.request.Request(url, headers={"If-None-Match": etag})
            )
        assert unchanged.value.code == 304
        clock[0] += 15
        snapshot(daemon)
        with urllib.request.urlopen(
            urllib.request.Request(url, headers={"If-None-Match": etag})
        ) as response:
            delegated = json.load(response)
            assert response.status == 200
            assert response.headers["ETag"] != etag
            assert len(delegated["edges"]) == 1
        clock[0] += 30
        snapshot(daemon)
        with urllib.request.urlopen(url) as response:
            reset = json.load(response)
            assert reset["meta"]["t3"]["replay"]["stage"] == 9
            assert reset["edges"] == []
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
