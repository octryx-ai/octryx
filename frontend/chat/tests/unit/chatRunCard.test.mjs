// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/chatRunCard.test.mjs
//
// The run card shows on top only the phases as steps, the state and the next action;
// loop counters only once used; provenance with run ids only under Details; the run's chat is titled by its Work
// item and current state; the turn status never stays on "Loading…"; the composer offers one control per choice
// : workflow, model ("Automatic · <model>") and Off / Quick / Thorough up front, no Workspace select,
// only the run location under Advanced; the audit fact is a small lock.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import * as runCardModel from "../../src/chat/workflowRun/runCardModel.ts";
import * as runBarModel from "../../src/chat/workflowRun/runBarModel.ts";
import { runPhaseShort, runPlaceText, runWorkflowName } from "../../src/chat/workflowRun/runBarModel.ts";
import { publishRunThreadTitle, runThreadTitleOf, subscribeRunThreadTitles } from "../../src/chat/workflowRun/runBarModel.ts";
import { runActionsInOrder, runCounterTexts, runDetailTexts, runNextAction, runSteps, runThreadTitle } from "../../src/chat/workflowRun/runCardModel.ts";
import { THINKING_SWITCH, thinkingLevelLabel } from "../../src/chat/composer/thinkingSwitch.ts";
import { THINKING_OPTIONS, getThinkingPillLabel } from "../../src/chat/appHelpers.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

function load(relative, mocks = {}, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, ...extra,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        const key = path.basename(name);
        if (key in mocks) return mocks[key];
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return loadFile(path.join(SRC, relative));
}

const RUN_ID = "3f1c2a9e-0b7d-4c1e-9a55-6d2f8e1b4c70";
const EARLIER = "a1b2c3d4-0000-4000-8000-000000000001";

function run(overrides = {}) {
  return {
    id: RUN_ID,
    title: "Continue workflow run pr-review-bot: phase 'Clarify'",
    workflow_key: "pr-review-bot",
    workflow_kind: "phased",
    workflow_version: "3",
    status: "waiting",
    waiting_kind: "waiting_for_reply",
    pause_reason: null,
    outcome: null,
    last_error: null,
    current_node: { id: "implement", title: "Implement", kind: "phase" },
    phase_position: { index: 2, total: 3 },
    nodes: [
      { id: "clarify", title: "Clarify", kind: "phase" },
      { id: "prepare", title: "Prepare folder", kind: "workspace.prepare" },
      { id: "implement", title: "Implement", kind: "phase" },
      { id: "review", title: "Review", kind: "phase" },
    ],
    loops: [
      { edge_id: "e1", title: "Test contract ↔ review", used: 0, limit: 2 },
      { edge_id: "e2", title: "Implement ↔ test", used: 1, limit: 3 },
      { edge_id: "e3", title: "Unbounded", used: 4, limit: 0 },
    ],
    gate: null,
    waiting: { kind: "waiting_for_reply", question: "Which login provider?" },
    adopted: { branch: { from_run: EARLIER } },
    work_item: { id: "wi-1", key: "BRD-12", title: "Login fix" },
    ticket_key: null,
    branch: "feature/brd-12",
    runtime_target: null,
    access: "requester",
    actions: [
      { key: "abort", label: "Abort the run", tone: "danger", input: { name: "reason", kind: "text", default: "", label: "Reason", required: true } },
      { key: "reply", label: "Reply", tone: null },
      { key: "change_runtime", label: "Change where it runs", tone: null },
    ],
    updated_at: "2026-11-06T10:00:00Z",
    ...overrides,
  };
}

test("the steps are the run's phases: done, the current one active (problem when paused), the rest pending", () => {
  assert.deepEqual(runSteps(run()).map((step) => `${step.title}:${step.state}`), ["Clarify:done", "Implement:active", "Review:pending"]);
  assert.deepEqual(runSteps(run({ status: "paused" })).map((step) => step.state), ["done", "problem", "pending"]);
  assert.deepEqual(runSteps(run({ status: "completed" })).map((step) => step.state), ["done", "done", "done"]);
  // Outside the phases (preparing the folder) the position falls back to the phase index; no phases, no steps.
  assert.deepEqual(runSteps(run({ current_node: { id: "prepare", title: "Prepare folder", kind: "workspace.prepare" } }))
    .map((step) => step.state), ["done", "active", "pending"]);
  assert.deepEqual(runSteps(run({ nodes: [], phase_position: { index: null, total: 0 } })), []);
});

