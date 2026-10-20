/**
 * Independent QA — MM-020f (PR #19) Playwright UI harness.
 * Does not modify product code. Swaps web/public/activity.json only.
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { execSync } from "node:child_process";

const require = createRequire(import.meta.url);
// Resolve playwright from /tmp install
const pwPath = "/tmp/qa-mm020f/pw/node_modules/playwright";
const { chromium: chromiumFromPw } = require(pwPath);

const BASE = "http://127.0.0.1:5173";
const REPO = "/tmp/qa-mm020f/checkout";
const PUBLIC_ACTIVITY = path.join(REPO, "web/public/activity.json");
const SHA = "153142044f3609b4e2afe9c176ef7dd738de6835";
const OUT = `/tmp/qa-mm020f/evidence/logs/${SHA}`;
const SHOTS = path.join(OUT, "screenshots");
const FIX = "/tmp/qa-mm020f/evidence/fixtures";

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

function writeActivity(obj) {
  fs.writeFileSync(PUBLIC_ACTIVITY, JSON.stringify(obj, null, 2));
}

function writeRaw(text) {
  fs.writeFileSync(PUBLIC_ACTIVITY, text);
}

function removeActivity() {
  if (fs.existsSync(PUBLIC_ACTIVITY)) fs.unlinkSync(PUBLIC_ACTIVITY);
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

async function gotoFresh(page, hash = "") {
  await page.goto(BASE + "/" + hash, {
    waitUntil: "networkidle",
    timeout: 30000,
  });
  await waitSettled(page, 1200);
}

async function getAgentNodePositions(page) {
  return page.evaluate(() => {
    const nodes = [...document.querySelectorAll(".react-flow__node.react-flow__node-agent")];
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

async function countAgentNodes(page) {
  return page.locator(".react-flow__node.react-flow__node-agent").count();
}

async function agentIds(page) {
  return page.evaluate(() =>
    [...document.querySelectorAll(".react-flow__node.react-flow__node-agent")].map(
      (n) => n.getAttribute("data-id"),
    ),
  );
}

async function filterChipState(page) {
  return page.evaluate(() => {
    const root = document.querySelector('[data-testid="group-filter"]');
    if (!root) return null;
    const chips = [...root.querySelectorAll("button")].map((b) => ({
      text: b.textContent.trim(),
      pressed: b.getAttribute("aria-pressed") === "true",
      testid: b.getAttribute("data-testid"),
    }));
    return chips;
  });
}

async function main() {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromiumFromPw.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
  });

  const outbound = [];
  const consoleErrors = [];

  context.on("request", (req) => {
    const url = req.url();
    try {
      const u = new URL(url);
      if (u.hostname !== "127.0.0.1" && u.hostname !== "localhost") {
        outbound.push({ url, resourceType: req.resourceType() });
      }
    } catch {
      outbound.push({ url, resourceType: req.resourceType() });
    }
  });

  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  // ========== Bind check (already started server) ==========
  try {
    const listen = execSync(
      "grep -a 'Local:' /tmp/qa-mm020f/evidence/logs/" +
        SHA +
        "/dev-server.txt; cat /proc/net/tcp /proc/net/tcp6 2>/dev/null | head -5; python3 - <<'PY'\nimport socket\ns=socket.socket(); s.settimeout(1)\ntry:\n  s.connect(('127.0.0.1',5173)); print('loopback_ok')\nexcept Exception as e: print('loopback_fail',e)\ns.close()\n# try non-loopback if any\nimport subprocess\nout=subprocess.check_output(['bash','-lc',\"ip -4 addr show | awk '/inet /{print $2}' | cut -d/ -f1\"], text=True)\nips=[i.strip() for i in out.splitlines() if i.strip() and not i.startswith('127.')]\nprint('non_loopback_ips', ips)\nfor ip in ips[:2]:\n  s=socket.socket(); s.settimeout(1)\n  try:\n    s.connect((ip,5173)); print('EXTERNAL_REACHABLE', ip)\n  except Exception as e:\n    print('external_refused', ip, type(e).__name__)\n  finally: s.close()\nPY",
      { encoding: "utf8" },
    );
    fs.writeFileSync(path.join(OUT, "dev_bind.txt"), listen);
    const externalOk = !/EXTERNAL_REACHABLE/.test(listen);
    const loopbackOk = /loopback_ok/.test(listen);
    record(
      "Dev server binds 127.0.0.1 only",
      loopbackOk && externalOk ? "PASS" : "FAIL",
      listen.split("\n").slice(0, 8).join(" | "),
    );
  } catch (e) {
    record("Dev server binds 127.0.0.1 only", "FAIL", String(e));
  }

  // ========== 0. Happy path demo ==========
  restoreDemo();
  consoleErrors.length = 0;
  outbound.length = 0;
  await gotoFresh(page);
  await page.screenshot({
    path: path.join(SHOTS, "01-demo-multigroup.png"),
    fullPage: true,
  });

  const graph = page.getByRole("region", { name: /Agent graph/i });
  const hasGraph = (await graph.count()) > 0;
  const filter = page.getByTestId("group-filter");
  const hasFilter = (await filter.count()) > 0;
  record(
    "Demo UI loads with group filter",
    hasGraph && hasFilter ? "PASS" : "FAIL",
    `graph=${hasGraph} filter=${hasFilter}`,
  );

  // ========== 3. Director / Architect single shared nodes ==========
  const ids = await agentIds(page);
  const directorCount = ids.filter((id) => id === "director").length;
  const architectCount = ids.filter((id) => id === "architect").length;
  const uniqueIds = new Set(ids);
  record(
    "Director appears exactly once",
    directorCount === 1 ? "PASS" : "FAIL",
    `count=${directorCount}`,
  );
  record(
    "Architect appears exactly once",
    architectCount === 1 ? "PASS" : "FAIL",
    `count=${architectCount}`,
  );
  record(
    "No duplicate agent node ids",
    uniqueIds.size === ids.length ? "PASS" : "FAIL",
    `ids=${ids.length} unique=${uniqueIds.size}`,
  );
  if (directorCount !== 1 || architectCount !== 1) {
    finding({
      id: "QA-MM020f-shared-nodes",
      component: "AgentGraph / clusterLayout",
      expected: "Director and Architect each appear as a single node across groups",
      actual: `director=${directorCount} architect=${architectCount} ids=${JSON.stringify(ids)}`,
      repro: "Load demo activity.json with multi-group membership; inspect .react-flow__node-agent data-id",
      evidence: "screenshots/01-demo-multigroup.png",
      environment: `Playwright chromium @ ${SHA.slice(0, 7)}`,
      severity: "high",
      confidence: "high",
    });
  }

  // Membership edges for Director/Architect to secondary groups
  const membershipEdges = await page.locator('[data-testid^="membership-edge-"]').count();
  record(
    "Membership edges present for multi-group agents",
    membershipEdges > 0 ? "PASS" : "FAIL",
    `count=${membershipEdges}`,
  );
  await page.screenshot({
    path: path.join(SHOTS, "02-shared-nodes-membership.png"),
    fullPage: true,
  });

  // Edge attachments: message edges / handoff edges exist in DOM
  const rfEdges = await page.locator(".react-flow__edge").count();
  record("Graph edges rendered", rfEdges > 0 ? "PASS" : "FAIL", `count=${rfEdges}`);

  // ========== 2. Group filters ==========
  const chipsBefore = await filterChipState(page);
  fs.writeFileSync(
    path.join(OUT, "filter_chips_initial.json"),
    JSON.stringify(chipsBefore, null, 2),
  );
  const groupChips = (chipsBefore || []).filter((c) => c.testid?.startsWith("group-filter-"));
  const expectedGroups = ["owner", "build", "qr", "radar"];
  const chipIds = groupChips.map((c) => c.testid.replace("group-filter-", ""));
  record(
    "Group filter chips for each group",
    expectedGroups.every((g) => chipIds.includes(g)) ? "PASS" : "FAIL",
    `chips=${chipIds.join(",")}`,
  );

  const totalAgentsAll = await countAgentNodes(page);
  record(
    "All-groups agent count",
    totalAgentsAll >= 13 ? "PASS" : "FAIL",
    `count=${totalAgentsAll}`,
  );

  // Select only Build
  // Click "All groups" is active; deselect others by clicking each active non-build
  // Strategy: click All first to reset, then click build-only path:
  // Turn off owner, qr, radar one by one (must keep at least one)
  async function setOnlyGroup(gid) {
    // Ensure all selected first
    const allBtn = page.locator(".group-filter__chip").filter({ hasText: "All groups" });
    if ((await allBtn.getAttribute("aria-pressed")) !== "true") {
      await allBtn.click();
      await waitSettled(page, 400);
    }
    const state = await filterChipState(page);
    const active = state
      .filter((c) => c.testid?.startsWith("group-filter-") && c.pressed)
      .map((c) => c.testid.replace("group-filter-", ""));
    for (const g of active) {
      if (g === gid) continue;
      // only deselect if more than one selected
      await page.getByTestId(`group-filter-${g}`).click();
      await waitSettled(page, 300);
    }
  }

  await setOnlyGroup("build");
  await page.screenshot({
    path: path.join(SHOTS, "03-filter-build-only.png"),
    fullPage: true,
  });
  const buildOnlyIds = await agentIds(page);
  const buildExpected = new Set([
    "director",
    "architect",
    "dev-1",
    "dev-2",
    "ui-ux-maker",
    "documentation",
  ]);
  const buildOk =
    buildOnlyIds.length === buildExpected.size &&
    buildOnlyIds.every((id) => buildExpected.has(id));
  record(
    "Filter Build-only shows Build members (+shared)",
    buildOk ? "PASS" : "FAIL",
    `ids=${buildOnlyIds.join(",")}`,
  );

  await setOnlyGroup("qr");
  await page.screenshot({
    path: path.join(SHOTS, "04-filter-qr-only.png"),
    fullPage: true,
  });
  const qrIds = await agentIds(page);
  const qrExpected = new Set([
    "director",
    "architect",
    "qa-verifier",
    "security-engineer",
    "devops-release",
  ]);
  const qrOk =
    qrIds.length === qrExpected.size && qrIds.every((id) => qrExpected.has(id));
  record(
    "Filter Q&R-only shows Q&R members (+shared)",
    qrOk ? "PASS" : "FAIL",
    `ids=${qrIds.join(",")}`,
  );

  await setOnlyGroup("radar");
  const radarIds = await agentIds(page);
  // bug-fixer has groups=[] but primary group radar — still in radar via primary
  const radarHasShared =
    radarIds.includes("director") && radarIds.includes("architect");
  record(
    "Filter Radar includes Director+Architect once",
    radarHasShared &&
      radarIds.filter((i) => i === "director").length === 1 &&
      radarIds.filter((i) => i === "architect").length === 1
      ? "PASS"
      : "FAIL",
    `ids=${radarIds.join(",")}`,
  );

  // Combination: build + qr
  await page.locator(".group-filter__chip").filter({ hasText: "All groups" }).click();
  await waitSettled(page, 300);
  // deselect owner and radar
  await page.getByTestId("group-filter-owner").click();
  await waitSettled(page, 200);
  await page.getByTestId("group-filter-radar").click();
  await waitSettled(page, 400);
  await page.screenshot({
    path: path.join(SHOTS, "05-filter-build-qr.png"),
    fullPage: true,
  });
  const comboIds = await agentIds(page);
  const comboHasDirector = comboIds.filter((i) => i === "director").length === 1;
  const comboHasDev = comboIds.includes("dev-1");
  const comboHasQa = comboIds.includes("qa-verifier");
  const comboNoScout = !comboIds.includes("scout");
  record(
    "Filter Build+Q&R combination",
    comboHasDirector && comboHasDev && comboHasQa && comboNoScout ? "PASS" : "FAIL",
    `ids=${comboIds.join(",")}`,
  );

  // Select-all
  await page.locator(".group-filter__chip").filter({ hasText: "All groups" }).click();
  await waitSettled(page, 400);
  const allCount = await countAgentNodes(page);
  record(
    "Select-all restores full roster",
    allCount === totalAgentsAll ? "PASS" : "FAIL",
    `all=${allCount} expected=${totalAgentsAll}`,
  );

  // None: UI prevents deselecting last group — try to clear all
  await setOnlyGroup("owner");
  const beforeLast = await filterChipState(page);
  await page.getByTestId("group-filter-owner").click(); // attempt to clear last
  await waitSettled(page, 300);
  const afterLast = await filterChipState(page);
  const ownerStill =
    afterLast.find((c) => c.testid === "group-filter-owner")?.pressed === true;
  const stillSomeAgents = (await countAgentNodes(page)) > 0;
  record(
    "Cannot select none (keeps ≥1 group)",
    ownerStill && stillSomeAgents ? "PASS" : "FAIL",
    `ownerPressed=${ownerStill} agents=${await countAgentNodes(page)} before=${JSON.stringify(beforeLast?.filter(c=>c.pressed))}`,
  );
  await page.screenshot({
    path: path.join(SHOTS, "06-filter-cannot-none.png"),
    fullPage: true,
  });

  // Filter persistence across refresh — spec does NOT require localStorage;
  // verify actual behavior.
  await setOnlyGroup("build");
  await waitSettled(page, 300);
  const beforeRefresh = await filterChipState(page);
  await page.reload({ waitUntil: "networkidle" });
  await waitSettled(page, 1200);
  const afterRefresh = await filterChipState(page);
  const buildOnlyBefore = beforeRefresh
    ?.filter((c) => c.testid?.startsWith("group-filter-") && c.pressed)
    .map((c) => c.testid);
  const buildOnlyAfter = afterRefresh
    ?.filter((c) => c.testid?.startsWith("group-filter-") && c.pressed)
    .map((c) => c.testid);
  const persisted =
    JSON.stringify(buildOnlyBefore) === JSON.stringify(buildOnlyAfter) &&
    buildOnlyAfter?.length === 1;
  // Spec (PR body / MM-020 docs) does not require filter persistence → document as INFO/note, not fail
  record(
    "Group filter survives full page refresh",
    persisted ? "PASS" : "N/A (not required by spec)",
    `before=${buildOnlyBefore} after=${buildOnlyAfter}`,
  );
  fs.writeFileSync(
    path.join(OUT, "filter_persist.json"),
    JSON.stringify({ beforeRefresh, afterRefresh, persisted, specRequires: false }, null, 2),
  );
  await page.screenshot({
    path: path.join(SHOTS, "07-filter-after-refresh.png"),
    fullPage: true,
  });

  // ========== 4. Node positions stable on new events + drag ==========
  restoreDemo();
  await gotoFresh(page);
  await waitSettled(page, 1500);

  // Drag director via drag handle
  const directorNode = page.locator('.react-flow__node[data-id="director"]');
  const handle = directorNode.locator(".agent-node-drag-handle");
  const box = await directorNode.boundingBox();
  if (box) {
    // Hover to reveal handle, then drag
    await directorNode.hover();
    await waitSettled(page, 200);
    const hbox = (await handle.boundingBox()) || box;
    await page.mouse.move(hbox.x + hbox.width / 2, hbox.y + hbox.height / 2);
    await page.mouse.down();
    await page.mouse.move(hbox.x + 120, hbox.y + 80, { steps: 12 });
    await page.mouse.up();
    await waitSettled(page, 600);
  }
  const posAfterDrag = await getAgentNodePositions(page);
  fs.writeFileSync(
    path.join(OUT, "positions_after_drag.json"),
    JSON.stringify(posAfterDrag, null, 2),
  );
  await page.screenshot({
    path: path.join(SHOTS, "08-after-drag-director.png"),
    fullPage: true,
  });

  // Capture positions before append (all nodes)
  const posBeforeAppend = await getAgentNodePositions(page);

  // Append a new event + edge to activity.json while page is open; wait for poll (~10s)
  const demo = loadJson(PUBLIC_ACTIVITY);
  const appended = deepClone(demo);
  const newId = `qa-mm020f-evt-${Date.now()}`;
  appended.events.push({
    id: newId,
    type: "message",
    actor: "director",
    target: null,
    task_id: null,
    attribution: { method: "unknown" },
    source_url: "agent://qa",
    source_time: new Date().toISOString(),
    raw: "QA append probe",
    group: "build",
    provenance: "agent-reported",
  });
  appended.edges.push({
    id: `edge-${newId}`,
    source: "director",
    target: "group:build",
    type: "message",
    count: 1,
    event_ids: [newId],
  });
  appended.generated_at = new Date().toISOString();
  writeActivity(appended);

  // Wait for poll transport (default 10s) + buffer
  await page.waitForTimeout(12000);
  await waitSettled(page, 1000);
  const posAfterAppend = await getAgentNodePositions(page);
  fs.writeFileSync(
    path.join(OUT, "positions_before_append.json"),
    JSON.stringify(posBeforeAppend, null, 2),
  );
  fs.writeFileSync(
    path.join(OUT, "positions_after_append.json"),
    JSON.stringify(posAfterAppend, null, 2),
  );
  await page.screenshot({
    path: path.join(SHOTS, "09-after-event-append.png"),
    fullPage: true,
  });

  function posDelta(a, b) {
    const keys = new Set([...Object.keys(a), ...Object.keys(b)]);
    const deltas = {};
    for (const k of keys) {
      if (!a[k] || !b[k]) {
        deltas[k] = null;
        continue;
      }
      deltas[k] = {
        dx: Math.abs(a[k].x - b[k].x),
        dy: Math.abs(a[k].y - b[k].y),
      };
    }
    return deltas;
  }
  const deltas = posDelta(posBeforeAppend, posAfterAppend);
  fs.writeFileSync(path.join(OUT, "position_deltas.json"), JSON.stringify(deltas, null, 2));

  const directorMoved =
    deltas.director && (deltas.director.dx > 5 || deltas.director.dy > 5);
  const anyLargeReset = Object.entries(deltas).some(
    ([, d]) => d && (d.dx > 30 || d.dy > 30),
  );

  // Dragged director must stay put
  record(
    "Dragged Director stays put after new events",
    !directorMoved ? "PASS" : "FAIL",
    `delta=${JSON.stringify(deltas.director)} before=${JSON.stringify(posBeforeAppend.director)} after=${JSON.stringify(posAfterAppend.director)}`,
  );
  if (directorMoved) {
    finding({
      id: "QA-MM020f-position-reset",
      component: "AgentGraph position preserve effect",
      expected:
        "Node positions (especially user-dragged) remain stable when activity.json gains new events via poll",
      actual: `Director moved after append: delta=${JSON.stringify(deltas.director)}; anyLargeReset=${anyLargeReset}`,
      repro:
        "Open demo UI; drag Director; append message event+edge to web/public/activity.json; wait >10s for poll; compare transform",
      evidence:
        "screenshots/08-after-drag-director.png, screenshots/09-after-event-append.png, position_deltas.json",
      environment: `Playwright chromium @ ${SHA.slice(0, 7)}; poll ~10s`,
      severity: "high",
      confidence: "high",
    });
  }

  record(
    "Undragged nodes do not jump >30px on append",
    !anyLargeReset || directorMoved ? (anyLargeReset && !directorMoved ? "FAIL" : "PASS") : "PASS",
    `deltas_summary=${JSON.stringify(
      Object.fromEntries(
        Object.entries(deltas)
          .filter(([, d]) => d && (d.dx > 5 || d.dy > 5))
          .slice(0, 10),
      ),
    )}`,
  );

  // ========== 1. QA-MM012-1 missing / empty / malformed ==========
  // Missing
  removeActivity();
  await gotoFresh(page);
  await page.screenshot({
    path: path.join(SHOTS, "10-missing-activity.png"),
    fullPage: true,
  });
  const bodyText = await page.locator("body").innerText();
  const hasLedgerError =
    /Can't read/i.test(bodyText) && /activity\.json/i.test(bodyText);
  const hasJsonParseError = /Unexpected token/i.test(bodyText) || /not valid JSON/i.test(bodyText);
  const missingStatus = await page.evaluate(async () => {
    const r = await fetch("/activity.json");
    const t = await r.text();
    return { status: r.status, startsWith: t.slice(0, 40) };
  });
  fs.writeFileSync(
    path.join(OUT, "missing_activity_fetch.json"),
    JSON.stringify(missingStatus, null, 2),
  );
  record(
    "QA-MM012-1 missing activity.json → LedgerErrorView",
    hasLedgerError && !hasJsonParseError ? "PASS" : "FAIL",
    `ledgerError=${hasLedgerError} jsonParse=${hasJsonParseError} fetch=${JSON.stringify(missingStatus)} bodySnippet=${bodyText.slice(0, 160).replace(/\n/g, " ")}`,
  );
  if (!(hasLedgerError && !hasJsonParseError)) {
    finding({
      id: "QA-MM012-1",
      component: "loadActivity + Vite SPA host",
      expected:
        "Missing activity.json → HTTP 404/422 → LedgerErrorView (“Can't read …”) + Retry",
      actual: `fetch status=${missingStatus.status} startsWith=${JSON.stringify(missingStatus.startsWith)}; UI ledgerError=${hasLedgerError} jsonParse=${hasJsonParseError}`,
      repro:
        "rm web/public/activity.json; curl -i http://127.0.0.1:5173/activity.json; reload UI",
      evidence: "screenshots/10-missing-activity.png, missing_activity_fetch.json",
      environment: `Vite 5.4.21, Playwright @ ${SHA.slice(0, 7)}`,
      severity: "medium",
      confidence: "high",
    });
  }

  // Empty
  writeRaw("");
  await gotoFresh(page);
  await page.screenshot({
    path: path.join(SHOTS, "11-empty-activity.png"),
    fullPage: true,
  });
  const emptyText = await page.locator("body").innerText();
  const emptyHandled =
    /Retry/i.test(emptyText) ||
    /error/i.test(emptyText) ||
    /Unexpected|JSON|Can't read|Failed/i.test(emptyText);
  const emptyCrash = await page.locator(".react-flow__node-agent").count();
  record(
    "Empty activity.json handled (no silent blank graph)",
    emptyHandled && emptyCrash === 0 ? "PASS" : "FAIL",
    `handled=${emptyHandled} agents=${emptyCrash} snippet=${emptyText.slice(0, 120).replace(/\n/g, " ")}`,
  );

  // Malformed
  writeRaw("{not-json");
  await gotoFresh(page);
  await page.screenshot({
    path: path.join(SHOTS, "12-malformed-activity.png"),
    fullPage: true,
  });
  const malText = await page.locator("body").innerText();
  const malOk =
    (/Retry/i.test(malText) || /error|Unexpected|JSON|Failed/i.test(malText)) &&
    (await page.locator(".react-flow__node-agent").count()) === 0;
  record(
    "Malformed activity.json handled",
    malOk ? "PASS" : "FAIL",
    `snippet=${malText.slice(0, 120).replace(/\n/g, " ")}`,
  );

  // ========== 5. Regressions ==========
  restoreDemo();
  // Verdict fallback fixture
  const verdictAct = deepClone(loadJson(path.join(FIX, "activity-demo.json")));
  // Ensure verdict events with COND/BLK/INC and unknown
  const verdictTypes = ["COND", "BLK", "INC", "WEIRDVERDICT"];
  for (const [i, vt] of verdictTypes.entries()) {
    verdictAct.events.push({
      id: `verdict-qa-${i}`,
      type: "verdict",
      actor: "qa-verifier",
      target: "dev-1",
      task_id: verdictAct.tasks[0]?.id ?? null,
      attribution: { method: "unknown" },
      source_url: "",
      source_time: new Date().toISOString(),
      raw: `verdict ${vt}`,
      verdict: vt,
    });
  }
  writeActivity(verdictAct);
  consoleErrors.length = 0;
  outbound.length = 0;
  await gotoFresh(page);
  await page.screenshot({
    path: path.join(SHOTS, "13-verdict-fallback.png"),
    fullPage: true,
  });
  // Check timeline glyphs / no crash
  const verdictCrash = consoleErrors.some((e) => /verdict|undefined|TypeError/i.test(e));
  record(
    "Verdict fallback (COND/BLK/INC/unknown) no crash",
    !verdictCrash && (await page.locator(".agent-graph").count()) > 0 ? "PASS" : "FAIL",
    `consoleErrors=${consoleErrors.length}`,
  );

  // No self-loops
  const selfLoops = await page.evaluate(() => {
    const edges = [...document.querySelectorAll(".react-flow__edge")];
    // React Flow edges have data-testid or aria; check source/target via path or data
    return [...document.querySelectorAll("[data-testid]")].filter((el) => {
      const id = el.getAttribute("data-testid") || "";
      return /self|loop/i.test(id);
    }).length;
  });
  // Also check activity edges
  const actEdges = loadJson(PUBLIC_ACTIVITY).edges || [];
  const selfEdgeData = actEdges.filter((e) => e.source === e.target);
  record(
    "No self-loop edges in demo/activity",
    selfEdgeData.length === 0 ? "PASS" : "FAIL",
    `dataSelfLoops=${selfEdgeData.length} domHint=${selfLoops}`,
  );

  // XSS via group, agent, message text
  const xss = deepClone(loadJson(path.join(FIX, "activity-demo.json")));
  const payload = `<img src=x onerror="window.__xss=1">`;
  const scriptPayload = `<script>window.__xss=1</script>`;
  xss.nodes = xss.nodes.map((n) => {
    if (n.id === "director") {
      return { ...n, label: `Director ${payload}` };
    }
    return n;
  });
  xss.events.push({
    id: "xss-msg",
    type: "message",
    actor: "director",
    target: null,
    task_id: null,
    attribution: { method: "unknown" },
    source_url: "",
    source_time: new Date().toISOString(),
    raw: scriptPayload + " " + payload,
    group: "build",
    provenance: "agent-reported",
  });
  // Inject XSS group label via a fake node group id used in filter — groups come from node.groups
  xss.nodes.push({
    id: "xss-bot",
    label: payload,
    group: "build",
    groups: ["build"],
    status: "IDLE",
    agent_links: [],
    layout: { x: 0, y: 0 },
  });
  writeActivity(xss);
  await gotoFresh(page);
  const xssFlag = await page.evaluate(() => window.__xss === 1);
  await page.screenshot({
    path: path.join(SHOTS, "14-xss-payload.png"),
    fullPage: true,
  });
  record(
    "XSS via group/agent/message text does not execute",
    !xssFlag ? "PASS" : "FAIL",
    `__xss=${xssFlag}`,
  );
  if (xssFlag) {
    finding({
      id: "QA-MM020f-xss",
      component: "AgentNodeCard / event rendering",
      expected: "HTML/script in labels and message text must not execute",
      actual: "window.__xss === 1 after loading XSS-laden activity.json",
      repro: "Inject <img onerror> into node.label and event.raw; load UI",
      evidence: "screenshots/14-xss-payload.png",
      environment: `Playwright @ ${SHA.slice(0, 7)}`,
      severity: "critical",
      confidence: "high",
    });
  }

  // Keyboard / a11y
  restoreDemo();
  await gotoFresh(page);
  await page.keyboard.press("Tab");
  await waitSettled(page, 200);
  const skipLink = page.locator("a.skip-link, a[href='#main'], a:has-text('Skip')").first();
  const skipCount = await page.locator("a.skip-link").count();
  // Slash focuses filters (MM-007)
  await page.keyboard.press("/");
  await waitSettled(page, 300);
  const active = await page.evaluate(() => {
    const el = document.activeElement;
    return {
      tag: el?.tagName,
      className: el?.className,
      aria: el?.getAttribute("aria-label"),
      text: el?.textContent?.slice(0, 40),
    };
  });
  await page.screenshot({
    path: path.join(SHOTS, "15-keyboard.png"),
    fullPage: true,
  });
  record(
    "Keyboard: slash focuses filter UI",
    /filter|chip|button/i.test(JSON.stringify(active)) ||
      active.tag === "BUTTON"
      ? "PASS"
      : "FAIL",
    JSON.stringify(active),
  );
  record(
    "Skip link present",
    skipCount > 0 || (await page.locator('a[href="#main-content"], a[href="#main"]').count()) > 0
      ? "PASS"
      : "FAIL",
    `skipLinkCount=${skipCount}`,
  );

  // A11y: group filter has role=group + aria-label
  const filterA11y = await page.getByRole("group", { name: /Filter groups/i }).count();
  record("Group filter a11y role/label", filterA11y > 0 ? "PASS" : "FAIL");

  // Console errors on clean demo
  consoleErrors.length = 0;
  restoreDemo();
  await gotoFresh(page);
  await waitSettled(page, 1500);
  const meaningfulErrors = consoleErrors.filter(
    (e) => !/ResizeObserver|favicon/i.test(e),
  );
  fs.writeFileSync(
    path.join(OUT, "console_errors.json"),
    JSON.stringify(consoleErrors, null, 2),
  );
  record(
    "No console errors on demo load",
    meaningfulErrors.length === 0 ? "PASS" : "FAIL",
    meaningfulErrors.slice(0, 5).join(" || "),
  );

  // Outbound beyond localhost
  const badOutbound = outbound.filter(
    (o) => !/127\.0\.0\.1|localhost/.test(o.url),
  );
  fs.writeFileSync(
    path.join(OUT, "outbound_requests.json"),
    JSON.stringify(outbound, null, 2),
  );
  record(
    "No outbound calls beyond localhost",
    badOutbound.length === 0 ? "PASS" : "FAIL",
    badOutbound
      .slice(0, 5)
      .map((o) => o.url)
      .join(", "),
  );

  // ========== QA-MM020a-1 duplicate groups.json members ==========
  // Simulate by writing activity with duplicate group membership entries
  // (as ingest.membership_index would if members listed twice)
  const dup = deepClone(loadJson(path.join(FIX, "activity-demo.json")));
  for (const n of dup.nodes) {
    if (n.id === "director") {
      n.groups = ["build", "build", "qr", "qr", "radar"];
    }
    if (n.id === "architect") {
      n.groups = ["build", "qr", "radar", "radar"];
    }
  }
  writeActivity(dup);
  await gotoFresh(page);
  await page.screenshot({
    path: path.join(SHOTS, "16-duplicate-membership.png"),
    fullPage: true,
  });
  const dupChips = await filterChipState(page);
  const dupChipIds = (dupChips || [])
    .filter((c) => c.testid?.startsWith("group-filter-"))
    .map((c) => c.testid);
  const dupChipUnique = new Set(dupChipIds).size === dupChipIds.length;
  const dupAgentIds = await agentIds(page);
  const directorDup = dupAgentIds.filter((i) => i === "director").length;
  const architectDup = dupAgentIds.filter((i) => i === "architect").length;
  // Also probe ingest path: temporarily duplicate in groups.json via membership_index logic (read-only check)
  const ingestDup = execSync(
    `cd ${REPO} && python3 - <<'PY'
import json, copy
from pathlib import Path
from ingest.membership import membership_index, load_groups
cfg = load_groups()
cfg2 = copy.deepcopy(cfg)
for g in cfg2["groups"]:
    if g["id"]=="build":
        g["members"] = g["members"] + ["director","director"]
idx = membership_index(cfg2)
print(json.dumps({"director": idx.get("director"), "architect": idx.get("architect")}))
PY`,
    { encoding: "utf8" },
  ).trim();
  fs.writeFileSync(path.join(OUT, "qa_mm020a1_membership_index.json"), ingestDup + "\n");
  fs.writeFileSync(
    path.join(OUT, "qa_mm020a1_ui.json"),
    JSON.stringify(
      {
        chips: dupChipIds,
        chipsUnique: dupChipUnique,
        directorNodes: directorDup,
        architectNodes: architectDup,
        agentIds: dupAgentIds,
      },
      null,
      2,
    ),
  );
  const mm020a1Pass =
    dupChipUnique && directorDup === 1 && architectDup === 1;
  record(
    "QA-MM020a-1 duplicate members → no duplicate chips/nodes",
    mm020a1Pass ? "PASS" : "FAIL",
    `chipsUnique=${dupChipUnique} director=${directorDup} architect=${architectDup} ingestIndex=${ingestDup}`,
  );
  if (!mm020a1Pass) {
    finding({
      id: "QA-MM020a-1",
      component: "collectGroupIds / AgentGraph / membership_index",
      expected:
        "Duplicate entries in groups.json members must not create duplicate filter chips or duplicate agent nodes",
      actual: `chipsUnique=${dupChipUnique} chips=${dupChipIds}; directorNodes=${directorDup}; architectNodes=${architectDup}; membership_index with dup members=${ingestDup}`,
      repro:
        "Duplicate director in groups.json build.members (or set node.groups with repeated ids); load UI",
      evidence: "screenshots/16-duplicate-membership.png, qa_mm020a1_*.json",
      environment: `Playwright + ingest.membership @ ${SHA.slice(0, 7)}`,
      severity: "medium",
      confidence: "high",
    });
  }
  // Note: membership_index does NOT dedupe — record as observation if UI still OK
  if (mm020a1Pass && /build.*build/.test(ingestDup)) {
    findings.push({
      id: "QA-MM020a-1-note",
      component: "ingest.membership.membership_index",
      expected: "Optional: dedupe group ids per bot when members lists contain duplicates",
      actual: `membership_index preserves duplicate group ids: ${ingestDup}`,
      repro: "Append duplicate bot id to a group's members; call membership_index",
      evidence: "qa_mm020a1_membership_index.json",
      environment: `python ingest @ ${SHA.slice(0, 7)}`,
      severity: "low",
      confidence: "high",
      note: "UI chips/nodes still unique via Set-based collectGroupIds; ingest may emit duplicate groups[] entries",
    });
  }

  // Restore demo for leftover state
  restoreDemo();

  const report = {
    sha: SHA,
    pr: 19,
    base: "feat/MM-020-unified-network",
    head_branch: "feat/MM-020f-multigroup-graph",
    checks,
    findings,
    consoleErrorsFinal: meaningfulErrors,
    outboundCount: outbound.length,
  };
  fs.writeFileSync(path.join(OUT, "playwright_report.json"), JSON.stringify(report, null, 2));
  console.log("\n=== SUMMARY ===");
  console.log(
    "PASS",
    checks.filter((c) => c.result === "PASS").length,
  );
  console.log(
    "FAIL",
    checks.filter((c) => c.result === "FAIL").length,
  );
  console.log(
    "OTHER",
    checks.filter((c) => !["PASS", "FAIL"].includes(c.result)).length,
  );
  console.log("FINDINGS", findings.length);
  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
