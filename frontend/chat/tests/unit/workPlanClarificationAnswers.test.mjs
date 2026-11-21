// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workPlanClarificationAnswers.test.mjs
//
// A reviewer answers the exact newest plan version's open questions and gets a revised version.
// The request is bound to that version, partial answers are explicit, nothing is truncated, a failure
// keeps every answer, a version switch never sends answers to another id, and a revised version shows
// the answers it came from. The backend is faked; real runtime and PostgreSQL state are judged live.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as clarification from "../../src/chat/work/workPlanClarificationModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const WORK_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/chat/work");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const buttons = (root, pattern) => root.findAll((node) => node.type === "button" && pattern.test(text(node)));
const answerFields = (root) => root.findAll((node) => node.type === "textarea" && /-answer-\d+$/.test(node.props.id || ""));
const flush = () => act(async () => { for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); });
const QUESTIONS = ["Which environment?", "Who owns rollback?", "Feature flag needed?"];

// Loads real modules from src/chat/work (transpiled), replacing only the given suffixes.
function makeLoader(stubs) {
  const cache = new Map();
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name.endsWith(suffix));
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
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, window: globalThis.window, document: globalThis.document,
      URL, URLSearchParams, console, require: (name) => resolve(name, path.dirname(file)),
    });
    return module.exports;
  };
  return (relative) => load(path.join(WORK_DIR, relative));
}

function plan(id, version, status, extra = {}) {
  return {
    id, work_item_id: "item-1", workflow_id: null, supersedes_plan_id: null, version, status, title: `Plan ${id}`,
    understood_request: `Request of ${id}`, assumptions: [], open_questions: [], affected_repositories: [], change_units: [],
    proposed_branches: [], planned_files: [], validation_plan: [], security_risks: [], reviewer_recommendations: [],
    required_approvals: [], expected_prs: [], rollback_plan: "", trace_refs: [], evidence: {}, jira_sync_preview: {},
    created_by: "u1", created_at: "2026-10-04T10:00:00", updated_at: `2026-10-04T10:0${version}:00`, ...extra,
  };
}

const answered = (sourceId, sourceVersion) => ({
  clarification: {
    source_plan_id: sourceId, source_version: sourceVersion, answered_by: "u1", answered_by_label: "Ada Planner",
    answered_at: "2026-10-04T10:05:00",
    answers: [{ question_index: 0, question: QUESTIONS[0], answer: "Staging only." }], unanswered_question_indexes: [1, 2],
  },
});

function deferred() {
  let resolve; let reject;
  const promise = new Promise((done, fail) => { resolve = done; reject = fail; });
  return { promise, resolve, reject };
}

// An in-memory plan backend; `answer` decides how the answers request ends.
function backend(initial, answer) {
  const state = { plans: [...initial], answers: [], generated: 0 };
  const workApi = {
    loadWorkItemChangePlans: async () => [...state.plans].sort((a, b) => b.version - a.version),
    decideWorkChangePlan: async () => ({}),
    generateWorkItemLlmWorkPlan: async () => {
      state.generated += 1;
      const newest = Math.max(...state.plans.map((row) => row.version));
      state.plans = state.plans.map((row) => (row.version === newest ? { ...row, status: "superseded" } : row));
      const created = plan(`plan-v${newest + 1}`, newest + 1, "needs_clarification", { open_questions: ["A new question?"] });
      state.plans.push(created);
      return created;
    },
    answerWorkPlanClarifications: async (args) => {
      state.answers.push(args);
      return answer(args, state);
    },
  };
  return { state, workApi };
}

function revise(args, state) {
  const source = state.plans.find((row) => row.id === args.changePlanId);
  state.plans = state.plans.map((row) => (row.id === source.id ? { ...row, status: "superseded" } : row));
  const created = plan(`plan-v${source.version + 1}`, source.version + 1, "ready_for_review",
    { supersedes_plan_id: source.id, evidence: answered(source.id, source.version) });
  state.plans.push(created);
  return created;
}

