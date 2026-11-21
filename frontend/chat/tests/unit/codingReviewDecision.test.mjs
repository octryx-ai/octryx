// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/codingReviewDecision.test.mjs
//
// Explicit review decisions: the panel sends the exact plan id/version and the whole Change
// Unit (or the whole Work Item) the reviewer sees, refuses duplicate submissions, keeps the input on
// error and never applies a late response to another selection. File feedback offers no
// "Review decision", and the panel stays reachable without planned files.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as model from "../../src/chat/coding/codingReviewDecisionModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const CODING_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/chat/coding");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

function makeLoader(stubs) {
  const cache = new Map();
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name === suffix || name.endsWith(suffix));
    if (stub) return stub[1];
    if (name.startsWith(".")) {
      const base = path.resolve(dir, name);
      for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return load(base + ext);
    }
    return require(name);
  };
  const load = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      // ES2020 like the app build: an ES5 target would turn `[...new Set()]` into an empty copy.
      compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, { module, exports: module.exports, console, require: (name) => resolve(name, path.dirname(file)) });
    return module.exports;
  };
  return (relative) => load(path.join(CODING_DIR, relative));
}

const apiCalls = [];
const loadModule = makeLoader({
  "/work/workApi": { createCodingReviewEvent: async (...args) => { apiCalls.push(args); return { id: "api" }; } },
  "@monaco-editor/react": { Editor: () => null, DiffEditor: () => null },
});
const { CodingReviewDecisionPanel } = loadModule("CodingReviewDecisionPanel.tsx");

const plan = { id: "plan-2", version: 2, status: "approved" };
const unit = (id, extra = {}) => ({
  id, repository_name: `repo-${id}`, branch_name: `feature/${id}`, status: "planned", updated_at: `2026-10-04T10:00:0${id.length}`, ...extra,
});

