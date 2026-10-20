#!/usr/bin/env python3
"""MM-020-P0 combined QA — locally merged #30+#29 onto feat/MM-020-unified-network."""
from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path("/tmp/qa-mm020p0/checkout")
MERGED = Path("/tmp/qa-mm020p0/evidence/logs/MERGED_HEAD.txt").read_text().strip()
OUT = Path(f"/tmp/qa-mm020p0/evidence/logs/{MERGED}")
SHOTS = Path("/tmp/qa-mm020p0/evidence/screenshots")
OUT.mkdir(parents=True, exist_ok=True)
SHOTS.mkdir(parents=True, exist_ok=True)
BIN = Path("/tmp/qa-mm020p0/bin")
PORT = 8787
STUB = Path("/tmp/qa-mm020p0/evidence/scripts/gh_p0_stub.py")

checks: list[dict] = []
findings: list[dict] = []


def record(check: str, result: str, detail: str = "") -> None:
    checks.append({"check": check, "result": result, "detail": detail})
    print(f"[{result}] {check}" + (f" — {detail}" if detail else ""), flush=True)


def finding(**kwargs) -> None:
    findings.append(kwargs)
    print(f"[FINDING:{kwargs.get('severity')}] {kwargs.get('id')}: {str(kwargs.get('actual',''))[:220]}", flush=True)


def kill_port() -> None:
    subprocess.run(["pkill", "-f", "ingest.live"], capture_output=True)
    subprocess.run(
        f"ss -lptn 'sport = :{PORT}' 2>/dev/null | awk -Fpid= 'NR>1{{print $2}}' | cut -d, -f1 | xargs -r kill -9",
        shell=True,
    )
    time.sleep(0.5)


def http(method: str, path: str, headers: dict | None = None, body: bytes | None = None, timeout: float = 5.0):
    hdrs = {"Host": f"127.0.0.1:{PORT}"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}{path}",
        data=body,
        headers=hdrs,
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()
    except Exception as e:
        return 0, {}, str(e).encode()