function render(fake, props = {}) {
  globalThis.window = { location: { origin: "https://octryx.example" } };
  const Plans = makeLoader({ "/workApi": fake.workApi, "/workChangePlanApi": fake.workApi, "/workCodingApi": fake.workApi })("WorkChangePlans.tsx").WorkChangePlans;
  const selected = [];
  const element = (extra) => createElement(Plans, { item: { id: "item-1" }, workflows: [], onSelectPlan: (id) => selected.push(id), ...props, ...extra });
  let view;
  act(() => { view = TestRenderer.create(element()); });
  return { view, selected, rerender: (extra) => act(() => view.update(element(extra))) };
}

const type = (field, value) => act(() => field.props.onChange({ target: { value } }));

// ---- pure contract ------------------------------------------------------------------------------

test("only the newest open version with questions can be answered", () => {
  const newest = plan("v2", 2, "needs_clarification", { open_questions: QUESTIONS });
  assert.equal(clarification.isAnswerable(newest, newest), true);
  assert.equal(clarification.isAnswerable(plan("v1", 1, "needs_clarification", { open_questions: QUESTIONS }), newest), false);
  assert.equal(clarification.isAnswerable({ ...newest, status: "approved" }, { ...newest, status: "approved" }), false);
  assert.equal(clarification.isAnswerable({ ...newest, open_questions: [] }, { ...newest, open_questions: [] }), false);
});

test("the body binds trimmed partial answers to exact questions and refuses instead of truncating", () => {
  const source = plan("v2", 2, "needs_clarification", { open_questions: QUESTIONS });
  const partial = clarification.checkClarificationDraft(source, ["  Staging only. ", "", "No."]);
  assert.deepEqual(partial.payload, {
    expected_latest_version: 2,
    answers: [{ question_index: 0, question: QUESTIONS[0], answer: "Staging only." }, { question_index: 2, question: QUESTIONS[2], answer: "No." }],
  });
  assert.deepEqual(partial.unanswered, [1]);
  assert.equal(clarification.checkClarificationDraft(source, [" ", "", undefined]).payload, null, "at least one answer");
  const long = clarification.checkClarificationDraft(source, ["x".repeat(100001)]);
  assert.equal(long.payload, null);
  assert.match(long.errors[0], /100000 characters \(now 100001\)/);
  const many = plan("v9", 9, "needs_clarification", { open_questions: Array.from({ length: 7 }, (_, i) => `Q${i}`) });
  const big = clarification.checkClarificationDraft(many, Array.from({ length: 7 }, () => "y".repeat(20000)));
  assert.equal(big.totalError, null, "no limit on all answers together");
  assert.equal(big.payload.answers.length, 7);
});

test("only the server's transport guards remain: 1000 answers, each 100000; long questions are fine", () => {
  const questions = Array.from({ length: 1001 }, (_, i) => `Question ${i + 1}?`);
  const many = plan("v4", 4, "needs_clarification", { open_questions: questions });
  const over = clarification.checkClarificationDraft(many, questions.map(() => "ok"));
  assert.equal(over.payload, null);
  assert.match(over.totalError, /At most 1000 answers can be sent at once \(now 1001\)\. Clear 1 of them here/);
  assert.equal(over.answers.length, 1001, "nothing is dropped from the draft");
  const allowed = clarification.checkClarificationDraft(many, questions.map((_, i) => (i < 1000 ? "ok" : "")));
  assert.equal(allowed.payload.answers.length, 1000);
  const longQuestion = plan("v5", 5, "needs_clarification", { open_questions: ["q".repeat(8001), "Short?"] });
  assert.equal(clarification.checkClarificationDraft(longQuestion, ["yes", ""]).payload.answers.length, 1);
});

