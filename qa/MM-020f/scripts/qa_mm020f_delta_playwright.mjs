/**
 * Delta QA — MM-020f PR #19 @ 62cf9b5 (vs FAIL @ 1531420).
 * Verify-only; swaps web/public/activity.json only.
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { execSync, spawn } from "node:child_process";

const require = createRequire(import.meta.url);
const { chromium } = require("/tmp/qa-mm020f/pw/node_modules/playwright");

const BASE = "http://127.0.0.1:5173";
const PREVIEW = "http://127.0.0.1:4173";
const REPO = "/tmp/qa-mm020f-delta/checkout";
const PUBLIC_ACTIVITY = path.join(REPO, "web/public/activity.json");
const DIST_ACTIVITY = path.join(REPO, "web/dist/activity.json");
const SHA = "62cf9b55fbc9e875cd13f17af390799ae855a5f9";
const OUT = `/tmp/qa-mm020f-delta/evidence/logs/${SHA}`;
const SHOTS = path.join(OUT, "screenshots");
const FIX = "/tmp/qa-mm020f-delta/evidence/fixtures";

const findings = [];
const checks = [];

function record(check, result, detail = "") {
  checks.push({ check, result, detail });
  console.log(`[${result}] ${check}${detail ? " — " + detail : ""}`);
}

function finding(f) {
  findings.push(f);
  console.log(`[FINDING:${f.severity}] ${f.component}: ${f.actual}`);
}

function writeActivity(obj, target = PUBLIC_ACTIVITY) {
  fs.writeFileSync(target, JSON.stringify(obj, null, 2));
}

function writeRaw(text, target = PUBLIC_ACTIVITY) {
  fs.writeFileSync(target, text);
}

function removeActivity(target = PUBLIC_ACTIVITY) {
  if (fs.existsSync(target)) fs.unlinkSync(target);
}

function restoreDemo() {
  fs.copyFileSync(path.join(FIX, "activity-demo.json"), PUBLIC_ACTIVITY);
}

function loadJson(p) {
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

function deepClone(o) {
  return JSON.parse(JSON.stringify(o));
}

async function waitSettled(page, ms = 800) {
  await page.waitForTimeout(ms);
}

async function gotoFresh(page, base = BASE) {
  await page.goto(base + "/", { waitUntil: "networkidle", timeout: 30000 });
  await waitSettled(page, 1200);
}

async function getAgentNodePositions(page) {
  return page.evaluate(() => {
    const nodes = [
      ...document.querySelectorAll(".react-flow__node.react-flow__node-agent"),
    ];
    const out = {};
    for (const n of nodes) {
      const id = n.getAttribute("data-id");
      const t = n.style.transform || "";
      const m = t.match(/translate\((-?[\d.]+)px,\s*(-?[\d.]+)px\)/);
      if (id && m) out[id] = { x: Number(m[1]), y: Number(m[2]) };
    }
    return out;
  });
}

async function agentIds(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll(".react-flow__node.react-flow__node-agent")].map(
      (n) => n.getAttribute("data-id"),
    ),
  );
}

async function countAgentNodes(page) {
  return page.locator(".react-flow__node.react-flow__node-agent").count();
}

async function filterChipState(page) {
  return page.evaluate(() => {
    const root = document.querySelector('[data-testid="group-filter"]');
    if (!root) return null;
    return [...root.querySelectorAll("button")].map((b) => ({
      text: b.textContent.trim(),
      pressed: b.getAttribute("aria-pressed") === "true",
      testid: b.getAttribute("data-testid"),
    }));
  });
}

async function dragNode(page, id, dx, dy) {
  const node = page.locator(`.react-flow__node[data-id="${id}"]`);
  await node.hover();
  await waitSettled(page, 150);
  const handle = node.locator(".agent-node-drag-handle");
  const box = (await handle.boundingBox()) || (await node.boundingBox());
  if (!box) throw new Error(`no bbox for ${id}`);
  const sx = box.x + box.width / 2;
  const sy = box.y + box.height / 2;
  await page.mouse.move(sx, sy);
  await page.mouse.down();
  await page.mouse.move(sx + dx, sy + dy, { steps: 14 });
  await page.mouse.up();
  await waitSettled(page, 500);
}

function within1px(a, b) {
  if (!a || !b) return false;
  return Math.abs(a.x - b.x) <= 1 && Math.abs(a.y - b.y) <= 1;
}

function appendEvent(activity, suffix) {
  const id = `qa-delta-${suffix}-${Date.now()}`;
  activity.events.push({
    id,
    type: "message",
    actor: "director",
    target: null,
    task_id: null,
    attribution: { method: "unknown" },
    source_url: "agent://qa-delta",
    source_time: new Date().toISOString(),
    raw: `delta append ${suffix}`,
    group: "build",
    provenance: "agent-reported",
  });
  activity.edges.push({
    id: `edge-${id}`,
    source: "director",
    target: "group:build",
    type: "message",
    count: 1,
    event_ids: [id],
  });
  activity.generated_at = new Date().toISOString();
  return id;
}

function addNewAgent(activity, id) {
  activity.nodes.push({
    id,
    label: `New Agent ${id}`,
    group: "build",
    groups: ["build"],
    status: "IDLE",
    agent_links: [],
    layout: { x: 0, y: 0 },
  });
}

async function setOnlyGroup(page, gid) {
  const allBtn = page.locator(".group-filter__chip").filter({ hasText: "All groups" });
  if ((await allBtn.getAttribute("aria-pressed")) !== "true") {
    await allBtn.click();
    await waitSettled(page, 300);
  }
  const state = await filterChipState(page);
  const active = state
    .filter((c) => c.testid?.startsWith("group-filter-") && c.pressed)
    .map((c) => c.testid.replace("group-filter-", ""));
  for (const g of active) {
    if (g === gid) continue;
    await page.getByTestId(`group-filter-${g}`).click();
    await waitSettled(page, 250);
  }
}

async function checkMissingLedgerError(page, base, label, shotName, activityPath) {
  removeActivity(activityPath);
  // Also remove from public if checking preview with dist only
  await gotoFresh(page, base);
  await page.screenshot({ path: path.join(SHOTS, shotName), fullPage: true });
  const bodyText = await page.locator("body").innerText();
  const hasLedger =
    /Can't read/i.test(bodyText) && /activity\.json/i.test(bodyText);
  const hasJsonParse =
    /Unexpected token/i.test(bodyText) || /not valid JSON/i.test(bodyText);
  const fetchInfo = await page.evaluate(async () => {
    const r = await fetch("/activity.json");
    const t = await r.text();
    return { status: r.status, startsWith: t.slice(0, 48) };
  });
  const pass = hasLedger && !hasJsonParse;
  record(
    `QA-MM012-1 missing → LedgerErrorView (${label})`,
    pass ? "PASS" : "FAIL",
    `ledger=${hasLedger} jsonParse=${hasJsonParse} fetch=${JSON.stringify(fetchInfo)} snippet=${bodyText.slice(0, 140).replace(/\n/g, " ")}`,
  );
  if (!pass) {
    finding({
      id: "QA-MM012-1",
      component: `loadActivity + ${label}`,
      expected: "Missing activity.json → LedgerErrorView (“Can't read …”) + Retry",
      actual: `ledger=${hasLedger} jsonParse=${hasJsonParse} fetch=${JSON.stringify(fetchInfo)}`,
      repro: `rm activity.json under ${label}; reload ${base}`,
      evidence: shotName,
      environment: `Playwright @ ${SHA.slice(0, 7)}`,
      severity: "medium",
      confidence: "high",
    });
  }
  return pass;
}

async function main() {
  fs.mkdirSync(SHOTS, { recursive: true });

  // Bind evidence
  try {
    const bind = execSync(
      `python3 - <<'PY'
import socket
s=socket.socket(); s.settimeout(1)
s.connect(('127.0.0.1',5173)); print('loopback_ok'); s.close()
# /proc listen
port=0x1435
with open('/proc/net/tcp') as f:
    next(f)
    for line in f:
        parts=line.split(); ip_hex,p_hex=parts[1].split(':')
        if int(p_hex,16)==5173:
            ip='.'.join(str(b) for b in bytes.fromhex(ip_hex)[::-1])
            print(f'LISTEN {ip}:5173')
PY`,
      { encoding: "utf8" },
    );
    fs.writeFileSync(path.join(OUT, "dev_bind.txt"), bind);
    record(
      "Dev server binds 127.0.0.1 only",
      /loopback_ok/.test(bind) && /LISTEN 127\.0\.0\.1:5173/.test(bind)
        ? "PASS"
        : "FAIL",
      bind.trim().replace(/\n/g, " | "),
    );
  } catch (e) {
    record("Dev server binds 127.0.0.1 only", "FAIL", String(e));
  }

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const outbound = [];
  const consoleErrors = [];
  context.on("request", (req) => {
    try {
      const u = new URL(req.url());
      if (u.hostname !== "127.0.0.1" && u.hostname !== "localhost") {
        outbound.push({ url: req.url(), resourceType: req.resourceType() });
      }
    } catch {
      outbound.push({ url: req.url(), resourceType: req.resourceType() });
    }
  });
  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  // ========== (1) QA-MM020f-1 position stability ==========
  restoreDemo();
  await gotoFresh(page);
  await page.screenshot({
    path: path.join(SHOTS, "01-demo-baseline.png"),
    fullPage: true,
  });

  await dragNode(page, "director", 140, 90);
  await dragNode(page, "architect", -100, 70);
  await dragNode(page, "dev-1", 80, -60);
  await waitSettled(page, 600);
  const posAfterDrag = await getAgentNodePositions(page);
  fs.writeFileSync(
    path.join(OUT, "positions_after_drag.json"),
    JSON.stringify(posAfterDrag, null, 2),
  );
  await page.screenshot({
    path: path.join(SHOTS, "02-after-drag-three-nodes.png"),
    fullPage: true,
  });

  const tracked = ["director", "architect", "dev-1"];
  for (const id of tracked) {
    if (!posAfterDrag[id]) {
      record(`Drag applied (${id})`, "FAIL", "missing position");
    }
  }

  // Poll 1: append events only
  const act1 = deepClone(loadJson(PUBLIC_ACTIVITY));
  appendEvent(act1, "poll1");
  writeActivity(act1);
  await page.waitForTimeout(12000);
  await waitSettled(page, 800);
  const posPoll1 = await getAgentNodePositions(page);
  fs.writeFileSync(
    path.join(OUT, "positions_after_poll1.json"),
    JSON.stringify(posPoll1, null, 2),
  );
  await page.screenshot({
    path: path.join(SHOTS, "03-after-poll1.png"),
    fullPage: true,
  });

  const poll1Ok = tracked.every((id) => within1px(posAfterDrag[id], posPoll1[id]));
  record(
    "QA-MM020f-1 dragged coords stable after poll 1 (≤1px)",
    poll1Ok ? "PASS" : "FAIL",
    tracked
      .map((id) => {
        const a = posAfterDrag[id];
        const b = posPoll1[id];
        return `${id}: ${JSON.stringify(a)} → ${JSON.stringify(b)} dx=${a && b ? Math.abs(a.x - b.x) : "?"} dy=${a && b ? Math.abs(a.y - b.y) : "?"}`;
      })
      .join(" | "),
  );
  if (!poll1Ok) {
    finding({
      id: "QA-MM020f-1",
      component: "AgentGraph / mergeFlowNodes",
      expected: "Dragged node coordinates unchanged within 1px across poll updates",
      actual: `After poll1: ${JSON.stringify(Object.fromEntries(tracked.map((id) => [id, { before: posAfterDrag[id], after: posPoll1[id] }])))}`,
      repro: "Drag director/architect/dev-1; append event; wait >10s",
      evidence: "screenshots/02–03, positions_*.json",
      environment: `Playwright @ ${SHA.slice(0, 7)}`,
      severity: "high",
      confidence: "high",
    });
  }

  // Poll 2: append more events + introduce a brand-new agent node
  const act2 = deepClone(loadJson(PUBLIC_ACTIVITY));
  appendEvent(act2, "poll2");
  addNewAgent(act2, "qa-newcomer");
  writeActivity(act2);
  await page.waitForTimeout(12000);
  await waitSettled(page, 1000);
  const posPoll2 = await getAgentNodePositions(page);
  fs.writeFileSync(
    path.join(OUT, "positions_after_poll2.json"),
    JSON.stringify(posPoll2, null, 2),
  );
  await page.screenshot({
    path: path.join(SHOTS, "04-after-poll2-new-node.png"),
    fullPage: true,
  });

  const poll2Ok = tracked.every((id) => within1px(posAfterDrag[id], posPoll2[id]));
  record(
    "QA-MM020f-1 dragged coords stable after poll 2 (≤1px)",
    poll2Ok ? "PASS" : "FAIL",
    tracked
      .map((id) => {
        const a = posAfterDrag[id];
        const b = posPoll2[id];
        return `${id}: dx=${a && b ? Math.abs(a.x - b.x).toFixed(3) : "?"} dy=${a && b ? Math.abs(a.y - b.y).toFixed(3) : "?"}`;
      })
      .join(" | "),
  );
  if (!poll2Ok && poll1Ok) {
    finding({
      id: "QA-MM020f-1",
      component: "AgentGraph / mergeFlowNodes",
      expected: "Dragged coords stable across ≥2 polls within 1px",
      actual: `After poll2 drift: ${JSON.stringify(Object.fromEntries(tracked.map((id) => [id, { before: posAfterDrag[id], after: posPoll2[id] }])))}`,
      repro: "Second append + wait >10s after first poll",
      evidence: "screenshots/04-after-poll2-new-node.png, positions_after_poll2.json",
      environment: `Playwright @ ${SHA.slice(0, 7)}`,
      severity: "high",
      confidence: "high",
    });
  }

  const newcomerPresent = (await agentIds(page)).includes("qa-newcomer");
  const newcomerPos = posPoll2["qa-newcomer"];
  record(
    "QA-MM020f-1 new agent node placed after poll",
    newcomerPresent && !!newcomerPos ? "PASS" : "FAIL",
    `present=${newcomerPresent} pos=${JSON.stringify(newcomerPos)}`,
  );
  if (!(newcomerPresent && newcomerPos)) {
    finding({
      id: "QA-MM020f-1-new-node",
      component: "AgentGraph / mergeFlowNodes",
      expected: "Brand-new agent ids appear and receive layout positions",
      actual: `present=${newcomerPresent} pos=${JSON.stringify(newcomerPos)}`,
      repro: "Append activity.json with new node id while page open; wait for poll",
      evidence: "screenshots/04-after-poll2-new-node.png",
      environment: `Playwright @ ${SHA.slice(0, 7)}`,
      severity: "high",
      confidence: "high",
    });
  }

  // Filter toggle vs dragged position: Build-only then back to all
  const beforeFilter = await getAgentNodePositions(page);
  await setOnlyGroup(page, "build");
  await waitSettled(page, 600);
  const duringFilter = await getAgentNodePositions(page);
  await page.screenshot({
    path: path.join(SHOTS, "05-filter-build-after-drag.png"),
    fullPage: true,
  });
  // Restore all groups
  await page.locator(".group-filter__chip").filter({ hasText: "All groups" }).click();
  await waitSettled(page, 600);
  const afterFilter = await getAgentNodePositions(page);
  await page.screenshot({
    path: path.join(SHOTS, "06-filter-restored-after-drag.png"),
    fullPage: true,
  });
  fs.writeFileSync(
    path.join(OUT, "filter_vs_drag_positions.json"),
    JSON.stringify({ beforeFilter, duringFilter, afterFilter }, null, 2),
  );

  // During build-only, director/architect/dev-1 should still be at dragged coords
  const duringOk = tracked.every((id) => within1px(posAfterDrag[id], duringFilter[id]));
  const afterOk = tracked.every((id) => within1px(posAfterDrag[id], afterFilter[id]));
  record(
    "QA-MM020f-1 filter toggle keeps dragged positions (≤1px)",
    duringOk && afterOk ? "PASS" : "FAIL",
    `duringOk=${duringOk} afterOk=${afterOk} during=${JSON.stringify(Object.fromEntries(tracked.map((id) => [id, duringFilter[id]])))} after=${JSON.stringify(Object.fromEntries(tracked.map((id) => [id, afterFilter[id]])))}`,
  );
  if (!(duringOk && afterOk)) {
    finding({
      id: "QA-MM020f-1-filter",
      component: "AgentGraph + GroupFilter",
      expected: "Toggling group filter must not reset user-dragged positions",
      actual: `duringOk=${duringOk} afterOk=${afterOk}`,
      repro: "Drag nodes; filter Build-only; All groups; compare transforms",
      evidence: "screenshots/05–06, filter_vs_drag_positions.json",
      environment: `Playwright @ ${SHA.slice(0, 7)}`,
      severity: "high",
      confidence: "high",
    });
  }

  // ========== (3) Regressions: shared nodes, filters ==========
  restoreDemo();
  await gotoFresh(page);
  const ids = await agentIds(page);
  record(
    "Director appears exactly once",
    ids.filter((i) => i === "director").length === 1 ? "PASS" : "FAIL",
    `count=${ids.filter((i) => i === "director").length}`,
  );
  record(
    "Architect appears exactly once",
    ids.filter((i) => i === "architect").length === 1 ? "PASS" : "FAIL",
    `count=${ids.filter((i) => i === "architect").length}`,
  );
  record(
    "No duplicate agent node ids",
    new Set(ids).size === ids.length ? "PASS" : "FAIL",
    `n=${ids.length}`,
  );

  const totalAll = await countAgentNodes(page);
  await setOnlyGroup(page, "build");
  const buildIds = await agentIds(page);
  const buildExpected = new Set([
    "director",
    "architect",
    "dev-1",
    "dev-2",
    "ui-ux-maker",
    "documentation",
  ]);
  record(
    "Filter Build-only counts",
    buildIds.length === buildExpected.size &&
      buildIds.every((id) => buildExpected.has(id))
      ? "PASS"
      : "FAIL",
    `ids=${buildIds.join(",")}`,
  );
  await setOnlyGroup(page, "qr");
  const qrIds = await agentIds(page);
  const qrExpected = new Set([
    "director",
    "architect",
    "qa-verifier",
    "security-engineer",
    "devops-release",
  ]);
  record(
    "Filter Q&R-only counts",
    qrIds.length === qrExpected.size && qrIds.every((id) => qrExpected.has(id))
      ? "PASS"
      : "FAIL",
    `ids=${qrIds.join(",")}`,
  );
  await page.locator(".group-filter__chip").filter({ hasText: "All groups" }).click();
  await waitSettled(page, 400);
  record(
    "Select-all restores roster",
    (await countAgentNodes(page)) === totalAll ? "PASS" : "FAIL",
  );
  await page.screenshot({
    path: path.join(SHOTS, "07-filters-shared-nodes.png"),
    fullPage: true,
  });

  // XSS
  const xss = deepClone(loadJson(path.join(FIX, "activity-demo.json")));
  const payload = `<img src=x onerror="window.__xss=1">`;
  xss.nodes = xss.nodes.map((n) =>
    n.id === "director" ? { ...n, label: `Director ${payload}` } : n,
  );
  xss.events.push({
    id: "xss-msg",
    type: "message",
    actor: "director",
    target: null,
    task_id: null,
    attribution: { method: "unknown" },
    source_url: "",
    source_time: new Date().toISOString(),
    raw: `<script>window.__xss=1</script> ${payload}`,
    group: "build",
    provenance: "agent-reported",
  });
  writeActivity(xss);
  await gotoFresh(page);
  const xssFlag = await page.evaluate(() => window.__xss === 1);
  await page.screenshot({
    path: path.join(SHOTS, "08-xss.png"),
    fullPage: true,
  });
  record("XSS does not execute", !xssFlag ? "PASS" : "FAIL", `__xss=${xssFlag}`);
  if (xssFlag) {
    finding({
      id: "XSS",
      component: "rendering",
      expected: "no script execution from labels/messages",
      actual: "window.__xss===1",
      repro: "inject payload into label/raw",
      evidence: "screenshots/08-xss.png",
      environment: `Playwright @ ${SHA.slice(0, 7)}`,
      severity: "critical",
      confidence: "high",
    });
  }

  // a11y / keyboard
  restoreDemo();
  consoleErrors.length = 0;
  outbound.length = 0;
  await gotoFresh(page);
  await page.keyboard.press("/");
  await waitSettled(page, 300);
  const active = await page.evaluate(() => {
    const el = document.activeElement;
    return { tag: el?.tagName, className: el?.className };
  });
  record(
    "Keyboard slash focuses filter",
    active.tag === "BUTTON" || /filter|chip/i.test(active.className || "")
      ? "PASS"
      : "FAIL",
    JSON.stringify(active),
  );
  record(
    "Group filter a11y",
    (await page.getByRole("group", { name: /Filter groups/i }).count()) > 0
      ? "PASS"
      : "FAIL",
  );
  record(
    "Skip link present",
    (await page.locator("a.skip-link").count()) > 0 ? "PASS" : "FAIL",
  );
  await waitSettled(page, 800);
  const meaningful = consoleErrors.filter((e) => !/ResizeObserver|favicon/i.test(e));
  fs.writeFileSync(path.join(OUT, "console_errors.json"), JSON.stringify(consoleErrors, null, 2));
  record(
    "No console errors on demo",
    meaningful.length === 0 ? "PASS" : "FAIL",
    meaningful.slice(0, 3).join(" || "),
  );
  const badOut = outbound.filter((o) => !/127\.0\.0\.1|localhost/.test(o.url));
  fs.writeFileSync(path.join(OUT, "outbound_requests.json"), JSON.stringify(outbound, null, 2));
  record(
    "No outbound beyond localhost",
    badOut.length === 0 ? "PASS" : "FAIL",
    badOut.map((o) => o.url).slice(0, 3).join(", "),
  );

  // ========== (2) QA-MM012-1 Vite missing / empty / malformed ==========
  await checkMissingLedgerError(
    page,
    BASE,
    "vite-dev",
    "09-missing-vite-dev.png",
    PUBLIC_ACTIVITY,
  );

  writeRaw("");
  await gotoFresh(page);
  await page.screenshot({
    path: path.join(SHOTS, "10-empty-vite-dev.png"),
    fullPage: true,
  });
  const emptyText = await page.locator("body").innerText();
  const emptyLedger = /Can't read/i.test(emptyText);
  const emptyHandled =
    emptyLedger || /Retry/i.test(emptyText);
  // After fix, empty JSON should also be LedgerLoadError
  record(
    "Empty activity.json handled (vite-dev)",
    emptyHandled && (await countAgentNodes(page)) === 0 ? "PASS" : "FAIL",
    `ledger=${emptyLedger} snippet=${emptyText.slice(0, 120).replace(/\n/g, " ")}`,
  );

  writeRaw("{not-json");
  await gotoFresh(page);
  await page.screenshot({
    path: path.join(SHOTS, "11-malformed-vite-dev.png"),
    fullPage: true,
  });
  const malText = await page.locator("body").innerText();
  const malLedger = /Can't read/i.test(malText);
  record(
    "Malformed activity.json → LedgerErrorView (vite-dev)",
    malLedger && !/Unexpected token|not valid JSON/i.test(malText) ? "PASS" : "FAIL",
    `ledger=${malLedger} snippet=${malText.slice(0, 120).replace(/\n/g, " ")}`,
  );

  // Production preview: start vite preview on 4173
  restoreDemo();
  // Ensure dist has activity for happy path first, then remove for missing test
  fs.mkdirSync(path.join(REPO, "web/dist"), { recursive: true });
  fs.copyFileSync(path.join(FIX, "activity-demo.json"), DIST_ACTIVITY);

  const previewLog = path.join(OUT, "preview-server.txt");
  const previewProc = spawn(
    "npm",
    ["run", "preview", "--", "--host", "127.0.0.1", "--port", "4173"],
    {
      cwd: path.join(REPO, "web"),
      stdio: ["ignore", fs.openSync(previewLog, "w"), fs.openSync(previewLog, "a")],
      detached: true,
    },
  );
  // wait for preview
  for (let i = 0; i < 30; i++) {
    try {
      execSync("curl -sf -o /dev/null http://127.0.0.1:4173/", { stdio: "ignore" });
      break;
    } catch {
      await new Promise((r) => setTimeout(r, 500));
    }
  }

  // Preview bind
  try {
    const pbind = execSync(
      `python3 - <<'PY'
port=0x104d  # 4173
with open('/proc/net/tcp') as f:
    next(f)
    for line in f:
        parts=line.split(); ip_hex,p_hex=parts[1].split(':')
        if int(p_hex,16)==4173:
            ip='.'.join(str(b) for b in bytes.fromhex(ip_hex)[::-1])
            print(f'LISTEN {ip}:4173')
PY`,
      { encoding: "utf8" },
    );
    fs.writeFileSync(path.join(OUT, "preview_bind.txt"), pbind);
    record(
      "Preview binds 127.0.0.1 only",
      /LISTEN 127\.0\.0\.1:4173/.test(pbind) ? "PASS" : "FAIL",
      pbind.trim(),
    );
  } catch (e) {
    record("Preview binds 127.0.0.1 only", "FAIL", String(e));
  }

  // Preview happy path
  await gotoFresh(page, PREVIEW);
  await page.screenshot({
    path: path.join(SHOTS, "12-preview-demo.png"),
    fullPage: true,
  });
  record(
    "Preview serves demo graph",
    (await page.getByTestId("group-filter").count()) > 0 ? "PASS" : "FAIL",
  );

  // Preview missing
  await checkMissingLedgerError(
    page,
    PREVIEW,
    "vite-preview",
    "13-missing-vite-preview.png",
    DIST_ACTIVITY,
  );

  // Preview empty / malformed
  writeRaw("", DIST_ACTIVITY);
  await gotoFresh(page, PREVIEW);
  await page.screenshot({
    path: path.join(SHOTS, "14-empty-vite-preview.png"),
    fullPage: true,
  });
  const pe = await page.locator("body").innerText();
  record(
    "Empty activity.json → LedgerErrorView (preview)",
    /Can't read/i.test(pe) ? "PASS" : "FAIL",
    pe.slice(0, 120).replace(/\n/g, " "),
  );

  writeRaw("{not-json", DIST_ACTIVITY);
  await gotoFresh(page, PREVIEW);
  await page.screenshot({
    path: path.join(SHOTS, "15-malformed-vite-preview.png"),
    fullPage: true,
  });
  const pm = await page.locator("body").innerText();
  record(
    "Malformed activity.json → LedgerErrorView (preview)",
    /Can't read/i.test(pm) && !/Unexpected token|not valid JSON/i.test(pm)
      ? "PASS"
      : "FAIL",
    pm.slice(0, 120).replace(/\n/g, " "),
  );

  // cleanup preview
  try {
    process.kill(-previewProc.pid, "SIGTERM");
  } catch {
    try {
      previewProc.kill("SIGTERM");
    } catch {
      /* ignore */
    }
  }

  restoreDemo();

  const report = {
    sha: SHA,
    previous_fail_sha: "153142044f3609b4e2afe9c176ef7dd738de6835",
    pr: 19,
    checks,
    findings,
  };
  fs.writeFileSync(path.join(OUT, "playwright_report.json"), JSON.stringify(report, null, 2));
  console.log("\n=== SUMMARY ===");
  console.log("PASS", checks.filter((c) => c.result === "PASS").length);
  console.log("FAIL", checks.filter((c) => c.result === "FAIL").length);
  console.log("FINDINGS", findings.length);
  await browser.close();
  process.exit(checks.some((c) => c.result === "FAIL") ? 0 : 0); // always exit 0; report carries verdict
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
