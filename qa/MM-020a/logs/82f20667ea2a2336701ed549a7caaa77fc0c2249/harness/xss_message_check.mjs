/**
 * MM-020a XSS re-check: message event raw/recipients + node labels must not execute.
 * Adapted from qa/MM-012 playwright harness; message-focused payloads.
 */
import { chromium } from "playwright";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { spawn } from "node:child_process";
import http from "node:http";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const EVIDENCE = path.resolve(__dirname, "..");
const CHECKOUT = path.resolve(EVIDENCE, "../checkout");
const WEB = path.join(CHECKOUT, "web");
const DIST = path.join(WEB, "dist");
const SHOTS = path.join(EVIDENCE, "screenshots");
const LOGS = path.join(EVIDENCE, "logs");
fs.mkdirSync(SHOTS, { recursive: true });
fs.mkdirSync(LOGS, { recursive: true });

const PAYLOAD = `<img src=x onerror="window.__xss=1"><script>window.__xss=1</script>`;

function waitForUrl(url, timeoutMs = 20000) {
  const start = Date.now();
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(url, (res) => {
        res.resume();
        resolve(res.statusCode);
      });
      req.on("error", () => {
        if (Date.now() - start > timeoutMs) reject(new Error("timeout waiting " + url));
        else setTimeout(tick, 200);
      });
    };
    tick();
  });
}

async function main() {
  // Ensure dist exists
  if (!fs.existsSync(path.join(DIST, "index.html"))) {
    throw new Error("web/dist missing — run npm run build first");
  }

  const baseActivity = JSON.parse(
    fs.readFileSync(path.join(CHECKOUT, "fixtures/sample-activity.json"), "utf8"),
  );

  // 1.0.0 fixture with XSS in classic fields + message-shaped event (UI must tolerate)
  const actOld = structuredClone(baseActivity);
  actOld.nodes[0].label = `XSS ${PAYLOAD}`;
  if (actOld.tasks[0]) actOld.tasks[0].title = PAYLOAD;
  if (actOld.events[0]) actOld.events[0].raw = `Note with ${PAYLOAD}`;

  // 1.1.0 activity with message event carrying XSS in raw + recipients display paths
  const actNew = structuredClone(baseActivity);
  actNew.schema_version = "1.1.0";
  actNew.nodes = actNew.nodes.map((n) => ({
    ...n,
    groups: n.id === "director" || n.id === "architect" ? ["build", "qr", "radar"] : n.group ? [n.group] : [],
  }));
  actNew.events.push({
    id: "xss-msg-1",
    type: "message",
    actor: "director",
    target: null,
    task_id: null,
    attribution: { method: "unknown" },
    source_url: "agent://emit",
    source_time: "2026-10-20T12:00:00-07:00",
    raw: `Group hello ${PAYLOAD}`,
    group: "build",
    provenance: "agent-reported",
    recipients: [`dev-1${PAYLOAD}`],
  });
  actNew.edges.push({
    id: "xss-edge-1",
    source: "director",
    target: "group:build",
    type: "message",
    count: 1,
    event_ids: ["xss-msg-1"],
  });
  // also poison a node label for 1.1.0 path
  actNew.nodes[0].label = `Dir ${PAYLOAD}`;

  const results = [];

  async function serveAndProbe(activity, name) {
    const activityPath = path.join(DIST, "activity.json");
    fs.writeFileSync(activityPath, JSON.stringify(activity, null, 2));
    const server = spawn("python3", ["-m", "http.server", "8791", "--bind", "127.0.0.1"], {
      cwd: DIST,
      stdio: ["ignore", "pipe", "pipe"],
    });
    try {
      await waitForUrl("http://127.0.0.1:8791/");
      const browser = await chromium.launch({ headless: true });
      const page = await browser.newPage();
      await page.addInitScript(() => {
        window.__xss = 0;
      });
      const consoleErrors = [];
      page.on("console", (msg) => {
        if (msg.type() === "error") consoleErrors.push(msg.text());
      });
      page.on("pageerror", (err) => consoleErrors.push(String(err)));
      await page.goto("http://127.0.0.1:8791/", { waitUntil: "networkidle", timeout: 30000 });
      await page.waitForTimeout(1500);
      const shot = path.join(SHOTS, `xss-${name}.png`);
      await page.screenshot({ path: shot, fullPage: true });
      const xssFlag = await page.evaluate(() => window.__xss === 1);
      const scriptNodes = await page.evaluate(() =>
        Array.from(document.querySelectorAll("script"))
          .map((s) => s.textContent || "")
          .filter((t) => t.includes("window.__xss")),
      );
      const imgHandlers = await page.evaluate(() =>
        Array.from(document.querySelectorAll("img[onerror]")).map((el) => el.outerHTML),
      );
      const bodyText = await page.evaluate(() => document.body.innerText);
      const loaded = !bodyText.includes("Can't read") && !/Unexpected token/.test(bodyText);
      const pass = !xssFlag && scriptNodes.length === 0 && imgHandlers.length === 0 && loaded;
      results.push({
        name,
        pass,
        xssFlag,
        scriptNodes,
        imgHandlers,
        loaded,
        consoleErrors: consoleErrors.slice(0, 10),
        shot,
        schema_version: activity.schema_version,
      });
      await browser.close();
    } finally {
      server.kill("SIGTERM");
      await new Promise((r) => setTimeout(r, 300));
    }
  }

  await serveAndProbe(actOld, "legacy-10");
  await serveAndProbe(actNew, "message-11");

  const out = path.join(LOGS, "xss_message_results.json");
  fs.writeFileSync(out, JSON.stringify(results, null, 2) + "\n");
  console.log(JSON.stringify(results, null, 2));
  const allPass = results.every((r) => r.pass);
  process.exit(allPass ? 0 : 1);
}

main().catch((err) => {
  console.error(err);
  process.exit(2);
});
