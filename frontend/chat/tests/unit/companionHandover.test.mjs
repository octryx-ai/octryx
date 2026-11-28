// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/companionHandover.test.mjs
//
// Octryx companion, stage 1 part C: a "handover" attention item is answered in place and an accept opens
// the run's thread, now the receiver's ("You now own this run."); a job's detail offers "Hand over…" (a person and a reason) and,
// for admins only, "Emergency stop" (reason required, last); closing a watched run sends {"unwatch": run_id}; quiet
// hours read as "Quiet until 08:00" and a refused save says which times are valid. Requests and the socket are stubs.
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
import { readAttention } from "../../src/chat/companion/companionRead.ts";
import { readJob } from "../../src/chat/companion/companionJobModel.ts";
import { needsText, readPool, runNowText } from "../../src/chat/companion/companionPoolModel.ts";
import {
  acceptedSessionId,
  canEmergencyStop,
  canHandOver,
  emergencyStopRequest,
  handoverRequest,
  isHandoverAccept,
  POOLED_TEXT,
  quietSaveErrorText,
  TO_POOL,
  quietUntilText,
  readCandidates,
  unwatchMessage,
} from "../../src/chat/companion/companionHandoverModel.ts";

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

const HANDOVER = {
  key: "handover:h-1", kind: "handover", id: "h-1", title: "Take over BRD-6 Onboarding", subtitle: "from Alex",
  text: "I am away tomorrow", severity: "action", workspace: { id: "ws-1", name: "BRD team" },
  actions: [
    { key: "accept", label: "Accept", tone: "primary", request: { method: "POST", path: "/api/v1/session-handovers/h-1/accept", body: {} } },
    { key: "decline", label: "Decline", tone: "neutral", input: { kind: "text", field: "reason", label: "Reason", placeholder: "", required: false },
      request: { method: "POST", path: "/api/v1/session-handovers/h-1/decline", body: {} } },
  ],
};
const JOB = {
  run_id: "run-1", title: "Continue workflow run", workflow_key: "kan-delivery", work_item: { id: "wi-6", key: "BRD-6", title: "Onboarding" },
  workspace: { id: "ws-1", name: "BRD team" }, owner: { id: "u-alex", name: "Alex" }, state: "working", status: "running",
  current_node: null, phase_index: 2, phase_count: 4, since: "2026-11-06T09:00:00Z", runtime_target: null, can_control: true,
  phases: [], current_step: null, events: [{ text: "Handover declined: not this week", kind: "handover_declined", at: "2026-11-06T09:05:00Z" }],
};

test("handover items need the person; accept is recognised and its thread read", () => {
  const attention = readAttention({ items: [HANDOVER], running: [], quiet: { active: true, until: "2026-11-07T07:00:00Z" } });
  assert.deepEqual(attention.items.map((item) => item.kind), ["handover"]);
  const [item] = attention.items;
  assert.equal(item.severity, "action");
  assert.equal(isHandoverAccept(item, item.actions[0]), true);
  assert.equal(isHandoverAccept(item, item.actions[1]), false);
  assert.equal(acceptedSessionId({ handover: {}, session_id: "s-new" }), "s-new");
  assert.equal(acceptedSessionId({ handover: {} }), null);
  assert.equal(quietUntilText(attention.quiet), "Quiet until 08:00");
  assert.equal(quietUntilText({ active: false, until: null }), "");
  assert.equal(quietSaveErrorText({ code: "invalid_quiet_hours", message: "raw" }), "Start and end must be times like 19:00.");
  assert.equal(quietSaveErrorText({ message: "Not allowed" }), "Not allowed");
});