function deferred() {
  let resolve; let reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

function controls(root) {
  const selects = root.findAll((node) => node.type === "select");
  return {
    subject: selects[0],
    decision: selects[1],
    note: root.findByType("textarea"),
    button: root.find((node) => node.type === "button" && /Record decision|Recording/.test(text(node))),
  };
}

// ---- model ----------------------------------------------------------------------------------

test("subjects are the active Change Units, or the whole Work Item without any", () => {
  assert.deepEqual(model.reviewDecisionSubjects([]),
    [{ value: model.WHOLE_ITEM_SUBJECT, label: "Whole Work Item", changeUnitId: null, marker: null }]);
  const subjects = model.reviewDecisionSubjects([unit("a"), unit("b", { status: "superseded" })]);
  assert.deepEqual(subjects.map((entry) => entry.changeUnitId), ["a"], "superseded units are not reviewable");
  assert.match(subjects[0].label, /^Change Unit repo-a · feature\/a$/);
});

test("the payload carries the displayed plan id/version and the whole subject; incomplete input builds nothing", () => {
  const [subject] = model.reviewDecisionSubjects([unit("a")]);
  assert.deepEqual(model.buildReviewDecisionPayload({ plan, subject, decision: "approved", note: "  ok " }), {
    event_type: "review_decision", decision: "approved", change_plan_id: "plan-2", expected_plan_version: 2,
    change_unit_id: "a", expected_change_unit_marker: "2026-10-04T10:00:01", file_path: "", body: "ok",
    metadata: { source: "coding_review_decision_panel" },
  });
  const [unknownState] = model.reviewDecisionSubjects([unit("a", { updated_at: null })]);
  assert.equal(model.buildReviewDecisionPayload({ plan, subject: unknownState, decision: "approved", note: "" }), null,
    "a unit decision is never sent without the displayed unit state");
  assert.equal(model.buildReviewDecisionPayload({ plan, subject, decision: "", note: "" }), null);
  assert.equal(model.buildReviewDecisionPayload({ plan: null, subject, decision: "approved", note: "" }), null);
  assert.equal(model.buildReviewDecisionPayload({ plan, subject: null, decision: "approved", note: "" }), null);
});

test("recorded decisions come only from the server record of this plan; other feedback is not a decision", () => {
  const events = [
    { id: "legacy", event_type: "review_decision", status: "approved", metadata: { source: "x" }, created_at: "2026-10-04T10:00:00" },
    { id: "old-plan", metadata: { review_decision_record: { decision: "approved", change_plan_id: "plan-1" } } },
    { id: "now", created_at: "2026-10-04T11:00:00", created_by: "u1",
      metadata: { review_decision_record: { decision: "changes_requested", change_plan_id: "plan-2", change_unit_id: "a",
        actor_label: "Alice Reviewer" } } },
    { id: "unlabelled", created_at: "2026-10-04T10:30:00", created_by: "7f3c2a1e-0000",
      metadata: { review_decision_record: { decision: "approved", change_plan_id: "plan-2", change_unit_id: "a" } } },
    { id: "bad", metadata: { review_decision_record: { decision: "lgtm", change_plan_id: "plan-2" } } },
  ];
  assert.deepEqual(model.decisionsForPlan(events, "plan-2").map((entry) => [entry.id, entry.decision, entry.changeUnitId, entry.reviewer]),
    [["now", "changes_requested", "a", "Alice Reviewer"], ["unlabelled", "approved", "a", "Reviewer"]],
    "the server label is shown; a missing label never falls back to the raw user id");
});

// ---- the panel --------------------------------------------------------------------------------

function render(props) {
  let view;
  act(() => { view = TestRenderer.create(createElement(CodingReviewDecisionPanel, props)); });
  return view;
}

test("recording sends the exact payload for the chosen unit and reports the created decision", async () => {
  const sent = [];
  const recorded = [];
  const submit = async (workItemId, payload) => { sent.push([workItemId, payload]); return { id: "decision-1", metadata: {} }; };
  const view = render({ workItemId: "item-1", latestPlan: plan, changeUnits: [unit("a"), unit("b")], events: [], onRecorded: (event) => recorded.push(event), submit });
  let ui = controls(view.root);
  assert.equal(ui.button.props.disabled, true, "a subject and a decision are required");
  assert.match(text(view.root), /plan v2 · approved/, "the scope is the heading; the explanation is in the help");
  assert.doesNotMatch(text(view.root), /not bound to a pull-request commit/);
  act(() => ui.subject.props.onChange({ target: { value: "b" } }));
  act(() => controls(view.root).decision.props.onChange({ target: { value: "approved" } }));
  act(() => controls(view.root).note.props.onChange({ target: { value: "Reviewed the unit." } }));
  ui = controls(view.root);
  assert.equal(ui.button.props.disabled, false);
  await act(async () => { await ui.button.props.onClick(); });
  // Compared as JSON: the payload object comes from the component's module realm.
  assert.equal(JSON.stringify(sent), JSON.stringify([["item-1", {
    event_type: "review_decision", decision: "approved", change_plan_id: "plan-2", expected_plan_version: 2,
    change_unit_id: "b", expected_change_unit_marker: "2026-10-04T10:00:01", file_path: "", body: "Reviewed the unit.",
    metadata: { source: "coding_review_decision_panel" },
  }]]));
  assert.deepEqual(recorded.map((event) => event.id), ["decision-1"]);
  assert.equal(controls(view.root).decision.props.value, "", "the decision is cleared after recording");
  act(() => view.unmount());
});

test("a Work Item without units is reviewed as a whole, without a file", async () => {
  const sent = [];
  const view = render({ workItemId: "item-1", latestPlan: plan, changeUnits: [], events: [], onRecorded: () => {},
    submit: async (_id, payload) => { sent.push(payload); return { id: "d" }; } });
  const ui = controls(view.root);
  assert.equal(ui.subject.props.value, model.WHOLE_ITEM_SUBJECT);
  assert.match(text(ui.subject), /Whole Work Item/);
  act(() => ui.decision.props.onChange({ target: { value: "rejected" } }));
  await act(async () => { await controls(view.root).button.props.onClick(); });
  assert.equal(sent[0].change_unit_id, null);
  assert.equal(sent[0].expected_change_unit_marker, null);
  assert.equal(sent[0].file_path, "");
  act(() => view.unmount());
});

test("without a plan nothing can be recorded", () => {
  const view = render({ workItemId: "item-1", latestPlan: null, changeUnits: [unit("a")], events: [], onRecorded: () => {} });
  assert.match(text(view.root), /No Change Plan is attached/);
  const ui = controls(view.root);
  assert.equal(ui.decision.props.disabled, true);
  assert.equal(ui.button.props.disabled, true);
  act(() => view.unmount());
});

test("a second click while a decision is pending sends nothing more", async () => {
  const pending = deferred();
  let calls = 0;
  const view = render({ workItemId: "item-1", latestPlan: plan, changeUnits: [unit("a")], events: [], onRecorded: () => {},
    submit: () => { calls += 1; return pending.promise; } });
  act(() => controls(view.root).decision.props.onChange({ target: { value: "approved" } }));
  const button = controls(view.root).button;
  act(() => { void button.props.onClick(); });
  act(() => { void button.props.onClick(); });
  assert.equal(calls, 1);
  assert.equal(controls(view.root).button.props.disabled, true);
  await act(async () => { pending.resolve({ id: "d" }); });
  act(() => view.unmount());
});

test("an error keeps the decision and note so the reviewer can retry", async () => {
  const view = render({ workItemId: "item-1", latestPlan: plan, changeUnits: [unit("a")], events: [], onRecorded: () => {},
    submit: async () => { throw new Error("The plan changed since it was displayed; reload and review the latest plan version"); } });
  act(() => controls(view.root).decision.props.onChange({ target: { value: "changes_requested" } }));
  act(() => controls(view.root).note.props.onChange({ target: { value: "Fix the migration." } }));
  await act(async () => { await controls(view.root).button.props.onClick(); });
  assert.match(text(view.root.findByProps({ role: "alert" })), /plan changed/);
  assert.equal(controls(view.root).decision.props.value, "changes_requested");
  assert.equal(controls(view.root).note.props.value, "Fix the migration.");
  act(() => view.unmount());
});

test("a late response for another Work Item is not applied to the new selection", async () => {
  const pending = deferred();
  const recorded = [];
  const props = { latestPlan: plan, changeUnits: [unit("a")], events: [], onRecorded: (event) => recorded.push(event), submit: () => pending.promise };
  let view;
  act(() => { view = TestRenderer.create(createElement(CodingReviewDecisionPanel, { ...props, workItemId: "item-1" })); });
  act(() => controls(view.root).decision.props.onChange({ target: { value: "approved" } }));
  act(() => { void controls(view.root).button.props.onClick(); });
  act(() => view.update(createElement(CodingReviewDecisionPanel, { ...props, workItemId: "item-2" })));
  await act(async () => { pending.resolve({ id: "late" }); });
  await flush();
  assert.deepEqual(recorded, [], "the decision for item-1 is not shown on item-2");
  assert.equal(controls(view.root).decision.props.value, "", "item-2 starts clean");
  act(() => view.unmount());
});

test("a re-render with an equal but new unit list keeps what the reviewer typed", () => {
  const props = { workItemId: "item-1", latestPlan: plan, events: [], onRecorded: () => {} };
  let view;
  act(() => { view = TestRenderer.create(createElement(CodingReviewDecisionPanel, { ...props, changeUnits: [] })); });
  act(() => controls(view.root).note.props.onChange({ target: { value: "typing" } }));
  act(() => view.update(createElement(CodingReviewDecisionPanel, { ...props, changeUnits: [] })));
  assert.equal(controls(view.root).note.props.value, "typing");
  act(() => view.unmount());
});

test("a unit whose state is not loaded cannot be decided, and says so", () => {
  const view = render({ workItemId: "item-1", latestPlan: plan, changeUnits: [unit("a", { updated_at: null })], events: [], onRecorded: () => {} });
  act(() => controls(view.root).decision.props.onChange({ target: { value: "approved" } }));
  assert.equal(controls(view.root).button.props.disabled, true);
  assert.match(text(view.root), /state is not loaded; reload before recording/);
  act(() => view.unmount());
});

test("recorded decisions show the reviewer label the server stored", () => {
  const events = [{ id: "e1", created_at: "2026-10-04T11:00:00",
    metadata: { review_decision_record: { decision: "approved", change_plan_id: "plan-2", change_unit_id: "a", actor_label: "Alice Reviewer" } } }];
  const view = render({ workItemId: "item-1", latestPlan: plan, changeUnits: [unit("a")], events, onRecorded: () => {} });
  const list = view.root.findByProps({ "aria-label": "Recorded review decisions" });
  assert.match(text(list), /^Alice Reviewer · Approve · Change Unit repo-a/);
  act(() => view.unmount());
});

test("a late error for a plan that is no longer displayed is not shown", async () => {
  const pending = deferred();
  const props = { workItemId: "item-1", changeUnits: [unit("a")], events: [], onRecorded: () => {}, submit: () => pending.promise };
  let view;
  act(() => { view = TestRenderer.create(createElement(CodingReviewDecisionPanel, { ...props, latestPlan: plan })); });
  act(() => controls(view.root).decision.props.onChange({ target: { value: "approved" } }));
  act(() => { void controls(view.root).button.props.onClick(); });
  act(() => view.update(createElement(CodingReviewDecisionPanel, { ...props, latestPlan: { ...plan, id: "plan-3", version: 3 } })));
  await act(async () => { pending.reject(new Error("The plan changed since it was displayed")); });
  await flush();
  assert.equal(view.root.findAll((node) => node.props?.role === "alert").length, 0, "plan v3 does not show v2's error");
  act(() => view.unmount());
});

test("a response after the panel unmounted does nothing", async () => {
  const pending = deferred();
  const recorded = [];
  const view = render({ workItemId: "item-1", latestPlan: plan, changeUnits: [unit("a")], events: [],
    onRecorded: (event) => recorded.push(event), submit: () => pending.promise });
  act(() => controls(view.root).decision.props.onChange({ target: { value: "approved" } }));
  act(() => { void controls(view.root).button.props.onClick(); });
  act(() => view.unmount());
  await act(async () => { pending.resolve({ id: "late" }); });
  await flush();
  assert.deepEqual(recorded, []);
});

// ---- the Changes view keeps file feedback only ---------------------------------------------------

test("Changes has no decision form, offers no approval type and points to Reviews", () => {
  const { CodingReviewWorkspace } = loadModule("CodingReviewWorkspace.tsx");
  const session = { id: "item-1", sourceKey: "OPS-2", workItem: { source_fields: {} }, repositories: [], branches: [] };
  const opened = [];
  const withFiles = { changeUnits: [unit("a", { expected_paths: ["src/app.py"] })], reviewEventsPayload: { items: [] } };
  let view;
  act(() => {
    view = TestRenderer.create(createElement(CodingReviewWorkspace, {
      session, detail: withFiles, latestPlan: plan, onOpenReviews: () => opened.push("reviews"),
    }));
  });
  assert.equal(view.root.findAll((node) => node.props?.["aria-label"] === "Review decision").length, 0);
  const feedbackType = view.root.findByProps({ "aria-label": "Agent feedback context" })
    .findAll((node) => node.type === "select")
    .find((node) => node.findAll((child) => child.type === "option").some((option) => text(option) === "Inline comment"));
  assert.deepEqual(feedbackType.findAll((node) => node.type === "option").map(text), ["Inline comment", "Manual edit", "Diagnostic"]);
  act(() => view.root.find((node) => node.type === "button" && text(node) === "Open Reviews").props.onClick());
  assert.deepEqual(opened, ["reviews"]);
  act(() => view.unmount());
});
