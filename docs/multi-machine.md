# Running Agent Mindmap on more than one Mac

Several Macs may run the **read-only collector** and the local dashboard. Exactly **one** Mac at a time publishes
`latest.json` / `summary.md` to the private feed (`ManpreetS2/agent-observability-private`). Ownership is explicit,
operator-controlled and fenced, so two Macs can never silently compete.

Nothing here starts a LaunchAgent, copies credentials or calls a model. Every command is plain Python.

## Concepts

| Thing | Where | Notes |
| --- | --- | --- |
| Machine identity | `~/.config/agent-mindmap/machine.json` (env `AGENT_MINDMAP_CONFIG_DIR`), dir 0700, file 0600 | `id` = `mac-` + 8 random hex, never from hostname/username/hardware; `label` is your choice ("Mac A"); `role` is `reader` (default) or `publisher` |
| Owner record | `publisher` object inside `latest.json` | `{machine_id,label,epoch,lease_expires_at,state:"active"\|"released"}`; additive, the two-file contract is unchanged |
| Lease | 20 min | every publish extends it (publishing runs at most every 3 min, heartbeat 9 min) |
| Epoch | integer | never changes while the owner publishes; every `claim` of a different owner bumps it by one |
| Local ownership record | `~/.local/state/agent-mindmap-publisher/state.json` → `ownership` | `owner`, `released` or `superseded` |

A Mac publishes only if **its local role is `publisher` AND** the freshly cloned remote feed allows it:

* no owner record, feed written < 20 min ago (an old publisher is still running) → **refuse** (needs `claim --force-takeover`)
* no owner record, older → `claim_required` (explicit `claim`, never automatic)
* owned by another Mac with an unexpired lease → **refuse**; expired → `claim_required`
* owned by me → publish; lease extended; epoch unchanged
* `state: "released"` → `claim_required` (a plain `claim`, no force)
* malformed feed / owner record, absurd lease → **refuse** (fail closed)

The check runs after every fresh clone, including the retry after a rejected push. The git push is the compare-and-swap:
two Macs racing from the same base cannot both win; the loser re-clones, re-decides and refuses.

Clocks: leases compare wall-clock times written by different Macs. Keep both on automatic time (NTP); the 20 min TTL
tolerates minutes of skew. A future-dated legacy feed counts as "fresh" (refuse).

## 1. Set up a new Mac (reader)

```bash
git clone https://github.com/ManpreetS2/agent-mindmap.git && cd agent-mindmap && git checkout <the branch/commit you deploy>
python3 -m tools.bootstrap_mac                              # read-only check of what is missing
python3 -m tools.bootstrap_mac install --dry-run --label "Mac B"
python3 -m tools.bootstrap_mac install --label "Mac B"      # idempotent; starts nothing
```

`install` finds a Python ≥ 3.12 itself (env `AGENT_MINDMAP_PYTHON`, the running interpreter, `PATH`, Homebrew, `~/.local/bin`),
builds the stable runtime from the **committed** code (clean tree required), creates a **reader** identity and state dirs.
Then, by hand:

1. Log in to the tools on this Mac yourself (`claude`, `codex`, `cursor-agent`, `gh auth login`). Credentials are never copied between Macs.
2. T3 once: copy the MCP URL from T3 Settings → Connections, run
   `python -m ingest.t3_mcp login --url <copied MCP URL>` and approve **read-only** in the browser. (If your T3 listens elsewhere, export
   `AGENT_MINDMAP_T3_URL=http://127.0.0.1:<port>/mcp` before staging the collector plist; loopback http only.)
3. `python -m tools.machine_doctor` (add `--json` for scripts). Fix every FAIL; read every WARN.

A reader runs the collector and the dashboard; its publisher job (if ever loaded) skips every run with exit 0 and writes nothing.

## 2. Designate the (first) publisher

On the Mac that should publish:

```bash
python -m tools.publisher_ownership status
python -m tools.publisher_ownership claim                   # legacy feed older than 20 min, released feed, or no feed
# legacy feed written < 20 min ago, i.e. the old publisher still runs: stop it first (see handover), or deliberately:
python -m tools.publisher_ownership claim --force-takeover --confirm-takeover-of legacy
```

`claim` rewrites only the `publisher` object in the existing `latest.json` (epoch = previous + 1; epoch 1 for a legacy feed),
sets the local role to `publisher` and clears failure/backoff state. With no feed yet it only sets the role; the first
publish creates the feed at epoch 1. Then enable timed publishing (needs your explicit approval flag):

