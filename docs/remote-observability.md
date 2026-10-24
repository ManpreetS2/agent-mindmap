# Hosted Agent Mindmap: public demo and private T3 observations

## Deployment model

The public GitHub Pages site must never expose live T3 private session titles, project names, credentials, local paths, or raw thread data. The public workflow (in .github/workflows/pages-demo.yml) builds the EXISTING React dashboard, then generates a synthetic activity.json from fixtures/t3-demo.json. The site is marked DEMO.

The workflow starts from the existing unmerged PR #36 code on branch feat/pages-observability-preview. It does NOT merge or enable local agents.

**Required one-time GitHub action:**
1. Open https://github.com/ManpreetS2/agent-mindmap/settings/pages
2. Under Build and deployment, choose **GitHub Actions** as the Source.
3. Rerun the latest Agent Mindmap Pages preview workflow or push another commit to the preview branch.
4. Verify a green deployment and visit https://manpreets2.github.io/agent-mindmap/
5. Confirm the banner says DEMO and no real account data appears.

The GitHub Pages build uses Vite's /agent-mindmap/ base path; the frontend's activity transport uses Vite BASE_URL for the corresponding activity.json request.

GitHub Pages hosts only static files. It cannot contact the Python collector at localhost on your Mac. Making the Pages site public is not approval to make private T3 activity public.

## Local T3 read-only collector

From a local clone of this branch, use Python 3.12+ and install dependencies:

    python -m pip install -e '.[dev,t3]'

Use the MCP URL actually copied from T3 Code -> Settings -> Connections, rather than assuming the example URL below is correct. Authorize the mind-map OAuth client with READ ONLY permissions.

    mkdir -p "$HOME/.local/share/agent-mindmap-collector"
    python -m ingest.t3_mcp login --url http://127.0.0.1:3773/mcp
    python -m ingest.live --source t3 --t3-url http://127.0.0.1:3773/mcp \
      --port 8799 \
      --activity-out "$HOME/.local/share/agent-mindmap-collector/activity.json"

In a second terminal, export a bounded PRIVATE summary:

    python tools/export_observability.py \
      --input "$HOME/.local/share/agent-mindmap-collector/activity.json"

The exporter validates the complete source against schema/activity.schema.json and writes only to ~/.local/share/agent-mindmap-private-feed, with owner-only file permissions:

- latest.json — structured current T3 session statuses, task summaries, timestamps and evidenced delegations.
- summary.md — human/ChatGPT-readable account and task status summary.

It **does not push or upload anything**. It refuses demo snapshots, omits raw thread IDs, prompts, messages, logs, and session credentials, and rejects output inside the public agent-mindmap repository. No T3 quota percentages are exposed by this collector. They stay marked unsupported rather than guessed.

The official T3 MCP can show Claude/Codex sessions it exposes, but cannot reliably distinguish the two Claude memberships after this projection, nor can it automatically read unrelated Cursor/Devin sessions. A missing agent is NOT proof that the account is idle. Actual quota routing needs a separately authorized per-account quota source.

## Making the private feed remotely readable to ChatGPT

Create a SEPARATE PRIVATE GitHub repository for the two exported files, such as ManpreetS2/agent-observability-private. Review the exported content and GitHub permission settings before publishing. Only copy latest.json and summary.md, never the raw collector activity.json.

Authorize the GitHub app connected to ChatGPT to access that private repository. Do not assume newly created private repositories are already accessible.

Use a dedicated least-privilege publishing credential (or approved local gh login). Do not reuse the Agent Control tokens scoped to agent-mindmap. Do not automate publishing until the private destination, connector access, and redaction have been verified.

For a future approved publisher, prefer up to one state-change snapshot every 3–5 minutes with no redundant Git commits, and let ChatGPT examine the snapshot's observed_at and exported_at for staleness. If the Mac is off, monitoring will stop; never claim the previous snapshot is fresh.

## Done criteria

1. GitHub Pages setup is enabled and deployment succeeds with synthetic data.
2. Web app loads its generated activity.json at /agent-mindmap/activity.json (not /activity.json).
3. No private metadata is included in the publicly hosted files.
4. Live Mac T3 read-only collection actually succeeds.
5. The PRIVATE GitHub feed is created, its export is reviewed, and the user's ChatGPT GitHub connection can read it.
6. Only after owner review, enable timed private publishing.

The public site and private feed have separate disclosure rules. Do not describe the DEMO site as live T3 activity.


## Private publisher (implemented)

Destination: `ManpreetS2/agent-observability-private` (PRIVATE, no Pages, issues/wiki/projects off). Only
`latest.json` and `summary.md` are ever written, to `main`, through your own `gh` login (never Agent Control tokens).

    # review exactly what would be uploaded (no network writes); files land in ~/.local/share/agent-mindmap-review
    python -m tools.publish_observability --collector-url http://127.0.0.1:8799/activity.json \
      --review-dir ~/.local/share/agent-mindmap-review
    # one upload (after you approve the review)
    python -m tools.publish_observability --collector-url http://127.0.0.1:8799/activity.json --for-real

Guarantees, each covered by `tests/test_publish_observability.py` against a real local git remote:
the destination must be exactly that repo and PRIVATE; demo, empty or invalid sources never publish; a second,
independent secret/path scan blocks the upload; the staged files must be inside the two-file allowlist; remote
symlinks or malformed feeds abort; no git hooks or templates run; a rejected push re-clones and retries once;
one publisher at a time (flock); at least 3 min between uploads; exponential backoff after failures; an unchanged
snapshot is not committed again (a 15 min heartbeat re-stamps it); if the collector disappears after a success,
an explicit `connection: unavailable` feed with no sessions is published once (UNKNOWN, never idle).
Diagnostics (`last_success_at`, `last_error`, failure count) live in `~/.local/state/agent-mindmap-publisher/state.json`
and never contain feed content.

### Quota pools

`quota.pools` always lists `claude-1`, `claude-2`, `cursor-premium`, `devin-free`, `codex` separately. They are
`UNKNOWN` unless you create `~/.config/agent-mindmap/quota-snapshots.json`:

    {"pools": {"claude-1": {"source": "manual: claude.ai usage page", "observed_at": "2026-10-23T19:00:00Z",
                            "five_hour_used_pct": 40, "weekly_used_pct": 12}}}

Entries need a source and timestamp; they become `STALE_MANUAL` after 24 h; out-of-range or future-dated entries
are ignored. No credential store or undocumented endpoint is read, and pools are never added together.

### Background publishing (off until you approve)

    python -m tools.publisher_launchd install    # writes the LaunchAgent plist, does not load it
    python -m tools.publisher_launchd enable --yes-i-approved-live-publishing
    python -m tools.publisher_launchd status     # last success / last error, no feed content
    python -m tools.publisher_launchd disable

### Remote access to the real dashboard

Not public. Options in order of preference: (1) ask ChatGPT, which reads the private feed; (2) T3 Connect's own
authenticated remote access to T3 itself; (3) `ssh -L 8799:127.0.0.1:8799 <your-mac>` from another machine. Never
tunnel or expose port 3773 (the MCP endpoint) or 8799 publicly, and do not copy the collector's activity.json into
any Pages build.