test("hand over and emergency stop: who may, what is sent, who can be chosen", () => {
  const job = readJob(JOB);
  assert.equal(canHandOver(job, false), true);
  assert.equal(canHandOver({ ...job, canControl: false }, false), false);
  assert.equal(canHandOver({ ...job, canControl: false }, true), true, "an admin hands over any run");
  assert.equal(canHandOver({ ...job, status: "completed" }, true), false);
  assert.equal(canEmergencyStop(job, false), false);
  assert.equal(canEmergencyStop(job, true), true);
  assert.deepEqual(handoverRequest("run-1", "", "x"), { error: "Choose who takes the run over." });
  assert.deepEqual(handoverRequest("run-1", "u-anna", " "), { error: "Enter a reason to continue." });
  assert.deepEqual(handoverRequest("run-1", "u-anna", " Away "), { path: "/api/v1/session-handovers", body: { run_id: "run-1", to_user_id: "u-anna", reason: "Away" } });
  assert.deepEqual(emergencyStopRequest("run-1", "Wrong system"), { path: "/api/v1/workflow-runs/run-1/emergency-stop", body: { reason: "Wrong system" } });
  assert.equal(unwatchMessage("run-1"), '{"unwatch":"run-1"}');
  const candidates = readCandidates({ members: [
    { id: "u-alex", display_name: "Alex" }, { id: "u-zoe", display_name: "Zoe" }, { id: "u-anna", display_name: "Anna" },
    { id: "u-zoe", display_name: "Zoe (group)" }, { display_name: "nobody" },
  ] }, "u-alex");
  assert.deepEqual(candidates, [{ id: "u-anna", name: "Anna" }, { id: "u-zoe", name: "Zoe" }], "owner, invalid and duplicates are left out");
  assert.deepEqual(readCandidates(null, "u-alex"), []);
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

const POOL_ENTRY = {
  id: "p-1", session_id: "s-pool", run_id: null, title: "Checkout copy", needs: { engine: "claude_code", profile: "governed" },
  state: "", summary: "Rewrite the checkout texts", can_run_now: true, created_at: "2026-11-06T09:00:00Z",
};

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
  const state = { items: [HANDOVER], quietSaveRefused: false, pool: [POOL_ENTRY, { ...POOL_ENTRY, id: "p-2", title: "Needs a seat", can_run_now: false, needs: { engine: "codex", profile: "seat" } }], poolTaken: false };
  const reply = (status, body) => ({ ok: status < 400, status, statusText: String(status), json: async () => body });
  const fetch = async (url, init = {}) => {
    const parsed = new URL(String(url), "http://localhost");
    const call = { url: parsed.pathname + parsed.search, method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null };
    calls.push(call);
    if (call.url === "/api/v1/attention") {
      return reply(200, { items: state.items, running: [], count: state.items.length, cursor: null, quiet: { active: true, until: "2026-11-07T07:00:00Z" } });
    }
    if (call.url === "/api/v1/notifications/preferences") {
      if (call.method === "PUT") return reply(422, { detail: { code: "invalid_quiet_hours", message: "quiet_hours invalid" } });
      return reply(200, { user_id: "u-alex", in_app_enabled: true, quiet_hours: { enabled: true, start: "19:00", end: "08:00", timezone: "Europe/Zurich" } });
    }
    if (call.url === "/api/v1/session-handovers/h-1/accept") {
      state.items = [];
      return reply(200, { handover: { state: "accepted" }, session_id: "s-new" });
    }
    if (call.url.startsWith("/api/v1/attention/jobs?")) return reply(200, { jobs: [JOB] });
    if (call.url === "/api/v1/attention/jobs/run-1") return reply(200, JOB);
    if (/^\/api\/v1\/workspaces\/[^/]+\/members$/.test(call.url)) return reply(200, { members: [{ id: "u-alex", display_name: "Alex" }, { id: "u-anna", display_name: "Anna" }] });
    if (call.url === "/api/v1/session-handovers") return reply(200, { handover: { status: "pending" } });
    if (call.url === "/api/v1/workflow-runs/run-1/emergency-stop") return reply(200, { run: {} });
    if (call.url === "/api/v1/session-handovers/pool") return reply(200, { entries: state.pool });
    if (call.url === "/api/v1/session-handovers/p-1/accept") {
      if (state.poolTaken) return reply(409, { detail: { code: "handover_taken", message: "Someone else took this session first." } });
      state.pool = [];
      return reply(200, { handover: { status: "accepted" }, session_id: "s-pool" });
    }
    return reply(404, { detail: "Not Found" });
  };
  return { fetch, calls, state };
}

async function render(srv, props = {}) {
  const { FakeSocket, sockets } = socketStub();
  const documentTarget = new EventTarget();
  const load = loader({
    fetch: srv.fetch, window: windowStub(), WebSocket: FakeSocket,
    document: { addEventListener: (...args) => documentTarget.addEventListener(...args), removeEventListener: (...args) => documentTarget.removeEventListener(...args) },
  });
  const { CompanionHost, CompanionLogoTrigger } = load("chat/companion/CompanionHost.tsx");
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(CompanionHost, { userId: "u-alex", onOpenAgents: () => {}, notificationApi: null, pollMs: 60_000, answeredMs: 0, ...props }, createElement(CompanionLogoTrigger)));
  });
  await tick();
  await act(async () => sockets[0].open());
  await act(async () => byTestId(view, "octryx-button")[0].props.onClick());
  await tick();
  return { view, socket: sockets[0] };
}

