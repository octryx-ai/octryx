// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/handoffPolicy.test.mjs
//
// Freeze 3b of the agent board (board-fe): the "Automatic handoff" card in Agents → Claims and handoffs
// (admin-editable, read-only for members, a plain-language explanation built from the values) and the display of an
// automatic handoff ("Handed over automatically" with the applied policy). Requests are stubs.
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
  policyBody,
  policyExplanation,
  policyProblems,
  policySaveErrorText,
  readHandoffPolicy,
} from "../../src/chat/agents/handoffPolicyModel.ts";
import { decisionLabel, snapshotLines } from "../../src/chat/agents/agentHandoffView.ts";
import { readTakeover } from "../../src/chat/agents/agentHandoffModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
const button = (view, label) => view.root.find((node) => node.type === "button" && text(node) === label);
const buttons = (view, label) => view.root.findAll((node) => node.type === "button" && text(node) === label);
const json = (value) => JSON.parse(JSON.stringify(value));

const DEFAULT_ANSWER = { project_id: "ws-1", handoff: { mode: "confirm", auto_threshold_pct: 90, require_spare_pct: 50,
  allowed_requesters: "members" }, source: "default", can_edit: false };
const ANNA = { id: "u-anna", display_name: "Anna" };
const BEN = { id: "u-ben", display_name: "Ben" };
const ALEX = { id: "u-alex", display_name: "Alex" };
const WORK = { id: "wi-6", key: "BRD-6", title: "Onboarding checklist" };
const AUTO_TAKEOVER = {
  id: "t9", work_item: WORK, from: { user: ANNA, agent_hash: "a-anna" }, to: { user: BEN, agent_hash: "a-ben" }, status: "confirmed",
  reason: null, expires_at: "2026-10-06T08:00:00Z", created_at: "2026-10-05T11:55:00Z", decided_at: "2026-10-05T11:56:00Z",
  decided_by: { kind: "system" }, policy_mode: "auto", automatic: false, message_id: "m9", handoff: { id: "h2", version: 2 },
};

// ---- model --------------------------------------------------------------------------------------

test("the policy answer is read strictly, the body uses the server's names, and the bounds match the server", () => {
  assert.deepEqual(json(readHandoffPolicy(DEFAULT_ANSWER)), { policy: { mode: "confirm", autoThresholdPct: 90, requireSparePct: 50,
    allowedRequesters: "members", push: null, autoTriggerPct: null, offerTimeoutMinutes: null }, source: "default", canEdit: false });
  assert.equal(readHandoffPolicy({}), null);
  assert.equal(readHandoffPolicy({ ...DEFAULT_ANSWER, handoff: { ...DEFAULT_ANSWER.handoff, mode: "yolo" } }), null);
  assert.equal(readHandoffPolicy({ ...DEFAULT_ANSWER, handoff: { ...DEFAULT_ANSWER.handoff, auto_threshold_pct: "90" } }), null);
  assert.equal(readHandoffPolicy({ ...DEFAULT_ANSWER, handoff: { ...DEFAULT_ANSWER.handoff, auto_threshold_pct: 85.5 } }).policy.autoThresholdPct, 85.5,
    "a fractional percentage is read, as the server checks the range only");
  assert.equal(readHandoffPolicy({ ...DEFAULT_ANSWER, can_edit: "yes" }).canEdit, false, "only true is true");
  const policy = { mode: "auto", autoThresholdPct: 85, requireSparePct: 30, allowedRequesters: "admins_and_owners", push: null, autoTriggerPct: null, offerTimeoutMinutes: null };
  assert.deepEqual(policyBody(policy), { mode: "auto", auto_threshold_pct: 85, require_spare_pct: 30, allowed_requesters: "admins_and_owners" });
  assert.deepEqual(policyProblems({ ...policy, autoThresholdPct: 1, requireSparePct: 0 }), []);
  assert.deepEqual(policyProblems({ ...policy, autoThresholdPct: 100, requireSparePct: 99 }), []);
  assert.equal(policyProblems({ ...policy, autoThresholdPct: 0 }).length, 1);
  assert.equal(policyProblems({ ...policy, autoThresholdPct: 101 }).length, 1);
  assert.deepEqual(policyProblems({ ...policy, autoThresholdPct: 90.5 }), [], "range only, like the server");
  assert.equal(policyProblems({ ...policy, autoThresholdPct: Number.NaN }).length, 1, "an empty field is refused");
  assert.equal(policyProblems({ ...policy, requireSparePct: 100 }).length, 1);
  assert.equal(policyProblems({ ...policy, requireSparePct: -1 }).length, 1);
});

