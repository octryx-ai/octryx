// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/companionJobs.test.mjs
//
// Octryx companion, stage 1 part B: reading GET /api/v1/attention/jobs and /jobs/{run_id} tolerantly,
// the row texts ("Phase n of m", target with "· offline"), Team following the active Workspace, and, rendered: the
// Jobs view lists runs, opens a run's detail, watches it over the attention socket ({"watch": run_id}) and reloads on
// its job_changed nudge, shows 404 as "no longer visible", and lets the owner abort with a required reason through
// the run's own action endpoint. Requests and the socket are stubs.
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
import {
  abortRequest,
  canAbort,
  jobLink,
  jobsPath,
  jobTitle,
  phaseText,
  readJobDetail,
  readJobs,
  targetText,
  watchMessage,
} from "../../src/chat/companion/companionJobModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id && typeof node.type === "string");
// Jobs are rows of a compact table; a row opens the job.
const jobRows = (view) => view.root.findAll((node) => node.type === "tr" && node.props["data-row-key"]);
const tick = (ms = 0) => act(() => new Promise((resolve) => setTimeout(resolve, ms)));

const JOB = {
  run_id: "run-1", title: "Continue workflow run", workflow_key: "kan-delivery", work_item: { id: "wi-6", key: "BRD-6", title: "Onboarding" },
  workspace: { id: "ws-1", name: "BRD team" }, owner: { id: "u-alex", name: "Alex" }, state: "working", status: "running",
  current_node: { id: "implement", title: "Implement", kind: "phase" }, phase_index: 2, phase_count: 4, since: "2026-11-06T09:00:00Z",
  runtime_target: { kind: "device", label: "Studio Mac", profile: "seat", reason: "", device_name: "Studio Mac", online: false, folder: "/Users/dev/src" },
  can_control: true,
};
const DETAIL = {
  ...JOB,
  phases: [{ id: "clarify", title: "Clarify", state: "done" }, { id: "implement", title: "Implement", state: "active" }, { id: "review", title: "Review", state: "weird" }],
  current_step: { text: "Started Implement", kind: "node_entered", technical: false, at: "2026-11-06T09:00:00Z" },
  events: [{ text: "Started Implement", kind: "node_entered", technical: false, at: "2026-11-06T09:00:00Z" },
    { text: "Run started", kind: "run_started", technical: false, at: "2026-11-06T08:50:00Z" }, { kind: "no text" }],
};

test("jobs and a job's detail are read tolerantly; rows say phase, target and offline", () => {
  const jobs = readJobs({ jobs: [JOB, { title: "no run id" }, null] });
  assert.equal(jobs.length, 1);
  const [job] = jobs;
  assert.equal(jobTitle(job), "BRD-6 Onboarding");
  assert.equal(jobTitle({ ...job, workItem: null }), "Continue workflow run");
  assert.equal(phaseText(job), "Phase 2 of 4");
  assert.equal(phaseText({ ...job, phaseIndex: null }), "4 phases", "without a known phase the row still says how many (C13)");
  assert.equal(phaseText({ ...job, phaseIndex: null, state: "done" }), "Phase 4 of 4", "a finished run stands at its last phase");
  assert.equal(targetText(job.target), "on Studio Mac · offline");
  assert.equal(targetText({ kind: "server", label: "the Server", online: null }), "on the server", "no \"the Server\"");
  assert.equal(job.target.folder, "/Users/dev/src");
  assert.equal(readJobs({ jobs: [{ ...JOB, runtime_target: { label: "Mac (seat)" } }] })[0].target.folder, null, "a watcher has no folder");
  assert.equal(readJobs({ items: [] }), null);
  assert.deepEqual(jobLink(job), { href: "/chat?area=work&work_item_id=wi-6", label: "Open work item" });
  const detail = readJobDetail(DETAIL);
  assert.deepEqual(detail.phases.map((phase) => phase.state), ["done", "active", "pending"], "an unknown phase state reads as pending");
  assert.equal(detail.events.length, 2, "an event without text is dropped");
  assert.equal(detail.currentStep.text, "Started Implement");
});