test("retained answers are read only from a complete evidence record", () => {
  const revised = plan("v3", 3, "ready_for_review", { evidence: answered("v2", 2) });
  assert.deepEqual(clarification.retainedClarification(revised), {
    sourcePlanId: "v2", sourceVersion: 2, answeredAt: "2026-10-04T10:05:00", answeredByLabel: "Ada Planner", answeredBy: "u1",
    answers: [{ question_index: 0, question: QUESTIONS[0], answer: "Staging only." }], unanswered: [1, 2],
  });
  for (const broken of [null, [], { source_plan_id: "v2", answers: [] }, { source_plan_id: "v2", source_version: 2, answers: [{ answer: 1 }] },
    { source_version: 2, answers: answered("v2", 2).clarification.answers }]) {
    assert.equal(clarification.retainedClarification(plan("x", 1, "draft", { evidence: { clarification: broken } })), null);
  }
});

test("refusal codes become readable text that says the answers are kept", () => {
  assert.match(clarification.clarificationErrorText("stale_plan_version: Version 2 is not the newest version"), /no longer the newest.*kept/);
  assert.match(clarification.clarificationErrorText("plan_generation_unavailable: No admitted runtime"), /Nothing was saved and your answers are kept/);
  assert.equal(clarification.clarificationErrorText("Service Unavailable"), "Service Unavailable. Your answers are kept.");
  assert.equal(clarification.clarificationErrorText("other_code: Something else."), "Something else. Your answers are kept.");
});

// ---- the plan detail ---------------------------------------------------------------------------

test("answers are sent once for the exact version and the revised version shows them", async () => {
  const gate = deferred();
  const fake = backend([plan("plan-v1", 1, "superseded"), plan("plan-v2", 2, "needs_clarification", { open_questions: QUESTIONS })],
    async (args, state) => { await gate.promise; return revise(args, state); });
  const { view, selected } = render(fake);
  await flush();
  const fields = answerFields(view.root);
  assert.equal(fields.length, 3, "one labelled field per open question");
  assert.equal(buttons(view.root, /^Generate v3 from answers$/)[0].props.disabled, true, "nothing to send yet");
  type(fields[0], "Staging only.");
  type(answerFields(view.root)[2], "No.");
  assert.match(text(view.root), /2 of 3 answered · unanswered: Q2/);

  act(() => { buttons(view.root, /^Generate v3 from answers$/)[0].props.onClick(); });
  act(() => { buttons(view.root, /^Working\.\.\.$/)[0].props.onClick(); });
  assert.equal(fake.state.answers.length, 1, "a double click sends once");
  // The component runs in its own realm: compare plain data.
  assert.deepEqual(JSON.parse(JSON.stringify(fake.state.answers[0])), {
    changePlanId: "plan-v2", expectedLatestVersion: 2,
    answers: [{ question_index: 0, question: QUESTIONS[0], answer: "Staging only." }, { question_index: 2, question: QUESTIONS[2], answer: "No." }],
  });
  for (const field of answerFields(view.root)) assert.equal(field.props.disabled, true);
  for (const label of [/^New version$/, /^Approve v2$/, /^Clarify$/]) assert.equal(buttons(view.root, label)[0].props.disabled, true, String(label));

  await act(async () => { gate.resolve(); });
  await flush();
  assert.deepEqual(selected, ["plan-v3"]);
  const shown = text(view.root);
  assert.match(shown, /Version 3/);
  assert.match(shown, /Answers from v2/);
  assert.match(shown, /Q1\. Which environment\? — Staging only\./);
  assert.match(shown, /2 questions were left unanswered/);
  act(() => view.unmount());
  delete globalThis.window;
});

test("a refused request keeps every answer and can be retried", async () => {
  const fake = backend([plan("plan-v2", 2, "needs_clarification", { open_questions: QUESTIONS })], async () => {
    throw new Error("stale_plan_version: Version 2 is not the newest version (newest is v3).");
  });
  const { view } = render(fake);
  await flush();
  type(answerFields(view.root)[1], "The platform team.");
  await act(async () => { buttons(view.root, /^Generate v3 from answers$/)[0].props.onClick(); });
  await flush();
  assert.match(text(view.root), /no longer the newest one\. Your answers are kept/);
  assert.equal(answerFields(view.root)[1].props.value, "The platform team.");
  assert.equal(buttons(view.root, /^Generate v3 from answers$/)[0].props.disabled, false, "retry is possible");
  act(() => view.unmount());
  delete globalThis.window;
});