test("counters only once used; provenance and ids only in Details", () => {
  assert.deepEqual(runCounterTexts(run()), ["Implement ↔ test 1/3"]);
  assert.deepEqual(runCounterTexts(run({ loops: [{ edge_id: "e1", title: "Idle", used: 0, limit: 2 }] })), []);
  const details = runDetailTexts(run());
  assert.equal(details[0], "Workflow pr-review-bot · version 3");
  assert.ok(details.some((line) => line.includes(EARLIER)), "the earlier run's id is in Details");
  assert.equal(details.at(-1), `Run ${RUN_ID}`);
});

test("the next action is the first non-destructive one while the run waits for the person; danger goes last", () => {
  assert.equal(runNextAction(run())?.key, "reply");
  assert.deepEqual(runActionsInOrder(run()).map((action) => action.key), ["reply", "change_runtime", "abort"]);
  assert.equal(runNextAction(run({ status: "running" })), null, "a working run asks nothing of the person");
  assert.equal(runNextAction(run({ actions: [run().actions[0]] })), null, "abort alone is never the next action");
});

test("a run's chat is titled by its Work item and current state, and the header follows it", () => {
  assert.equal(runThreadTitle(run()), "BRD-12 Login fix · Waiting for you");
  assert.equal(runThreadTitle(run({ status: "running", actions: [] })), "BRD-12 Login fix · Working");
  assert.equal(runThreadTitle(run({ status: "completed", actions: [] })), "BRD-12 Login fix · Done");
  assert.equal(runThreadTitle(run({ work_item: null, status: "failed", actions: [] })),
    "Continue workflow run pr-review-bot: phase 'Clarify' · Failed");
  let calls = 0;
  const stop = subscribeRunThreadTitles(() => { calls += 1; });
  publishRunThreadTitle("s-1", "BRD-12 Login fix · Working");
  publishRunThreadTitle("s-1", "BRD-12 Login fix · Working");
  assert.equal(calls, 1, "the same title notifies once");
  assert.equal(runThreadTitleOf("s-1"), "BRD-12 Login fix · Working");
  publishRunThreadTitle("s-1", null);
  assert.equal(runThreadTitleOf("s-1"), null);
  assert.equal(runThreadTitleOf("s-2"), null);
  stop();
});

function renderBanner(current, storage = new Map()) {
  const sessionStorage = {
    getItem: (key) => (storage.has(key) ? storage.get(key) : null),
    setItem: (key, value) => storage.set(key, String(value)),
    removeItem: (key) => storage.delete(key),
  };
  const { WorkflowRunBanner } = load("chat/workflowRun/WorkflowRunBanner.tsx", {
    useWorkflowRun: { useWorkflowRun: () => ({ run: current, busy: false, problem: null, act: async (action) => { acted.push(action.key); return null; } }) },
    executionTarget: { readExecutionTarget: () => ({ kind: "server" }), setExecutionTarget() {} },
    linkedAccountsModel: { LINK_ACCOUNT_HREF: "/chat?area=personal" },
    // The same module instances the test reads the published title from.
    runCardModel,
    runBarModel,
  }, { window: { location: { assign() {} }, sessionStorage, addEventListener() {}, removeEventListener() {} } });
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkflowRunBanner, { sessionId: "s-9", refreshKey: 1 })); });
  return view;
}
const acted = [];

test("the bar is one quiet line: workflow, phase, state, where, and the next action; details folded away", () => {
  const view = renderBanner(run({ runtime_target: { kind: "server", label: "the Server" } }));
  const bar = view.root.findByProps({ "data-testid": "workflow-run-bar" });
  const toggle = view.root.findByProps({ "data-testid": "workflow-run-bar-toggle" });
  assert.equal(text(toggle), "▸PR review bot · Phase 2/3");
  assert.equal(toggle.props["aria-expanded"], false);
  const state = view.root.findByProps({ "data-testid": "workflow-run-bar-state" });
  assert.equal(state.props["data-tone"] ?? state.findByType("span").props["data-tone"], "attention");
  assert.equal(text(view.root.findByProps({ "data-testid": "workflow-run-bar-place" })), "on the server");
  assert.equal(text(view.root.findByProps({ "data-testid": "workflow-run-next-action" })), "Reply");
  assert.equal(view.root.findAllByProps({ "data-testid": "workflow-run-bar-details" }).length, 0, "collapsed by default");
  assert.doesNotMatch(text(bar), new RegExp(`${RUN_ID}|${EARLIER}|Implement ↔ test`), "no ids or counters in the line");
  act(() => view.unmount());
});

function toneOf(view) {
  return view.root.findAll((node) => node.props && node.props["data-testid"] === "workflow-run-bar-state" && node.props["data-tone"])[0].props["data-tone"];
}

