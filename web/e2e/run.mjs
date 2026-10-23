import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import path from "node:path";
import os from "node:os";

const root = path.resolve(import.meta.dirname ?? path.dirname(new URL(import.meta.url).pathname), "../..");
const outDir = path.resolve(process.env.OUT_DIR ?? "/tmp/e2e-out");
const chromePath = process.env.CHROME_PATH ?? path.join(os.homedir(), "Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing");
const base = process.env.DEMO_URL ?? "http://127.0.0.1:8931/";
const replay = process.env.REPLAY_URL ?? "http://127.0.0.1:8933/";
const legacy = process.env.LEGACY_URL ?? "http://127.0.0.1:8932/";
await fs.mkdir(outDir, { recursive: true });
const results = [];
const measurements = {};
let browser;

function check(condition, message) { if (!condition) throw new Error(message); }
async function scenario(name, fn) {
  try { const details = await fn(); results.push({ name, status: "PASS", ...details }); }
  catch (error) { results.push({ name, status: "FAIL", error: String(error?.stack ?? error) }); }
}
const wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
async function open(url = base, options = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 860 }, deviceScaleFactor: 2, ...options });
  await context.addInitScript(() => localStorage.setItem("mindmapDebug", "1"));
  const page = await context.newPage();
  page.errors = [];
  page.on("pageerror", (e) => page.errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error" && !/404/.test(m.text())) page.errors.push(m.text()); });
  await page.goto(url, { waitUntil: "networkidle", timeout: 30000 });
  return { context, page };
}
const getNodes = (page) => page.evaluate(() => window.__mindmap?.nodes() ?? []);
const minDistance = (nodes) => {
  let d = Infinity;
  for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) d = Math.min(d, Math.hypot(nodes[i].x - nodes[j].x, nodes[i].y - nodes[j].y));
  return d;
};
const maxDrift = (a, b) => Math.max(0, ...a.map((n) => { const m = b.find((v) => v.id === n.id); return m ? Math.hypot(n.x - m.x, n.y - m.y) : 0; }));
const snap = async (page, name) => page.screenshot({ path: path.join(outDir, `${name}.png`) });
const stageOf = (page) => page.locator(".demo-replay-banner").innerText().then((s) => Number(s.match(/Stage (\d+)/)?.[1] ?? 0));
const safeClose = async (ctx) => ctx?.close().catch(() => {});

