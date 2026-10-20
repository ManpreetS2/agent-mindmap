/**
 * Independent QA — MM-012 (PR #14) Playwright UI harness.
 * Does not modify product code. Swaps web/public/activity.json only.
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
// Prefer /tmp playwright install
const PLAYWRIGHT_ROOT = "/tmp/node_modules/playwright";

const BASE = "http://127.0.0.1:5173";
const REPO = "/tmp/qa-mm012-checkout";
const PUBLIC_ACTIVITY = path.join(REPO, "web/public/activity.json");
const OUT = "/tmp/qa-mm012-artifacts/ceebb76";
const SHOTS = path.join(OUT, "screenshots");
const FIX = path.join(OUT, "fixtures");

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

function baseActivity() {
  return loadJson(path.join(FIX, "sample-activity.json"));
}

function deepClone(o) {
  return JSON.parse(JSON.stringify(o));
}

function contrastRatio(fg, bg) {
  const lum = (c) => {
    const s = c.map((v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * s[0] + 0.7152 * s[1] + 0.0722 * s[2];
  };
  const L1 = lum(fg);
  const L2 = lum(bg);
  const lighter = Math.max(L1, L2);
  const darker = Math.min(L1, L2);
  return (lighter + 0.05) / (darker + 0.05);
}

function parseRgb(str) {
  const m = String(str).match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
  if (!m) return null;
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

async function waitSettled(page, ms = 800) {
  await page.waitForTimeout(ms);
}

async function gotoFresh(page, hash = "") {
  await page.goto(BASE + "/" + hash, { waitUntil: "networkidle", timeout: 30000 });
  await waitSettled(page, 1000);
}

async function main() {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 900 },
    // Block anything not localhost
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
    if (msg.type() === "error") {
      consoleErrors.push(msg.text());
    }
  });
  page.on("pageerror", (err) => {
    consoleErrors.push(String(err));
  });

  // ---------- 1. Happy path / demo fixture ----------
  restoreDemo();
  consoleErrors.length = 0;
  outbound.length = 0;
  await gotoFresh(page);
  await page.screenshot({ path: path.join(SHOTS, "01-demo-graph.png"), fullPage: true });

  const graph = page.getByRole("region", { name: /Agent graph/i });
  const timeline = page.getByRole("region", { name: /Activity timeline/i });
  const legend = page.getByRole("list", { name: /Edge types legend/i });
  const hasGraph = await graph.count();
  const hasTimeline = await timeline.count();
  const hasLegend = await legend.count();
  record(
    "UI loads demo activity (graph+timeline+legend)",
    hasGraph && hasTimeline && hasLegend ? "PASS" : "FAIL",
    `graph=${hasGraph} timeline=${hasTimeline} legend=${hasLegend}`,
  );
  if (!(hasGraph && hasTimeline && hasLegend)) {
    finding({
      component: "MindmapView",
      expected: "Graph region, timeline, and edge legend visible with demo fixture",
      actual: `graph=${hasGraph} timeline=${hasTimeline} legend=${hasLegend}`,
      repro: "make refresh-demo; cd web && npm run dev; open http://127.0.0.1:5173/",
      evidence: "screenshots/01-demo-graph.png",
      environment: "Playwright chromium headless @ ceebb76",
      severity: "high",
      confidence: "high",
    });
  }

  // PR claim features
  const minimap = page.locator(".react-flow__minimap");
  const brush = page.locator(".timeline-brush");
  const nowLine = page.locator(".timeline-now-line");
  const zoom = page.getByRole("toolbar", { name: /Timeline zoom/i });
  const dragHandle = page.locator(".agent-node-drag-handle").first();
  record("MiniMap present", (await minimap.count()) > 0 ? "PASS" : "FAIL");
  record("Timeline brush present", (await brush.count()) > 0 ? "PASS" : "FAIL");
  record("Timeline now-line present", (await nowLine.count()) > 0 ? "PASS" : "FAIL");
  record("Timeline zoom toolbar present", (await zoom.count()) > 0 ? "PASS" : "FAIL");
  record(
    "Drag handle exists (hover-only CSS)",
    (await dragHandle.count()) > 0 ? "PASS" : "FAIL",
  );

  // Legend position top-right (polish)
  if (hasLegend) {
    const box = await legend.boundingBox();
    const graphBox = await graph.boundingBox();
    if (box && graphBox) {
      const midX = graphBox.x + graphBox.width / 2;
      const midY = graphBox.y + graphBox.height / 2;
      const rightish = box.x > midX;
      const topish = box.y < midY;
      record(
        "Edge legend top-right of graph",
        rightish && topish ? "PASS" : "FAIL",
        `legend=(${box.x.toFixed(0)},${box.y.toFixed(0)}) mid=(${midX.toFixed(0)},${midY.toFixed(0)})`,
      );
    }
  }

  // List view toggle
  const listToggle = page.getByRole("button", { name: /^List$/i });
  if (await listToggle.count()) {
    await listToggle.click();
    await waitSettled(page, 500);
    await page.screenshot({ path: path.join(SHOTS, "02-list-view.png"), fullPage: true });
    record(
      "List view toggle",
      (await page.getByRole("region", { name: /List view/i }).count()) > 0
        ? "PASS"
        : "FAIL",
    );
    const graphToggle = page.getByRole("button", { name: /^Graph$/i });
    if (await graphToggle.count()) await graphToggle.click();
    await waitSettled(page, 500);
  } else {
    record("List view toggle", "FAIL", "button not found");
  }

  // Keyboard: skip link + Tab focus
  await page.keyboard.press("Tab");
  const focused1 = await page.evaluate(() => {
    const el = document.activeElement;
    return {
      tag: el?.tagName,
      className: el?.className,
      text: el?.textContent?.slice(0, 80),
      href: el?.getAttribute?.("href"),
    };
  });
  const skipOk =
    focused1.href === "#main-content" ||
    /skip/i.test(focused1.text || "") ||
    /skip-link/i.test(focused1.className || "");
  record("Keyboard focus reaches skip link on first Tab", skipOk ? "PASS" : "WARN", JSON.stringify(focused1));
  if (!skipOk) {
    finding({
      component: "SkipLink / keyboard",
      expected: "First Tab focuses skip link to #main-content",
      actual: JSON.stringify(focused1),
      repro: "Load UI; press Tab once",
      evidence: "qa_mm012_playwright.mjs keyboard check",
      environment: "Playwright chromium headless @ ceebb76",
      severity: "medium",
      confidence: "medium",
    });
  }

  // Open a node detail via click
  const node = page.locator('[data-testid^="agent-node-"]').first();
  if (await node.count()) {
    await node.click({ force: true });
    await waitSettled(page, 600);
    const panel = page.locator(".detail-panel");
    record(
      "Detail panel opens on node click",
      (await panel.count()) > 0 ? "PASS" : "FAIL",
    );
    await page.screenshot({ path: path.join(SHOTS, "03-detail-panel.png"), fullPage: true });
    await page.keyboard.press("Escape");
    await waitSettled(page, 300);
  }

  // Contrast spot-check on header / status pill
  const contrastSamples = await page.evaluate(() => {
    const samples = [];
    const pick = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return;
      const cs = getComputedStyle(el);
      let bgEl = el;
      let bg = cs.backgroundColor;
      while (bgEl && (bg === "rgba(0, 0, 0, 0)" || bg === "transparent")) {
        bgEl = bgEl.parentElement;
        if (!bgEl) break;
        bg = getComputedStyle(bgEl).backgroundColor;
      }
      samples.push({
        sel,
        color: cs.color,
        backgroundColor: bg,
        fontSize: cs.fontSize,
      });
    };
    pick(".app-header h1, .command-center-shell h1, header h1, .app-title");
    pick(".status-pill");
    pick(".edge-legend");
    pick("body");
    return samples;
  });
  let contrastPass = true;
  for (const s of contrastSamples) {
    const fg = parseRgb(s.color);
    const bg = parseRgb(s.backgroundColor);
    if (!fg || !bg) continue;
    const ratio = contrastRatio(fg, bg);
    const ok = ratio >= 3; // spot-check UI chrome; 3:1 large text / 4.5:1 normal
    if (!ok) contrastPass = false;
    record(
      `Contrast spot-check ${s.sel}`,
      ok ? "PASS" : "FAIL",
      `ratio=${ratio.toFixed(2)} fg=${s.color} bg=${s.backgroundColor}`,
    );
  }
  if (!contrastPass) {
    finding({
      component: "theme / a11y contrast",
      expected: "Spot-check contrast ratio >= 3:1 on header/status/legend",
      actual: JSON.stringify(contrastSamples),
      repro: "Load demo UI; inspect computed colors",
      evidence: "screenshots/01-demo-graph.png",
      environment: "Playwright chromium headless @ ceebb76",
      severity: "low",
      confidence: "medium",
    });
  }

  const demoConsole = [...consoleErrors];
  record(
    "No console errors on demo load",
    demoConsole.length === 0 ? "PASS" : "FAIL",
    demoConsole.slice(0, 5).join(" | "),
  );
  if (demoConsole.length) {
    finding({
      component: "console",
      expected: "No console errors on demo fixture",
      actual: demoConsole.join("\n"),
      repro: "Load http://127.0.0.1:5173/ with demo activity.json",
      evidence: "logs consoleErrors",
      environment: "Playwright chromium headless @ ceebb76",
      severity: "medium",
      confidence: "high",
    });
  }

  // ---------- 2. Unknown / known verdict glyphs ----------
  {
    const act = deepClone(baseActivity());
    const now = act.events[0]?.source_time || "2026-10-20T00:00:00Z";
    const verdicts = [
      "CONDITIONAL",
      "BLOCKED",
      "INCONCLUSIVE",
      "TOTALLY_NEW_TOKEN",
      "weird",
      null,
    ];
    act.events = verdicts.map((v, i) => ({
      id: `qa-verdict-${i}`,
      type: "verdict",
      actor: "qa-verifier",
      target: "dev-1",
      task_id: "MM-012",
      attribution: { method: "signature" },
      source_url: "https://github.com/ManpreetS2/fencepost/pull/99",
      source_time: now,
      raw: `verdict ${v}`,
      verdict: v,
    }));
    // keep nodes/edges
    writeActivity(act);
    consoleErrors.length = 0;
    await gotoFresh(page);
    await waitSettled(page, 1200);
    await page.screenshot({
      path: path.join(SHOTS, "04-verdict-fallbacks.png"),
      fullPage: true,
    });

    // Timeline markers should render without crashing; unknown -> VER
    const pageText = await page.locator("body").innerText();
    const crashed = /Failed to load|Something went wrong|Cannot read/i.test(pageText);
    const hasCond = /COND/i.test(pageText);
    const hasBlk = /\bBLK\b/.test(pageText);
    const hasInc = /\bINC\b/.test(pageText);
    const hasVer = /\bVER\b/.test(pageText);
    record(
      "Known widened verdicts render (COND/BLK/INC)",
      !crashed && hasCond && hasBlk && hasInc ? "PASS" : "FAIL",
      `cond=${hasCond} blk=${hasBlk} inc=${hasInc} crashed=${crashed}`,
    );
    record(
      "Unknown verdict tokens fall back to VER",
      !crashed && hasVer ? "PASS" : "FAIL",
      `ver=${hasVer}`,
    );
    if (crashed) {
      finding({
        component: "eventGlyph / TimelineSwimlanes",
        expected: "Unknown verdicts fall back gracefully without UI crash",
        actual: pageText.slice(0, 400),
        repro: "Inject verdict events with TOTALLY_NEW_TOKEN into activity.json",
        evidence: "screenshots/04-verdict-fallbacks.png",
        environment: "Playwright chromium headless @ ceebb76",
        severity: "high",
        confidence: "high",
      });
    }
  }

  // ---------- 3. Empty activity ----------
  {
    const empty = loadJson(path.join(REPO, "web/src/fixtures/state-empty.json"));
    writeActivity(empty);
    consoleErrors.length = 0;
    await gotoFresh(page);
    await waitSettled(page, 1000);
    await page.screenshot({ path: path.join(SHOTS, "05-empty-state.png"), fullPage: true });
    const body = await page.locator("body").innerText();
    const ok =
      /empty|idle|no activity|no events/i.test(body) ||
      (await page.locator('[data-testid^="agent-node-"]').count()) > 0;
    record("Empty activity.json renders gracefully", ok ? "PASS" : "FAIL", body.slice(0, 120));
  }

  // ---------- 4. Missing activity.json (404 → ledger error) ----------
  {
    removeActivity();
    consoleErrors.length = 0;
    await gotoFresh(page);
    await waitSettled(page, 1000);
    await page.screenshot({
      path: path.join(SHOTS, "06-missing-activity.png"),
      fullPage: true,
    });
    const alert = page.getByRole("alert");
    const text = (await alert.count())
      ? await alert.innerText()
      : await page.locator("body").innerText();
    const ok = /Can'?t read|ledger|404|Failed to load/i.test(text);
    record("Missing activity.json shows error UI", ok ? "PASS" : "FAIL", text.slice(0, 160));
    if (!ok) {
      finding({
        component: "loadActivity / LedgerErrorView",
        expected: "404/missing activity.json shows ledger error or load failure with Retry",
        actual: text.slice(0, 300),
        repro: "rm web/public/activity.json; reload UI",
        evidence: "screenshots/06-missing-activity.png",
        environment: "Playwright chromium headless @ ceebb76",
        severity: "high",
        confidence: "high",
      });
    }
  }

  // ---------- 5. Malformed activity.json ----------
  {
    writeRaw("{not valid json!!!");
    consoleErrors.length = 0;
    await gotoFresh(page);
    await waitSettled(page, 1000);
    await page.screenshot({
      path: path.join(SHOTS, "07-malformed-activity.png"),
      fullPage: true,
    });
    const text = await page.locator("body").innerText();
    const hasAlert = (await page.getByRole("alert").count()) > 0;
    const ok =
      hasAlert ||
      /Failed to load|JSON|Unexpected|error|Retry/i.test(text);
    // Should NOT show a broken empty graph pretending success
    const pretendOk =
      (await page.getByRole("region", { name: /Agent graph/i }).count()) > 0 &&
      !(await page.getByRole("alert").count());
    record(
      "Malformed activity.json shows error (no silent success)",
      ok && !pretendOk ? "PASS" : "FAIL",
      `alert=${hasAlert} pretendOk=${pretendOk} text=${text.slice(0, 120)}`,
    );
    if (!(ok && !pretendOk)) {
      finding({
        component: "loadActivity / App error boundary",
        expected: "Malformed JSON surfaces an error/alert with Retry; no graph shell",
        actual: text.slice(0, 300),
        repro: "Write invalid JSON to web/public/activity.json; reload",
        evidence: "screenshots/07-malformed-activity.png",
        environment: "Playwright chromium headless @ ceebb76",
        severity: "high",
        confidence: "high",
      });
    }
  }

  // ---------- 6. Partial github + unparsed fixtures ----------
  for (const [name, file] of [
    ["partial-skipped", "state-partial-github-skipped.json"],
    ["partial-error", "state-partial-github-error.json"],
    ["unparsed", "state-unparsed.json"],
    ["stale", "state-stale.json"],
  ]) {
    const data = loadJson(path.join(REPO, "web/src/fixtures", file));
    writeActivity(data);
    await gotoFresh(page);
    await waitSettled(page, 900);
    await page.screenshot({
      path: path.join(SHOTS, `08-${name}.png`),
      fullPage: true,
    });
    const crashed = await page.evaluate(() => !document.body || !document.body.innerText);
    record(`Fixture state ${name} renders`, !crashed ? "PASS" : "FAIL");
    if (name === "unparsed") {
      const dbg = page.getByRole("button", { name: /Debug \(\d+\)/ });
      record("Debug drawer toggle present (unparsed)", (await dbg.count()) > 0 ? "PASS" : "FAIL");
      if (await dbg.count()) {
        await dbg.click();
        await waitSettled(page, 400);
        await page.screenshot({
          path: path.join(SHOTS, "08-unparsed-debug-open.png"),
          fullPage: true,
        });
      }
    }
  }

  // ---------- 7. XSS via ledger/task text ----------
  {
    const act = deepClone(baseActivity());
    const payload = `<img src=x onerror="window.__xss=1"><script>window.__xss=1</script>`;
    if (act.nodes[0]) {
      act.nodes[0].label = `XSS ${payload}`;
      act.nodes[0].current_task = payload;
    }
    if (act.tasks?.[0]) {
      act.tasks[0].title = payload;
      act.tasks[0].id = act.tasks[0].id || "XSS-1";
    }
    if (act.events?.[0]) {
      act.events[0].raw = `Note with ${payload}`;
      act.events[0].task_id = act.events[0].task_id || "XSS-1";
    }
    // also add a node specifically
    writeActivity(act);
    consoleErrors.length = 0;
    await gotoFresh(page);
    await waitSettled(page, 1200);
    // click first node to open detail with raw
    const n = page.locator('[data-testid^="agent-node-"]').first();
    if (await n.count()) {
      await n.click({ force: true });
      await waitSettled(page, 500);
    }
    await page.screenshot({ path: path.join(SHOTS, "09-xss-payload.png"), fullPage: true });
    const xssFlag = await page.evaluate(() => window.__xss === 1);
    const scriptNodes = await page.evaluate(() => {
      // Any executable script injected from fixture text?
      return Array.from(document.querySelectorAll("script"))
        .map((s) => s.textContent || "")
        .filter((t) => t.includes("window.__xss"));
    });
    const imgHandlers = await page.evaluate(() =>
      Array.from(document.querySelectorAll("img[onerror]")).map((i) => i.outerHTML),
    );
    const escapedVisible = await page.evaluate(() => {
      const html = document.body.innerHTML;
      return (
        html.includes("&lt;script&gt;") ||
        html.includes("&lt;img") ||
        (!html.includes("<script>window.__xss") &&
          document.body.innerText.includes("<script>") )
      );
    });
    const pass = !xssFlag && scriptNodes.length === 0 && imgHandlers.length === 0;
    record(
      "XSS payload from fixture text does not execute",
      pass ? "PASS" : "FAIL",
      `xssFlag=${xssFlag} scripts=${scriptNodes.length} imgOnerror=${imgHandlers.length} escapedVisible=${escapedVisible}`,
    );
    if (!pass) {
      finding({
        component: "React text rendering / DetailPanel",
        expected: "Ledger/task/event text rendered as text; no script/onerror execution",
        actual: `xssFlag=${xssFlag} scripts=${JSON.stringify(scriptNodes)} imgs=${JSON.stringify(imgHandlers)}`,
        repro: "Put <script>/onerror payload in node.label, current_task, event.raw; reload; open detail",
        evidence: "screenshots/09-xss-payload.png",
        environment: "Playwright chromium headless @ ceebb76",
        severity: "critical",
        confidence: "high",
      });
    }
  }

  // ---------- 8. Self-loop edges (data + UI) ----------
  {
    restoreDemo();
    const demo = loadJson(PUBLIC_ACTIVITY);
    const sample = loadJson(path.join(FIX, "sample-activity.json"));
    const loops = [...demo.edges, ...sample.edges].filter(
      (e) => e.source === e.target,
    );
    record(
      "No self-loop edges in demo + sample fixtures",
      loops.length === 0 ? "PASS" : "FAIL",
      JSON.stringify(loops),
    );
    // Inject a self-loop and ensure UI still loads (ingest should prevent; UI should tolerate)
    const act = deepClone(sample);
    act.edges.push({
      id: "self-loop-qa",
      source: "architect",
      target: "architect",
      type: "handoff",
      count: 1,
      event_ids: [],
    });
    writeActivity(act);
    await gotoFresh(page);
    await waitSettled(page, 800);
    await page.screenshot({
      path: path.join(SHOTS, "10-self-loop-injected.png"),
      fullPage: true,
    });
    const stillUp = (await page.getByRole("region", { name: /Agent graph/i }).count()) > 0;
    record("UI tolerates injected self-loop edge without crash", stillUp ? "PASS" : "FAIL");
  }

  // ---------- 9. PR joins keyed on (repo, number) — static/pytest evidence + fixture check ----------
  {
    // UI-level: sample fixture should distinguish repos if both present; verify data contract
    const sample = loadJson(path.join(FIX, "sample-activity.json"));
    const prEvents = (sample.events || []).filter((e) =>
      ["pr_opened", "pr_updated", "merged", "verdict"].includes(e.type),
    );
    const withRepo = prEvents.filter((e) => e.repo || (e.source_url || "").includes("github.com"));
    record(
      "PR-related events carry repo identity (repo field or github URL)",
      prEvents.length === 0 || withRepo.length === prEvents.length ? "PASS" : "WARN",
      `prEvents=${prEvents.length} withRepo=${withRepo.length}`,
    );
  }

  // ---------- 10. Network outbound ----------
  {
    restoreDemo();
    outbound.length = 0;
    await gotoFresh(page);
    await waitSettled(page, 2000);
    // Click agent link if any — those ARE outbound by design (cursor.com) — note separately
    const agentLinks = page.locator('a[href^="https://cursor.com/agents/"]');
    const agentCount = await agentLinks.count();
    // Filter: ignore intentional user-clickable external agent links not auto-fetched
    // Request listener catches navigations/subresources. At idle load:
    const autoOutbound = outbound.filter((o) => {
      // Vite HMR / sourcemaps stay local; fonts/cdns would fail
      return true;
    });
    const nonLocal = autoOutbound.filter((o) => {
      try {
        const h = new URL(o.url).hostname;
        return h !== "127.0.0.1" && h !== "localhost";
      } catch {
        return true;
      }
    });
    record(
      "No automatic outbound network beyond localhost on load",
      nonLocal.length === 0 ? "PASS" : "FAIL",
      nonLocal
        .slice(0, 10)
        .map((o) => o.url)
        .join(" | ") + ` (agent_link_anchors=${agentCount})`,
    );
    if (nonLocal.length) {
      finding({
        component: "web runtime network",
        expected: "UI fetch only localhost /activity.json (no CDN/API)",
        actual: nonLocal.map((o) => o.url).join("\n"),
        repro: "Load UI with Playwright request listener",
        evidence: "qa_report outbound",
        environment: "Playwright chromium headless @ ceebb76",
        severity: "high",
        confidence: "high",
      });
    }
  }

  // ---------- 11. Labels / a11y roles spot-check ----------
  {
    restoreDemo();
    await gotoFresh(page);
    const roles = await page.evaluate(() => {
      const need = [
        ["region", /Agent graph/i],
        ["region", /Activity timeline/i],
        ["list", /Edge types legend/i],
        ["link", /Skip to main content/i],
      ];
      const results = [];
      for (const [role, name] of need) {
        // approximate
        results.push({
          role,
          name: String(name),
          found: !!document.body.innerHTML,
        });
      }
      return {
        skip: !!document.querySelector('a.skip-link, a[href="#main-content"]'),
        graph: !!document.querySelector('[aria-label="Agent graph"]'),
        timeline: !!document.querySelector('[aria-label="Activity timeline"]'),
        legend: !!document.querySelector('[aria-label="Edge types legend"]'),
        filters: !!document.querySelector('[aria-label="Timeline filters"]'),
      };
    });
    const ok = roles.skip && roles.graph && roles.timeline && roles.legend;
    record("A11y labels present (skip/graph/timeline/legend)", ok ? "PASS" : "FAIL", JSON.stringify(roles));
  }

  // Final restore
  restoreDemo();

  const report = {
    sha: "ceebb76030cf7b0ada835edd7df1069190b6afb5",
    checks,
    findings,
    console_errors_last: consoleErrors,
    outbound_last: outbound,
  };
  fs.writeFileSync(
    path.join(OUT, "playwright_report.json"),
    JSON.stringify(report, null, 2),
  );
  console.log("\n=== SUMMARY ===");
  console.log(
    "PASS",
    checks.filter((c) => c.result === "PASS").length,
    "FAIL",
    checks.filter((c) => c.result === "FAIL").length,
    "WARN",
    checks.filter((c) => c.result === "WARN").length,
  );
  console.log("Findings:", findings.length);
  await browser.close();
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