test("the bar's state is neutral for a normal run; colour only for exceptions", () => {
  const view = renderBanner(run({ status: "running", waiting_kind: null, waiting: null, actions: [] }));
  assert.equal(toneOf(view), "neutral");
  assert.equal(view.root.findAllByProps({ "data-testid": "workflow-run-next-action" }).length, 0, "no action without a decision");
  act(() => view.unmount());
  const failed = renderBanner(run({ status: "failed", waiting: null, actions: [] }));
  assert.equal(toneOf(failed), "problem");
  act(() => failed.unmount());
});

test("opening the details shows steps, counters > 0, actions with danger in the menu, ids only in Details; remembered per run", () => {
  const storage = new Map();
  const view = renderBanner(run(), storage);
  act(() => view.root.findByProps({ "data-testid": "workflow-run-bar-toggle" }).props.onClick());
  const details = view.root.findByProps({ "data-testid": "workflow-run-bar-details" });
  assert.equal(text(view.root.findByProps({ "data-testid": "workflow-run-steps" })), "ClarifyImplementReview");
  assert.match(text(details), /Implement ↔ test 1\/3/);
  assert.doesNotMatch(text(details), /Test contract ↔ review|Unbounded/);
  assert.match(text(details), /Which login provider\?/);
  const inline = details.findAllByType("button").map(text);
  assert.ok(inline.includes("Reply") && inline.includes("Change where it runs"));
  assert.ok(!inline.includes("Abort the run"), "the destructive action sits in the ⋯ menu");
  assert.equal(details.findAllByProps({ "aria-label": "More actions for BRD-12 Login fix" }).length, 1);
  const provenance = view.root.findByProps({ "data-testid": "workflow-run-details" });
  const outside = text(view.root).replace(text(provenance), "");
  assert.doesNotMatch(outside, new RegExp(`${RUN_ID}|${EARLIER}`), "no id outside Details");
  assert.equal(storage.get(`octryx.runbar.open.${RUN_ID}`), "1", "remembered for this run");
  act(() => view.unmount());
  const again = renderBanner(run(), storage);
  assert.equal(again.root.findAllByProps({ "data-testid": "workflow-run-bar-details" }).length, 1, "reopens as left");
  assert.equal(runThreadTitleOf("s-9"), "BRD-12 Login fix · Waiting for you", "the banner publishes the title");
  act(() => again.unmount());
});

test("the bar's next action acts at once; an action that asks for a value opens the details instead", async () => {
  acted.length = 0;
  const view = renderBanner(run());
  await act(async () => { view.root.findByProps({ "data-testid": "workflow-run-next-action" }).props.onClick(); });
  assert.deepEqual(acted, ["reply"]);
  act(() => view.unmount());
  const asking = run({ actions: [{ key: "retry", label: "Run again", tone: null, input: { name: "iterations", kind: "number", default: 1, min: 1, max: 3, label: "Rounds" } }] });
  const second = renderBanner(asking);
  act(() => second.root.findByProps({ "data-testid": "workflow-run-next-action" }).props.onClick());
  assert.equal(second.root.findAllByProps({ "data-testid": "workflow-run-bar-details" }).length, 1);
  assert.deepEqual(acted, ["reply"], "nothing sent before the value is seen");
  act(() => second.unmount());
});

test("bar model: workflow name, short phase, place", () => {
  assert.equal(runWorkflowName({ workflow_key: "incident-triage" }), "Incident triage");
  // The definition's current name wins over the key (outsider walkthrough: "Epic delivery").
  assert.equal(runWorkflowName({ workflow_key: "epic-delivery", workflow_title: "Story / epic delivery" }),
    "Story / epic delivery");
  assert.equal(runPhaseShort({ status: "running", current_node: { id: "p", title: "Prepare folder", kind: "workspace.prepare" }, phase_position: { index: null, total: 3 } }), "Prepare folder");
  assert.equal(runPhaseShort({ status: "completed", current_node: null, phase_position: { index: null, total: 3 } }), "Phase 3/3");
  assert.equal(runPlaceText({ kind: "device", label: "Studio Mac", online: false }), "on Studio Mac · offline");
  assert.equal(runPlaceText(null), "");
});

