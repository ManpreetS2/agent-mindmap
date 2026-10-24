# Evidence package — runtime / portability (recon, 2026-10-24, PR #38 @ 59bdfd9 + contract commit)

Environment facts (this Mac): macOS 27.0.1 arm64; Node 24.19; Python 3.12.1 at `/usr/local/bin/python3` (NOT `~/.local/bin/python3.12`);
`gh` at `~/.local/bin/gh` (logged in, keyring); `codex` 0.164.0 and `cursor-agent` at `~/.local/bin`; `t3` CLI is NOT on PATH (T3 Code (Beta).app 0.1.2 in /Applications);
T3 MCP listens on 127.0.0.1:3773 and answers 401 until OAuth login (browser approval needed; do not automate). No runtime, collector, publisher state, private-feed dir or
`~/.config/agent-mindmap` exists here yet. No LaunchAgents for mindmap collector/publisher are loaded (two unrelated legacy jobs `com.manpreet.mindmap.{devserver,refresh}` exist: do NOT touch).
Private feed (`ManpreetS2/agent-observability-private`, PRIVATE, branch main) was last written 2026-10-24T05:06Z by the OTHER Mac and has no machine identity field.

Portability hazards found with rg (file:line):
- tools/runtime_install.py:42 `PYTHON = AGENT_MINDMAP_PYTHON or ~/.local/bin/python3.12` (does not exist here) ; :43 `PATH_ENV` hardcodes /opt/homebrew:/usr/local; :37 COLLECTOR_LABEL `com.manpreets2.*`; :40 PORT 8799 fixed.
- tools/publisher_launchd.py:25-28,45 LABEL, COLLECTOR_URL 8799, PATH hardcoded; :26 plist path under ~/Library/LaunchAgents.
- tools/run_collector.py:17-18 fixed PORT 8799 and T3_URL http://127.0.0.1:3773/mcp (T3 URL differs per install: docs say copy the MCP URL from T3 Settings -> Connections).
- tools/publish_observability.py: DESTINATION constant; SENSITIVE regex already rejects /Users/, /home/, .t3, .config, .ssh; lock = flock on <state>/publisher.lock; state at ~/.local/state/agent-mindmap-publisher/state.json; push_snapshot re-clones and retries once (this retry is where an ownership check must run, after the fresh clone and before writing).
- tests/test_publisher_qa.py, tests/test_publish_observability.py use a REAL local git remote (pattern to copy for two-machine race tests); tests/test_runtime_install.py monkeypatches launchctl/lsof.
- Existing tests that assert launchd behaviour: tests/test_runtime_install.py, tests/test_publish_observability.py (opt-in launchd job). Nothing may call real `launchctl bootstrap` in tests.
- Feed writer: tools/export_observability.py `make_feed()` (commander-owned; will gain optional `machine`/`publisher` args). Keys today: format, source, observed_at, exported_at, freshness, connection, trusted_until, reader_guidance, quota, limitations, status_counts, sessions, delegations. TRUST_WINDOW_SEC=900, HEARTBEAT_SEC=540, MIN_INTERVAL_SEC=180.
- docs: docs/remote-observability.md (runtime + publisher sections), docs/t3-integration.md.
