"""T3 source for the existing localhost daemon and activity transport."""

from __future__ import annotations

import asyncio
import hashlib
import json
import threading
from dataclasses import dataclass, field

from .build import write_activity
from .live import LiveDaemon, _etag_for_body, _iso_now
from .t3 import T3Projection, demo_replay, read_demo
from .t3_mcp import connect


@dataclass
class T3Daemon(LiveDaemon):
    t3_url: str = ""
    demo: bool = False
    poll_sec: float = 15
    stale_after: float = 300
    replay: bool = False
    demo_step_sec: float = 5
    _replay_started: float = field(init=False)
    _projection: T3Projection = field(init=False)
    _read_cache: dict = field(default_factory=dict, init=False)

    def __post_init__(self):
        if self.replay and not self.demo:
            raise ValueError("Demo replay requires the t3-demo source")
        if self.replay:
            demo_replay(
                0, self.demo_step_sec
            )  # Validate before starting a thread/server.
        self._replay_started = self.clock()
        source = (
            "t3-demo-replay"
            if self.replay
            else "t3-demo"
            if self.demo
            else "t3-" + hashlib.sha256(self.t3_url.encode()).hexdigest()[:16]
        )
        self._projection = T3Projection(
            source,
            demo=self.demo,
            stale_after=self.stale_after,
            poll_sec=self.demo_step_sec if self.replay else self.poll_sec,
        )

    def run_poll_cycle(self):
        try:
            replay_meta = None
            if self.replay:
                raw, replay_meta, now = demo_replay(
                    self.clock() - self._replay_started, self.demo_step_sec
                )
            else:
                raw = (
                    read_demo()
                    if self.demo
                    else asyncio.run(
                        asyncio.wait_for(
                            connect(self.t3_url, cache=self._read_cache), timeout=60
                        )
                    )
                )
                # DEMO freezes a documented observation time; no fictional live heartbeat.
                now = 1792699200 if self.demo else self.clock()
            activity = self._projection.snapshot(raw, now)
            if replay_meta is not None:
                activity["meta"]["t3"]["replay"] = replay_meta
                activity["project"] = "BlockForge · SIMULATED"
                for event in activity["events"]:
                    event["raw"] = event["raw"].replace(
                        "Simulated", "SIMULATED replay", 1
                    )
        except Exception:  # noqa: BLE001 — redact upstream error payloads
            activity = self._projection.snapshot(None, self.clock())
        if activity["meta"]["t3"]["connection"] == "connected" and not self.demo and not self.replay:
            with self._lock:
                self._health.last_t3_poll = _iso_now(self.clock)
        comparable = {k: v for k, v in activity.items() if k != "generated_at"}
        fp = hashlib.sha256(json.dumps(comparable, sort_keys=True).encode()).hexdigest()
        if fp == self._activity_fp:
            return
        write_activity(activity, self.activity_path)
        body = self.activity_path.read_bytes()
        with self._lock:
            self._activity_bytes = body
            self._activity_etag = _etag_for_body(body)
            self._activity_fp = fp
            self._health.last_build = _iso_now(self.clock)
            self._health.errors = (
                []
                if activity["meta"]["t3"]["connection"] == "connected"
                else ["T3 unavailable; last snapshot retained as stale"]
            )

    def start_polling(self):
        def loop():
            interval = (
                min(0.5, self.demo_step_sec / 4) if self.replay else self.poll_sec
            )
            while not self._stop.wait(interval):
                try:
                    self.run_poll_cycle()
                except Exception:  # noqa: BLE001 — redact upstream error payloads
                    self._append_error("T3 snapshot write failed")

        self._poll_thread = threading.Thread(
            target=loop, name="mindmap-t3", daemon=True
        )
        self._poll_thread.start()