test("the turn status shows an outline while loading and ends with a plain sentence and Try again", () => {
  const retries = [];
  const { TurnExecutionStatusCard } = load("chat/run/TurnExecutionStatusCard.tsx", {}, { window: { location: { origin: "http://localhost" } } });
  let view;
  act(() => { view = TestRenderer.create(createElement(TurnExecutionStatusCard, { load: { status: "loading" }, onRetry: () => retries.push(1) })); });
  assert.equal(view.root.findAllByProps({ "data-testid": "loading-state" }).length, 1);
  assert.doesNotMatch(text(view.root), /Loading execution status/);
  act(() => view.update(createElement(TurnExecutionStatusCard, { load: { status: "error" }, onRetry: () => retries.push(1) })));
  assert.match(text(view.root), /Status not available\./);
  const tryAgain = view.root.findAllByType("button").find((button) => text(button) === "Try again");
  act(() => tryAgain.props.onClick());
  assert.equal(retries.length, 1);
  act(() => view.unmount());
});

test("Off / Quick / Thorough are the thinking levels off / light / deep, in one switch", () => {
  assert.deepEqual(THINKING_SWITCH, [{ value: "off", label: "Off" }, { value: "light", label: "Quick" }, { value: "deep", label: "Thorough" }]);
  assert.deepEqual(THINKING_OPTIONS.map((option) => `${option.value}:${option.label}`), ["off:Off", "light:Quick", "deep:Thorough"]);
  assert.equal(getThinkingPillLabel("deep"), "Thorough");
  assert.equal(thinkingLevelLabel("light"), "Quick");
  assert.equal(thinkingLevelLabel("Deep"), "Thorough");
  assert.equal(thinkingLevelLabel("Quick"), "Quick");
  assert.equal(thinkingLevelLabel(""), "Quick");
});

function routingPills() {
  return load("chat/composer/ComposerRoutingPills.tsx", {
    ChatShellIcons: { BrainIcon: () => null },
    ModeOfWorkPill: { ModeOfWorkPill: () => createElement("span", { "data-testid": "workflow-pill" }, "Workflow Automatic") },
    chatOnboarding: { shortRuntimeLabel: (label) => label },
  }).ComposerRoutingPills;
}

function routingProps(overrides = {}) {
  return {
    runOn: createElement("span", { "data-testid": "run-on" }, "Run on: Server"),
    composerDisabled: false, runtimePillLabel: "Automatic · claude-sonnet-5-5", selectedRuntimeTargetId: "",
    setSelectedRuntimeTargetId() {},
    runtimeOptions: [{ value: "", label: "Automatic · claude-sonnet-5-5" }, { value: "t-1", label: "claude-haiku-5-5" }],
    selectedThinkingLevel: "light", setSelectedThinkingLevel() {}, workflowOptions: [], selectedWorkflowKey: "",
    setSelectedWorkflowKey() {}, workflowPillLabel: "Automatic", selectedWorkflowCapability: null, ...overrides,
  };
}

test("the composer has one control per choice: workflow, one model pill, one thinking switch, no Workspace select", () => {
  const ComposerRoutingPills = routingPills();
  const chosen = [];
  let view;
  act(() => { view = TestRenderer.create(createElement(ComposerRoutingPills, routingProps({ setSelectedThinkingLevel: (value) => chosen.push(value) }))); });
  const switchButtons = view.root.findByProps({ role: "group" }).findAllByType("button");
  assert.deepEqual(switchButtons.map((button) => [text(button), button.props["aria-pressed"]]), [["Off", false], ["Quick", true], ["Thorough", false]]);
  assert.ok(switchButtons.every((button) => button.props.title), "every level explains itself");
  act(() => switchButtons[2].props.onClick());
  act(() => switchButtons[0].props.onClick());
  assert.deepEqual(chosen, ["deep", "off"]);
  // One model control, up front, naming the model Automatic uses (from the server's runtime options).
  const models = view.root.findAllByProps({ "aria-label": "Model" });
  assert.equal(models.length, 1);
  assert.deepEqual(models[0].findAllByType("option").map(text), ["Automatic · claude-sonnet-5-5", "claude-haiku-5-5"]);
  const pill = view.root.findByProps({ "data-testid": "composer-model-pill" });
  assert.match(text(pill), /^ModelAutomatic · claude-sonnet-5-5/);
  // No second thinking select, no runtime select under another name, no Workspace select.
  assert.equal(view.root.findAllByProps({ "aria-label": "Thinking mode" }).length, 0);
  assert.equal(view.root.findAllByProps({ "aria-label": "Runtime selection" }).length, 0);
  assert.equal(view.root.findAllByProps({ "aria-label": "Project selection" }).length, 0);
  assert.equal(view.root.findAllByType("select").length, 1);
  // Only the run location waits under Advanced.
  assert.equal(view.root.findAllByProps({ "data-testid": "run-on" }).length, 0, "run location waits under Advanced");
  const advanced = view.root.findAllByType("button").find((button) => text(button) === "Advanced");
  act(() => advanced.props.onClick());
  assert.equal(view.root.findAllByProps({ "data-testid": "run-on" }).length, 1);
  assert.equal(view.root.findAllByType("select").length, 1);
  act(() => view.unmount());
});