test("switching versions keeps answers per version and never sends them to another id", async () => {
  const fake = backend([plan("plan-v1", 1, "needs_clarification", { open_questions: ["Old question?"] }),
    plan("plan-v2", 2, "needs_clarification", { open_questions: QUESTIONS })], revise);
  const { view, rerender } = render(fake, { focusPlanId: "plan-v2" });
  await flush();
  type(answerFields(view.root)[0], "Staging only.");

  rerender({ focusPlanId: "plan-v1" });
  assert.equal(answerFields(view.root).length, 0, "an older version is read-only");
  assert.match(text(view.root), /Only the newest version can be answered \(v2\)/);
  rerender({ focusPlanId: "plan-v2" });
  assert.equal(answerFields(view.root)[0].props.value, "Staging only.", "the draft of v2 is still there");

  // A new version replaces v2 before the answers were sent: they stay visible, unsent.
  await act(async () => { buttons(view.root, /^New version$/)[0].props.onClick(); });
  await flush();
  rerender({ focusPlanId: "plan-v3" });
  assert.deepEqual(answerFields(view.root).map((field) => field.props.value), [""], "v3 starts empty");
  rerender({ focusPlanId: "plan-v2" });
  assert.equal(answerFields(view.root).length, 0);
  assert.match(text(view.root), /Your unsent answers for v2 are kept/);
  assert.match(text(view.root), /Q1\. Staging only\./);
  assert.equal(fake.state.answers.length, 0, "nothing was sent to any version");
  act(() => view.unmount());
  delete globalThis.window;
});

test("a reloaded revised version shows its retained answers; an approved version offers no answer form", async () => {
  const fake = backend([plan("plan-v2", 2, "superseded", { open_questions: QUESTIONS }),
    plan("plan-v3", 3, "approved", { open_questions: ["Still open?"], evidence: answered("plan-v2", 2) })], revise);
  const { view } = render(fake);
  await flush();
  assert.ok(view.root.findByProps({ "data-testid": "clarification-retained" }));
  assert.match(text(view.root), /Answers from v2/);
  assert.equal(answerFields(view.root).length, 0);
  assert.match(text(view.root), /This version is decided; its questions can no longer be answered\./);
  act(() => view.unmount());
  delete globalThis.window;
});

test("21 answers are sent in one request; no old limit of 20 is left", async () => {
  const questions = Array.from({ length: 21 }, (_, i) => `Question ${i + 1}?`);
  const fake = backend([plan("plan-v1", 1, "needs_clarification", { open_questions: questions })], revise);
  const { view } = render(fake);
  await flush();
  for (const field of answerFields(view.root)) type(field, "An answer.");
  assert.doesNotMatch(text(view.root), /At most/);
  assert.equal(buttons(view.root, /^Generate v2 from answers$/)[0].props.disabled, false);
  act(() => view.unmount());
  delete globalThis.window;
});

test("retained answers name the recorded actor; without a label the id is only a detail", async () => {
  const unlabeled = answered("plan-v1", 1);
  delete unlabeled.clarification.answered_by_label;
  for (const [evidence, heading, detail] of [
    [answered("plan-v1", 1), /Answered by Ada Planner · /, null],
    [unlabeled, /Answered by a recorded user · /, /Recorded user id: u1/],
  ]) {
    const fake = backend([plan("plan-v1", 1, "superseded", { open_questions: QUESTIONS }),
      plan("plan-v2", 2, "ready_for_review", { evidence })], revise);
    const { view } = render(fake);
    await flush();
    const shown = text(view.root.findByProps({ "data-testid": "clarification-retained" }));
    assert.match(shown, heading);
    if (detail) assert.match(shown, detail); else assert.doesNotMatch(shown, /Recorded user id/);
    act(() => view.unmount());
    delete globalThis.window;
  }
});

