// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/companionPanelLayout.test.mjs
//
// Octryx: the panel is the design system's side panel over the dimmed page; Now / Jobs are
// segmented tabs; jobs are rows of a compact table; every run appears in exactly one group, by precedence
// Needs you > Problems > Running > Done; a card says each thing once ("Go on?" once, "Finished" once).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import { badgeCount, groupAttention } from "../../src/chat/companion/companionGroups.ts";
import { companionLabel } from "../../src/chat/companion/companionModel.ts";
import { readAttention, readAttentionItem } from "../../src/chat/companion/companionRead.ts";
import { cardParts, itemTitle } from "../../src/chat/companion/companionLabels.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id && typeof node.type === "string");
const tick = (ms = 0) => act(() => new Promise((resolve) => setTimeout(resolve, ms)));

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

const action = (run, key, label, extra = {}) => ({ key, label, tone: "neutral",
  request: { method: "POST", path: `/api/v1/workflow-runs/${run}/actions`, body: { action: key } }, ...extra });
// The server's shapes (backend services/attention/run_items.py, running.py): run items carry `run.id`.
const APPROVAL = { key: "run:run-12:1", kind: "gate", id: "run-12", title: "[companion fixture]", subtitle: "Go on?",
  text: "Go on?", severity: "action", run: { id: "run-12" }, workspace: { id: "ws-1", name: "Test" },
  actions: [action("run-12", "confirm", "Go to the next phase", { tone: "primary" }), action("run-12", "later", "Not now")] };
const KAN14_DONE = { key: "run:run-14:2", kind: "done", id: "run-14", title: "BRD-14 Add capitalize_words", subtitle: "Merged",
  text: "The pull request is open and waits for your review and merge.", severity: "info", run: { id: "run-14" } };
const FINISHED = { key: "done:run-7", kind: "done", id: "run-7", title: "[companion fixture]", subtitle: "completed",
  text: "Finished (completed).", severity: "info", run: { id: "run-7" }, workspace: { id: "ws-1", name: "Test" } };
const PAUSED = { key: "run:run-11:1", kind: "problem", id: "run-11", title: "BRD-11 Login", subtitle: "Go on?", severity: "warning",
  text: "The phase's turn ended without finishing it.", run: { id: "run-11" } };
const QUESTION = { key: "clarification:q1", kind: "question", id: "q1", title: "Which branch?", text: "main or release?", severity: "action",
  session_id: "s-1", run: null };
const RUNNING = [
  { id: "run-12", state: "needs_you", status: "waiting", waiting_kind: "awaiting_confirmation", title: "[companion fixture]" },
  { id: "run-14", state: "working", status: "waiting", current_node: "merged", work_item: { id: "w", key: "BRD-14", title: "Add capitalize_words" } },
  { id: "run-11", state: "working", status: "running", title: "BRD-11 Login" },
  { id: "run-20", state: "working", status: "running", title: "BRD-20 Search" },
];

test("each run is in exactly one group: Needs you > Problems > Running > Done", () => {
  const attention = readAttention({ items: [APPROVAL, KAN14_DONE, FINISHED, PAUSED, QUESTION], running: RUNNING });
  const groups = groupAttention(attention.items, attention.running);
  assert.deepEqual(groups.needs.map((item) => item.key), ["run:run-12:1", "clarification:q1"]);
  assert.deepEqual(groups.problems.map((item) => item.key), ["run:run-11:1"]);
  assert.deepEqual(groups.running.map((run) => run.key), ["run-14", "run-20"], "the approval run and the paused run are not Running too");
  assert.deepEqual(groups.done.map((item) => item.key), ["done:run-7"], "BRD-14 still runs: it is not Done as well");
  const shown = [...groups.needs.map((item) => item.runId), ...groups.problems.map((item) => item.runId),
    ...groups.running.map((run) => run.key), ...groups.done.map((item) => item.runId)].filter(Boolean);
  assert.equal(new Set(shown).size, shown.length, "no run twice");
  assert.equal(badgeCount(attention.items), 3);
  assert.equal(companionLabel(attention), "Octryx: 2 needs you, 2 working, 1 done, 1 problem");
});

test("an item's run is read from run.id, else from a run, done or handover key; other items have none", () => {
  assert.equal(readAttentionItem(APPROVAL).runId, "run-12");
  assert.equal(readAttentionItem({ ...FINISHED, run: undefined }).runId, "run-7");
  assert.equal(readAttentionItem({ key: "handover:run-3:1", kind: "handover", id: "run-3", title: "Take over" }).runId, "run-3");
  assert.equal(readAttentionItem(QUESTION).runId, null);
  assert.equal(readAttentionItem({ key: "tool_approval:a1", kind: "gate", id: "a1", title: "Allow write" }).runId, null);
});

test("a card says each thing once: 'Go on?' once, 'Finished' once", () => {
  const approval = readAttentionItem(APPROVAL);
  const parts = cardParts(approval, itemTitle(approval));
  assert.equal(parts.subtitle, "", "the subtitle repeats the question");
  assert.equal(parts.body, "Go on?");
  assert.deepEqual(parts.meta, ["Approval", "Test"]);
  const finished = readAttentionItem(FINISHED);
  const done = cardParts(finished, itemTitle(finished));
  const shown = [itemTitle(finished), done.subtitle, ...done.meta, done.body].join(" ");
  assert.equal(shown.match(/finished/gi)?.length, 1, shown);
  const paused = readAttentionItem(PAUSED);
  assert.equal(cardParts(paused, itemTitle(paused)).subtitle, "Go on?", "a different body keeps the phase name");
});

