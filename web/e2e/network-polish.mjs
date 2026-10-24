/** Graph-specific visual/performance evidence. Uses the repository's optional playwright-core setup.
 * Run against the sprint build's T3 demo server, never the legacy daemon:
 * GRAPH_URL=http://127.0.0.1:8951 REPLAY_URL=http://127.0.0.1:8953 node web/e2e/network-polish.mjs
 * Optional: --matrix, --performance, --events, or --live. Live requires LIVE_DATA_URL explicitly.
 * Reports contain synthetic coordinates and aggregate live counts, never messages/credentials.
 */
import { chromium } from "playwright-core";
import fs from "node:fs/promises";
import os from "node:os";
import path from "node:path";

const base = process.env.GRAPH_URL ?? "http://127.0.0.1:8951";
const replay = process.env.REPLAY_URL ?? "http://127.0.0.1:8953";
const out = process.env.OUT_DIR ?? "/tmp/network-sprint/verified";
const mode = process.argv[2];
const chrome = process.env.CHROME_PATH ?? path.join(os.homedir(), "Library/Caches/ms-playwright/chromium-1248/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing");
const baseline = await fetch(`${base}/activity.json`).then(r => r.json());
if (baseline.meta?.t3?.mode !== "demo") throw new Error("GRAPH_URL must serve synthetic T3 demo data");
await fs.mkdir(out, { recursive: true });
const browser = await chromium.launch({ executablePath: chrome, headless: true });
const report = { generatedAt: new Date().toISOString(), matrix: [], performance: [], events: {}, live: [] };
const check = (ok, message) => { if (!ok) throw new Error(message); };
const tasks = ["Plan the graph architecture", "Implement canvas rendering", "Review event truthfulness", "Validate camera stability", "Polish accessible controls", "Investigate arrival physics", "Measure frame performance", "Audit source freshness"];

function fixture(count) {
  const a = structuredClone(baseline);
  a.nodes = Array.from({ length: count }, (_, i) => {
    const n = structuredClone(baseline.nodes[i % baseline.nodes.length]);
    n.id = `demo-agent-${i}`; n.label = n.current_task = `${tasks[i % tasks.length]}${count > 8 ? ` · ${i + 1}` : ""}`;
    n.session.thread_id = n.id; n.session.provider = i % 2 ? "Codex" : "Claude Code";
    n.session.model = i % 2 ? "gpt-6-astra" : "claude-sonnet-5-5";
    n.status = ["IN_PROGRESS", "IN_PROGRESS", "BLOCKED", "DONE", "IDLE", "FAILED"][i % 6];
    n.session.stale = false; return n;
  });
  a.edges = Array.from({ length: count - 1 }, (_, i) => ({ id: `demo-edge-${i}`, source: `demo-agent-${Math.floor(i / 3)}`, target: `demo-agent-${i + 1}`, type: "delegation", count: 1, event_ids: [] }));
  a.events = []; return a;
}

async function open({ width = 1440, height = 900, reduced = false, data, url = base } = {}) {
  const context = await browser.newContext({ viewport: { width, height }, reducedMotion: reduced ? "reduce" : "no-preference" });
  const page = await context.newPage(); const errors = [];
  page.on("pageerror", e => errors.push(e.message));
  await page.addInitScript(() => {
    localStorage.setItem("mindmapDebug", "1"); localStorage.setItem("mindmapHintSeen", "1");
    window.__graphCalls = { measureText: 0, createRadialGradient: 0, fillText: 0 };
    window.__paintedReactions = {};
    for (const method of Object.keys(window.__graphCalls)) {
      const original = CanvasRenderingContext2D.prototype[method];
      CanvasRenderingContext2D.prototype[method] = function (...args) {
        window.__graphCalls[method]++;
        if (method === "fillText" && /^DEMO · (STARTED|RESUMED|FAILED|BLOCKED|COMPLETED|DELEGATED|NEW DELEGATION)$/.test(args[0])) window.__paintedReactions[args[0]] = performance.now();
        return original.apply(this, args);
      };
    }
  });
  if (data) await page.route("**/activity.json", route => route.fulfill({ json: typeof data === "function" ? data() : data }));
  await page.goto(url, { waitUntil: "domcontentloaded" });
  if (width < 768) await page.getByRole("button", { name: "Graph view", exact: true }).click();
  await page.waitForFunction(() => window.__mindmap?.nodes().length > 0);
  return { page, context, errors };
}

