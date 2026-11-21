// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/companionWordingAndActions.test.mjs
//
// Octryx companion wording and actions: user language instead of raw terms, decisions visible and stop or
// abort in the ⋯ menu, "Dismiss" everywhere, short titles with Markdown text, one count rule, phases that follow the
// run, events in sentences, "on the server"; rendered: settings behind the gear, the section order, relative times
// that never go stale, and an answered card that holds its place before it leaves.
process.env.TZ = "Europe/Zurich";

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { cardActions, firstSentence, itemText, itemTitle, stripMarkdown, subtitleText, targetPhrase } from "../../src/chat/companion/companionLabels.ts";
import { currentSentence, eventViews, phaseStates, technicalCount } from "../../src/chat/companion/companionEvents.ts";
import { badgeCount } from "../../src/chat/companion/companionGroups.ts";
import { readAttention, readAttentionItem } from "../../src/chat/companion/companionRead.ts";
import { jobProblemItem, readJobDetail } from "../../src/chat/companion/companionJobModel.ts";
import { formatRelative } from "../../src/admin/utils/dateTime.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id && typeof node.type === "string");
const tick = (ms = 0) => act(() => new Promise((resolve) => setTimeout(resolve, ms)));

const RUN_ACTIONS = "/api/v1/workflow-runs/run-9/actions";
const runAction = (key, label, extra = {}) => ({ key, label, tone: "neutral", request: { method: "POST", path: RUN_ACTIONS, body: { action: key } }, ...extra });
const GATE = {
  key: "run:run-9:1", kind: "gate", id: "run-9", title: "**Confirm the test contract** for a3-spring-boot-upgrade. The tests cover login.",
  subtitle: "contract", severity: "action", created_at: "2026-11-06T07:35:36.595034+00:00",
  text: "**Confirm the test contract** for a3-spring-boot-upgrade. The tests cover login.",
  actions: [
    runAction("confirm", "Confirm these tests", { tone: "primary" }),
    runAction("change", "Change the tests"),
    runAction("stop", "Stop", { input: { kind: "text", field: "reason", label: "Why does the run stop?", required: true } }),
    runAction("abort", "Abort the run", { input: { kind: "text", field: "reason", label: "Why does the run stop?", required: true } }),
    runAction("confirm", "Confirm these tests", { tone: "primary" }),
  ],
};
const DONE = {
  key: "done:run-7", kind: "done", id: "run-7", title: "BRD-7 Onboarding", subtitle: "merged", severity: "info",
  created_at: "2026-11-06T07:35:36.595034+00:00", text: "Finished (merged). Pull request: https://example.test/pr/7",
  actions: [
    { key: "dismiss", label: "Done", tone: "primary", request: { method: "POST", path: "/api/v1/attention/dismiss", body: { key: "done:run-7" } } },
    runAction("abort", "Abort the run", { tone: "danger" }),
  ],
};
const PROBLEM = { key: "run:run-11:1", kind: "problem", id: "run-11", title: "BRD-11 Login", subtitle: "implement", severity: "warning",
  created_at: "2026-11-06T07:30:00+00:00", text: "The tests could not start.", actions: [runAction("continue", "Run the phase again", { tone: "primary" })] };

test("Decisions stay visible, stop and abort go into the menu once, a finished item only dismisses", () => {
  const gate = cardActions(readAttentionItem(GATE));
  assert.deepEqual(gate.decisions.map((action) => action.label), ["Confirm these tests", "Change the tests"], "identical actions once");
  assert.deepEqual(gate.menu.map((action) => action.key), ["stop", "abort"]);
  const done = cardActions(readAttentionItem(DONE));
  assert.deepEqual(done.decisions.map((action) => [action.key, action.label, action.tone]), [["dismiss", "Dismiss", "neutral"]]);
  assert.deepEqual(done.menu, [], "no abort on a finished run");
});

test("User language, a first-sentence title and Markdown-free plain text", () => {
  const gate = readAttentionItem(GATE);
  assert.equal(itemTitle(gate), "Confirm the test contract for a3-spring-boot-upgrade.");
  assert.equal(subtitleText(gate), "Test contract to confirm");
  assert.equal(subtitleText(readAttentionItem({ ...GATE, subtitle: "ask" })), "Approval");
  assert.equal(subtitleText(readAttentionItem({ ...GATE, subtitle: "work_item_state" })), "Work item state");
  assert.equal(itemText(readAttentionItem(DONE)), "Finished and merged. Pull request: https://example.test/pr/7");
  assert.equal(itemText(readAttentionItem({ ...DONE, text: "Finished (done)." })), "Finished.");
  assert.equal(stripMarkdown("## Plan\n- **a3_spring_boot** `x`"), "Plan a3_spring_boot x", "snake case stays intact");
  assert.equal(firstSentence("Which branch? main or release"), "Which branch?");
});

test("One count rule, needs you plus problems", () => {
  const attention = readAttention({ items: [GATE, PROBLEM, DONE], running: [] });
  assert.equal(badgeCount(attention.items), 2);
});