```bash
python -m tools.publisher_launchd install
python -m tools.publisher_launchd enable --yes-i-approved-live-publishing
```

## 3. Handover, operator controlled

`python -m tools.publisher_ownership handover` prints this checklist.

**Old Mac → new Mac (both alive)**

| Old Mac | New Mac |
| --- | --- |
| `publisher_ownership status` | |
| `publisher_launchd disable` | |
| `publisher_ownership release` (feed gets `state:"released"`, role → reader) | |
| | `machine_doctor` (T3 login done, gh logged in) |
| | `publisher_ownership claim` (no force needed) |
| | `publisher_launchd install` + `enable --yes-i-approved-live-publishing` |
| `publisher_ownership status` → reader | `publisher_ownership status` → publisher, epoch + 1 |

Going back (**new → old**) is the same procedure with the roles swapped. The epoch only ever grows.

## 4. Recovery after a dead publisher

The old Mac is lost, asleep for good or unreachable and cannot `release`.

1. Wait for its lease to expire (20 min after its last publish). The feed meanwhile turns stale on its own (`trusted_until`, 15 min); readers must treat it as unknown.
2. On the replacement Mac: `publisher_ownership claim`. After expiry no force is needed.
3. In a hurry (lease still valid): `claim --force-takeover --confirm-takeover-of <machine id printed by the refused claim>`.
   The typed id must match the **current** owner, so a takeover cannot accidentally hit a feed that changed meanwhile.
4. If the old Mac comes back: its next run sees a higher epoch, refuses, records `superseded` in its local state and never writes.
   Clean it up with `publisher_ownership release` (it only demotes itself locally, because it is not the owner) and `publisher_launchd disable`.

Corrupt owner record (valid JSON): `claim --force-takeover --confirm-takeover-of corrupt`. If `latest.json` is not valid JSON at all,
every publisher fails closed; repair or delete that file in the private repo by hand (it is the only manual git step in this runbook).

## 5. "Two machines both think they own it"

Symptoms: `machine_doctor` FAILs `ownership` ("This Mac thinks it is the publisher but the feed says …") or `processes`
shows two publishers; `status` shows the feed owned by someone else.

* The feed's `publisher` object is the single source of truth, not either Mac's local role.
* The Mac that is **not** named in the feed: `publisher_launchd disable`, then `publisher_ownership release` (demotes locally). It cannot corrupt anything meanwhile: its publishes are refused after the fresh clone.
* The Mac named in the feed keeps going. If you actually prefer the other Mac, do a normal handover.
* If both show "owner" with the same epoch, someone edited the feed by hand; set it right with a forced `claim` on the Mac that should win.

## Failure behaviour

* **GitHub outage** (clone/push fails): the run fails, the failure counter backs off (1, 3, 10, 30 min); the ownership record in `state.json` is untouched.
* **Rejected push** (another Mac pushed): re-clone, re-decide from the new truth, publish or refuse.
* **Reader / no identity**: `SKIPPED`, no network call at all. Local checks (`publish_observability` without `--for-real`) work for any role.
* **Collector down on the owner**: it publishes an explicit `unavailable` feed once (existing behaviour) and still carries the owner record.
* Labels and ids are the only owner data in the feed; hostnames, usernames and paths are never published (the secret/path scan also covers the owner record).

## Diagnostics

```bash
python -m tools.machine_doctor           # PASS/WARN/FAIL/UNKNOWN per check; exit 1 only on FAIL
python -m tools.publisher_ownership status [--offline]   # local role, local ownership, remote owner, what this Mac would do
python -m tools.runtime_install status
```

`feed_health()` in `tools/publisher_ownership.py` (local records only, no network) feeds the `feed` object of `/observability.json`.
On a reader it shows `disabled` until `status` (or a doctor-style read) has recorded a read-only look at the feed.

## Known limits

* Lease/epoch fencing relies on git's non-fast-forward rejection and on Macs reading the same `main`; it is not a distributed lock. A Mac that was
  offline during a handover cannot overwrite after waking up, but a **human** who force-pushes the private repo can.
* The LaunchAgent labels (`com.manpreets2.agent-mindmap-*`) are intentionally identical on every Mac (per-user launchd domain).
* Ports are fixed per Mac: collector 8799 (loopback). 8787 belongs to a legacy server and is never touched.