test("refusals name the field; the explanation says what the server will do with these values", () => {
  assert.equal(policySaveErrorText(422, { detail: { errors: [{ code: "invalid_percentage", field: "agent_gateway_policy.handoff.auto_threshold_pct" }] } }),
    "Not saved: a percentage is out of range (threshold 1 to 100, spare 0 to 99) (Holder threshold).");
  assert.equal(policySaveErrorText(422, { detail: { errors: [{ code: "unknown_field", field: "colour" }, { code: "invalid_handoff_mode", field: "mode" }] } }),
    "Not saved: the server does not know one of the fields (colour); the mode must be Confirm each handoff or Hand over automatically (Mode).");
  assert.equal(policySaveErrorText(403, { detail: "Workspace admin or owner role required" }),
    "Not saved: only Workspace admins and owners can change the handoff policy.");
  assert.match(policySaveErrorText(404, null), /not found, or you are not a member/);
  assert.equal(policySaveErrorText(500, { detail: "boom" }), "Not saved: boom.");
  const confirm = policyExplanation({ mode: "confirm", autoThresholdPct: 90, requireSparePct: 50, allowedRequesters: "members", push: null, autoTriggerPct: null, offerTimeoutMinutes: null });
  assert.match(confirm[0], /^Every takeover waits until the receiving person/);
  const auto = policyExplanation({ mode: "auto", autoThresholdPct: 85, requireSparePct: 30, allowedRequesters: "admins_and_owners", push: null, autoTriggerPct: null, offerTimeoutMinutes: null });
  assert.match(auto[0], /requested by an agent of a Workspace admin or owner is confirmed by Octryx without a person/);
  assert.match(auto[1], /at 85 % or more of its weekly allowance/);
  assert.match(auto[2], /used at most 70 % of its own allowance/);
  assert.match(auto[3], /a handoff has been written/);
});

test("an automatic handoff reads 'Handed over automatically' with the applied policy; a person's decision names them", () => {
  const auto = readTakeover(AUTO_TAKEOVER);
  assert.equal(decisionLabel(auto), "Handed over automatically");
  assert.deepEqual(snapshotLines(auto), ["Workspace handoff mode at the request: automatic"], "without a snapshot: the recorded mode");
  const withSnapshot = readTakeover({ ...AUTO_TAKEOVER, policy_snapshot: { mode: "auto", auto_threshold_pct: 90, require_spare_pct: 50,
    allowed_requesters: "members", conditions: { holder_needs_handoff: true, requester_has_spare: true, requester_allowed: true, handoff_exists: true } } });
  assert.deepEqual(snapshotLines(withSnapshot), [
    "Policy: automatic · threshold 90 % · spare 50 % · requesters: members",
    "✓ holder at its limit, threshold, stopped or silent", "✓ requester had spare allowance",
    "✓ requester allowed by the policy", "✓ a handoff existed",
  ]);
  assert.equal(decisionLabel(readTakeover({ ...AUTO_TAKEOVER, decided_by: { kind: "human", user: ALEX } })), "Confirmed by Alex");
  assert.equal(decisionLabel(readTakeover({ ...AUTO_TAKEOVER, status: "declined", decided_by: { kind: "human", user: ALEX } })), "Declined by Alex");
  assert.equal(decisionLabel(readTakeover({ ...AUTO_TAKEOVER, status: "pending", decided_by: null })), "");
});

// ---- rendered -----------------------------------------------------------------------------------

function loader(extra = {}) {
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
      encodeURIComponent, setInterval, clearInterval, setTimeout, CustomEvent, Set, Map, String, Array, Boolean,
      ...extra,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.endsWith("/layout/LoadingState")) return loadingState;
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

const windowStub = (search = "") => {
  const target = new EventTarget();
  return {
    location: { origin: "http://localhost", search, href: `http://localhost/chat${search}` },
    localStorage: { getItem: () => null, setItem: () => {} },
    history: { state: null, replaceState: () => {} },
    addEventListener: (...args) => target.addEventListener(...args),
    removeEventListener: (...args) => target.removeEventListener(...args),
    dispatchEvent: (event) => target.dispatchEvent(event),
  };
};
const documentStub = () => ({ visibilityState: "visible", addEventListener: () => {}, removeEventListener: () => {} });