test("The server's phase states win; all pending falls back to the run's phase index", () => {
  const base = { run_id: "run-11", state: "problem", status: "paused", phase_count: 3, phase_index: 2,
    phases: [{ id: "clarify", title: "Clarify", state: "pending" }, { id: "contract", title: "Contract", state: "pending" }, { id: "implement", title: "Implement", state: "pending" }],
    events: [] };
  assert.deepEqual(phaseStates(readJobDetail(base)).map((phase) => phase.state), ["done", "problem", "pending"]);
  const given = { ...base, phases: [{ id: "clarify", title: "Clarify", state: "done" }, { id: "contract", title: "Contract", state: "pending" }, { id: "implement", title: "Implement", state: "pending" }] };
  assert.deepEqual(phaseStates(readJobDetail(given)).map((phase) => phase.state), ["done", "pending", "pending"], "backend states win");
  assert.deepEqual(phaseStates(readJobDetail({ ...base, state: "done", status: "completed" })).map((phase) => phase.state), ["done", "done", "done"]);
});

test("The server's sentences, repeats grouped, technical events behind their switch", () => {
  const job = readJobDetail({ run_id: "run-12", state: "working", current_step: { text: "Clarify: passed", kind: "phase_passed", technical: false, at: null }, events: [
    { text: "Go on?: confirmed", kind: "decision", technical: false, at: null },
    { text: "Clarify: a helper agent finished", kind: "subagent_reported", technical: false, at: null },
    { text: "Clarify: a helper agent finished", kind: "subagent_reported", technical: false, at: null },
    { text: "Loop iteration 2", kind: "loop_iteration", technical: true, at: null },
    { text: "Started Clarify", kind: "node_entered", technical: false, at: null },
  ] });
  assert.deepEqual(eventViews(job.events).map((event) => [event.text, event.count]), [
    ["Go on?: confirmed", 1], ["Clarify: a helper agent finished", 2], ["Started Clarify", 1],
  ], "a decision the server words is not hidden");
  assert.equal(technicalCount(job.events), 1);
  assert.equal(eventViews(job.events, { technical: true }).length, 4);
  assert.equal(currentSentence(job), "Clarify: passed");
});

test("A paused run's reason and the owner's decisions come with the job detail", () => {
  const decisions = [runAction("continue", "Run the phase again", { tone: "primary" }), runAction("abort", "Abort the run", { tone: "danger" })];
  const job = readJobDetail({ run_id: "run-9", state: "problem", can_control: true,
    problem: { reason: "tests_failed", code: "phase_failed", message: "The tests could not start." }, actions: decisions });
  const item = jobProblemItem(job);
  assert.equal(item.title, "The tests could not start.");
  assert.equal(item.text, "tests_failed");
  assert.deepEqual(cardActions(item).decisions.map((action) => action.label), ["Run the phase again"]);
  assert.deepEqual(cardActions(item).menu.map((action) => action.label), ["Abort the run"]);
  const watcher = readJobDetail({ run_id: "run-9", state: "problem", can_control: false, problem: { reason: "", code: "x", message: "Paused." }, actions: decisions });
  assert.deepEqual(watcher.actions, [], "no decisions without can_control");
  assert.equal(jobProblemItem(watcher).title, "Paused.");
  assert.equal(jobProblemItem(readJobDetail({ run_id: "run-9", state: "problem" })), null, "no problem and no decisions: no card");
});

test("Where a run runs reads as a phrase", () => {
  assert.equal(targetPhrase({ kind: "server", label: "the Server", online: null }), "on the server");
  assert.equal(targetPhrase({ kind: "device", label: "Studio Mac", online: false }), "on Studio Mac · offline");
  assert.equal(targetPhrase(null), "");
});

test("The server's microsecond timestamps read as UTC", () => {
  const now = Date.parse("2026-11-06T08:35:36Z");
  assert.equal(formatRelative("2026-11-06T07:35:36.595034+00:00", "", now), "59 min ago");
  assert.equal(formatRelative("2026-11-06T07:35:36.595034", "", now), "59 min ago", "a value without zone is UTC");
});

function loader(extra) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl, JSON,
      encodeURIComponent, setInterval, clearInterval, setTimeout, clearTimeout, CustomEvent, Set, Map, String, Array, Boolean, RegExp,
      ...extra,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return (relative) => loadFile(path.join(SRC, relative));
}

function windowStub() {
  const target = new EventTarget();
  return {
    location: { origin: "http://localhost", search: "", href: "http://localhost/chat" },
    localStorage: { getItem: () => null, setItem() {} },
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    addEventListener: (...args) => target.addEventListener(...args),
    removeEventListener: (...args) => target.removeEventListener(...args),
    dispatchEvent: (event) => target.dispatchEvent(event),
  };
}