async function renderPanel(attention, extra = {}) {
  const reply = (body) => ({ ok: true, status: 200, statusText: "200", json: async () => body });
  const jobs = { jobs: [
    { run_id: "run-14", title: "Feature delivery", work_item: { id: "w", key: "BRD-14", title: "Add capitalize_words" }, state: "working",
      status: "waiting", current_node: { id: "merged", title: "Merged" }, phase_index: 4, phase_count: 5, runtime_target: { kind: "server", label: "Server" } },
    { run_id: "run-7", title: "[companion fixture]", state: "done", status: "completed", phase_count: 2 },
  ] };
  const fetch = async (url) => reply(String(url).includes("/api/v1/attention/jobs") ? jobs : { quiet_hours: null });
  const load = loader({ fetch, window: windowStub(), ...extra });
  const { CompanionPanel } = load("chat/companion/CompanionPanel.tsx");
  const closed = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(CompanionPanel, { attention, problem: null, onClose: () => closed.push(1), onDone() {},
      onOpenAgents() {}, footer: { userId: "u-alex", notificationApi: null }, watchJob() {}, answeredMs: 0 }));
  });
  return { view, closed };
}

test("the panel is the side panel over the dimmed page, with Now / Jobs as segmented tabs and jobs as table rows", async () => {
  const attention = readAttention({ items: [APPROVAL, KAN14_DONE, FINISHED], running: RUNNING });
  const { view, closed } = await renderPanel(attention);
  try {
    const sheet = byTestId(view, "octryx-panel")[0];
    assert.equal(sheet.props.role, "dialog");
    assert.match(sheet.props.className, /ds-panel--narrow/);
    const backdrop = byTestId(view, "octryx-panel-backdrop")[0];
    await act(async () => backdrop.props.onMouseDown({ target: backdrop, currentTarget: backdrop }));
    assert.equal(closed.length, 1, "a click on the dimmed page closes it");
    const tabs = view.root.findAll((node) => node.props.role === "tab" && typeof node.type === "string");
    assert.deepEqual(tabs.map(text), ["Now", "Jobs"]);
    assert.deepEqual(view.root.findAll((node) => node.type === "h3").map(text), ["Needs you (1)", "Running (3)", "Done in the last 3 days (1)"]);
    assert.equal(text(byTestId(view, "octryx-needs")[0]).match(/Go on\?/g)?.length, 1, "'Go on?' once per card");
    await act(async () => tabs[1].props.onClick());
    await tick();
    const table = byTestId(view, "octryx-jobs-table")[0];
    assert.ok(table.find((node) => node.type === "table"));
    const rows = table.findAll((node) => node.type === "tr" && node.props["data-row-key"]);
    assert.equal(rows.length, 2);
    assert.match(text(rows[0]), /BRD-14 Add capitalize_words/);
    assert.equal(view.root.findAll((node) => typeof node.props.className === "string" && node.props.className.includes("octryx-jobs__row")).length, 0,
      "no job cards");
  } finally {
    view.unmount();
  }
});

test("Escape closes the side panel, but in an open confirmation only the confirmation", async () => {
  const doc = new EventTarget();
  doc.activeElement = null;
  const load = loader({ window: windowStub(), document: doc });
  const { SidePanel } = load("layout/SidePanel.ts");
  let dialogOpen = true;
  const closed = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(SidePanel, { title: "Octryx", onClose: () => closed.push(1) }, "body"), {
      createNodeMock: () => ({ focus() {}, querySelector: (selector) => (selector === '[role="alertdialog"]' && dialogOpen ? {} : null) }),
    });
  });
  const escape = () => { const event = new Event("keydown", { cancelable: true }); event.key = "Escape"; doc.dispatchEvent(event); };
  await act(async () => escape());
  assert.equal(closed.length, 0, "the confirmation takes Escape");
  dialogOpen = false;
  await act(async () => escape());
  assert.equal(closed.length, 1);
  act(() => view.unmount());
});

test("a finished Mac turn is done and a failed one a problem; only the failed one counts in the badge", () => {
  const turn = (key, severity, subtitle) => ({ key, kind: "turn", id: key, title: "On your Mac (demo)", subtitle, severity,
    created_at: "2026-11-21T08:00:00Z", text: "", actions: [] });
  const attention = readAttention({ items: [turn("turn:ok", "info", "success"), turn("turn:red", "warning", "timeout")], running: [] });
  const groups = groupAttention(attention.items, attention.running);
  assert.deepEqual(groups.done.map((item) => item.key), ["turn:ok"]);
  assert.deepEqual(groups.problems.map((item) => item.key), ["turn:red"]);
  assert.equal(badgeCount(attention.items), 1);
});

test("a turn of an imported sample run says so instead of 'Mac turn'", () => {
  const item = readAttentionItem({ key: "turn:j:t1", kind: "turn", id: "j", title: "Finished in the sample run (demo-ocx2)",
    subtitle: "success", severity: "info", sample: true, actions: [] });
  assert.equal(item.sample, true);
  // The title already says it: the card names it once, never "Mac turn".
  assert.deepEqual(cardParts(item, item.title).meta, []);
  assert.deepEqual(cardParts(item, "Finished (demo-ocx2)").meta, ["Sample run"]);
  const own = readAttentionItem({ key: "turn:j:t2", kind: "turn", id: "j", title: "Finished on your Mac (src)", severity: "info", actions: [] });
  assert.deepEqual(cardParts(own, own.title).meta, ["Mac turn"]);
});