async function matrix() {
  for (const count of [2, 5, 12, 30]) for (const [width, height] of [[1440, 900], [768, 1024], [390, 844]]) {
    const { page, context, errors } = await open({ width, height, reduced: true, data: fixture(count) });
    try {
      await page.waitForTimeout(250);
      const result = await page.evaluate(() => {
        const graph = window.__mindmap, host = document.querySelector(".network-canvas").getBoundingClientRect(), camera = graph.camera();
        return { count: graph.nodes().length, zoom: graph.zoom(), overflow: document.documentElement.scrollWidth > innerWidth,
          labelCount: graph.labels().length,
          clippedLabels: graph.labels().filter(l => (l.x - l.width / 2 - camera.x) * camera.zoom + host.width / 2 < -1 || (l.x + l.width / 2 - camera.x) * camera.zoom + host.width / 2 > host.width + 1 || (l.y - camera.y) * camera.zoom + host.height / 2 < -1 || (l.y + l.height - camera.y) * camera.zoom + host.height / 2 > host.height + 1).length };
      });
      await page.screenshot({ path: path.join(out, `${count}-${width}.png`) });
      check(result.count === count && !result.overflow && !result.clippedLabels && !errors.length, `matrix ${count}/${width}: ${JSON.stringify({ result, errors })}`);
      report.matrix.push({ width, height, ...result, errors });
      console.log(`PASS matrix ${count} agents / ${width}px / ${result.labelCount} labels`);
    } finally { await context.close(); }
  }
}

async function performanceChecks() {
  for (const count of [2, 5, 12, 30]) {
    const { page, context, errors } = await open({ data: fixture(count) });
    try {
      await page.waitForTimeout(5500);
      const result = await page.evaluate(() => new Promise(resolve => {
        const initial = { ...window.__graphCalls }; let last = performance.now(); const frames = [];
        const frame = now => {
          frames.push(now - last); last = now;
          if (frames.length < 120) return requestAnimationFrame(frame);
          const sorted = frames.slice(1).sort((a, b) => a - b);
          resolve({ p50: sorted[Math.floor(sorted.length * 0.5)], p95: sorted[Math.floor(sorted.length * 0.95)],
            callsPerFrame: Object.fromEntries(Object.entries(window.__graphCalls).map(([key, value]) => [key, (value - initial[key]) / 120])) });
        }; requestAnimationFrame(frame);
      }));
      check(result.callsPerFrame.measureText === 0 && !errors.length, `unchanged labels were remeasured: ${JSON.stringify(result)}`);
      // Report timing instead of asserting an environment-dependent frame-rate threshold.
      report.performance.push({ count, ...result, errors }); console.log(`PASS profile ${count} agents: ${JSON.stringify(result)}`);
    } finally { await context.close(); }
  }
}

async function eventChecks() {
  const { page, context, errors } = await open({ url: replay });
  try {
    const start = Date.now(), captures = new Set(); let firstCycle;
    const cycles = new Map();
    // At most 2.5 cycles; starting partway through a cycle must not animate its historical edge.
    while (Date.now() - start < 130000) {
      const sample = await page.evaluate(() => ({ banner: document.querySelector(".demo-replay-banner")?.textContent ?? "",
        particles: window.__mindmap.particlesEmitted(), reactions: window.__mindmap.reactions(), observations: window.__mindmap.observations(),
        painted: Object.entries(window.__paintedReactions).filter(([, time]) => performance.now() - time < 500).map(([text]) => text) }));
      const cycle = Number(sample.banner.match(/Cycle (\d+)/)?.[1]);
      const stage = Number(sample.banner.match(/Stage (\d+)/)?.[1]);
      firstCycle ??= cycle;
      if (!cycles.has(cycle)) cycles.set(cycle, new Set());
      for (const text of sample.painted) cycles.get(cycle).add(text);
      for (const reaction of sample.reactions) {
        const key = `${cycle}-${reaction.caption}`;
        if (!captures.has(key)) { captures.add(key); await page.screenshot({ path: path.join(out, `event-${key}.png`) }); }
      }
      if (sample.observations.some(o => o.kind === "new-delegation") && !captures.has(`edge-${cycle}`)) {
        captures.add(`edge-${cycle}`); await page.screenshot({ path: path.join(out, `delegation-${cycle}.png`) });
      }
      if (cycle >= firstCycle + 2 && stage >= 5) {
        const wholeCycle = [...cycles.get(firstCycle + 1)];
        for (const name of ["STARTED", "BLOCKED", "FAILED", "RESUMED", "COMPLETED", "DELEGATED", "NEW DELEGATION"]) check(wholeCycle.includes(`DEMO · ${name}`), `missing painted ${name}: ${JSON.stringify(wholeCycle)}`);
        check(cycles.get(firstCycle + 2).has("DEMO · NEW DELEGATION"), "second complete replay suppressed delegation");
        check(sample.particles >= 2, "expected two separately observed one-shot delegations");
        check(!errors.length, JSON.stringify(errors));
        report.events = { elapsedMs: Date.now() - start, particles: sample.particles, cycles: [...cycles].map(([cycle, painted]) => ({ cycle, painted: [...painted] })), errors };
        console.log(`PASS replay: painted all event types, ${sample.particles} one-shot particles`); return;
      }
      await page.waitForTimeout(150);
    }
    throw new Error("Replay did not complete the two-cycle event proof within 130 seconds");
  } finally { await context.close(); }
}