function server({ policy = DEFAULT_ANSWER, putAnswer = null, takeovers = { pending: [], confirmed: [AUTO_TAKEOVER] } } = {}) {
  const calls = [];
  const state = { policy, putAnswer, takeovers };
  const fetch = async (url, init = {}) => {
    const href = String(url);
    const method = init.method || "GET";
    calls.push({ url: href, method, body: init.body ? JSON.parse(init.body) : null });
    const parsed = new URL(href, "http://localhost");
    const reply = (status, body) => ({ ok: status < 400, status, statusText: "", json: async () => body });
    if (parsed.pathname.endsWith("/agent-gateway/handoff-policy")) {
      if (method === "PUT") return state.putAnswer ? state.putAnswer(JSON.parse(init.body)) : reply(200, state.policy);
      return reply(200, state.policy);
    }
    const viewer = { user_id: "u-ben", can_admin: false };
    if (parsed.pathname.endsWith("/takeovers")) return reply(200, { items: state.takeovers[parsed.searchParams.get("status")] ?? [], viewer });
    if (parsed.pathname.endsWith("/handoffs")) return reply(200, { items: [], viewer });
    if (parsed.pathname.endsWith("/claims")) return reply(200, { items: [], viewer });
    return reply(404, { detail: "Not Found" });
  };
  return { fetch, calls, state };
}
const tick = (ms = 0) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

