// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/companionJobCards.test.mjs
//
// Running lists only runs still going; a finished card says "Finished"
// once; a working run shows no problem box; the handover form stacks its fields and its button always says "Request
// handover"; after an accept the former owner reads "they own it now" instead of "Hand over…"; a stopped run reads
// "Stopped"; a timestamp without zone is UTC. Typing a stop reason is tested in confirmDialogTyping.
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
import { cardParts, itemTitle } from "../../src/chat/companion/companionLabels.ts";
import { readAttentionItem, readRunningAgent } from "../../src/chat/companion/companionRead.ts";
import { runningNow } from "../../src/chat/companion/companionGroups.ts";
import { jobProblemItem, jobStateLabel, readJobDetail, showsProblem } from "../../src/chat/companion/companionJobModel.ts";
import { handedOverText, handoverStatus } from "../../src/chat/companion/companionHandoverModel.ts";
import { timeOf } from "../../src/admin/utils/dateTime.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id && typeof node.type === "string");

const action = (key, label, extra = {}) => ({ key, label, tone: "neutral", request: { method: "POST", path: `/api/v1/workflow-runs/run-1/${key}`, body: {} }, ...extra });

test("Running lists only runs that are still going", () => {
  const running = ["working", "needs_you", "done", "problem"].map((state) => readRunningAgent({ id: `run-${state}`, state, title: state }));
  assert.deepEqual(runningNow(running).map((run) => run.state), ["working", "needs_you"]);
});

test("A finished card says Finished once", () => {
  const plain = readAttentionItem({ key: "done:1", kind: "done", id: "1", title: "Finished", text: "Finished (done).", workspace: { id: "w", name: "Test" } });
  const parts = cardParts(plain, itemTitle(plain));
  const shown = [itemTitle(plain), ...parts.meta, parts.body].join(" ");
  assert.equal(shown.match(/finished/gi)?.length, 1, shown);
  assert.deepEqual(parts.meta, ["Test"]);
  const merged = readAttentionItem({ key: "done:2", kind: "done", id: "2", title: "BRD-7 Onboarding", text: "Finished (merged)." });
  const mergedParts = cardParts(merged, itemTitle(merged));
  assert.equal(mergedParts.body, "Finished and merged.", "an informative body stays");
  assert.deepEqual(mergedParts.meta, [], "the body already says it; no extra kind word");
  const question = readAttentionItem({ key: "q", kind: "question", id: "q", title: "Which branch?", text: "main or release" });
  assert.deepEqual(cardParts(question, itemTitle(question)).meta, ["Question"], "other kinds keep their word");
});

test("A working run shows no problem box, a stopped run reads Stopped", () => {
  const working = readJobDetail({ run_id: "run-1", state: "working", status: "running", can_control: true, problem: null,
    actions: [action("pause", "Pause")] });
  assert.equal(showsProblem(working), false);
  assert.equal(jobProblemItem(working), null, "a working run's actions are no problem");
  const paused = readJobDetail({ run_id: "run-1", state: "problem", status: "paused", can_control: true,
    problem: { reason: "", code: "x", message: "The tests could not start." }, actions: [action("continue", "Run the phase again")] });
  assert.equal(showsProblem(paused), true);
  assert.equal(jobProblemItem(paused).title, "The tests could not start.");
  const stopped = readJobDetail({ run_id: "run-1", state: "problem", status: "stopped", can_control: false });
  assert.equal(jobStateLabel(stopped), "Stopped");
  assert.equal(showsProblem(stopped), false, "a stopped run asks for no decision");
  assert.equal(jobStateLabel(readJobDetail({ run_id: "run-1", state: "problem", status: "aborted" })), "Stopped");
  assert.equal(jobStateLabel(paused), "Problem");
});

test("The latest handover from the events", () => {
  const owner = { id: "u-anna", name: "Companion fixture member" };
  assert.deepEqual(handoverStatus({ owner, events: [{ kind: "handover_accepted" }, { kind: "handover_requested" }] }),
    { state: "accepted", owner: "Companion fixture member" });
  assert.equal(handoverStatus({ owner, events: [{ kind: "handover_requested" }] }).state, "requested");
  assert.equal(handoverStatus({ owner, events: [{ kind: "phase_started" }] }), null);
  assert.equal(handedOverText("Companion fixture member"), "Handed over to Companion fixture member · they own it now.");
});