async function denseEvents() {
  let data = fixture(30);
  data.nodes.forEach(n => { n.status = "IN_PROGRESS"; });
  data.meta.t3.replay = { cycle: 0, stage: 0, stage_count: 10, step_sec: 2, label: "Synthetic simultaneous transitions" };
  const { page, context } = await open({ data: () => data });
  try {
    await page.waitForTimeout(5500);
    data = structuredClone(data);
    data.generated_at = new Date(Date.parse(data.generated_at) + 2000).toISOString();
    data.nodes.forEach((n, i) => { n.status = ["BLOCKED", "FAILED", "DONE"][i % 3]; });
    await page.waitForFunction(() => window.__mindmap.reactions().length === 30);
    await page.waitForTimeout(250);
    const result = await page.evaluate(() => {
      const g = window.__mindmap, camera = g.camera(), host = document.querySelector(".network-canvas").getBoundingClientRect();
      const ctx = document.querySelector(".network-canvas canvas").getContext("2d");
      ctx.save(); ctx.font = "700 11px ui-sans-serif, system-ui, sans-serif";
      const tags = g.reactions().map(r => { const n = g.nodes().find(n => n.id === r.id); const width = ctx.measureText(`DEMO · ${r.caption}`).width + 16;
        return { id: r.id, x: n.sx - width / 2, y: n.sy - 26 * camera.zoom - 33, width, height: 22 }; });
      ctx.restore();
      const labels = g.labels().map(l => ({ ...l, x: (l.x - l.width / 2 - camera.x) * camera.zoom + host.width / 2, y: (l.y - camera.y) * camera.zoom + host.height / 2, width: l.width * camera.zoom, height: l.height * camera.zoom }));
      const intersects = (a, b) => a.x < b.x + b.width && a.x + a.width > b.x && a.y < b.y + b.height && a.y + a.height > b.y;
      return { reactions: tags.length, labels: labels.length, tagLabelOverlaps: tags.reduce((sum, a) => sum + labels.filter(b => intersects(a, b)).length, 0), tagOverlaps: tags.reduce((sum, a, i) => sum + tags.slice(i + 1).filter(b => intersects(a, b)).length, 0) };
    });
    await page.screenshot({ path: path.join(out, "dense-events.png") });
    report.events.dense = result;
    console.log(JSON.stringify(result));
  } finally { await context.close(); }
}

async function liveChecks() {
  if (!process.env.LIVE_DATA_URL) throw new Error("Set LIVE_DATA_URL to an authorized, sanitized read-only activity.json endpoint");
  const activity = await fetch(process.env.LIVE_DATA_URL).then(r => r.json());
  check(activity.meta?.t3?.mode === "live", "Expected verified live mode");
  for (const [width, height] of [[1440, 900], [768, 1024], [390, 844]]) {
    const { page, context, errors } = await open({ width, height, reduced: true, data: activity });
    try {
      await page.waitForTimeout(250);
      const result = await page.evaluate(() => ({ nodes: window.__mindmap.nodes().length,
        particles: window.__mindmap.particlesEmitted(), reactions: window.__mindmap.reactions().length,
        demoBanner: Boolean(document.querySelector(".demo-replay-banner")), overflow: document.documentElement.scrollWidth > innerWidth }));
      check(!result.particles && !result.reactions && !result.demoBanner && !result.overflow && !errors.length, JSON.stringify(result));
      // Keep real task titles out of committed screenshots/reports. Only aggregate metadata is retained.
      report.live.push({ width, ...result, connection: activity.meta.t3.connection, errors }); console.log(`PASS live ${width}: ${result.nodes} agents, no baseline reactions`);
    } finally { await context.close(); }
  }
}

try {
  if (!mode || mode === "--matrix") await matrix();
  if (!mode || mode === "--performance") await performanceChecks();
  if (!mode || mode === "--events") await eventChecks();
  if (mode === "--live") await liveChecks();
  if (mode === "--dense-events") await denseEvents();
} finally {
  await browser.close();
  await fs.writeFile(path.join(out, `${mode?.slice(2) ?? "report"}.json`), JSON.stringify(report, null, 2));
}