async function renderPanel({ attention, clock, onDone = () => {}, answeredMs = 40 }) {
  const reply = (status, body) => ({ ok: status < 400, status, statusText: String(status), json: async () => body });
  const fetch = async (url) => (String(url) === RUN_ACTIONS ? reply(200, { ok: true }) : reply(200, { quiet_hours: null }));
  const load = loader({ fetch, window: windowStub() });
  const { CompanionPanel } = load("chat/companion/CompanionPanel.tsx");
  const props = (next) => ({ attention: next, problem: null, onClose() {}, onDone, onOpenAgents() {},
    footer: { userId: "u-alex", notificationApi: null }, watchJob() {}, now: () => clock.now, answeredMs });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(CompanionPanel, props(attention))); });
  return { view, rerender: (next) => act(async () => view.update(createElement(CompanionPanel, props(next)))) };
}

test("Settings behind the gear, Needs you → Problems → Running → Done, times read against the current clock", async () => {
  const clock = { now: Date.parse("2026-11-06T07:30:00Z") };
  const first = readAttention({ items: [GATE, PROBLEM], running: [{ id: "r1", state: "working", current_node: "implement" }] });
  const { view, rerender } = await renderPanel({ attention: first, clock });
  try {
    assert.equal(byTestId(view, "octryx-footer").length, 0, "quiet hours wait behind the gear");
    const order = view.root.findAll((node) => node.type === "section" && String(node.props["data-testid"] || "").startsWith("octryx-")).map((node) => node.props["data-testid"]);
    assert.deepEqual(order, ["octryx-needs", "octryx-problems", "octryx-working"]);
    assert.match(text(byTestId(view, "octryx-problems")[0]), /^Problems \(1\)/);
    clock.now = Date.parse("2026-11-06T07:40:00Z");
    await rerender(readAttention({ items: [GATE, PROBLEM, DONE], running: [] }));
    const done = byTestId(view, "octryx-done")[0];
    assert.match(text(done), /4 min ago/, "a later item never reads as being in the future");
    assert.doesNotMatch(text(byTestId(view, "octryx-panel")[0]), /\bin (less than a minute|\d+ min)/);
    await act(async () => byTestId(view, "octryx-settings")[0].props.onClick());
    assert.equal(byTestId(view, "octryx-footer").length, 1);
  } finally {
    view.unmount();
  }
});

test("An answered card says Answered where it stands, then leaves; the next card does not move before that", async () => {
  const clock = { now: Date.parse("2026-11-06T07:40:00Z") };
  const second = { ...GATE, key: "run:run-10:1", id: "run-10", title: "Approve the plan.", text: "Approve the plan." };
  const left = [];
  const attention = readAttention({ items: [GATE, second], running: [] });
  const { view, rerender } = await renderPanel({ attention, clock, onDone: (key) => left.push(key) });
  try {
    await act(async () => byTestId(view, "octryx-action")[0].props.onClick());
    await tick();
    // The server already dropped the answered item: it still stands first, saying "Answered".
    await rerender(readAttention({ items: [second], running: [] }));
    const cards = byTestId(view, "octryx-item");
    assert.equal(cards.length, 2);
    assert.equal(text(byTestId(view, "octryx-answered")[0]), "Answered");
    assert.equal(cards[0].props["aria-busy"], true, "the answered card keeps its place");
    assert.match(text(byTestId(view, "octryx-needs")[0]), /^Needs you \(1\)/);
    await tick(60);
    assert.deepEqual(left, ["run:run-9:1"]);
    assert.equal(byTestId(view, "octryx-item").length, 1);
    const menus = view.root.findAll((node) => node.type === "button" && String(node.props["aria-label"] || "").startsWith("More actions for"));
    assert.equal(menus.length, 1, "stop and abort sit in one ⋯ menu");
  } finally {
    view.unmount();
  }
});

test("rendered: the job detail shows the paused run's reason and decisions from the job itself", async () => {
  const reply = (status, body) => ({ ok: status < 400, status, statusText: String(status), json: async () => body });
  const JOB = { run_id: "run-9", title: "Login", state: "problem", status: "paused", can_control: true,
    problem: { reason: "", code: "phase_failed", message: "The tests could not start." },
    actions: [runAction("continue", "Run the phase again", { tone: "primary" }), runAction("abort", "Abort the run", { tone: "danger" })],
    events: [{ text: "Paused: The tests could not start.", kind: "paused", technical: false, at: null }] };
  const fetch = async (url) => (String(url).endsWith("/attention/jobs/run-9") ? reply(200, JOB) : reply(200, { ok: true }));
  const load = loader({ fetch, window: windowStub(), document: undefined });
  const { CompanionJobDetail } = load("chat/companion/CompanionJobDetail.tsx");
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(CompanionJobDetail, { runId: "run-9", onBack() {}, watchJob() {}, now: () => Date.parse("2026-11-06T08:00:00Z") }));
  });
  await tick();
  try {
    const decision = byTestId(view, "octryx-job-decision")[0];
    assert.ok(decision, "the job's own problem card is shown");
    assert.match(text(decision), /The tests could not start\./);
    assert.deepEqual(byTestId(view, "octryx-action").map((node) => text(node)), ["Run the phase again"]);
    assert.equal(byTestId(view, "octryx-job-abort").length, 0, "abort sits in the card's menu, not twice");
  } finally {
    view.unmount();
  }
});