test("A timestamp without zone is read as UTC", () => {
  assert.equal(timeOf("2026-11-06T10:30:46.046134"), Date.UTC(2026, 10, 6, 10, 30, 46, 46));
  assert.equal(timeOf("2026-11-06T10:30:46.046134+00:00"), Date.UTC(2026, 10, 6, 10, 30, 46, 46));
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
      encodeURIComponent, setInterval, clearInterval, setTimeout, clearTimeout, Set, Map, String, Array, Boolean, RegExp,
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

const JOB = {
  run_id: "run-1", title: "Fixture run", workflow_key: "kan", work_item: { id: "wi", key: "BRD-11", title: "Fixture" },
  workspace: { id: "ws-1", name: "Test" }, owner: { id: "u-alex", name: "Alex" }, state: "working", status: "running",
  phase_index: 1, phase_count: 3, can_control: true, phases: [], events: [], problem: null, actions: [],
};

async function renderDetail(job, isAdmin, posts) {
  const reply = (status, body) => ({ ok: status < 400, status, statusText: String(status), json: async () => body });
  const fetch = async (url, init = {}) => {
    const call = { url: String(url), method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null };
    if (call.method !== "GET") posts.push([call.url, call.body]);
    if (call.url === "/api/v1/attention/jobs/run-1") return reply(200, job);
    if (call.url === "/api/v1/workspaces/ws-1/members") return reply(200, { members: [{ id: "u-alex", display_name: "Alex" }, { id: "u-anna", display_name: "Anna" }] });
    return reply(200, {});
  };
  const document = { addEventListener() {}, removeEventListener() {} };
  const window = { location: { origin: "http://localhost", search: "" }, addEventListener() {}, removeEventListener() {} };
  const load = loader({ fetch, window, document });
  const { CompanionJobDetail } = load("chat/companion/CompanionJobDetail.tsx");
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(CompanionJobDetail, { runId: "run-1", onBack() {}, watchJob() {}, isAdmin }),
      { createNodeMock: () => ({ focus() {} }) });
  });
  await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
  return view;
}

test("The handover form stacks its fields and its button always says Request handover; the full reason is sent", async () => {
  const posts = [];
  const view = await renderDetail(JOB, false, posts);
  assert.equal(byTestId(view, "octryx-job-problem").length + byTestId(view, "octryx-job-decision").length, 0, "no problem box while working");
  await act(async () => byTestId(view, "octryx-job-handover")[0].props.onClick());
  await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
  const form = byTestId(view, "octryx-handover")[0];
  assert.equal(form.props.className, "octryx-handover");
  const send = byTestId(view, "octryx-handover-send")[0];
  assert.equal(text(send), "Request handover");
  assert.equal(send.props.disabled, true);
  assert.equal(text(byTestId(view, "octryx-handover-why")[0]), "Choose who takes the run over.", "the hint stands below the button");
  await act(async () => byTestId(view, "octryx-handover-to")[0].props.onChange({ target: { value: "u-anna" } }));
  const reason = "I am away tomorrow, please finish the review";
  for (let length = 1; length <= reason.length; length += 1) {
    await act(async () => byTestId(view, "octryx-handover-reason")[0].props.onChange({ target: { value: reason.slice(0, length) } }));
  }
  assert.equal(text(byTestId(view, "octryx-handover-send")[0]), "Request handover");
  assert.equal(byTestId(view, "octryx-handover-send")[0].props.disabled, false);
  await act(async () => form.props.onSubmit({ preventDefault() {} }));
  await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));
  assert.deepEqual(posts, [["/api/v1/workflow-runs/run-1/handover-requests", { to_user_id: "u-anna", reason }]]);
  await act(async () => view.unmount());
});

test("After the accept the former owner reads who owns it now; a stopped run reads Stopped", async () => {
  const accepted = { ...JOB, owner: { id: "u-anna", name: "Anna" }, can_control: false,
    events: [{ text: "Handed over: away", kind: "handover_accepted", at: "2026-11-06T10:30:46.046134" }] };
  const view = await renderDetail(accepted, true, []);
  assert.equal(byTestId(view, "octryx-job-handover").length, 0, "no Hand over… for the former owner");
  assert.equal(text(byTestId(view, "octryx-handover-notice")[0]), "Handed over to Anna · they own it now.");
  await act(async () => view.unmount());
  const stopped = { ...JOB, state: "problem", status: "stopped", can_control: false,
    events: [{ text: "Emergency stop: UX acceptance: emergency stop test on fixture run", kind: "emergency_stop", technical: false, at: "2026-11-06T10:31:00+00:00" }] };
  const stoppedView = await renderDetail(stopped, true, []);
  const header = stoppedView.root.find((node) => node.type === "span" && text(node).startsWith("Stopped"));
  assert.ok(header, "the state reads Stopped");
  assert.equal(byTestId(stoppedView, "octryx-job-decision").length + byTestId(stoppedView, "octryx-job-reason").length, 0, "no decision box");
  assert.equal(byTestId(stoppedView, "octryx-job-emergency-stop").length, 0, "an ended run cannot be stopped again");
  await act(async () => stoppedView.unmount());
});