def wait_healthz(timeout: float = 60.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        st, _, body = http("GET", "/healthz")
        if st == 200:
            last = json.loads(body)
            return last
        last = {"_st": st, "_body": body[:200].decode(errors="replace")}
        time.sleep(0.3)
    return last


def start_mac(*, unset_ledger: bool = True, extra_env: dict | None = None) -> subprocess.Popen:
    kill_port()
    env = {
        **os.environ,
        "PATH": f"{BIN}{os.pathsep}{os.environ.get('PATH','')}",
        "MINDMAP_PORT": str(PORT),
        "MINDMAP_EVENTS_SOURCE": "gh",
        "MINDMAP_PYTHON": str(ROOT / ".venv/bin/python"),
    }
    env.pop("MINDMAP_LEDGER", None)
    if not unset_ledger:
        env["MINDMAP_LEDGER"] = str(ROOT / "tests/fixtures/ledger-sample.md")
    if extra_env:
        env.update(extra_env)
    log = OUT / "start_mac.log"
    lf = log.open("w")
    proc = subprocess.Popen(
        ["./scripts/start-mac.sh"],
        cwd=str(ROOT),
        env=env,
        stdout=lf,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    health = wait_healthz(90)
    ok = bool(health and health.get("mode") == "live")
    record("start-mac LIVE starts", "PASS" if ok else "FAIL", str(health)[:200])
    if not ok:
        finding(
            id="START-mac",
            component="scripts/start-mac.sh",
            expected="live daemon on :8787",
            actual=f"health={health} log={(OUT/'start_mac.log').read_text()[-400:]}",
            repro="./scripts/start-mac.sh with gh stub, no MINDMAP_LEDGER",
            evidence="start_mac.log",
            severity="high",
            confidence="high",
        )
    return proc


def stop(proc: subprocess.Popen | None) -> None:
    if proc and proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except Exception:
            proc.terminate()
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except Exception:
                pass
    kill_port()


def check_1_ledger_missing():
    st, _, body = http("GET", "/activity.json")
    doc = json.loads(body) if st == 200 else {}
    (OUT / "activity_no_ledger.json").write_text(json.dumps(doc, indent=2)[:80000], encoding="utf-8")
    meta = doc.get("meta") or {}
    events = doc.get("events") or []
    edges = doc.get("edges") or []
    nodes = doc.get("nodes") or []

    ledger_ok = meta.get("ledger") in ("unavailable", "not_found", "error") and bool(meta.get("ledger_error"))
    # Prefer unavailable for missing data/ledger
    gh_ok = meta.get("github") == "ok"
    nonempty = len(events) > 0 and len(edges) > 0
    statuses = {n.get("id"): n.get("status") for n in nodes}
    idle_fake = [n for n in nodes if n.get("status") == "IDLE" and meta.get("ledger") in ("unavailable", "not_found")]
    # When ledger unavailable, nodes should be UNKNOWN not fake IDLE (per AC)
    unknownish = all(
        (n.get("status") in ("UNKNOWN", None) or n.get("status") != "IDLE")
        or True  # evaluated below
        for n in nodes
    )
    # stricter: no IDLE when ledger unavailable — all should be UNKNOWN if no ledger activity
    no_idle = not any(n.get("status") == "IDLE" for n in nodes)
    all_unknown = all(n.get("status") == "UNKNOWN" for n in nodes) if nodes else False

    record("(1) meta.ledger unavailable + ledger_error", "PASS" if ledger_ok else "FAIL", str(meta))
    record("(1) github=ok (not skipped)", "PASS" if gh_ok else "FAIL", str(meta.get("github")))
    record("(1) events/edges nonempty", "PASS" if nonempty else "FAIL", f"events={len(events)} edges={len(edges)}")
    record("(1) nodes UNKNOWN not fake IDLE", "PASS" if all_unknown else "FAIL", f"statuses sample={list(statuses.items())[:8]} idle_count={sum(1 for n in nodes if n.get('status')=='IDLE')}")

    if not ledger_ok:
        finding(id="P0-1-ledger-meta", component="activity.meta", expected="ledger unavailable + ledger_error", actual=str(meta), repro="start-mac without MINDMAP_LEDGER; gh stub 404 ledger", evidence="activity_no_ledger.json", severity="high", confidence="high")
    if not gh_ok:
        finding(id="P0-1-github-ok", component="activity.meta.github", expected="ok (not skipped)", actual=str(meta.get("github")), repro="same", evidence="activity_no_ledger.json", severity="high", confidence="high")
    if not nonempty:
        finding(id="P0-1-nonempty", component="activity events/edges", expected=">0 events and edges from gh/network", actual=f"e={len(events)} edges={len(edges)}", repro="same", evidence="activity_no_ledger.json", severity="high", confidence="high")
    if not all_unknown:
        finding(id="P0-1-unknown-status", component="node.status", expected="UNKNOWN rather than fake IDLE when ledger missing", actual=f"idle={sum(1 for n in nodes if n.get('status')=='IDLE')} statuses={list(statuses.values())[:12]}", repro="GET /activity.json with missing ledger", evidence="activity_no_ledger.json", severity="high", confidence="high")

    # message edges from network
    msg_edges = [e for e in edges if e.get("type") == "message"]
    record("(1/6) message edges present", "PASS" if msg_edges else "FAIL", f"n={len(msg_edges)}")
    return doc


def check_2_live_event(doc_before: dict):
    """Inject via POST /refresh after updating events file served by stub — or append via second poll.
    Practical: stub already served 3 events; prove a NEW one appears after rebuilding stub body + refresh.
    """
    # Rewrite stub events file dynamically by patching a sidecar the stub reads
    side = Path("/tmp/qa-mm020p0/evidence/scripts/extra_events.jsonl")
    # Update stub to read extra — simpler: call ingest via refresh after modifying Events
    # For start-mac process we can't easily inject. Use POST /refresh after updating a drop-in events cache?
    # Alternative: use curl SSE and also force refresh — mutate the gh stub's EVENTS by rewriting the .py and... won't reload.
    # Best approach for running daemon: write to daemon's events by hitting refresh after changing mock mapping via a file the stub reads each call.
    return  # filled by dynamic stub below


def seed_events() -> Path:
    events_path = Path("/tmp/qa-mm020p0/evidence/logs/live_events.jsonl")
    events_path.parent.mkdir(parents=True, exist_ok=True)
    initial = [
        {"id": "p0-net-1", "ts": "2026-10-20T22:00:00+00:00", "sender": "director", "recipients": ["architect"], "group": "build", "type": "message", "summary": "msg1", "provenance": "agent-reported", "repo": "ManpreetS2/agent-mindmap"},
        {"id": "p0-net-2", "ts": "2026-10-20T22:01:00+00:00", "sender": "architect", "recipients": ["qa-verifier"], "group": "qr", "type": "message", "summary": "msg2", "provenance": "agent-reported", "repo": "ManpreetS2/agent-mindmap"},
        {"id": "p0-net-3", "ts": "2026-10-20T22:02:00+00:00", "sender": "dev-1", "recipients": ["dev-2"], "group": "build", "type": "message", "summary": "msg3", "provenance": "agent-reported", "repo": "ManpreetS2/fencepost"},
    ]
    events_path.write_text("".join(json.dumps(e) + "\n" for e in initial), encoding="utf-8")
    stub = BIN / "gh"
    stub.chmod(0o755)
    return events_path


def check_2_and_3(events_path: Path):
    # baseline event count
    st, _, body = http("GET", "/activity.json")
    doc0 = json.loads(body)
    ids0 = {e.get("id") for e in doc0.get("events") or []}
    # append new network event to stub file
    with events_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({
            "id": "p0-live-new",
            "ts": "2026-10-20T22:10:00+00:00",
            "sender": "director",
            "recipients": ["dev-1"],
            "group": "build",
            "type": "message",
            "summary": "appears without reload",
            "provenance": "agent-reported",
            "repo": "ManpreetS2/agent-mindmap",
        }) + "\n")
    # POST /refresh → 202
    st1, h1, b1 = http("POST", "/refresh", headers={"Origin": f"http://127.0.0.1:{PORT}", "Content-Length": "0"}, body=b"")
    record("(3) POST /refresh → 202", "PASS" if st1 == 202 else "FAIL", f"status={st1} body={b1[:120]}")
    if st1 != 202:
        finding(id="P0-3-refresh-202", component="POST /refresh", expected="202", actual=f"{st1} {b1[:200]}", repro="POST /refresh with Origin localhost", evidence="refresh.json", severity="high", confidence="high")
    # wait for rebuild
    appeared = False
    for _ in range(40):
        time.sleep(0.25)
        st, _, body = http("GET", "/activity.json")
        doc = json.loads(body) if st == 200 else {}
        ids = {e.get("id") for e in doc.get("events") or []}
        if "p0-live-new" in ids:
            appeared = True
            break
    record("(2) new network event without reload", "PASS" if appeared else "FAIL", f"had={sorted(ids0)[:5]} now_has_new={appeared}")
    if not appeared:
        finding(id="P0-2-live-event", component="network→activity via /refresh", expected="p0-live-new in /activity.json after refresh", actual=f"ids sample={list(ids)[:10] if st==200 else None}", repro="append events.jsonl stub; POST /refresh; GET /activity.json", evidence="activity_no_ledger.json", severity="high", confidence="high")

    # burst → 429
    st2, h2, b2 = http("POST", "/refresh", headers={"Origin": f"http://127.0.0.1:{PORT}", "Content-Length": "0"}, body=b"")
    # immediate second
    st3, h3, b3 = http("POST", "/refresh", headers={"Origin": f"http://127.0.0.1:{PORT}", "Content-Length": "0"}, body=b"")
    burst_ok = st3 == 429
    retry_after = None
    try:
        retry_after = json.loads(b3).get("retry_after_s")
    except Exception:
        pass
    record("(3) burst POST /refresh → 429 + countdown", "PASS" if burst_ok and retry_after else "FAIL", f"st={st3} retry_after={retry_after} body={b3[:120]}")
    if not (burst_ok and retry_after):
        finding(id="P0-3-rate-limit", component="POST /refresh", expected="429 with retry_after_s", actual=f"{st3} {b3[:200]}", repro="two POST /refresh within 5s", evidence="refresh.json", severity="high", confidence="high")
    (OUT / "refresh.json").write_text(json.dumps({"first": st1, "second": st2, "third": st3, "retry_after": retry_after, "b3": b3.decode(errors="replace")}, indent=2), encoding="utf-8")
    return retry_after


def check_8_host_origin():
    origin = f"http://127.0.0.1:{PORT}"
    # bad Host
    st_bad, _, _ = http("POST", "/refresh", headers={"Host": "evil.example", "Origin": origin, "Content-Length": "0"}, body=b"")
    # Origin null
    st_null, _, _ = http("POST", "/refresh", headers={"Origin": "null", "Content-Length": "0"}, body=b"")
    # foreign Origin
    st_foreign, _, _ = http("POST", "/refresh", headers={"Origin": "https://evil.example", "Content-Length": "0"}, body=b"")
    # same-origin — may be 202 or 429 depending on prior; both are "allowed" (not 403)
    st_ok, _, _ = http("POST", "/refresh", headers={"Origin": origin, "Content-Length": "0"}, body=b"")
    # GET /refresh
    st_get, _, _ = http("GET", "/refresh", headers={"Origin": origin})
    # PUT
    st_put, _, _ = http("PUT", "/refresh", headers={"Origin": origin, "Content-Length": "0"}, body=b"")

    bad_host_ok = st_bad == 403
    null_ok = st_null == 403
    foreign_ok = st_foreign == 403
    same_ok = st_ok in (202, 429)  # allowed through gate
    get_ok = st_get in (405, 404, 403)  # not silently 202 — typically method not allowed if path gated after method check... looking at code: do_GET doesn't handle /refresh specially → static 404
    put_ok = st_put == 405

    record("(8) bad Host → 403", "PASS" if bad_host_ok else "FAIL", str(st_bad))
    record("(8) Origin: null → 403", "PASS" if null_ok else "FAIL", str(st_null))
    record("(8) foreign Origin → 403", "PASS" if foreign_ok else "FAIL", str(st_foreign))
    record("(8) same-origin allowed (202/429)", "PASS" if same_ok else "FAIL", str(st_ok))
    record("(8) GET /refresh not accepted as refresh", "PASS" if get_ok else "FAIL", str(st_get))
    record("(8) PUT → 405", "PASS" if put_ok else "FAIL", str(st_put))

    for ok, fid, exp, act in [
        (bad_host_ok, "P0-8-bad-host", "403", st_bad),
        (null_ok, "P0-8-origin-null", "403", st_null),
        (foreign_ok, "P0-8-origin-foreign", "403", st_foreign),
        (same_ok, "P0-8-same-origin", "202 or 429", st_ok),
        (get_ok, "P0-8-get", "not 202", st_get),
        (put_ok, "P0-8-put", "405", st_put),
    ]:
        if not ok:
            finding(id=fid, component="POST /refresh Host/Origin gate", expected=str(exp), actual=str(act), repro="curl with forged Host/Origin", evidence="host_origin.json", severity="high", confidence="high")
    (OUT / "host_origin.json").write_text(json.dumps({"bad_host": st_bad, "null": st_null, "foreign": st_foreign, "same": st_ok, "get": st_get, "put": st_put}, indent=2), encoding="utf-8")


def check_6_7_9(doc: dict):
    edges = doc.get("edges") or []
    events = doc.get("events") or []
    nodes = doc.get("nodes") or []
    # (6) message edges only from recipients — unit covered; check no edges without matching event recipients
    msg_edges = [e for e in edges if e.get("type") == "message"]
    # fabricated check: every message edge endpoints appear in some event recipients/sender
    fabricated = []
    for e in msg_edges:
        src, tgt = e.get("source"), e.get("target")
        ok = any(
            ev.get("type") == "message"
            and ev.get("sender") == src
            and tgt in (ev.get("recipients") or [])
            for ev in events
        )
        # network events may be mapped differently — also check event_ids
        if not ok and not e.get("event_ids"):
            fabricated.append(e)
    record("(6) message edges trace to recipients", "PASS" if msg_edges and not fabricated else ("FAIL" if fabricated or not msg_edges else "PASS"), f"msg_edges={len(msg_edges)} fabricated={len(fabricated)}")
    if fabricated or not msg_edges:
        finding(id="P0-6-edges", component="message edges", expected="edges only from real recipients", actual=f"msg={len(msg_edges)} fabricated={fabricated[:2]}", repro="inspect activity edges vs network events", evidence="activity_no_ledger.json", severity="high", confidence="medium")

    # (7) start-mac rebuild
    dist = ROOT / "web/dist/index.html"
    mtime_before = dist.stat().st_mtime
    # touch web/src file
    src_file = ROOT / "web/src/App.tsx"
    os.utime(src_file, None)
    time.sleep(0.1)
    # run ensure logic via start-mac dry — call the function by running bash snippet
    env = {**os.environ, "PATH": f"{BIN}{os.pathsep}{os.environ.get('PATH','')}", "MINDMAP_PYTHON": str(ROOT/".venv/bin/python")}
    # Use a short-circuit: source the rebuild check
    script = f'''
set -euo pipefail
REPO_ROOT="{ROOT}"
source /dev/null
# inline the functions from start-mac
{Path(ROOT/"scripts/start-mac.sh").read_text()}
'''
    # Simpler: run start-mac with timeout after touch — but that starts server. Instead invoke ensure_web_dist via bash extract.
    probe = subprocess.run(
        ["bash", "-c", f'''
set -euo pipefail
REPO_ROOT="{ROOT}"
cd "$REPO_ROOT"
REBUILD=false
web_sources_newer_than_dist() {{
  local dist="$REPO_ROOT/web/dist/index.html"
  [[ ! -f "$dist" ]] && return 0
  if find "$REPO_ROOT/web/src" -type f -newer "$dist" -print -quit 2>/dev/null | grep -q .; then return 0; fi
  if find "$REPO_ROOT/shared" -type f -newer "$dist" -print -quit 2>/dev/null | grep -q .; then return 0; fi
  return 1
}}
if web_sources_newer_than_dist; then echo NEEDS_REBUILD; else echo NO_REBUILD; fi
'''],
        capture_output=True, text=True,
    )
    needs = "NEEDS_REBUILD" in probe.stdout
    record("(7) touch web/src → rebuild needed", "PASS" if needs else "FAIL", probe.stdout.strip())
    # restore mtime newer dist by rebuilding once then check no rebuild
    subprocess.run(["npm", "run", "build"], cwd=str(ROOT / "web"), capture_output=True)
    probe2 = subprocess.run(
        ["bash", "-c", f'''
REPO_ROOT="{ROOT}"
web_sources_newer_than_dist() {{
  local dist="$REPO_ROOT/web/dist/index.html"
  [[ ! -f "$dist" ]] && return 0
  if find "$REPO_ROOT/web/src" -type f -newer "$dist" -print -quit 2>/dev/null | grep -q .; then return 0; fi
  if find "$REPO_ROOT/shared" -type f -newer "$dist" -print -quit 2>/dev/null | grep -q .; then return 0; fi
  return 1
}}
if web_sources_newer_than_dist; then echo NEEDS_REBUILD; else echo NO_REBUILD; fi
'''],
        capture_output=True, text=True,
    )
    no_need = "NO_REBUILD" in probe2.stdout
    record("(7) fresh dist → no rebuild", "PASS" if no_need else "FAIL", probe2.stdout.strip())
    if not needs or not no_need:
        finding(id="P0-7-rebuild", component="start-mac.sh web_sources_newer_than_dist", expected="rebuild when src newer; skip otherwise", actual=f"after_touch={probe.stdout.strip()} after_build={probe2.stdout.strip()}", repro="touch web/src/App.tsx; check; npm run build; check", evidence="rebuild.txt", severity="medium", confidence="high")
    (OUT / "rebuild.txt").write_text(f"touch:{probe.stdout}\nbuild:{probe2.stdout}\n", encoding="utf-8")

    # (9) groups: 3 team + owner standalone
    cfg = json.loads((ROOT / "config/groups.json").read_text())
    ids = [g["id"] for g in cfg["groups"]]
    team = [g for g in ids if g != "owner"]
    g_ok = ids[0] == "owner" or "owner" in ids and len(team) == 3
    record("(9) 3 team groups + Owner", "PASS" if len(team) == 3 and "owner" in ids else "FAIL", str(ids))
    # Bug fixer not in radar members
    radar = next(g for g in cfg["groups"] if g["id"] == "radar")
    bf_ok = "bug-fixer" not in radar["members"]
    # but is it rendered in radar cluster? home group radar
    bf_node = next((n for n in nodes if n.get("id") == "bug-fixer"), None)
    record("(9) Bug fixer not in radar.members", "PASS" if bf_ok else "FAIL", str(radar["members"]))
    if bf_node and bf_node.get("group") == "radar":
        finding(id="P0-9-bug-fixer-radar", component="bots.json / layout", expected="Bug fixer not in Radar cluster", actual=f"node.group={bf_node.get('group')} members_ok={bf_ok}", repro="LIVE UI Research/Radar frame", evidence="browser screenshots", severity="medium", confidence="high")
        record("(9) Bug fixer not rendered in Radar", "FAIL", f"group={bf_node.get('group')}")
    else:
        record("(9) Bug fixer not rendered in Radar", "PASS" if not bf_node or bf_node.get("group") != "radar" else "FAIL")

    # message edges exist
    record("(9) message edges exist", "PASS" if msg_edges else "FAIL", f"n={len(msg_edges)}")
    if not msg_edges:
        finding(id="P0-9-message-edges", component="activity.edges", expected="message edges present", actual="0", repro="activity with network events", evidence="activity_no_ledger.json", severity="medium", confidence="high")

    # UNKNOWN sender where real known — check events
    bad_unknown = [e for e in events if e.get("actor") == "UNKNOWN" or e.get("sender") == "UNKNOWN"]
    # filter ones that have resolvable info? hard — flag if any network event has UNKNOWN sender incorrectly
    net_unknown = [e for e in events if e.get("id", "").startswith("p0-") and (e.get("actor") == "UNKNOWN")]
    record("(9) no UNKNOWN sender on known p0 network events", "PASS" if not net_unknown else "FAIL", str(net_unknown)[:120])

    project = doc.get("project") or meta_project(doc)
    record("(5) project is agent-mindmap not Fencepost", "PASS" if project == "agent-mindmap" else "FAIL", str(project))
    if project != "agent-mindmap":
        finding(id="P0-5-project", component="activity.project / header", expected="agent-mindmap", actual=str(project), repro="GET /activity.json; UI header", evidence="activity_no_ledger.json", severity="high", confidence="high")

    # repo field on events
    repos = {e.get("repo") for e in events if e.get("repo")}
    fence_ev = [e for e in events if e.get("repo") == "ManpreetS2/fencepost" or "fencepost" in str(e.get("source_url", ""))]
    record("(5) events carry repo / fencepost attribution", "INFO", f"repos={repos} fence_events={len(fence_ev)}")


def meta_project(doc):
    return (doc.get("meta") or {}).get("project") or doc.get("project")


def browser_checks():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle", timeout=45000)
        page.wait_for_selector("[data-mode]", timeout=15000)
        # settle banner
        page.wait_for_function("() => document.querySelector('[data-mode]')?.getAttribute('data-mode')==='live'", timeout=10000)

        # SOURCE UNAVAILABLE + ledger_error
        body_text = page.locator("body").inner_text()
        src_unavail = "SOURCE UNAVAILABLE" in body_text
        ledger_err = "ledger" in body_text.lower() and ("unavailable" in body_text.lower() or "not found" in body_text.lower() or "ledger_error" in body_text.lower() or "missing" in body_text.lower())
        record("(1) UI shows SOURCE UNAVAILABLE", "PASS" if src_unavail else "FAIL", body_text[:200].replace("\n", " "))
        if not src_unavail:
            finding(id="P0-1-ui-source-unavailable", component="MindmapStatusBar", expected="SOURCE UNAVAILABLE visible", actual=body_text[:300], repro="open UI with missing ledger", evidence="p0-overview.png", severity="high", confidence="high")

        # header project
        header = page.locator(".app-header__project").inner_text()
        header_ok = "agent-mindmap" in header and "Fencepost" not in header and "fencepost" not in header.lower()
        record("(5) header Project: agent-mindmap", "PASS" if header_ok else "FAIL", header)
        if not header_ok:
            finding(id="P0-5-header", component="MindmapView header", expected="Project: agent-mindmap", actual=header, repro="read .app-header__project", evidence="p0-overview.png", severity="high", confidence="high")

        # single status bar
        bars = page.locator(".mindmap-status-bar, .partial-source-banner").count()
        # Mode banner separate OK; source/status should be one mindmap-status-bar
        status_bars = page.locator(".mindmap-status-bar").count()
        record("(4) single MindmapStatusBar", "PASS" if status_bars <= 1 else "FAIL", f"mindmap-status-bar={status_bars} banner-like={bars}")

        page.screenshot(path=str(SHOTS / "p0-overview.png"), full_page=False)

        # group filters: Owner + 3 teams
        labels = page.evaluate("""() => Array.from(document.querySelectorAll('[data-testid=group-filter] button, .group-filter button')).map(b => (b.textContent||'').trim())""")
        record("(9) group filter chips", "INFO", str(labels))

        # repo tag / filter
        has_repo_filter = page.locator("text=/Repo|fencepost|agent-mindmap/i").count() > 0 and page.locator(".timeline-filters__heading", has_text="Repo").count() > 0
        # also check for repo chips/tags on events
        repo_tags = page.evaluate("""() => {
          const t = document.body.innerText;
          return {hasFencepost: /fencepost/i.test(t), hasRepoHeading: /\\bRepo\\b/.test(t)};
        }""")
        record("(5) Fencepost repo tag + filter in UI", "PASS" if has_repo_filter or (repo_tags.get("hasFencepost") and repo_tags.get("hasRepoHeading")) else "FAIL", str(repo_tags))
        if not (has_repo_filter or (repo_tags.get("hasFencepost") and repo_tags.get("hasRepoHeading"))):
            finding(
                id="P0-5-repo-filter",
                component="Timeline / event UI",
                expected="Fencepost events show repo tag and a repo filter",
                actual=f"filters={labels} bodyProbe={repo_tags}",
                repro="inspect timeline filters and event chips for repo",
                evidence="p0-overview.png",
                severity="medium",
                confidence="high",
            )

        # Retry disabled during rate limit — trigger 429 via UI if possible
        # Use API first then check UI retry button
        http("POST", "/refresh", headers={"Origin": f"http://127.0.0.1:{PORT}", "Content-Length": "0"}, body=b"")
        http("POST", "/refresh", headers={"Origin": f"http://127.0.0.1:{PORT}", "Content-Length": "0"}, body=b"")
        page.reload(wait_until="networkidle")
        # click Retry to hit 429
        retry = page.locator("button", has_text="Retry")
        if retry.count():
            retry.first.click()
            time.sleep(0.3)
            # second click quickly
            if retry.count() and retry.first.is_enabled():
                retry.first.click()
            time.sleep(0.5)
            disabled = retry.count() and retry.first.is_disabled()
            rate_txt = "rate limited" in page.locator("body").inner_text().lower() or "try again" in page.locator("body").inner_text().lower()
            record("(3) UI Retry disabled on 429 countdown", "PASS" if disabled or rate_txt else "FAIL", f"disabled={disabled} rate_txt={rate_txt}")
            page.screenshot(path=str(SHOTS / "p0-rate-limit.png"), full_page=False)
            if not (disabled or rate_txt):
                finding(id="P0-3-ui-429", component="MindmapStatusBar Retry", expected="Retry disabled + countdown on 429", actual=f"disabled={disabled}", repro="double-click Retry", evidence="p0-rate-limit.png", severity="medium", confidence="medium")
        else:
            record("(3) UI Retry button present", "FAIL", "no Retry button")
            finding(id="P0-3-ui-retry-missing", component="MindmapStatusBar", expected="Retry button", actual="missing", repro="open UI with SOURCE UNAVAILABLE", evidence="p0-overview.png", severity="medium", confidence="high")

        # Kill SSE → DISCONNECTED, single bar
        page.route("**/events", lambda route: route.abort())
        # wait for disconnect signaling
        time.sleep(3.5)
        txt = page.locator("body").inner_text()
        disc = "DISCONNECTED" in txt
        status_bars = page.locator(".mindmap-status-bar").count()
        record("(4) DISCONNECTED after SSE kill", "PASS" if disc else "FAIL", txt[txt.find("DISC"):txt.find("DISC")+80] if disc else "not found")
        record("(4) still single status bar after disconnect", "PASS" if status_bars <= 1 else "FAIL", f"count={status_bars}")
        page.screenshot(path=str(SHOTS / "p0-disconnected.png"), full_page=False)
        if not disc:
            finding(id="P0-4-disconnected", component="SSE status", expected="DISCONNECTED in status bar", actual="not shown", repro="abort /events in browser", evidence="p0-disconnected.png", severity="high", confidence="high")
        if status_bars > 1:
            finding(id="P0-4-duplicate-bars", component="MindmapStatusBar", expected="one status bar", actual=f"count={status_bars}", repro="same", evidence="p0-disconnected.png", severity="medium", confidence="high")
        page.unroute("**/events")

        # Drag persist across reload
        page.add_style_tag(content="[data-testid=group-filter]{pointer-events:none !important}")
        node = page.locator(".react-flow__node").filter(has_text="Director").first
        if node.count() == 0:
            node = page.locator(".react-flow__node").first
        handle = node.locator(".agent-node-drag-handle")
        box = node.bounding_box()
        persisted = False
        moved = False
        if handle.count() and box:
            h = handle.bounding_box()
            page.mouse.move(h["x"] + 3, h["y"] + 3)
            page.mouse.down()
            page.mouse.move(h["x"] + 140, h["y"] + 90, steps=20)
            page.mouse.up()
            time.sleep(0.4)
            box2 = node.bounding_box()
            moved = box2 and (abs(box2["x"] - box["x"]) > 20)
            page.screenshot(path=str(SHOTS / "p0-after-drag.png"), full_page=False)
            page.reload(wait_until="networkidle")
            page.wait_for_selector("[data-mode]", timeout=10000)
            node2 = page.locator(".react-flow__node").filter(has_text="Director").first
            if node2.count() == 0:
                node2 = page.locator(".react-flow__node").first
            box3 = node2.bounding_box()
            if moved and box2 and box3:
                persisted = abs(box3["x"] - box2["x"]) < 30 and abs(box3["y"] - box2["y"]) < 30
            (OUT / "drag.json").write_text(json.dumps({"before": box, "after": box2, "reload": box3, "moved": moved, "persisted": persisted}, indent=2), encoding="utf-8")
        record("(9) drag moves", "PASS" if moved else "FAIL")
        record("(9) drag persists across reload", "PASS" if persisted else "FAIL", f"moved={moved} persisted={persisted}")
        if not persisted:
            finding(id="P0-9-drag-persist", component="AgentGraph positions", expected="dragged position persists across reload", actual=f"moved={moved} persisted={persisted}", repro="drag Director handle; reload", evidence="p0-after-drag.png, drag.json", severity="medium", confidence="high")

        # UNKNOWN vs IDLE pills visible
        page.screenshot(path=str(SHOTS / "p0-final.png"), full_page=False)
        browser.close()


def browser_unreachable():
    from playwright.sync_api import sync_playwright

    proc2 = start_mac()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            page.goto(f"http://127.0.0.1:{PORT}/", wait_until="networkidle", timeout=30000)
            page.wait_for_selector("[data-mode]")
            stop(proc2)
            proc2 = None
            time.sleep(0.3)
            btn = page.locator("button", has_text="Retry")
            if btn.count():
                btn.first.click()
                time.sleep(1.2)
            txt = page.locator("body").inner_text()
            unreachable = "unreachable" in txt.lower()
            record("(3) server stopped → unreachable UI", "PASS" if unreachable else "FAIL", txt[-200:].replace("\n", " "))
            page.screenshot(path=str(SHOTS / "p0-unreachable.png"), full_page=False)
            if not unreachable:
                finding(id="P0-3-unreachable", component="postRefresh / status bar", expected='shows "server unreachable"', actual=txt[-300:], repro="load UI; kill server; click Retry", evidence="p0-unreachable.png", severity="high", confidence="high")
            browser.close()
    finally:
        stop(proc2)


def main() -> int:
    os.chdir(ROOT)
    BIN.mkdir(parents=True, exist_ok=True)
    events_path = seed_events()

    proc = start_mac(unset_ledger=True)
    try:
        doc = check_1_ledger_missing()
        check_2_and_3(events_path)
        check_8_host_origin()
        st, _, body = http("GET", "/activity.json")
        doc = json.loads(body) if st == 200 else doc
        check_6_7_9(doc)
        browser_checks()
    finally:
        stop(proc)

    browser_unreachable()

    report = {"merged": MERGED, "pr30": "4bcb907", "pr29": "e3d4db5", "checks": checks, "findings": findings}
    (OUT / "e2e_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("\n=== SUMMARY ===", flush=True)
    print("PASS", sum(1 for c in checks if c["result"] == "PASS"), flush=True)
    print("FAIL", sum(1 for c in checks if c["result"] == "FAIL"), flush=True)
    print("INFO", sum(1 for c in checks if c["result"] == "INFO"), flush=True)
    print("FINDINGS", len(findings), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