test("Team follows the active Workspace; abort only for the owner of a run that has not ended", () => {
  assert.equal(jobsPath("mine", "ws-1"), "/api/v1/attention/jobs?scope=mine");
  assert.equal(jobsPath("team", "ws-1"), "/api/v1/attention/jobs?scope=team&workspace_id=ws-1");
  assert.equal(jobsPath("team", ""), "/api/v1/attention/jobs?scope=team");
  const [job] = readJobs({ jobs: [JOB] });
  assert.equal(canAbort(job), true);
  assert.equal(canAbort({ ...job, canControl: false }), false);
  assert.equal(canAbort({ ...job, status: "completed" }), false);
  assert.deepEqual(abortRequest("run-1", "Wrong branch"), { path: "/api/v1/workflow-runs/run-1/actions", body: { action: "abort", reason: "Wrong branch" } });
  assert.equal(watchMessage("run-1"), '{"watch":"run-1"}');
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
    location: { origin: "http://localhost", protocol: "http:", host: "localhost", search: "?workspace_id=ws-1", href: "http://localhost/chat" },
    localStorage: { getItem: () => null, setItem() {} },
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    addEventListener: (...args) => target.addEventListener(...args),
    removeEventListener: (...args) => target.removeEventListener(...args),
    dispatchEvent: (event) => target.dispatchEvent(event),
  };
}

function socketStub() {
  const sockets = [];
  class FakeSocket {
    constructor(url) { this.url = url; this.readyState = 0; this.sent = []; sockets.push(this); }
    send(message) { this.sent.push(message); }
    close() { this.readyState = 3; }
    open() { this.readyState = 1; this.onopen?.(); }
    push(message) { this.onmessage?.({ data: JSON.stringify(message) }); }
  }
  return { FakeSocket, sockets };
}

function server() {
  const calls = [];
  const state = { detail: DETAIL, visible: true, jobs: [JOB] };
  const reply = (status, body) => ({ ok: status < 400, status, statusText: String(status), json: async () => body });
  const fetch = async (url, init = {}) => {
    // readJson makes a URL with a query absolute; the stub compares path and query.
    const parsed = new URL(String(url), "http://localhost");
    const call = { url: parsed.pathname + parsed.search, method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null };
    calls.push(call);
    if (call.url === "/api/v1/attention") return reply(200, { items: [], running: [], count: 0, cursor: null, quiet: { active: false, until: null } });
    if (call.url === "/api/v1/notifications/preferences") return reply(200, { user_id: "u-alex", in_app_enabled: true });
    if (call.url.startsWith("/api/v1/attention/jobs?")) return reply(200, { jobs: state.jobs });
    if (call.url === "/api/v1/attention/jobs/run-1") return state.visible ? reply(200, state.detail) : reply(404, { detail: "Not Found" });
    if (call.url === "/api/v1/workflow-runs/run-1/actions") {
      state.detail = { ...state.detail, status: "stopped", state: "problem" };
      return reply(200, { run: {} });
    }
    return reply(404, { detail: "Not Found" });
  };
  return { fetch, calls, state };
}

async function renderJobs(srv) {
  const { FakeSocket, sockets } = socketStub();
  const documentTarget = new EventTarget();
  const load = loader({
    fetch: srv.fetch, window: windowStub(), WebSocket: FakeSocket,
    document: { addEventListener: (...args) => documentTarget.addEventListener(...args), removeEventListener: (...args) => documentTarget.removeEventListener(...args) },
  });
  const { CompanionHost, CompanionLogoTrigger } = load("chat/companion/CompanionHost.tsx");
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(CompanionHost, { userId: "u-alex", onOpenAgents: () => {}, notificationApi: null, pollMs: 60_000, answeredMs: 0 }, createElement(CompanionLogoTrigger)));
  });
  await tick();
  await act(async () => sockets[0].open());
  await act(async () => byTestId(view, "octryx-button")[0].props.onClick());
  await act(async () => view.root.find((node) => node.props.role === "tab" && node.props.id === "octryx-view-tab-jobs").props.onClick());
  await tick();
  return { view, socket: sockets[0] };
}

