# MM-020 Unified Live Multi-Agent Network — Phase 1 Audit

**Status:** AUDIT ONLY — no product code in this PR.  
**Audit snapshot base:** `main` @ `3b02368` (plus open PRs #14 / #15 audited at tip SHAs below).  
**Implementation base (plan):** **`main` after PR #14 and PR #15 merge** — MM-020 workstreams start from that tip, not from folding those PRs as side branches.  
**DO NOT MERGE without Manpreet approval.**

**Author:** Architect (audit agent)  
**Date:** 2026-10-20

---

## 0. Spec summary (target)

One **live graph** across all groups. A bot has **one identity** across every group it belongs to. Later groups must be addable dynamically.

| Group | Members (v1) |
|-------|----------------|
| **Build** | Director, Architect, DEV 1, DEV 2, UI/UX Maker, Documentation |
| **Quality & Release** | Director, Architect, Security Engineer, DevOps/Release, QA/Verifier |
| **Research / Radar** | Director, Scout, Skeptic, NOMEN, Architect |

Separate models for: **identity**, **membership**, **messages**, **tasks**, **activity**.

**Live event** fields: `id`, `ts`, `sender`, `recipients` (only when explicit), `group`, `type`, `task_id`, sanitized `summary`, `provenance` (`observed` \| `agent-reported` \| `github-verified`), `related_id`.

- Untargeted group message → edge **sender → group**.
- Transport: **SSE** from a local collector; dedupe, reconnect, replay.
- Agent state: `ACTIVE` \| `IDLE` \| `BLOCKED` \| `COMPLETED` \| `UNKNOWN` from evidence.
- Animate **only** on real events.
- Hard constraints: read-only GitHub + canonical ledger; **localhost only**; no new tokens / paid services; no secrets or raw conversations in telemetry; **`activity.json` backward-compatible**.

---

## 1. Platform facts (reported by Architect — not verifiable from this VM)

Recorded verbatim as operational constraints for the collection design:

| ID | Fact (Architect-reported) |
|----|---------------------------|
| **(a)** | Bots talk through an agent-to-agent message tool and group-chat posts. There is **NO** documented public event stream or webhook for those messages. |
| **(b)** | Bot owners can read their own bots' transcripts on request. That is **pull-based**, holds **raw conversation** (must not go into telemetry directly), and is **not real time**. |
| **(c)** | All bots share one Linux box filesystem (`/workspace`) plus a shared **Agent Store**, where the **canonical task ledger** lives. |
| **(d)** | The ledger mirror (**MM-010**) already publishes `ledger.md` to branch `data/ledger`. |
| **(e)** | The viewer runs on **Manpreet's Mac** and reads through the existing **`gh` login only**. |

Implication: the Mac cannot assume a private SSE tunnel to the Linux box. Anything the Mac consumes must arrive via **`gh`-reachable git content** and/or a **localhost** process on the Mac.

---

## 2. Baseline plan (PR #14 + PR #15 → main first)

**Plan change (Director/Architect):** PR **#14 (MM-012)** and PR **#15 (MM-011)** are going through review and merge to **`main` first**. MM-020 **builds on top of them**. Treat both as **baseline infrastructure**, not as work to “fold in” during MM-020.

| PR | Tip SHA audited | Role after merge |
|----|-----------------|------------------|
| **#14** MM-012 redesign | `ceebb76` | Baseline UI: command-center shell, graph layout (≥24px gaps), poll `ActivityTransport`, motion, timeline brush |
| **#15** MM-011 live daemon | `aaeef2b` | Baseline Mac host: `ingest.live` poll ledger+gh, serve `/activity.json` + static on **127.0.0.1** |

MM-020 task split (§6) assumes **`main` contains both**. Until they land, this audit PR stays draft and product work waits.

---

## 3. Component audit (keep / extend / replace)

| Component | Verdict | Why |
|-----------|---------|-----|
| **`config/bots.json`** | **Extend** | Has 13 bots + owner with aliases and fixed `layout`, but each bot has a **single** `group` (`owner`\|`build`\|`qr`\|`radar`). MM-020 needs **multi-membership** (Director/Architect in Build + Q&R + Radar) and dynamic later groups. Keep ids/aliases/layout; add `groups: string[]` (or membership table) and stop treating `group` as identity. Note: roster today includes Bug fixer in `radar`; Research v1 list does not — resolve in MM-020a config. |
| **`web/src/components/AgentGraph.tsx`** | **Extend** (post-#14 baseline) | On `ceebb76`: React Flow + group-band/`dagre` layout, MiniMap, default `<Controls>`, lifecycle glow, handoff particles. Still one node per bot id and bot↔bot edges. Keep as unified canvas; extend for **group nodes**, **sender→group** edges, multi-membership (one node, many frames), animate only on real NetworkEvent ids. |
| **`web/src/views/MindmapView.tsx`** | **Extend** (post-#14 baseline) | Shell + poll feed hooks after #14. Extend to prefer SSE transport when `/events` exists; keep poll/`activity.json` fallback. |
| **`web/src/data/activityTransport.ts`** | **Extend** (post-#14 baseline) | Pluggable `ActivityTransport` with `createPollTransport` (10s). **Keep** interface; add `createSseTransport` for MM-020. |
| **`shared/types.ts`** | **Extend** | Mirrors `activity.json`. Needs additive types: membership, live `NetworkEvent`, provenance, group entity, state enum mapping — without breaking existing `Activity` / `Event` / `Edge`. |
| **`schema/activity.schema.json`** | **Extend** | Snapshot contract. Additive optional fields / `$defs/networkEvent`; keep required fields so old fixtures validate. |
| **`ingest/`** | **Extend** (post-#15 baseline) | Existing parsers/pollers + **`ingest/live.py`** after #15. Add events mirror fetch + SSE; no chat webhooks (fact a). |
| **`tools/ledger_mirror.py` (MM-010)** | **Keep + reuse pattern** | Proven flush gating + SEC-MM010-1 secret scan + `data/ledger`. Clone for **`data/events`**; do not overload ledger.md. |
| **`tests/`** | **Extend** | Keep schema/ledger/poller/edges/mirror/live ACs. Add live NetworkEvent + SSE + e2e proof cases. |
| **PR #14 @ `ceebb76` (MM-012)** | **Baseline (keep); MM-020 extends** | See **§3.2**. Merges to main before MM-020 product work. Known nits tracked for UI polish, not blockers for baseline. |
| **PR #15 @ `aaeef2b` (MM-011)** | **Baseline (keep); MM-020 extends** | See **§3.1**. Merges to main before MM-020 product work. **SEC-MM011-1** (Host/Origin) is an MM-020 security task on that daemon. |
| **Planned MM-013 (PR lanes)** | **Extend ingest (post-baseline)** | Not on `main` yet. DEV workstream under MM-020e after #14/#15 land — GitHub-verified PR edges into live rebuild. |

### 3.1 MM-011 actual code audit (PR #15 @ `aaeef2b`, based on `3b02368`)

**Draft PR:** https://github.com/ManpreetS2/agent-mindmap/pull/15 — 94 tests claimed; files: `ingest/live.py`, `ops/com.manpreet.mindmap.plist`, `tests/test_live.py`, `Makefile`, `README.md`.

| Piece | Verdict | What it does today | MM-020 extension (after merge) |
|-------|---------|--------------------|--------------------------------|
| **`LiveDaemon`** | **Keep + extend** | Poll ledger (`path` or `gh` via MM-010 `fetch_ledger_from_gh`) + GitHub; fingerprint → `assemble_activity` → atomic `write_activity`; last-good GH; rate-limit backoff; threaded intervals (30s/60s). | Third poll source: **`data/events`**. In-memory NetworkEvent log; merge into rebuild or parallel feed. Keep fingerprint skip-rewrite. |
| **`assemble_activity` / rebuild** | **Keep + extend** | Same shape as `build.build_activity`; `schema_version: 1.0.0`. | Keep snapshot path. Project live events into `events`/`edges` or `meta.live`. Do not break AC3. |
| **`MindmapHandler` HTTP** | **Keep + extend** | `127.0.0.1:8787`; GET/HEAD; `/healthz`; `/activity.json` ETag/304; static with traversal guards; 405 on mutating methods; `refuse_public_bind`. **No Host/Origin allowlist** → **SEC-MM011-1**. | Add SSE `GET /events` + **Host + Origin checks on every endpoint** (incl. SSE). |
| **SSE / event stream** | **Missing → add** | No `/events`, no replay. UI uses poll (`ActivityTransport`). | MM-020d: SSE + Last-Event-ID + dedupe. |
| **CLI / env / plist / `make live`** | **Keep + lightly extend** | `--ledger-source path\|gh`; launchd placeholders; Makefile path-or-gh. | Events poll flags/env; prefer `gh` ledger on Mac (fact e). |
| **`tests/test_live.py`** | **Keep + extend** | AC1–AC6 (bind, ETag, skip rewrite, last-good, traversal, plist). | SSE + SEC-MM011-1 Host/Origin tests. |

**Satisfies today:** localhost bind; read-only `gh`; MM-010 ledger ferry; atomic writes; stdlib-only.

**Does not provide:** agent-message bus (fact a); JSONL emitter; `data/events`; SSE; multi-membership; NetworkEvent model; **Host/Origin allowlist (SEC-MM011-1)**.

**Rule:** After #15 merges, **extend `ingest/live.py` — do not rewrite a second daemon.**

### 3.2 MM-012 actual code audit (PR #14 @ `ceebb76`)

**PR:** https://github.com/ManpreetS2/agent-mindmap/pull/14 — tip **`ceebb76030cf7b0ada835edd7df1069190b6afb5`** (`fix(web): MM-012 polish layout, chrome, legend, unsourced tags`). Note: branch tip is currently based on pre-MM-010 `main` (`63e1bdf`); rebase/merge onto post-#15/#10 tip is a merge concern for #14 itself, not for MM-020 once both are on `main`.

| Piece | Verdict | What it does at `ceebb76` | MM-020 extension (after merge) |
|-------|---------|---------------------------|--------------------------------|
| **`graphLayout.ts` + test** | **Keep** | Group-band grid with **≥24px** gaps (`MIN_NODE_GAP`); `enforceMinGap`; dagre fallback for unexpected rosters. **`graphLayout.test.ts`** asserts no overlapping pairs on sample fixture and documents that raw fixture layout still overlaps. | Keep; membership/layout may need multi-group placement later (one node, multiple frames). |
| **`AgentGraph.tsx`** | **Keep + extend** | Applies layout; drag handle; MiniMap; React Flow `<Controls showInteractive={false} />`; motion/particles; reduced-motion. | Group edges; SSE-driven animation only on real event ids. |
| **`activityTransport.ts` / `useActivityFeed` / `activityDiff`** | **Keep + extend** | Poll 10s + id diff-patch; pluggable transport. | Add SSE transport; poll remains fallback. |
| **`TimelineSwimlanes` / brush** | **Keep + polish nits** | Zoom/brush + now line; unsourced tag via `foreignObject` at `x+14` when `!hasSource`; sourced markers wrap `<a href={source_url}>`. | Optional nit fixes (below); not MM-020 blockers. |
| **Theme / shell** | **Keep** | Tailwind/shadcn/Magic UI glass-neon `CommandCenterShell`. | Preserve; no redesign required for MM-020. |

**Known nits at `ceebb76` (record only — UI/UX can fix on main or as small follow-ups):**

1. **Unsourced tag vs timeline link:** `UnsourcedTag` foreignObject (`x+14`, width 100) can visually overlap adjacent sourced markers’ `<a>` hit targets when events are dense on the lane (tag sits beside markers but competes for horizontal space with neighboring source links).
2. **Zoom controls unstyled:** React Flow default `<Controls>` on the graph are not glass-themed (legend was moved top-right “away from zoom controls,” but Controls themselves remain stock styling). Timeline’s `.timeline-zoom-btn` *is* styled — nit is primarily **graph** Controls.

**Rule:** After #14 merges, MM-020 **extends** this UI baseline — do not re-ship a parallel redesign.

---

## 4. Exists today vs missing (deliverable 1)

Baseline for the gap table = **`main` @ 3b02368 + PR #14 @ ceebb76 + PR #15 @ aaeef2b`** (as if already merged).

| Area | Exists (baseline) | Missing for MM-020 |
|------|-------------------|--------------------|
| Bot identity | Stable `id` + aliases in `bots.json` | Multi-group membership; dynamic groups |
| Groups | Single enum frame (`build`/`qr`/`radar`/`owner`) | First-class group entities; Director/Architect in multiple groups |
| Tasks | Ledger table → `tasks[]` | Link live messages to tasks with provenance |
| Activity snapshot | `activity.json` via ledger + `gh` (+ live rebuild on Mac) | Backward-compatible live overlay / NetworkEvent stream |
| Edges | Derived handoff/verdict/pr/merge | Sender→group edges; message edges; animate only on real events |
| GitHub | Read-only `gh api`, ETag, attribution by signature | Unchanged; MM-013 PR lanes later |
| Ledger | Local path + MM-010 `data/ledger` mirror | Remains canonical for tasks; not a chat log |
| Agent messages | **None** | Opt-in emitter + shared JSONL (facts a–c) |
| Live transport to UI | #15: `/activity.json` ETag on 127.0.0.1; #14: 10s poll transport | **SSE `/events`** with dedupe, reconnect, replay |
| Localhost HTTP hardening | Bind refusal only | **SEC-MM011-1:** Host + Origin allowlist on all endpoints incl. SSE |
| Agent state model | `IDLE`/`IN_PROGRESS`/`IN_REVIEW`/`BLOCKED`/`DONE`/`UNKNOWN` | Map to ACTIVE/IDLE/BLOCKED/COMPLETED/UNKNOWN from evidence |
| Secrets / raw chat | SEC-MM010-1 on ledger mirror; no tokens | Same for events; never emit raw transcripts (fact b) |
| Mac viewer | #14 UI + #15 daemon + `gh` (fact e) | Events must be `gh`-pullable into that daemon |

---

## 5. Collection approach — options, choice, limits (deliverable 2)

### 5.1 Recommended architecture (chosen)

**Opt-in emitter → shared JSONL (box / Agent Store) → MM-010-style mirror to `data/events` → Mac `ingest.live` (baseline #15) pulls via `gh` → localhost SSE to the UI (baseline #14 transport extended).**

1. **Emitter (each bot, opt-in):** append **one sanitized JSON line** per event to shared JSONL (`O_APPEND`, one write/line, ≤ `PIPE_BUF`).
2. **Mirror (box):** flush to branch **`data/events`** with secret scan (MM-010 pattern).
3. **Mac collector (extend baseline `LiveDaemon`):** poll `data/events` + existing ledger/GitHub; in-memory event log; keep `activity.json`; expose **SSE** `/events` with Last-Event-ID; enforce **SEC-MM011-1**.
4. **UI (extend baseline `ActivityTransport`):** SSE implementation; animate only on new event ids; poll remains fallback.

### 5.2 Alternative considered: box-side SSE collector

**Rejected as primary** for the Mac viewer: fact (e) — Mac uses **`gh` only**. Box SSE optional for on-box bots only.

### 5.3 Comparison

| Criterion | JSONL + `data/events` + Mac live SSE (chosen) | Box-side SSE only |
|-----------|-----------------------------------------------|-------------------|
| **Latency** | Seconds–minutes (mirror + Mac poll); SSE instant after pull | Sub-second on box; Mac unreachable without extra plumbing |
| **Coverage** | Only emitter-adopting bots | Same emitter dependency |
| **Security** | MM-010 secret scan + `gh` read-only + SEC-MM011-1 on Mac | Extra box network surface; Mac still needs a ferry |
| **Fits facts (c)(d)(e)** | Yes | Conflicts with (e) as sole path |

### 5.4 Exactly what will NOT be captured

- Messages from bots that **have not adopted** the emitter.
- Anything said **only in DMs** / 1:1 channels (out of scope unless later opted in).
- **Raw conversation transcripts** (fact b) — never into JSONL/telemetry.
- Posts with **no emitter fire** (fact a: no public webhook to backfill).
- Historical chat before emitter adoption.
- Secrets / tokens / Authorization headers.
- Non-allowlisted GitHub activity.
- Room ambient presence without an event line.

---

## 6. Event schema + migration from `activity.json` (deliverable 3)

### 6.1 Live network event (collector JSONL + SSE payload)

```ts
type Provenance = "observed" | "agent-reported" | "github-verified";
type AgentState = "ACTIVE" | "IDLE" | "BLOCKED" | "COMPLETED" | "UNKNOWN";

interface NetworkEvent {
  id: string;                 // stable sha1(source + locator) or emitter uuid
  ts: string;                 // ISO-8601 with offset
  sender: string;             // bot id
  recipients?: string[];      // only when explicit @ / DM-style target
  group: string;              // group id, e.g. "build" | "qr" | "radar" | later
  type: string;               // message | handoff | assigned | verdict | ...
  task_id?: string | null;
  summary: string;            // sanitized, short; NEVER raw transcript
  provenance: Provenance;
  related_id?: string | null; // correlates reply / PR / prior event
}
```

JSONL: one `NetworkEvent` per line. Untargeted group message ⇒ graph edge `sender → group:{group}`.

### 6.2 Separate models (logical)

| Model | Responsibility |
|-------|----------------|
| **Identity** | `bots.json` id, display_name, aliases |
| **Membership** | `(bot_id, group_id)[]` — many groups per bot |
| **Messages** | `NetworkEvent` stream |
| **Tasks** | Existing ledger `tasks[]` |
| **Activity** | Snapshot `activity.json` + derived edges/nodes for UI |

### 6.3 Migration / compatibility

1. Keep `schema_version: "1.0.0"` `activity.json` validating as today.
2. Additive optional fields only (e.g. `meta.live`, `meta.events_source`, node `states` map).
3. Adapter: `NetworkEvent[]` → existing `events[]` / `edges[]` where possible; group-targeted messages become edges with `target = "group:<id>"` **or** parallel `live_edges` if needed (prefer projecting into `edges` with a minor schema bump under Manpreet OK).
4. Status mapping: `IN_PROGRESS`/`IN_REVIEW` → `ACTIVE`; `DONE` → `COMPLETED`; others align 1:1.
5. UI loads snapshot first, then applies SSE patches by event `id` (dedupe).

---

## 7. Task split (deliverable 4)

**Prerequisite:** PR #14 (`ceebb76`) and PR #15 (`aaeef2b`) **merged to `main`**. All MM-020* branches cut from that tip.

| ID | Owner | Scope | Primary files | Acceptance criteria | Depends on |
|----|-------|-------|---------------|---------------------|------------|
| **MM-020a** | Architect | **IMPLEMENTED** on this branch (rebased onto `main` @ `1a3a0cc`): membership model + schema 1.1.0 (`message` edges, provenance); `config/groups.json`; migration test for 1.0.0 fixtures | `config/bots.json`, `config/groups.json`, `schema/activity.schema.json`, `shared/types.ts`, `ingest/membership.py`, `ingest/migrate.py`, `ingest/edges.py`, `ingest/build.py` | Multi-membership for Director/Architect; Research without Bug fixer; schema validates old fixtures unchanged; types compile | #14+#15 on `main` ✓ |
| **MM-020b** | DEV 1 | Emitter library + JSONL append contract; secret-safe summary helper | `tools/event_emit.py` (new), tests | Concurrent writers (N processes) lose no lines; line ≤ PIPE_BUF guidance; secrets refused; idempotent ids | MM-020a |
| **MM-020c** | DEV 2 | Events mirror (MM-010 pattern) → `data/events`; allowlisted `gh` fetch | `tools/events_mirror.py`, `ingest/events_fetch.py`, tests | Same flush/secret rules as MM-010; Mac can `gh api` contents; no tokens | MM-020b, MM-010 |
| **MM-020d** | DEV 1 | Extend baseline **`ingest/live.py`**: pull `data/events` + ledger + GitHub; localhost SSE `/events` with replay; implement **SEC-MM011-1** Host/Origin on all endpoints | `ingest/live.py`, `ops/*.plist`, `tests/test_live.py` | Existing AC1–AC6 green; SSE reconnect + Last-Event-ID; dedupe by id; bind 127.0.0.1 only; Host/Origin checks pass (§7.1) | MM-020c; #15 on `main` |
| **MM-020e** | DEV 2 | **MM-013** PR lanes into live rebuild (github-verified provenance) | `ingest/github_poller.py`, `ingest/edges.py`, live merge | PR edges with provenance `github-verified`; allowlist unchanged | MM-020d; MM-013 plan |
| **MM-020f** | UI/UX Maker | Extend baseline MM-012 UI: SSE `ActivityTransport`, one identity across groups, group edges, animate only on real events; optional nits (unsourced overlap, graph Controls theme) | `AgentGraph.tsx`, `MindmapView.tsx`, `activityTransport.ts`, motion | Director single node in Build+Q&R+Radar; sender→group edge; reduced-motion OK | MM-020a, MM-020d; #14 on `main` |
| **MM-020g** | QA | E2E proof + negative tests (see §8) | `tests/`, fixtures | All §8 cases green in CI | MM-020d–f |
| **MM-020h** | Security | Threat review: emitter sanitization, mirror secret scan, no raw transcripts, localhost binding, **SEC-MM011-1** sign-off | review notes + tests | Written sign-off; SEC cases in CI | MM-020b–d |
| **SEC-MM011-1** | Security + DEV 1 | **LOW** — DNS rebinding: daemon has **no Host header allowlist**, so a malicious page could rebind a hostname to `127.0.0.1` and read `/activity.json` (and future SSE). **Require** `Host` ∈ `{127.0.0.1, localhost}` (with optional port) **and** an `Origin` check (same-origin / null-or-localhost policy) on **every** MM-020 endpoint including `/activity.json`, `/healthz`, static, and **`/events` SSE**. Reject with 403 otherwise. | `ingest/live.py`, `tests/test_live.py` | Tests: forged `Host` → 403; missing/bad `Origin` on sensitive GETs → 403; valid localhost Host+Origin → 200; SSE subject to same checks | Lands with **MM-020d**; reviewed under **MM-020h** |

**Ownership reminder:** DEV 1 + DEV 2 = collector & ingestion (extend baseline live + MM-013). UI/UX Maker = visualization (extend baseline MM-012). QA + Security = review (incl. SEC-MM011-1).

### 7.1 SEC-MM011-1 detail (LOW)

| Field | Value |
|-------|-------|
| **ID** | SEC-MM011-1 |
| **Severity** | LOW |
| **Found in** | PR #15 `MindmapHandler` @ `aaeef2b` — binds `127.0.0.1` but never validates `Host` / `Origin` |
| **Risk** | DNS-rebinding browser page → read local `/activity.json` (and later SSE event summaries) |
| **Fix** | Allowlist `Host` to `127.0.0.1` / `localhost` (port optional); require acceptable `Origin` (or treat missing Origin per safe localhost policy documented in tests); apply to **all** routes including SSE |
| **Owners** | DEV 1 implements in MM-020d; Security verifies in MM-020h |

---

## 8. End-to-end proof plan (deliverable 5)

### 8.1 Happy path (manual + automated)

1. **Two groups** configured (Build + Quality & Release) with shared membership.
2. **Director** appears as **one node** belonging to both groups (frames/highlights, not duplicated ids).
3. **One bot-to-bot message** (explicit recipients) → edge sender→recipient with provenance `agent-reported`.
4. **One cross-group handoff** (e.g. Architect in Build → QA in Q&R) → visible on the unified graph with correct `group` on the event.
5. UI receives events via **localhost SSE**; animation fires **only** for those event ids.

### 8.2 Automated tests (required)

| Case | Expect |
|------|--------|
| **Reconnect** | Client disconnect/reconnect resumes via Last-Event-ID; no crash |
| **Duplicates** | Same `id` twice → one edge/animation |
| **Missing attribution** | Event without resolvable sender → `UNKNOWN` / no false edge |
| **Simultaneous writers** | N emitters append concurrently → all lines present, valid JSONL |
| **Unconfigured rooms** | Event for unknown `group` → ignored or parked; no throw; graph stable |
| **SEC-MM011-1** | Bad `Host` / `Origin` → 403 on `/activity.json` and `/events` |

### 8.3 Explicit non-goals for the proof

No requirement to show DMs, non-emitting bots, or raw transcript pulls.

---

## 9. Open questions for Manpreet / Director

1. Confirm Research membership (include Bug fixer or not?).
2. Approve `data/events` branch mirror naming and retention (overwrite vs append blob).
3. Schema: new edge type for `message` / `group` vs overload `note`+custom target.
4. Confirm #14 and #15 merge order to `main` (either order OK for MM-020 as long as both land before MM-020a).

---

## 10. Recommendation (one paragraph)

Merge **PR #14 (`ceebb76`)** and **PR #15 (`aaeef2b`)** to **`main` first** as the MM-020 baseline. Then ship an **opt-in sanitized JSONL emitter** on the shared box/store, ferry it with the **MM-010 mirror pattern** on `data/events`, and **extend** (do not replace) baseline `LiveDaemon` / `MindmapHandler` for events pull + **SSE `/events`**, with **SEC-MM011-1 Host+Origin checks** on every endpoint. Extend bots config, graph, types, schema, and MM-012’s `ActivityTransport`; add MM-013 PR lanes afterward. This respects Architect facts (a–e), keeps GitHub/ledger read-only, and leaves `activity.json` backward-compatible.
