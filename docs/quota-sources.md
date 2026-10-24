# Quota sources (`tools/quota`)

Five **separate** pools, in this order: `claude-1`, `claude-2`, `cursor-premium`, `devin-free`, `codex`.
Verified data only; everything else is an honest `UNKNOWN`/`UNSUPPORTED`/`ERROR`. Collection makes **zero LLM calls**
and never reads credential stores (Keychain, `~/.codex/auth.json`, Claude credentials).

| Pool | Source | Status on this Mac |
| --- | --- | --- |
| codex | `codex app-server` stdio JSON-RPC: `initialize`, `initialized`, `account/rateLimits/read` only (enforced allowlist) | **Verified** (`python -m tools.quota collect`) — plan, 5h + weekly windows |
| claude-1 / claude-2 | Claude Code status-line tap (`rate_limits.five_hour|seven_day`) | **Supported, not enabled** — needs owner approval below; UNKNOWN until a Claude Code session runs with the tap |
| cursor-premium | `cursor-agent about --format json` → plan only | Plan verified, usage **UNSUPPORTED**; add usage with `manual set` |
| devin-free | none | UNKNOWN unless entered manually |
| T3 UI | Usage → Limits is visible in the T3 app, not exposed through the read-only MCP | UNSUPPORTED, `supported_programmatically=false` (`tools.quota.models.T3_UI_SOURCE`) |

## Commands
```
python -m tools.quota collect                 # codex + cursor only
python -m tools.quota show [--json]           # the five pools
python -m tools.quota manual set --pool devin-free --window weekly --used-pct 20 \
    --resets-at 2026-10-30T00:00:00Z --source "Devin UI" --observed-at 2026-10-24T06:00:00Z
python -m tools.quota manual clear --pool devin-free
```
Library: `tools.quota.api.pools(now=None, state_dir=None)`; `to_feed_pools(pools)` gives the backward-compatible
private-feed dict (old keys `five_hour_used_pct`, `weekly_used_pct`, `status`, `source`, `observed_at`, `note` + `windows`).

## Enabling the Claude status-line taps (needs the owner's approval)
Each Claude account is a separate `CLAUDE_CONFIG_DIR`, so each needs its own tap. Nothing has been applied.
Preview (dry run, writes nothing):
```
python -m tools.quota install-claude-statusline --alias claude-1 --config-dir ~/.claude
python -m tools.quota install-claude-statusline --alias claude-2 --config-dir ~/.claude_second
```
Apply (merges `statusLine` into `settings.json`, keeps a timestamped `settings.json.bak-<time>`):
```
python -m tools.quota install-claude-statusline --alias claude-1 --config-dir ~/.claude --apply --yes-i-approved-settings-change
python -m tools.quota install-claude-statusline --alias claude-2 --config-dir ~/.claude_second --apply --yes-i-approved-settings-change
```
`claude-statusline-snippet --alias A --config-dir D` prints the JSON to paste by hand. If a `statusLine` already exists the
installer refuses (it never overwrites); chain the printed command from your existing script. Run the commands from the repo
(or runtime) checkout so `python -m tools.quota` resolves; the snippet embeds absolute paths.

The tap keeps only `rate_limits.{five_hour,seven_day}.{used_percentage,resets_at}`; session id, cwd, cost, prompt and
transcript data are discarded. It always exits 0 and never breaks the status line. Windows are optional and handled
independently; a payload with no valid window leaves the previous reading untouched.

## Expiry rules (computed at read time)
- Live readings: valid 15 min, and never past any window's `resets_at`. Manual: 24 h (the oldest window governs).
- Expired → `STALE`: values stay as history, never `VERIFIED`. A window whose `resets_at` has passed is dropped.
- No reading → `UNKNOWN`; known-unsupported → `UNSUPPORTED` + reason; failed collection → `ERROR` + reason, no values.
- Preference when several exist: fresh live > fresh manual > ERROR > UNSUPPORTED > STALE > UNKNOWN. Cursor's plan is kept alongside a manual usage reading.
- Rejected: NaN/inf, percentages outside 0..100, malformed or timezone-less timestamps, `observed_at` > 60 s in the future, duplicate windows.
- Codex `ordinaryUsageAllowed`: `false` is shown as a reason; `null` is unknown and never inferred; percentages are never rewritten.

## Cross-account guard
One file per alias in the state dir (default `~/.local/state/agent-mindmap-quota/`, env `AGENT_MINDMAP_QUOTA_DIR`; dir 0700, files
0600, atomic writes). Every reading carries its alias; a write under another alias, or a file whose embedded alias differs, is
rejected. The Claude tap also takes `--expect-config-dir` and writes nothing if the process's `CLAUDE_CONFIG_DIR` (default
`~/.claude`) is a different account. Account ids, emails and tokens are never stored (allowlisted keys only).
