// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/chatWorkflowContext.test.mjs
//
// Calm workflow context in chat: an offered workflow is shown once per user turn, later assistant messages of the
// same user turn show none, and a pending workflow decision is never suppressed and keeps its exact governed answer
// payload.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { repeatedTurnMessageIds } from "../../src/chat/run/workflowTurnContext.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const CHAT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/chat");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

// ---- which messages repeat their turn ----------------------------------------------------------

const user = (id) => ({ kind: "message", id, message: { id, role: "user", turnTraceId: null } });
const assistant = (id, trace) => ({ kind: "message", id, message: { id, role: "assistant", turnTraceId: trace } });
const approval = (id) => ({ kind: "approval", id, approval: { id } });
const repeats = (items) => [...repeatedTurnMessageIds(items)].sort();

test("within one user turn only the first traced assistant message shows the context", () => {
  // Progress messages and the final answer of one turn each carry their own trace.
  assert.deepEqual(repeats([user("u1"), assistant("a1", "t1"), assistant("a2", "t2"), approval("p1"), assistant("a3", "t3")]), ["a2", "a3"]);
  assert.deepEqual(repeats([user("u1"), assistant("a1", "t1"), assistant("a2", "t1")]), ["a2"], "a shared trace too");
  assert.deepEqual(repeats([user("u1"), assistant("n1", null), assistant("a1", "t1"), assistant("a2", "t2")]), ["a2"], "an untraced message is not the lead");
});

test("a new user turn shows its context again, for an unchanged or a changed workflow", () => {
  const items = [
    user("u1"), assistant("a1", "t1"), assistant("a2", "t2"),
    user("u2"), assistant("b1", "t3"), assistant("b2", "t4"),
    user("u3"), user("u4"), assistant("c1", "t5"),
  ];
  assert.deepEqual(repeats(items), ["a2", "b2"]);
});

test("edges: paginated start, missing or odd trace ids, user messages and approvals never repeat", () => {
  // The first loaded message of a paginated turn is its lead (earlier siblings not loaded yet).
  assert.deepEqual(repeats([assistant("a1", "t1"), assistant("a2", "t2")]), ["a2"]);
  assert.deepEqual(repeats([
    assistant("n1", null), assistant("n2", null), assistant("n3", ""), assistant("n4", "  "),
    assistant("n5", 7), approval("p1"), user("u1"), user("u2"),
  ]), []);
  assert.deepEqual(repeats([null, { kind: "message", message: null }, assistant(undefined, "t1"), assistant("x", "t1")]), [], "an id-less message is never the lead, so the next one still shows");
});

// ---- the rendered offer and prompt -------------------------------------------------------------

function load(relative) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console,
      // The sources button reads the origin once; it finds no answer body in the test renderer.
      window: { location: { origin: "http://localhost" } },
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
  return loadFile(path.join(CHAT, relative));
}
const { WorkflowProposalOptions } = load("run/WorkflowProposalOptions.tsx");

const proposal = (overrides = {}) => ({
  status: "offered", reasonCode: null, proposalId: "prop-1", workflowKey: "release-notes",
  workflowTitle: "Release notes", confidence: "high", changeCapable: false, ...overrides,
});
const details = (overrides = {}) => ({ proposalId: "prop-1", reason: "The question asks for release changes.", ...overrides });

function render(props) {
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkflowProposalOptions, { disabled: false, ...props })); });
  return view;
}

test("an offered workflow is a quiet optional card; a later message of the same turn shows none", () => {
  const view = render({ proposal: proposal(), details: details() });
  const offer = view.root.findByProps({ "aria-label": "Workflow offer" });
  assert.equal(text(offer), 'Optional: the workflow "Release notes" may fit this request. – The question asks for release changes.');
  const otherProposal = render({ proposal: proposal(), details: details({ proposalId: "prop-other" }) });
  assert.doesNotMatch(text(otherProposal.root.findByProps({ "aria-label": "Workflow offer" })), /release changes/,
    "a reason for another proposal is never shown");
  assert.equal(render({ proposal: proposal(), details: details(), repeatsTurn: true }).toJSON(), null);
});

test("a pending decision is never suppressed and sends its exact governed answer", async () => {
  const chosen = [];
  const onChoose = async (choice) => { chosen.push(choice); };
  const pending = proposal({ status: "needs_confirmation", changeCapable: true });
  const view = render({ proposal: pending, details: details(), repeatsTurn: true, onChoose });
  assert.equal(text(view.root.findByType("strong")), 'Run the workflow "Release notes"?');
  const buttons = view.root.findAllByType("button");
  assert.deepEqual(buttons.map((button) => text(button)), ["Allow once", "Other workflow…", "Deny"]);
  await act(async () => { await buttons[0].props.onClick(); });
  // Copied into this realm: the component builds the payload in its own module realm.
  assert.deepEqual(chosen.map((choice) => ({ ...choice })), [{ decisionKey: "workflow_proposal", value: "apply", label: "Allow once: Release notes", proposalId: "prop-1" }]);

  const disabled = render({ proposal: pending, details: details(), onChoose, disabled: true });
  assert.ok(disabled.root.findAllByType("button").every((button) => button.props.disabled === true));
  const decided = render({ proposal: pending, details: details({ decision: "skip" }), onChoose });
  assert.equal(decided.root.findAllByType("button").length, 0);
  assert.equal(text(decided.root.findByProps({ className: "turn-exec-card__muted" })), "Denied: continued without the workflow.");
});

