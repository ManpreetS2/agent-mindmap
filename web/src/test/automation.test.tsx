import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import type { Automation, AutomationTask } from "@shared/automation";
import demoJson from "../../../fixtures/automation/demo.json";
import { AutomationPanel } from "../components/AutomationPanel";
import { createAutomationPollTransport } from "../data/automationTransport";
import {
  AUTOMATION_STALE_MS,
  RUNNING_STALE_MS,
  evaluateAutomation,
  isAutomationShape,
  sanitizeAutomation,
} from "../utils/automationEval";

const demo = demoJson as unknown as Automation;
const NOW = Date.parse(demo.generated_at) + 30_000;
const ok = (data: Automation) => ({ status: "ok" as const, data });
const live = (patch: Partial<Automation> = {}): Automation => ({
  ...demo,
  mode: "live",
  notes: demo.notes.filter((n) => !/SYNTHETIC/.test(n)),
  ...patch,
});
const task = (patch: Partial<AutomationTask>): AutomationTask => ({ ...demo.tasks[1], ...patch });

describe("shape guard", () => {
  it("accepts the demo fixture", () => {
    expect(isAutomationShape(demo)).toBe(true);
  });
  it.each([
    ["wrong schema", { ...demo, schema: "agent-mindmap-automation/v2" }],
    ["unknown mode", { ...demo, mode: "simulated" }],
    ["unknown source status", { ...demo, source: { ...demo.source, status: "ok" } }],
    ["unknown task state", { ...demo, tasks: [{ ...demo.tasks[0], state: "done" }] }],
    ["bad task id", { ...demo, tasks: [{ ...demo.tasks[0], id: "t3:abc" }] }],
    ["too many tasks", { ...demo, tasks: Array.from({ length: 51 }, () => demo.tasks[0]) }],
    ["missing assignment", { ...demo, tasks: [{ ...demo.tasks[0], assignment: null }] }],
    ["non-array notes", { ...demo, notes: "x" }],
  ])("rejects %s", (_n, doc) => {
    expect(isAutomationShape(doc)).toBe(false);
  });
});

describe("sanitize", () => {
  it("drops non-GitHub links and redacts private-looking text", () => {
    const dirty = live({
      tasks: [
        task({
          issue: { number: 1, title: "see /Users/someone/private", url: "javascript:alert(1)" },
          pull_request_url: "https://evil.example/pull/1",
          state_basis: "owner@example.com did it",
          error_evidence: { type: "agent_failed", time: null, severity: "error", summary: "Bearer abcdef0123456789" },
        }),
      ],
    });
    const clean = sanitizeAutomation(dirty).tasks[0];
    expect(clean.issue.url).toBeNull();
    expect(clean.issue.title).toBe("[redacted]");
    expect(clean.pull_request_url).toBeNull();
    expect(clean.state_basis).toBe("[redacted]");
    expect(clean.error_evidence?.summary).toBe("[redacted]");
  });
});

describe("evaluate", () => {
  const running = live({ tasks: [task({ state: "running", state_observed_at: demo.generated_at })] });
  it("keeps a fresh running task running", () => {
    expect(evaluateAutomation(running, NOW).tasks[0].effectiveState).toBe("running");
  });
  it("a stale document never shows running", () => {
    const e = evaluateAutomation(running, Date.parse(demo.generated_at) + AUTOMATION_STALE_MS + 1);
    expect(e.documentStale).toBe(true);
    expect(e.tasks[0].effectiveState).toBe("unknown");
    expect(e.tasks[0].downgradeReason).toMatch(/stale/i);
  });
  it("an old observation never shows running even in a fresh document", () => {
    const old = live({ generated_at: demo.generated_at, tasks: [task({ state: "running", state_observed_at: new Date(Date.parse(demo.generated_at) - RUNNING_STALE_MS - 1).toISOString() })] });
    expect(evaluateAutomation(old, NOW).tasks[0].effectiveState).toBe("unknown");
  });
  it("counts effective states and marks demo tasks simulated", () => {
    const e = evaluateAutomation(demo, NOW);
    expect(e.tasks.every((t) => t.simulated)).toBe(true);
    expect(e.counts.running + e.counts.queued + e.counts.blocked + e.counts.failed + e.counts.completed + e.counts.unknown).toBe(demo.tasks.length);
  });
});