try {
  browser = await chromium.launch({ executablePath: chromePath, headless: true });

  let desktopErrors = [];
  await scenario("desktop render, spacing, drift, console", async () => {
    const { context, page } = await open();
    await page.waitForFunction(() => window.__mindmap?.nodes()?.length === 5, null, { timeout: 20000 });
    await wait(4500);
    const a = await getNodes(page); await wait(2000); const b = await getNodes(page);
    const d = minDistance(b), drift = maxDrift(a, b);
    desktopErrors = [...page.errors];
    await snap(page, "desktop");
    measurements.desktop = { count: b.length, minPairDistance: +d.toFixed(2), ambientDrift2s: +drift.toFixed(2), errors: desktopErrors };
    await safeClose(context);
    check(b.length === 5, `expected five agents, got ${b.length}`);
    // 14px node radius + 30px label allowance on each side.
    check(d >= 2 * 14 + 2 * 30, `minimum pair distance ${d.toFixed(1)}px < 88px radius+label allowance`);
    check(drift < 8, `ambient drift ${drift.toFixed(2)}px is not <8px over 2s`);
    check(desktopErrors.length === 0, `browser errors: ${desktopErrors.join(" | ")}`);
    return measurements.desktop;
  });

  await scenario("hover/click inspector, neighbour state, Esc", async () => {
    const { context, page } = await open(); await page.waitForFunction(() => window.__mindmap?.nodes()?.length === 5); await wait(1800);
    await page.getByRole("button", { name: "Pause motion" }).click(); await wait(300);
    const canvas = page.locator(".network-canvas canvas").first(); const box = await canvas.boundingBox();
    const related = page.locator(".roster-item[aria-description]").first();
    const testId = await related.getAttribute("data-testid");
    const target = (await getNodes(page)).find((n) => testId?.endsWith(n.id));
    check(target, "no delegated neighbour exists in the static demo");
    const canvasBefore = await canvas.evaluate((el) => el.toDataURL());
    await page.mouse.move(box.x + target.sx, box.y + target.sy); await wait(350);
    const hover = await page.locator(".roster-item.is-hovered").count();
    const canvasAfter = await canvas.evaluate((el) => el.toDataURL());
    await page.mouse.click(box.x + target.sx, box.y + target.sy); await wait(250);
    const opened = await page.locator(".inspector").count(); const selected = await page.locator(".roster-item.is-selected").count();
    await snap(page, "inspector-open");
    await page.keyboard.press("Escape"); await wait(150);
    const closed = await page.locator(".inspector").count();
    await safeClose(context);
    check(hover > 0, "hover did not mark the connected roster item"); check(canvasBefore !== canvasAfter, "hover did not change canvas pixels (neighbor focus/dimming)"); check(opened === 1 && selected === 1, "canvas click did not open matching inspector/roster selection"); check(closed === 0, "Escape did not close inspector");
    return { hoverRosterItems: hover, canvasPixelsChanged: canvasBefore !== canvasAfter, inspectorOpen: opened, selectedRosterItems: selected, closedByEscape: closed === 0 };
  });

  await scenario("drag pin stability and release", async () => {
    const { context, page } = await open(); await page.waitForFunction(() => window.__mindmap?.nodes()?.length === 5); await wait(1800);
    const canvas = page.locator(".network-canvas canvas").first(); const box = await canvas.boundingBox(); const nodes = await getNodes(page); const n = nodes.find((x) => x.status === "DONE") ?? nodes[0];
    await page.mouse.move(box.x + n.sx, box.y + n.sy); await page.mouse.down(); await page.mouse.move(box.x + n.sx + 110, box.y + n.sy + 65, { steps: 10 }); await page.mouse.up(); await wait(400);
    const after = (await getNodes(page)).find((x) => x.id === n.id); await wait(3100); const later = (await getNodes(page)).find((x) => x.id === n.id);
    const stable = Math.hypot(after.sx - later.sx, after.sy - later.sy); const release = page.getByRole("button", { name: /Release \d+ pinned/ }); const releaseText = await release.textContent().catch(() => "");
    await snap(page, "pinned"); if (await release.count()) await release.click(); await wait(300);
    const unpinned = !(await getNodes(page)).find((x) => x.id === n.id)?.pinned;
    await safeClose(context);
    check(after.pinned, "dragged node did not become pinned"); check(stable < 2, `pinned node moved ${stable.toFixed(1)}px over 3s`); check(/Release 1 pinned/.test(releaseText ?? ""), `unexpected release control: ${releaseText}`); check(unpinned, "Release pinned did not free dragged node");
    return { pinned: after.pinned, pinnedDrift3s: +stable.toFixed(2), releaseButton: releaseText, released: unpinned };
  });

  await scenario("camera persistence and inspector resize centre", async () => {
    const { context, page } = await open(); await page.waitForFunction(() => window.__mindmap?.nodes()?.length === 5); await wait(1800);
    const canvas = page.locator(".network-canvas canvas").first(); const box = await canvas.boundingBox();
    await page.mouse.move(box.x + box.width * .6, box.y + box.height * .45); await page.mouse.wheel(0, -450); await wait(350);
    const z1 = await page.evaluate(() => window.__mindmap.zoom()); await wait(10500); const z2 = await page.evaluate(() => window.__mindmap.zoom());
    const before = await getNodes(page); const n = before[0]; const cam0 = await page.evaluate(() => window.__mindmap.camera());
    await page.mouse.click(box.x + n.sx, box.y + n.sy); await wait(600); const opened = await getNodes(page); const camOpen = await page.evaluate(() => window.__mindmap.camera());
    const selectedAfter = opened.find((v) => v.id === n.id); const shiftOpen = Math.hypot(selectedAfter.sx - n.sx, selectedAfter.sy - n.sy);
    await page.keyboard.press("Escape"); await wait(600); const closed = await getNodes(page); const camClosed = await page.evaluate(() => window.__mindmap.camera()); const selectedClosed = closed.find((v) => v.id === n.id); const shiftClose = Math.hypot(selectedClosed.sx - n.sx, selectedClosed.sy - n.sy);
    await snap(page, "zoom-inspector-resize"); await safeClose(context);
    check(Math.abs(z2 - z1) < 1e-6, `zoom changed across poll interval: ${z1} -> ${z2}`); // Spec: the camera CENTRE (world coordinates) and zoom survive the canvas resize. Nodes may move on screen
    // toward the new canvas centre when the docked inspector narrows the canvas; that is expected.
    const centreShift = (c) => Math.hypot(c.x - cam0.x, c.y - cam0.y);
    check(centreShift(camOpen) < 1 && centreShift(camClosed) < 1, `camera centre moved (open ${centreShift(camOpen).toFixed(2)}, closed ${centreShift(camClosed).toFixed(2)} world units)`);
    check(Math.abs(camOpen.zoom - cam0.zoom) < 1e-6 && Math.abs(camClosed.zoom - cam0.zoom) < 1e-6, "zoom changed across inspector open/close");
    return { zoomPoll1: z1, zoomPoll2: z2, zoomStable: true, cameraCentreShiftOpen: +centreShift(camOpen).toFixed(3), cameraCentreShiftClosed: +centreShift(camClosed).toFixed(3), nodeScreenShiftOpen: +shiftOpen.toFixed(2), nodeScreenShiftClosed: +shiftClose.toFixed(2) };
  });

  await scenario("pause and resume motion", async () => {
    const { context, page } = await open(); await page.waitForFunction(() => window.__mindmap?.nodes()?.length === 5); await wait(2500);
    await page.getByRole("button", { name: "Pause motion" }).click(); await wait(400); const a = await getNodes(page); await wait(2000); const b = await getNodes(page); const paused = maxDrift(a, b);
    await page.getByRole("button", { name: "Resume motion" }).click(); await wait(250); const c = await getNodes(page); await wait(1200); const d = await getNodes(page); const resumed = maxDrift(c, d);
    await snap(page, "pause-resume"); await safeClose(context);
    check(paused < 1, `pause allowed ${paused.toFixed(2)}px drift`); check(resumed > 0.1, `resume did not restart movement (${resumed.toFixed(2)}px)`);
    return { pausedDrift2s: +paused.toFixed(2), resumedDrift1_2s: +resumed.toFixed(2) };
  });

  await scenario("reduced motion", async () => {
    const { context, page } = await open(base, { reducedMotion: "reduce" }); await page.waitForFunction(() => window.__mindmap?.nodes()?.length === 5); await wait(1800);
    const a = await getNodes(page); await wait(2000); const b = await getNodes(page); const drift = maxDrift(a, b); const disabled = await page.getByRole("button", { name: "Resume motion" }).isDisabled();
    await snap(page, "reduced-motion"); await safeClose(context);
    check(drift < .1, `reduced-motion drift ${drift.toFixed(2)}px`); check(disabled, "motion control was not disabled for reduced motion");
    return { drift2s: +drift.toFixed(3), pauseDisabled: disabled };
  });

  await scenario("replay cycle transitions, jitter, edge, highlight", async () => {
    const { context, page } = await open(replay); await page.waitForFunction(() => window.__mindmap?.nodes()?.length >= 2);
    // Begin at a clean stage-1 boundary so this is precisely one replay cycle.
    await page.waitForFunction(() => /Stage 1\/10/.test(document.querySelector(".demo-replay-banner")?.innerText ?? ""), null, { timeout: 55000 });
    let prev = null, maxStep = 0, minGap = Infinity, samples = 0, appearanceCount = 0, disappearanceCount = 0, lastEdge = false, stageSamples = new Map(), jumpCount = 0;
    const frames = []; let priorStage = 0, lastCapturedStage = 0;
    while (true) {
      const st = await stageOf(page); const ns = await getNodes(page);
      // Stage (banner DOM) and statuses (graph model) come from separate round-trips; a sample that
      // straddles a stage boundary would pair one stage's banner with the next stage's statuses.
      if (st !== await stageOf(page)) { await wait(50); continue; }
      const edgeCount = await page.locator(".agent-roster .roster-rel").count(); const edge = edgeCount > 0;
      if (st) { stageSamples.set(st, ns.map((n) => n.status).join("/")); if (edge && !lastEdge) appearanceCount++; if (!edge && lastEdge) disappearanceCount++; }
      if (prev && ns.length === prev.length) {
        const step = maxDrift(prev, ns); maxStep = Math.max(maxStep, step); if (step > 40) jumpCount++;
        for (let i = 0; i < ns.length; i++) for (let j = i + 1; j < ns.length; j++) minGap = Math.min(minGap, Math.hypot(ns[i].x - ns[j].x, ns[i].y - ns[j].y));
      }
      if (st !== lastCapturedStage) {
        const frame = { stage: st, statuses: ns.map((n) => n.status), edge, banner: (await page.locator(".demo-replay-banner").innerText()).split("\n").at(-1) };
        frames.push(frame); await page.screenshot({ path: path.join(outDir, `replay-stage-${st}.png`) }); lastCapturedStage = st;
      }
      samples++; prev = ns; lastEdge = edge;
      if (priorStage === 10 && st === 1) break;
      priorStage = st; await wait(200);
    }
    const transitions = Object.fromEntries([...stageSamples.entries()]);
    const expectedStages = { 1: "IDLE/IDLE", 2: "IDLE/IDLE", 3: "IN_PROGRESS/IDLE", 4: "IN_PROGRESS/BLOCKED", 5: "IN_PROGRESS/IN_PROGRESS", 6: "BLOCKED/IN_PROGRESS", 7: "BLOCKED/FAILED", 8: "IN_PROGRESS/IN_PROGRESS", 9: "DONE/DONE", 10: "IDLE/IDLE" };
    await snap(page, "replay-final"); await safeClose(context);
    measurements.replay = { samples, stages: transitions, maxFrameDisplacement: +maxStep.toFixed(2), minPairDistance: +minGap.toFixed(2), edgeAppearances: appearanceCount, edgeDisappearance: disappearanceCount, jumpsOver40: jumpCount, frames };
    check(Object.keys(transitions).length >= 9, `sampled only ${Object.keys(transitions).length} stages`);
    check(JSON.stringify(transitions) === JSON.stringify(expectedStages), `replay status sequence differed from expected stages: ${JSON.stringify(transitions)}`);
    check(appearanceCount >= 1 && disappearanceCount >= 1, `edge visibility transitions not seen (${appearanceCount}/${disappearanceCount})`);
    check(jumpCount === 0, `${jumpCount} layout jumps >40px without topology change`);
    // Highlights are a single transient class in DOM; count only appearance edges in the timeline.
    // Canvas particles are intentionally not exposed in DOM, so the harness records the observable edge transition proxy.
    const highlightEvidence = "roster delegation row appears once per edge transition; transient particle is canvas-only and cannot be counted reliably via DOM";
    results.push({ name: "replay highlight proxy", status: appearanceCount === 1 ? "PASS" : "FAIL", expectedAppearances: 1, observedAppearances: appearanceCount, evidence: highlightEvidence });
    check(appearanceCount === 1, `expected exactly one NEW DELEGATION edge appearance, saw ${appearanceCount}`);
    return measurements.replay;
  });

  await scenario("responsive widths 390, 768, 1024", async () => {
    const { context, page } = await open(base, { viewport: { width: 390, height: 844 }, deviceScaleFactor: 1 });
    const reports = [];
    for (const width of [390, 768, 1024]) {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 860 }); await wait(500);
      await page.getByRole("button", { name: /^(Graph|List) view$/ }).first().waitFor({ timeout: 15000 });
      const toggle = page.getByRole("button", { name: "Graph view" }); const defaultList = await toggle.count();
      if (width === 390) { check(defaultList === 1, "narrow viewport did not default to list view"); await toggle.click(); await wait(600); }
      else if (!(await page.locator(".network-view").count()) && await page.getByRole("button", { name: "Graph view" }).count()) await page.getByRole("button", { name: "Graph view" }).click();
      const graph = await page.locator(".network-view").count();
      if (width === 390) await snap(page, "narrow-390");
      const boxes = await page.evaluate(() => {
        const rect = (s) => { const e = document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); return { x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height }; };
        return { controls: rect(".network-controls"), roster: rect(".agent-roster"), legend: rect(".network-legend"), canvas: rect(".network-canvas") };
      });
      const controlsClear = !boxes.controls || !boxes.roster || boxes.controls.x >= boxes.roster.right || boxes.controls.right <= boxes.roster.x || boxes.controls.y >= boxes.roster.bottom || boxes.controls.bottom <= boxes.roster.y;
      const legendClear = !boxes.legend || !boxes.controls || boxes.legend.bottom <= boxes.controls.y || boxes.legend.y >= boxes.controls.bottom || boxes.legend.right <= boxes.controls.x || boxes.legend.x >= boxes.controls.right;
      reports.push({ width, defaultList: width === 390 ? defaultList === 1 : undefined, graph, controlsClearOfRoster: controlsClear, legendClearOfControls: legendClear, boxes });
      check(graph === 1, `graph missing at ${width}px`); check(controlsClear, `controls overlap roster at ${width}px`); check(legendClear, `legend overlaps controls at ${width}px`);
    }
    await safeClose(context); return { widths: reports };
  });

  await scenario("legacy dashboard unaffected", async () => {
    const { context, page } = await open(legacy, { deviceScaleFactor: 1 }); await page.waitForFunction(() => document.querySelectorAll(".react-flow__node").length > 10, null, { timeout: 15000 }).catch(() => {}); await wait(500);
    const nodes = await page.locator(".react-flow__node").count(), network = await page.locator(".network-view").count(); await snap(page, "legacy-dashboard"); const errors = [...page.errors]; await safeClose(context);
    check(nodes > 10, `legacy React Flow nodes=${nodes}`); check(network === 0, "legacy dashboard contains network view"); check(errors.length === 0, `legacy console errors: ${errors.join(" | ")}`);
    return { reactFlowNodes: nodes, networkView: network, errors };
  });

  await scenario("static demo separation", async () => {
    const { context, page } = await open(); await page.waitForFunction(() => window.__mindmap?.nodes()?.length === 5); const text = await page.locator("body").innerText(); await snap(page, "demo-separation"); await safeClose(context);
    check(/DEMO — offline fixtures/i.test(text), "static demo label is missing"); check(!/DEMO REPLAY|Stage \d+\//i.test(text), "static demo includes a replay stage banner");
    return { demoLabel: true, replayBanner: false };
  });

  await scenario("StrictMode single canvas", async () => {
    const { context, page } = await open(); await page.waitForFunction(() => window.__mindmap?.nodes()?.length === 5); const count = await page.locator(".network-canvas canvas").count(); await safeClose(context);
    check(count === 1, `expected one .network-canvas canvas, got ${count}`); return { canvases: count };
  });
} catch (error) {
  results.push({ name: "harness startup", status: "FAIL", error: String(error?.stack ?? error) });
} finally { await browser?.close().catch(() => {}); }

const report = { generatedAt: new Date().toISOString(), base, replay, legacy, screenshots: outDir, measurements, results, summary: { pass: results.filter((r) => r.status === "PASS").length, fail: results.filter((r) => r.status === "FAIL").length } };
await fs.writeFile(path.join(outDir, "results.json"), `${JSON.stringify(report, null, 2)}\n`);
console.log(JSON.stringify(report, null, 2));
if (report.summary.fail) process.exitCode = 1;