async function openJob(view) {
  await act(async () => view.root.find((node) => node.props.role === "tab" && node.props.id === "octryx-view-tab-jobs").props.onClick());
  await tick();
  await act(async () => jobRows(view)[0].props.onClick());
  await tick();
}

test("accepting a handover opens the run's thread and says who owns the run now", async () => {
  const srv = server();
  const opened = [];
  const { view } = await render(srv, { onOpenSession: (id) => opened.push(id) });
  try {
    assert.equal(text(byTestId(view, "octryx-quiet")[0]), "Quiet until 08:00");
    const item = byTestId(view, "octryx-item")[0];
    assert.equal(item.props["data-kind"], "handover");
    assert.match(text(item), /from Alex/);
    assert.match(text(item), /I am away tomorrow/);
    const accept = byTestId(view, "octryx-action").find((button) => text(button) === "Accept");
    await act(async () => accept.props.onClick());
    await tick();
    assert.deepEqual(opened, ["s-new"]);
    assert.equal(text(byTestId(view, "octryx-accepted")[0]), "You now own this run.");
    assert.equal(byTestId(view, "octryx-item").length, 0, "the answered item is gone");
  } finally {
    view.unmount();
  }
});

test("emergency stop shows only for admins, last; hand over asks for a person and a reason; closing unwatches", async () => {
  const member = await render(server());
  try {
    await openJob(member.view);
    assert.equal(byTestId(member.view, "octryx-job-emergency-stop").length, 0, "not for a member");
    assert.equal(byTestId(member.view, "octryx-job-handover").length, 1, "the owner hands over");
  } finally {
    member.view.unmount();
  }
  const srv = server();
  const { view, socket } = await render(srv, { isAdmin: true });
  try {
    await openJob(view);
    const buttons = byTestId(view, "octryx-job").at(0).findAll((node) => node.type === "button").map((button) => text(button));
    assert.equal(buttons.at(-1), "Emergency stop", "the emergency stop comes last");
    await act(async () => byTestId(view, "octryx-job-handover")[0].props.onClick());
    await tick();
    const options = byTestId(view, "octryx-handover-to")[0].findAll((node) => node.type === "option").map((option) => text(option));
    assert.deepEqual(options, ["Choose a person", "Anna", "The session pool (whoever can run it now)"], "the owner is not offered");
    await act(async () => view.root.find((node) => node.props["data-testid"] === "octryx-handover").props.onSubmit({ preventDefault() {} }));
    assert.equal(text(byTestId(view, "octryx-handover-problem")[0]), "Choose who takes the run over.");
    await act(async () => byTestId(view, "octryx-handover-to")[0].props.onChange({ target: { value: "u-anna" } }));
    await act(async () => byTestId(view, "octryx-handover-reason")[0].props.onChange({ target: { value: "Away tomorrow" } }));
    await act(async () => view.root.find((node) => node.props["data-testid"] === "octryx-handover").props.onSubmit({ preventDefault() {} }));
    await tick();
    assert.equal(text(byTestId(view, "octryx-handover-notice")[0]), "Handover requested to Anna.");
    await act(async () => byTestId(view, "octryx-job-emergency-stop")[0].props.onClick());
    const dialog = view.root.find((node) => node.props.role === "alertdialog");
    assert.match(text(dialog), /Emergency stop of the run "BRD-6 Onboarding"\?/);
    await act(async () => dialog.find((node) => node.type === "textarea").props.onChange({ target: { value: "Wrong system" } }));
    const ready = view.root.find((node) => node.props.role === "alertdialog").findAll((node) => node.type === "button").find((button) => text(button) === "Emergency stop");
    await act(async () => ready.props.onClick());
    await tick();
    assert.deepEqual(srv.calls.filter((call) => call.method === "POST").map((call) => [call.url, call.body]), [
      ["/api/v1/session-handovers", { run_id: "run-1", to_user_id: "u-anna", reason: "Away tomorrow" }],
      ["/api/v1/workflow-runs/run-1/emergency-stop", { reason: "Wrong system" }],
    ]);
    assert.equal(text(byTestId(view, "action-done")[0]).startsWith('Run "BRD-6 Onboarding" stopped.'), true);
    await act(async () => view.root.findAll((node) => node.type === "button" && text(node) === "← All jobs")[0].props.onClick());
    await tick();
    assert.equal(socket.sent.at(-1), '{"unwatch":"run-1"}');
  } finally {
    view.unmount();
  }
});