test("Jobs lists Mine, switches to Team of the active Workspace, and watches an opened run live", async () => {
  const srv = server();
  const { view, socket } = await renderJobs(srv);
  try {
    const row = jobRows(view)[0];
    assert.match(text(row), /BRD-6 Onboarding/);
    assert.match(text(row), /Phase 2 of 4 · on Studio Mac · offline/);
    assert.equal(text(row.find((node) => node.props["data-tone"])), "Working", "the state as the design system's label");
    assert.doesNotMatch(text(row), /Alex$/, "Mine does not name the owner");
    await act(async () => view.root.find((node) => node.props.role === "tab" && node.props.id === "octryx-jobs-tab-team").props.onClick());
    await tick();
    assert.ok(srv.calls.some((call) => call.url === "/api/v1/attention/jobs?scope=team&workspace_id=ws-1"));
    await act(async () => jobRows(view)[0].props.onClick());
    await tick();
    assert.deepEqual(byTestId(view, "octryx-job-phases")[0].findAll((node) => node.type === "li").map((li) => li.props["data-state"]), ["done", "active", "pending"]);
    assert.match(text(byTestId(view, "octryx-job-step")[0]), /Now: Started Implement/, "events read as sentences (C11)");
    assert.match(text(byTestId(view, "octryx-job-target")[0]), /\/Users\/dev\/src/, "the owner sees the folder");
    assert.deepEqual(socket.sent, ['{"watch":"run-1"}']);
    const loads = () => srv.calls.filter((call) => call.url === "/api/v1/attention/jobs/run-1").length;
    const before = loads();
    await act(async () => socket.push({ type: "job_changed", run_id: "other" }));
    await act(async () => socket.push({ type: "job_changed", run_id: "run-1" }));
    await tick();
    assert.equal(loads(), before + 1, "only the watched run's nudge reloads the detail");
    srv.state.visible = false;
    await act(async () => socket.push({ type: "job_changed", run_id: "run-1" }));
    await tick();
    assert.equal(text(byTestId(view, "octryx-job-problem")[0]), "This job is no longer visible to you.");
  } finally {
    view.unmount();
  }
});

test("A job on the server without a phase starts with its time, not with a stray dot", async () => {
  const srv = server();
  srv.state.jobs = [{ ...JOB, run_id: "run-9", work_item: null, title: "[companion fixture]", current_node: null, phase_index: null,
    phase_count: null, runtime_target: { kind: "server", label: "Server" }, since: new Date(Date.now() - 3_600_000).toISOString() }];
  const { view } = await renderJobs(srv);
  try {
    const meta = jobRows(view)[0].find((node) => typeof node.props.className === "string" && node.props.className.includes("octryx-jobs__meta"));
    assert.doesNotMatch(text(meta), /^\s*·/);
    assert.match(text(meta), /^1 h ago$/);
    assert.equal(text(byTestId(view, "octryx-jobs-window")[0]), "Runs that worked in the last 24 hours.", "the list names its window");
  } finally {
    view.unmount();
  }
});

test("the owner aborts a run only with a reason, through the run's own action endpoint", async () => {
  const srv = server();
  const { view } = await renderJobs(srv);
  try {
    await act(async () => jobRows(view)[0].props.onClick());
    await tick();
    await act(async () => byTestId(view, "octryx-job-abort")[0].props.onClick());
    const dialog = view.root.find((node) => node.props.role === "alertdialog");
    assert.match(text(dialog), /Abort the run "BRD-6 Onboarding"\?/);
    const confirm = dialog.findAll((node) => node.type === "button").find((button) => text(button) === "Abort run");
    assert.equal(confirm.props.disabled, true, "the reason is required");
    await act(async () => dialog.find((node) => node.type === "textarea").props.onChange({ target: { value: "Wrong branch" } }));
    const ready = view.root.find((node) => node.props.role === "alertdialog").findAll((node) => node.type === "button").find((button) => text(button) === "Abort run");
    await act(async () => ready.props.onClick());
    await tick();
    assert.deepEqual(srv.calls.filter((call) => call.method === "POST").map((call) => [call.url, call.body]),
      [["/api/v1/workflow-runs/run-1/actions", { action: "abort", reason: "Wrong branch" }]]);
    assert.equal(text(byTestId(view, "action-done")[0]).startsWith('Run "BRD-6 Onboarding" aborted.'), true);
    assert.equal(byTestId(view, "octryx-job-abort").length, 0, "an ended run offers no abort");
  } finally {
    view.unmount();
  }
});