test("a phased proposal shows its start card: Start sends apply with Run on; Other workflow swaps the workflow", async () => {
  const chosen = [];
  const onChoose = async (choice) => { chosen.push({ ...choice }); };
  const pending = proposal({ status: "needs_confirmation", workflowKey: "spec-writing", workflowTitle: "Spec writing", changeCapable: true });
  const start = {
    workflow_key: "spec-writing", workflow_title: "Spec writing", project_id: "ws-1", jira_project: null, notes: [],
    work_item: { mode: "new", type: "epic", type_label: "Epic", title: "Hello Kitchen", description: "Build it.", key: null, id: null },
    run_on: { options: [{ key: "auto", label: "Automatic" }, { key: "server", label: "Server" }], default: "auto" },
    steps: [{ title: "Read" }, { title: "Write" }], summary: "Start Spec writing for a new Epic 'Hello Kitchen'",
  };
  const workflowOptions = [
    { key: "spec-writing", title: "Spec writing", description: "" },
    { key: "epic-delivery", title: "Story / epic delivery", description: "Build one story" },
  ];
  const view = render({ proposal: pending, details: details({ phased: true, start, decision: null }), onChoose, workflowOptions });
  assert.equal(text(view.root.findByType("h3")), "Start Spec writing for a new Epic 'Hello Kitchen'");
  assert.equal(view.root.findAll((node) => node.props["aria-label"] === "Workflow suggestion decision").length, 0, "one set of buttons");
  // The first select is Run on; the Model select follows it.
  act(() => { view.root.findAllByType("select")[0].props.onChange({ target: { value: "server" } }); });
  const button = (value) => view.root.find((node) => node.type === "button" && node.props["data-decision-value"] === value);
  await act(async () => { await button("apply").props.onClick(); });
  assert.deepEqual(chosen.at(-1), { decisionKey: "workflow_proposal", value: "apply", label: "Start: Spec writing", proposalId: "prop-1", inline: true, runOn: "server" });

  act(() => { button("other").props.onClick(); });
  const options = view.root.findAll((node) => node.type === "button" && node.props["data-workflow-key"]);
  assert.deepEqual(options.map((node) => node.props["data-workflow-key"]), ["epic-delivery"], "the current workflow is not offered");
  await act(async () => { await options[0].props.onClick(); });
  assert.deepEqual(chosen.at(-1), { decisionKey: "workflow_proposal", value: "other", label: "Other workflow: Story / epic delivery", proposalId: "prop-1", workflowKey: "epic-delivery" });

  const started = render({ proposal: pending, onChoose, details: details({ phased: true, start, decision: "apply",
    started: { href: "/chat?session_id=s-2", work_item_key: "CHEF-14" } }) });
  assert.equal(text(started.root.findByProps({ "data-testid": "workflow-start-open-run" })), "Open the run · CHEF-14");
  assert.equal(started.root.findAll((node) => node.type === "button").length, 0);
});

// ---- the message content passes the turn context through --------------------------------------

test("message content shows the offered workflow on the turn's first message only", async () => {
  const { MessageBubbleContent } = load("messageBubbleContent.tsx");
  const { parseTurnExecutionSummary } = await import("../../src/chat/run/turnExecutionSummaryParse.ts");
  const { buildSummaryFixture } = await import("../e2e/turnExecutionSummaryFixtures.mjs");
  const summary = parseTurnExecutionSummary(buildSummaryFixture({
    traceId: "trace-1", sessionId: "session-1", reasonCode: "runtime_finished",
    workflowProposal: {
      status: "offered", reason_code: null, proposal_id: "prop-1",
      workflow_key: "release-notes", workflow_title: "Release notes", confidence: "high", change_capable: false,
    },
  }));
  assert.equal(summary?.workflowProposal?.status, "offered");
  const parsed = { status: "ready", summary };
  const noop = () => {};
  const base = {
    message: { id: "a1", role: "assistant", content: "Answer text", turnTraceId: "trace-1", toolEvents: [] },
    isUser: false, isThinking: false, toolOnlyAssistant: false, displayContent: "Answer text", theme: "light",
    executionSummary: parsed, retryExecutionSummary: noop, workflowProposal: details(),
    actionsDisabled: false, onWorkflowDecision: async () => {}, referencedArtifacts: [], retryPrompt: null,
    effectiveTurnTrace: null, performance: null, copied: false, reused: false, speaking: false, traceOpen: false,
    timestamp: "", participantTitle: "Assistant", participantSupportLabel: "", hasTurnTrace: false,
    thinkingOpen: false, thinkingLoading: false, performanceOpen: false, performanceLoading: false,
    traceLoading: false, thinkingText: "", thinkingUnavailable: false, performanceUnavailable: false,
    feedbackDisabled: true, retrying: false,
  };
  const handlers = Object.fromEntries([
    "setThinkingOpen", "setPerformanceOpen", "setTraceOpen", "toggleThinking", "togglePerformance", "toggleTrace",
    "onPreviewArtifact", "onSubmitFeedback", "triggerRetryFromToolEvent", "copyMessage", "startEditMessage",
    "reuseMessage", "triggerRetryFromHere", "triggerRetryPrompt", "toggleSpeak", "setTraceClosed",
  ].map((name) => [name, noop]));
  const props = (repeatsTurnContext) => ({ ...handlers, ...base, repeatsTurnContext });
  const notes = (repeatsTurnContext) => {
    let view;
    act(() => { view = TestRenderer.create(createElement(MessageBubbleContent, { ...props(repeatsTurnContext) })); });
    const found = view.root.findAll((node) => node.type === "section" && node.props["aria-label"] === "Workflow offer").map(text);
    act(() => view.unmount());
    return found;
  };
  assert.deepEqual(notes(false), ['Optional: the workflow "Release notes" may fit this request. – The question asks for release changes.']);
  assert.deepEqual(notes(true), [], "a later message of the same turn");
});