test("a refused quiet-hours save says which times are valid", async () => {
  const srv = server();
  const { view } = await render(srv);
  try {
    assert.equal(byTestId(view, "octryx-footer").length, 0, "quiet hours wait behind the gear");
    await act(async () => byTestId(view, "octryx-settings")[0].props.onClick());
    await act(async () => byTestId(view, "octryx-quiet-start")[0].props.onChange({ target: { value: "20:00" } }));
    const save = byTestId(view, "octryx-footer")[0].findAll((node) => node.type === "button").find((button) => text(button) === "Save");
    await act(async () => save.props.onClick());
    await tick();
    assert.equal(text(byTestId(view, "octryx-quiet-status")[0]), "Start and end must be times like 19:00.");
  } finally {
    view.unmount();
  }
});


test("pool entries read what the taker needs and whether they can run it now", () => {
  const [governed, seat] = readPool({ entries: [POOL_ENTRY, { ...POOL_ENTRY, id: "p-2", can_run_now: false, needs: { engine: "codex", profile: "seat" } }] });
  assert.equal(needsText(governed), "Claude Code on the platform's models");
  assert.equal(runNowText(governed), "You can run it now");
  assert.equal(needsText(seat), "Codex on your own seat");
  assert.equal(runNowText(seat), "Needs a device of yours with a Codex seat online");
  assert.deepEqual(readPool({ entries: [{ id: "x" }, null] }), []);
});

test("a pool item needs the person and its accept opens the session; a handover without a run names no run", () => {
  const accept = { key: "accept", label: "Take over", tone: "primary", request: { method: "POST", path: "/api/v1/session-handovers/p-1/accept", body: {} } };
  const attention = readAttention({ items: [
    { key: "pool:p-1", kind: "pool", id: "s-pool", title: "Checkout copy", severity: "action", session_id: "s-pool", actions: [accept] },
    { key: "handover:h-9", kind: "handover", id: "s-9", title: "A session for you", severity: "action", actions: [accept] },
  ], running: [] });
  const [pool, handover] = attention.items;
  assert.equal(pool.kind, "pool");
  assert.equal(isHandoverAccept(pool, pool.actions[0]), true);
  assert.equal(handover.runId, null, "its id is the session's");
  assert.deepEqual(handoverRequest("run-1", TO_POOL, "Away"), { path: "/api/v1/session-handovers", body: { run_id: "run-1", reason: "Away" } });
  assert.match(POOLED_TEXT, /session pool/);
});

test("the Pool tab lists the waiting sessions; taking one opens it, and a lost race shows the refusal", async () => {
  const srv = server();
  const opened = [];
  const { view } = await render(srv, { onOpenSession: (id) => opened.push(id) });
  try {
    await act(async () => view.root.find((node) => node.props.role === "tab" && node.props.id === "octryx-view-tab-pool").props.onClick());
    await tick();
    const entries = byTestId(view, "octryx-pool-entry");
    assert.equal(entries.length, 2);
    assert.match(text(entries[0]), /Rewrite the checkout texts/);
    const [take, blocked] = byTestId(view, "octryx-pool-take");
    assert.equal(blocked.props.disabled, true, "nothing of the person's can run the seat entry now");
    srv.state.poolTaken = true;
    await act(async () => take.props.onClick());
    await tick();
    assert.equal(text(byTestId(view, "octryx-pool-problem")[0]), "Someone else took this session first.");
    assert.deepEqual(opened, []);
    srv.state.poolTaken = false;
    await act(async () => byTestId(view, "octryx-pool-take")[0].props.onClick());
    await tick();
    assert.deepEqual(opened, ["s-pool"]);
    assert.match(text(byTestId(view, "octryx-pool-notice")[0]), /it is yours now/);
  } finally {
    view.unmount();
  }
});