async function renderCard(srv) {
  const load = loader({ fetch: srv.fetch, window: windowStub(), document: documentStub() });
  const { AgentsHandoffPolicy } = load("chat/agents/AgentsHandoffPolicy.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsHandoffPolicy, { projectId: "ws-1" })); });
  await tick();
  return view;
}
const fieldset = (view) => view.root.findByType("fieldset");
const radio = (view, mode) => view.root.find((node) => node.type === "input" && node.props.type === "radio" && node.props.value === mode);

test("rendered card for a member: the policy and its explanation, read-only, nothing to save", async () => {
  const srv = server();
  const view = await renderCard(srv);
  try {
    assert.ok(srv.calls[0].url.endsWith("/api/v1/workspaces/ws-1/agent-gateway/handoff-policy"));
    assert.equal(text(byTestId(view, "agents-handoff-policy-source")[0]),
      "This Workspace uses the default policy. Read-only: Workspace admins and owners can change it.");
    assert.equal(fieldset(view).props.disabled, true);
    assert.equal(radio(view, "confirm").props.checked, true);
    assert.equal(buttons(view, "Save handoff policy").length, 0);
    assert.match(text(byTestId(view, "agents-handoff-policy-explanation")[0]), /^Every takeover waits until the receiving person/);
  } finally { act(() => view.unmount()); }
});

test("rendered card for an admin: switch to automatic, bounds checked before saving, PUT with every field, saved answer shown", async () => {
  const srv = server({ policy: { ...DEFAULT_ANSWER, can_edit: true } });
  srv.state.putAnswer = (body) => ({ ok: true, status: 200, statusText: "", json: async () => ({ ...DEFAULT_ANSWER, handoff: body, source: "workspace", can_edit: true }) });
  const view = await renderCard(srv);
  try {
    assert.equal(fieldset(view).props.disabled, false);
    assert.equal(button(view, "Save handoff policy").props.disabled, true, "nothing changed yet");
    await act(async () => { radio(view, "auto").props.onChange(); });
    const threshold = () => view.root.findByProps({ "aria-label": "Holder threshold" });
    const spare = () => view.root.findByProps({ "aria-label": "Required spare allowance" });
    await act(async () => { threshold().props.onChange({ target: { value: "0" } }); });
    assert.equal(button(view, "Save handoff policy").props.disabled, true, "an invalid threshold is not saved");
    assert.ok(view.root.findAll((node) => node.props.role === "alert").some((node) => /number from 1 to 100/.test(text(node))));
    await act(async () => { threshold().props.onChange({ target: { value: "85" } }); });
    await act(async () => { spare().props.onChange({ target: { value: "30" } }); });
    await act(async () => { view.root.findByProps({ "aria-label": "Allowed requesters" }).props.onChange({ target: { value: "admins_and_owners" } }); });
    assert.match(text(byTestId(view, "agents-handoff-policy-explanation")[0]), /at 85 % or more.*used at most 70 %/s);
    await act(async () => { button(view, "Save handoff policy").props.onClick(); });
    await tick();
    const put = srv.calls.find((call) => call.method === "PUT");
    assert.ok(put.url.endsWith("/api/v1/workspaces/ws-1/agent-gateway/handoff-policy"));
    assert.deepEqual(put.body, { mode: "auto", auto_threshold_pct: 85, require_spare_pct: 30, allowed_requesters: "admins_and_owners" });
    assert.equal(text(byTestId(view, "agents-handoff-policy-message")[0]), "Saved. The handoff policy applies to the next takeover request.");
    assert.equal(text(byTestId(view, "agents-handoff-policy-source")[0]), "This Workspace has its own policy.");
    assert.equal(button(view, "Save handoff policy").props.disabled, true, "saved: nothing left to save");
  } finally { act(() => view.unmount()); }
});

test("rendered card: a 422 names the refused field and keeps the draft; Discard restores the saved policy", async () => {
  const srv = server({ policy: { ...DEFAULT_ANSWER, can_edit: true } });
  srv.state.putAnswer = () => ({ ok: false, status: 422, statusText: "", json: async () => ({ detail: { errors: [{ code: "invalid_percentage", field: "require_spare_pct" }] } }) });
  const view = await renderCard(srv);
  try {
    await act(async () => { radio(view, "auto").props.onChange(); });
    await act(async () => { button(view, "Save handoff policy").props.onClick(); });
    await tick();
    assert.equal(text(byTestId(view, "agents-handoff-policy-message")[0]),
      "Not saved: a percentage is out of range (threshold 1 to 100, spare 0 to 99) (Required spare allowance).");
    assert.equal(radio(view, "auto").props.checked, true, "the draft is kept");
    await act(async () => { button(view, "Discard changes").props.onClick(); });
    assert.equal(radio(view, "confirm").props.checked, true);
    assert.equal(byTestId(view, "agents-handoff-policy-message").length, 0);
  } finally { act(() => view.unmount()); }
});

test("rendered: an automatic handoff is listed as 'Handed over automatically' with its policy; its notification link focuses it", async () => {
  const srv = server();
  const load = loader({ fetch: srv.fetch, window: windowStub("?area=agents&workspace_id=ws-1&takeover_id=t9"), document: documentStub() });
  const { AgentsAreaWorkspace } = load("chat/agents/AgentsAreaWorkspace.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsAreaWorkspace, {
    projects: [{ id: "ws-1", name: "BRD team" }], fallbackWorkspaceId: "ws-1", pollMs: 60_000, boardPollMs: 60_000 })); });
  try {
    await tick();
    assert.ok(srv.calls.some((call) => call.url.endsWith("/takeovers?project_id=ws-1&status=confirmed")));
    const [card] = byTestId(view, "agents-recent-takeover");
    assert.match(card.props.className, /is-focused/, "the info notification's takeover");
    assert.equal(text(byTestId(view, "agents-recent-decision")[0]), "Handed over automatically");
    assert.deepEqual(byTestId(view, "agents-recent-snapshot")[0].findAllByType("li").map(text), ["Workspace handoff mode at the request: automatic"]);
    assert.equal(byTestId(view, "agents-handoff-policy").length, 1, "the policy card is in Claims and handoffs");
  } finally { act(() => view.unmount()); }

  const human = server({ takeovers: { pending: [AUTO_TAKEOVER], confirmed: [{ ...AUTO_TAKEOVER, id: "t8", decided_by: { kind: "human", user: { id: "u-alex", display_name: "Alex" } } },
    { ...AUTO_TAKEOVER, id: "t7", status: "declined", decided_by: { kind: "human", user: { id: "u-alex", display_name: "Alex" } } }] } });
  const humanLoad = loader({ fetch: human.fetch, window: windowStub(), document: documentStub() });
  const { AgentsHandoffs } = humanLoad("chat/agents/AgentsHandoffs.tsx");
  await act(async () => { view = TestRenderer.create(createElement(AgentsHandoffs, { projectId: "ws-1", pollMs: 60_000 })); });
  try {
    await tick();
    assert.deepEqual(byTestId(view, "agents-recent-decision").map(text), ["Confirmed by Alex"], "only confirmed takeovers, whatever the server sends");
    assert.equal(byTestId(view, "agents-recent-snapshot").length, 0, "no policy for a person's decision");
    assert.equal(byTestId(view, "agents-takeover").length, 0, "a confirmed takeover sent as pending is not offered for a decision");
  } finally { act(() => view.unmount()); }
});