// Two items: the answers request for item A resolves after the view moved to item B.
function twoItemBackend(outcome) {
  const gate = deferred();
  const plans = {
    "item-a": [plan("plan-a1", 1, "needs_clarification", { work_item_id: "item-a", open_questions: QUESTIONS })],
    "item-b": [plan("plan-b1", 1, "needs_clarification", { work_item_id: "item-b", open_questions: ["B question?"] })],
  };
  const loads = [];
  const answers = [];
  const workApi = {
    loadWorkItemChangePlans: async (itemId) => { loads.push(itemId); return [...plans[itemId]]; },
    decideWorkChangePlan: async () => ({}),
    generateWorkItemLlmWorkPlan: async () => ({}),
    answerWorkPlanClarifications: async (args) => {
      answers.push(args);
      await gate.promise;
      if (outcome === "error") throw new Error("plan_generation_unavailable: No admitted runtime produced a Work Plan.");
      plans["item-a"].push(plan("plan-a2", 2, "ready_for_review", { work_item_id: "item-a" }));
      return plans["item-a"].at(-1);
    },
  };
  return { gate, loads, answers, workApi };
}

for (const outcome of ["success", "error"]) {
  test(`a late ${outcome} for the previous item never reloads, reselects or clears the current item`, async () => {
    const fake = twoItemBackend(outcome);
    const changed = [];
    globalThis.window = { location: { origin: "https://octryx.example" } };
    const Plans = makeLoader({ "/workApi": fake.workApi, "/workChangePlanApi": fake.workApi, "/workCodingApi": fake.workApi })("WorkChangePlans.tsx").WorkChangePlans;
    const selected = [];
    const element = (itemId) => createElement(Plans, {
      item: { id: itemId }, workflows: [], onSelectPlan: (id) => selected.push(id), onPlansChanged: () => changed.push(itemId),
    });
    let view;
    act(() => { view = TestRenderer.create(element("item-a")); });
    await flush();
    type(answerFields(view.root)[0], "Staging only.");
    act(() => { buttons(view.root, /^Generate v2 from answers$/)[0].props.onClick(); });
    assert.equal(fake.answers[0].changePlanId, "plan-a1");

    act(() => view.update(element("item-b")));
    await flush();
    assert.match(text(view.root), /Request of plan-b1/);
    type(answerFields(view.root)[0], "Draft for B.");
    const loadsBefore = fake.loads.length;

    await act(async () => { fake.gate.resolve(); });
    await flush();
    assert.deepEqual(fake.loads.slice(loadsBefore), [], "no reload with the previous item's request");
    assert.deepEqual(selected, [], "the previous item's new version is not selected");
    assert.deepEqual(changed, []);
    const shown = text(view.root);
    assert.match(shown, /Request of plan-b1/);
    assert.doesNotMatch(shown, /plan-a|Your answers are kept/);
    assert.equal(answerFields(view.root)[0].props.value, "Draft for B.", "the current item's draft is untouched");
    assert.equal(buttons(view.root, /^Generate v2 from answers$/)[0].props.disabled, false, "the view is usable again");
    act(() => view.unmount());
    delete globalThis.window;
  });
}

test("a reply after the requested plan changed reloads but does not override the new selection", async () => {
  const gate = deferred();
  const fake = backend([plan("plan-v1", 1, "superseded", { open_questions: ["Old?"] }),
    plan("plan-v2", 2, "needs_clarification", { open_questions: QUESTIONS })],
  async (args, state) => { await gate.promise; return revise(args, state); });
  const { view, selected, rerender } = render(fake, { focusPlanId: "plan-v2" });
  await flush();
  type(answerFields(view.root)[0], "Staging only.");
  act(() => { buttons(view.root, /^Generate v3 from answers$/)[0].props.onClick(); });
  rerender({ focusPlanId: "plan-v1" });
  await act(async () => { gate.resolve(); });
  await flush();
  assert.deepEqual(selected, [], "the user's newer choice stands");
  assert.match(text(view.root), /Version 1/);
  assert.match(text(view.root), /newest is v3/, "the plans were reloaded for the same item");
  act(() => view.unmount());
  delete globalThis.window;
});

