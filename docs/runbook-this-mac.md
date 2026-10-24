# Runbook — this MacBook (written during Mission 003)

State on first inspection: no runtime, collector, publisher state, machine identity or private-feed directory existed here; T3 Code
(Beta) 0.1.x is running and its MCP (127.0.0.1:3773) answers 401 until OAuth login; `claude` (two accounts), `codex`, `cursor-agent`
and `gh` are logged in. The private feed was last written by the **other** Mac and carries no owner record. Nothing below starts a background
service; every step marked **[approval]** needs the owner.

## 1. Look (read-only, safe any time)
    python -m tools.machine_doctor            # PASS/WARN/FAIL/UNKNOWN; never prints tokens or emails
    python -m tools.bootstrap_mac --check     # what `install` would create
    python -m tools.quota show                # five separate quota pools
    python -m tools.publisher_ownership status --offline

## 2. Prepare this Mac (creates files, starts nothing)
    python -m tools.bootstrap_mac --dry-run --label "Mac B"     # prints the plan, writes nothing
    python -m tools.bootstrap_mac install --label "Mac B"       # config dir 0700, anonymous id (role READER), state dirs, stable runtime

## 3. Collect (read-only)
- **T3 sessions [approval: browser sign-in]:** copy the MCP URL from T3 -> Settings -> Connections, then
  `python -m ingest.t3_mcp login --url <that URL>` and approve **Read only**. Credentials stay on this Mac (`~/.config/agent-mindmap/`, 0600); never copy them between Macs.
- **Codex quota:** `python -m tools.quota collect` (supported `codex app-server account/rateLimits/read`; no model call).
- **Cursor:** `cursor-agent about` gives the plan only; usage is manual: `python -m tools.quota manual set --pool cursor-premium ...`.
- **Devin Free:** manual only: `python -m tools.quota manual set --pool devin-free ...`.
- **Claude 1 / Claude 2 [approval: edits each account's settings.json]:** Claude Code exposes `rate_limits` to a status-line command only inside a running session.
  Preview (writes nothing): `python -m tools.quota claude-statusline-snippet --alias claude-1 --config-dir ~/.claude` and `... --alias claude-2 --config-dir ~/.claude_second`;
  apply with `install-claude-statusline ... --apply --yes-i-approved-settings-change`. Readings appear after the first reply in a session and expire after 15 minutes.

## 4. Publishing the private feed (one Mac at a time)
This Mac is a **reader** by default and never writes. To make it the publisher **[approval]**:
1. Old Mac (if reachable): `python -m tools.publisher_ownership release`.
2. This Mac: `python -m tools.publisher_ownership handover` (prints the exact steps), then `claim` (an unexpired foreign lease needs `--force-takeover --confirm-takeover-of <token>`).
3. Review once: `python -m tools.publish_observability --collector-url http://127.0.0.1:8799/activity.json --review-dir ~/.local/share/agent-mindmap-review`.
Background jobs stay off until you run `python -m tools.runtime_install activate --yes-i-approved-persistent-collector` **[approval]**.

## 5. Dashboard
    python -m ingest.live --source t3 --t3-url <MCP URL> --port 8799      # or the demo: --source t3-demo --demo-replay
The page loads `/activity.json` and `/observability.json` (machine, collector, feed owner, five quota pools). The public Pages site only ever publishes the synthetic demo fixture.

## 6. One-time owner actions still open
- `gh auth refresh -h github.com -s workflow`, then `git apply docs/evidence/pages-observability-demo.patch` (workflow edits need the `workflow` scope).
- T3 OAuth login (3), Claude status-line approvals (3), publisher claim (4), LaunchAgent activation (4).