// ---- real backend answers ------------------------------------------------------------------------
// tests/unit/fixtures/handoffPolicyBackend.json holds synthetic backend test-client responses for handoff policy.
const REAL = JSON.parse(fs.readFileSync(new URL("./fixtures/handoffPolicyBackend.json", import.meta.url), "utf8"));

test("real backend answers: the policy (floats included) is read; the real refusals name the card's fields", () => {
  assert.deepEqual(json(readHandoffPolicy(REAL.policy_member_default.body)), { policy: { mode: "confirm", autoThresholdPct: 90,
    requireSparePct: 50, allowedRequesters: "members", push: null, autoTriggerPct: null, offerTimeoutMinutes: null }, source: "default", canEdit: false });
  assert.equal(readHandoffPolicy(REAL.policy_owner_default.body).canEdit, true);
  assert.deepEqual(json(readHandoffPolicy(REAL.put_owner.body).policy), { mode: "auto", autoThresholdPct: 85, requireSparePct: 30,
    allowedRequesters: "admins_and_owners", push: null, autoTriggerPct: null, offerTimeoutMinutes: null });
  assert.equal(readHandoffPolicy(REAL.put_owner_partial.body).policy.requireSparePct, 50, "a partial PUT takes the defaults");
  assert.equal(readHandoffPolicy(REAL.policy_member_after.body).source, "workspace");
  assert.equal(policySaveErrorText(REAL.put_invalid.status, REAL.put_invalid.body),
    "Not saved: a percentage is out of range (threshold 1 to 100, spare 0 to 99) (Holder threshold).");
  assert.equal(policySaveErrorText(REAL.put_unknown.status, REAL.put_unknown.body),
    "Not saved: the server does not know one of the fields (Work in progress travels as).", "the 3b server did not know push yet");
  assert.equal(policySaveErrorText(REAL.put_member.status, REAL.put_member.body), "Not saved: only Workspace admins and owners can change the handoff policy.");
  const [auto] = REAL.takeovers_confirmed_ben.items.map(readTakeover);
  assert.equal(decisionLabel(auto), "Handed over automatically");
  assert.deepEqual(snapshotLines(auto), ["Workspace handoff mode at the request: automatic"], "when no snapshot is sent, show the recorded mode");
});

