# Command center UI (Mission 003)

Operational dashboard on top of the existing Agent Mindmap React app (`web/`).
It answers, with evidence: which agents are working; who delegated to whom; what is
waiting/blocked/failed; which **account** has usable quota; collector health; GitHub
snapshot freshness; which machine supplied the data.

## Panels

### Source health (`SourceHealthBar`)
Always mounted as a sibling **above** `.mindmap-body` (never inside `.mindmap-main`).

| State | What you see |
| --- | --- |
| Observability absent / rejected | “Source health unavailable” — activity dashboard still works |
| `mode=demo` | Unmistakable **DEMO — SYNTHETIC DATA**; no “verified” wording |
| Live | Mode, collector status + last T3 poll age, GitHub snapshot (feed) status, machine label+role, feed owner + owned_by_this_machine |

UNKNOWN/STALE feed or collector states use muted/warn tones and text — never a green “healthy” treatment.

### Account quota (`QuotaPanel`)
Five **separate** cards in fixed order: `claude-1`, `claude-2`, `cursor-premium`,
`devin-free`, `codex`. Never combined or averaged.

| Effective status | Bars / numbers |
| --- | --- |
| VERIFIED / MANUAL (fresh) | `role=meter` + used/remaining % |
| STALE (server or client expiry) | Greyed/struck last values + “expired reading from \<time\>”; **no** meters |
| UNKNOWN / UNSUPPORTED / ERROR | Reason text only; **no** numbers |

Client-side re-evaluation (`utils/observabilityEval.ts`): if `expires_at` or any window
`resets_at` has passed vs `now`, VERIFIED/MANUAL is downgraded to STALE even if the
server still said VERIFIED. Document `generated_at` older than 15 minutes marks the
doc stale.

### Workload recommendations (`WorkloadRecommendations`)
Pure `recommend(activity, observability, now)` in `utils/recommendations.ts`.

Requires: observability present, `mode=live`, collector connected with fresh
`last_t3_poll`, activity not stale. Pool eligible only if VERIFIED|MANUAL, not expired,
≥1 window, every numeric `used_pct` \< **85** (`QUOTA_USED_PCT_LIMIT`), no reset passed.
Rank: lowest max used%, then fixed pool order.

Wording is always **“Possible next worker (evidence below)”** — never “switch account”
or dispatch/billing actions. Blockers (BLOCKED/FAILED sessions, waiting tasks) are listed
separately from quota.

### Roster / inspector
- Roster keeps pinned `aria-label` `${provider}, ${model}, ${status}, ${task}`.
- Account is a separate element / `aria-description` (`session.account.label` or
  “account not reported”). Completed/idle sessions are labelled “not an available worker”.
- Inspector: evidenced parent/child with evidence time, vs “Lineage not reported”.

## Data

| URL | Behaviour |
| --- | --- |
| `/activity.json` | Existing poll transport; 404 is a hard error screen |
| `/observability.json` | **Separate** transport (`observabilityTransport.ts`); 404/network → absent; bad JSON/schema → rejected |

## Fixtures

`fixtures/observability/{demo,live-mixed,live-all-unknown,live-collector-down,reader-other-owner}.json`

Copy one to `web/dist/observability.json` when serving a static build to exercise UI states
before the collector serves the live document.

## How to test

```bash
cd web && npm ci && npx vitest run && npx tsc --noEmit -p tsconfig.json && npm run build
# serve (ports 8951–8959 only; never 8787/8799):
python -m ingest.live --source t3-demo --demo-replay --demo-step-sec 5 \
  --port 8951 --static-dir <worktree>/web/dist
cp ../fixtures/observability/live-mixed.json dist/observability.json
```

Ops drawer body overlays the graph (like the timeline) so opening it does not resize the
force-graph camera host.