test("with a device target the run location stays visible and the Server-only pills hide", () => {
  const ComposerRoutingPills = routingPills();
  let view;
  act(() => { view = TestRenderer.create(createElement(ComposerRoutingPills, routingProps({ hideServerOnly: true }))); });
  assert.equal(view.root.findAllByProps({ "data-testid": "run-on" }).length, 1);
  assert.equal(view.root.findAllByProps({ "aria-label": "Model" }).length, 0);
  assert.equal(view.root.findAllByProps({ "data-testid": "workflow-pill" }).length, 0);
  assert.equal(view.root.findAllByType("button").filter((button) => text(button) === "Advanced").length, 0);
  act(() => view.unmount());
});

test("the composer keeps no explanatory lines: no route bar, no keyboard hints (they are in the chat help)", () => {
  const shell = fs.readFileSync(path.join(SRC, "chat/ComposerShell.tsx"), "utf8");
  const notices = fs.readFileSync(path.join(SRC, "chat/ComposerNotices.tsx"), "utf8");
  const footer = fs.readFileSync(path.join(SRC, "chat/ComposerFooterControls.tsx"), "utf8");
  assert.doesNotMatch(shell, /buildRoutingNotice|routingNotice/);
  assert.doesNotMatch(notices, /RoutingNotice|Workspace route/);
  assert.doesNotMatch(footer, /Shift Enter|for newline|for commands|to mention/);
  const help = fs.readFileSync(path.join(SRC, "../help/chat/index.md"), "utf8");
  assert.match(help, /\*\*Shift Enter\*\* starts a new line/);
  assert.match(help, /switch at the top of the rail/);
});

test("the audit fact is a small lock with its sentence as tooltip, not in the composer footer", () => {
  const { AuditMark, AUDIT_MARK_TITLE } = load("chat/composer/AuditMark.tsx");
  let view;
  act(() => { view = TestRenderer.create(createElement(AuditMark)); });
  const mark = view.root.findByProps({ "data-testid": "chat-audit-mark" });
  assert.equal(mark.props.title, AUDIT_MARK_TITLE);
  assert.equal(text(mark), "Audited");
  const footer = fs.readFileSync(path.join(SRC, "chat/ComposerFooterControls.tsx"), "utf8");
  assert.doesNotMatch(footer, /Policies enforced|All runs audited|AuditMark/);
  assert.match(fs.readFileSync(path.join(SRC, "chat/WorkspaceHeader.tsx"), "utf8"), /<AuditMark \/>/);
  act(() => view.unmount());
});

test("a seat pause says what it needs in words, and its next step shows without opening the details", async () => {
  const { runStatusLabel } = await import("../../src/chat/workflowRun/workflowRunStatus.ts");
  const paused = (code) => run({
    status: "paused", waiting_kind: null, waiting: null, pause_reason: "seat_required",
    pause: { reason: "seat_required", detail: "This run needs a Codex seat. Take it over on your device.", code },
  });
  assert.equal(runStatusLabel(paused("seat_required")), "Paused · Needs a person's seat");
  assert.equal(runStatusLabel(paused("no_seat_device_online")), "Paused · Needs a person's seat · no device with one online");
  const view = renderBanner(paused("seat_required"));
  assert.doesNotMatch(text(view.root.findByProps({ "data-testid": "workflow-run-bar" })), /seat_required/);
  assert.equal(text(view.root.findByProps({ "data-testid": "workflow-run-bar-pause" })),
    "This run needs a Codex seat. Take it over on your device.");
  act(() => view.unmount());
});

test("the header keeps a title a run or a person gave the chat, and names the run's subject over a first prompt", () => {
  const { runChatTitle } = runCardModel;
  const done = run({ status: "completed", actions: [] });
  assert.equal(runChatTitle(done, { title: "PR review bot", titleSource: "run" }), "PR review bot · Done");
  assert.equal(runChatTitle(done, { title: "My review", titleSource: "user" }), "My review · Done");
  assert.equal(runChatTitle(done, { title: "please fix the login", titleSource: "prompt" }), "BRD-12 Login fix · Done");
  assert.equal(runChatTitle(done, null), "BRD-12 Login fix · Done");
});