test("real backend answers rendered: a member's card is read-only; the owner's real 422 is shown; the automatic takeover is listed", async () => {
  const member = await renderCard(server({ policy: REAL.policy_member_after.body }));
  try {
    assert.equal(fieldset(member).props.disabled, true);
    assert.equal(radio(member, "auto").props.checked, true);
    assert.equal(member.root.findByProps({ "aria-label": "Holder threshold" }).props.value, 90);
  } finally { act(() => member.unmount()); }
  const srv = server({ policy: REAL.policy_owner_default.body });
  srv.state.putAnswer = () => ({ ok: false, status: 422, statusText: "", json: async () => REAL.put_invalid.body });
  const owner = await renderCard(srv);
  try {
    await act(async () => { radio(owner, "auto").props.onChange(); });
    await act(async () => { button(owner, "Save handoff policy").props.onClick(); });
    await tick();
    assert.equal(text(byTestId(owner, "agents-handoff-policy-message")[0]),
      "Not saved: a percentage is out of range (threshold 1 to 100, spare 0 to 99) (Holder threshold).");
  } finally { act(() => owner.unmount()); }
  const takeovers = server({ takeovers: { pending: REAL.takeovers_pending_ben.items, confirmed: REAL.takeovers_confirmed_ben.items } });
  const load = loader({ fetch: takeovers.fetch, window: windowStub(), document: documentStub() });
  const { AgentsHandoffs } = load("chat/agents/AgentsHandoffs.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsHandoffs, { projectId: REAL.ids.workspace, pollMs: 60_000 })); });
  try {
    await tick();
    assert.deepEqual(byTestId(view, "agents-recent-decision").map(text), ["Handed over automatically"]);
    assert.equal(byTestId(view, "agents-recent-takeover")[0].props["data-takeover-id"], REAL.ids.takeover);
  } finally { act(() => view.unmount()); }
});

// ---- judge-s4 F1: offered, never assigned ----------------------------------------------------------
import { workStateExplanation } from "../../src/chat/agents/handoffPolicyModel.ts";
import * as loadingState from "../../src/layout/LoadingState.ts";

test("judge-s4 F1: the offer time is read, sent back and bounded; the explanation says offered, never assigned", () => {
  const answer = { ...DEFAULT_ANSWER, handoff: { ...DEFAULT_ANSWER.handoff, mode: "auto", push: "branch", auto_trigger_pct: 99, offer_timeout_minutes: 15 } };
  const policy = readHandoffPolicy(answer).policy;
  assert.equal(policy.offerTimeoutMinutes, 15);
  assert.equal(policyBody(policy).offer_timeout_minutes, 15, "a save never resets it to the default");
  assert.equal(readHandoffPolicy({ ...answer, handoff: { ...answer.handoff, offer_timeout_minutes: "15" } }), null);
  assert.equal(readHandoffPolicy(DEFAULT_ANSWER).policy.offerTimeoutMinutes, null, "not in the answer: not shown, not sent");
  assert.equal("offer_timeout_minutes" in policyBody(readHandoffPolicy(DEFAULT_ANSWER).policy), false);
  assert.deepEqual(policyProblems({ ...policy, offerTimeoutMinutes: 1 }), []);
  assert.deepEqual(policyProblems({ ...policy, offerTimeoutMinutes: 1440 }), []);
  assert.equal(policyProblems({ ...policy, offerTimeoutMinutes: 0 }).length, 1);
  assert.equal(policyProblems({ ...policy, offerTimeoutMinutes: 1441 }).length, 1);
  assert.equal(policySaveErrorText(422, { detail: { errors: [{ code: "invalid_minutes", field: "agent_gateway_policy.handoff.offer_timeout_minutes" }] } }),
    "Not saved: the offer time must be from 1 to 1440 minutes (Offer moves on after).");
  const lines = [...policyExplanation(policy), ...workStateExplanation(policy)].join(" ");
  assert.match(lines, /never hands an item to an agent that did not ask for it/);
  assert.match(lines, /offered to the agent with the most spare allowance; if that agent does not ask within 15 minutes, the offer moves to the next one/);
  assert.match(lines, /changes hands only when an agent requests the takeover/);
  assert.match(lines, /the item is offered, never assigned, until an agent asks for it/);
  assert.doesNotMatch(lines, /picks|assigns|hands its work over by itself/i, "no wording that the server chooses or assigns");
});

test("judge-s4 F1 rendered: the admin edits the offer time; it is saved with the rest", async () => {
  const answer = { ...DEFAULT_ANSWER, can_edit: true, handoff: { ...DEFAULT_ANSWER.handoff, mode: "auto", push: "branch", auto_trigger_pct: 99, offer_timeout_minutes: 10 } };
  const srv = server({ policy: answer });
  srv.state.putAnswer = (body) => ({ ok: true, status: 200, statusText: "", json: async () => ({ ...answer, handoff: body }) });
  const view = await renderCard(srv);
  try {
    const field = () => view.root.findByProps({ "aria-label": "Offer moves on after" });
    assert.equal(field().props.value, 10);
    await act(async () => { field().props.onChange({ target: { value: "0" } }); });
    assert.equal(button(view, "Save handoff policy").props.disabled, true);
    await act(async () => { field().props.onChange({ target: { value: "20" } }); });
    await act(async () => { button(view, "Save handoff policy").props.onClick(); });
    await tick();
    assert.equal(srv.calls.find((call) => call.method === "PUT").body.offer_timeout_minutes, 20);
    assert.match(text(byTestId(view, "agents-handoff-policy-explanation")[0]), /within 20 minutes/);
  } finally { act(() => view.unmount()); }
});

test("real judge-s4 policy: offer_timeout_minutes is read (10.0 as 10) and sent back with every other field", () => {
  const JS4 = JSON.parse(fs.readFileSync(new URL("./fixtures/judgeS4Backend.json", import.meta.url), "utf8"));
  const policy = readHandoffPolicy(JS4.policy_owner).policy;
  assert.equal(policy.offerTimeoutMinutes, 10);
  assert.deepEqual(Object.keys(policyBody(policy)).sort(), ["allowed_requesters", "auto_threshold_pct", "auto_trigger_pct", "mode",
    "offer_timeout_minutes", "push", "require_spare_pct"], "every field the server knows, so a save resets nothing");
});