describe("transport", () => {
  const respond = (status: number, body: unknown = null) =>
    (async () => new Response(typeof body === "string" ? body : JSON.stringify(body), { status })) as typeof fetch;
  const run = (fetchImpl: typeof fetch) => createAutomationPollTransport({ url: "/automation.json", fetchImpl }).fetch();

  it("404, other HTTP failures and network errors are absent", async () => {
    expect(await run(respond(404))).toEqual({ kind: "absent" });
    expect(await run(respond(500))).toEqual({ kind: "absent" });
    expect(await run((async () => { throw new Error("down"); }) as typeof fetch)).toEqual({ kind: "absent" });
  });
  it("invalid JSON and off-contract payloads are rejected, not trusted", async () => {
    expect((await run(respond(200, "{nope"))).kind).toBe("rejected");
    expect((await run(respond(200, { schema: "other" }))).kind).toBe("rejected");
  });
  it("valid payload is sanitized on the way in", async () => {
    const dirty = live({ tasks: [task({ pull_request_url: "https://evil.example/pull/1" })] });
    const r = await run(respond(200, dirty));
    expect(r.kind).toBe("ok");
    if (r.kind === "ok") expect(r.data.tasks[0].pull_request_url).toBeNull();
  });
});

describe("AutomationPanel", () => {
  it("absent says unknown, not empty", () => {
    render(<AutomationPanel state={{ status: "absent" }} nowMs={NOW} />);
    const p = screen.getByTestId("automation-panel");
    expect(p).toHaveTextContent(/not connected/i);
    expect(p).toHaveTextContent(/not evidence that nothing is queued/i);
    expect(screen.queryAllByTestId("automation-task")).toHaveLength(0);
  });
  it("rejected is shown with its reason", () => {
    render(<AutomationPanel state={{ status: "rejected", reason: "bad shape" }} nowMs={NOW} />);
    expect(screen.getByTestId("automation-panel")).toHaveTextContent(/rejected \(bad shape\)/);
  });
  it("demo is labelled synthetic and every state renders with its basis", () => {
    render(<AutomationPanel state={ok(demo)} nowMs={NOW} />);
    const panel = screen.getByTestId("automation-panel");
    expect(panel).toHaveTextContent(/DEMO — SYNTHETIC TASKS/);
    const states = screen.getAllByTestId("automation-task").map((el) => el.getAttribute("data-state"));
    expect(states).toEqual(expect.arrayContaining(["running", "queued", "blocked", "failed", "completed", "unknown"]));
    const failed = screen.getAllByTestId("automation-task").find((el) => el.getAttribute("data-state") === "failed")!;
    expect(within(failed).getByTestId("automation-evidence")).toHaveTextContent(/error/);
    expect(panel).toHaveTextContent(/simulated/);
  });
  it("a live running task shows account and model only when known, and unknown otherwise", () => {
    const doc = live({
      tasks: [
        task({ id: "taskbot:example/demo-app#1", state: "running", state_observed_at: demo.generated_at, assignment: { account: "personal", model: "m-1", effort: "low", known: true, source: "run_record" } }),
        task({ id: "taskbot:example/demo-app#2", issue: { number: 2, title: "Two", url: null }, state: "running", state_observed_at: demo.generated_at, assignment: { account: null, model: null, effort: null, known: false, source: "none" } }),
      ],
    });
    render(<AutomationPanel state={ok(doc)} nowMs={NOW} />);
    const [a, b] = screen.getAllByTestId("automation-task");
    expect(a).toHaveTextContent("personal · m-1 low");
    expect(b).toHaveTextContent(/Model and account not reported/);
    expect(screen.getByTestId("automation-panel")).not.toHaveTextContent(/DEMO/);
  });
  it("a PR link is bookkeeping, never presented as delegation", () => {
    const doc = live({ tasks: [task({ state: "completed", pull_request_url: "https://github.com/example/demo-app/pull/21" })] });
    render(<AutomationPanel state={ok(doc)} nowMs={NOW} />);
    const link = screen.getByRole("link", { name: /Draft PR opened by taskbot/ });
    expect(link).toHaveAttribute("href", "https://github.com/example/demo-app/pull/21");
    expect(link).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByTestId("automation-panel")).toHaveTextContent(/not model delegation/);
  });
  it("source problems say the job state is unknown", () => {
    const doc = live({ source: { ...demo.source, status: "unreadable", reason: "OperationalError: locked" }, tasks: [] });
    render(<AutomationPanel state={ok(doc)} nowMs={NOW} />);
    expect(screen.getByTestId("automation-source")).toHaveTextContent(/unreadable.*Job state is unknown/);
  });
  it("a stale live document warns and downgrades running", () => {
    const doc = live({ tasks: [task({ state: "running", state_observed_at: demo.generated_at })] });
    render(<AutomationPanel state={ok(doc)} nowMs={Date.parse(demo.generated_at) + AUTOMATION_STALE_MS + 1000} />);
    expect(screen.getByTestId("automation-panel")).toHaveTextContent(/Stale/);
    expect(screen.getByTestId("automation-task")).toHaveAttribute("data-state", "unknown");
  });
});
