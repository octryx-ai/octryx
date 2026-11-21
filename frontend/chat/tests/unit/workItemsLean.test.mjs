// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workItemsLean.test.mjs
//
// Work items lean: badges only for exceptions; "Start run" is the primary action and says why it is
// disabled; the run location's sentence stands below its select; repository, branch and run limits live under
// Advanced; "My work" only through an explicit "You in Jira" choice (never matched by e-mail or name), with a clear
// needs-configuration state while the server cannot store it.
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
import { firstException, workItemDetailStatus, workItemExceptions } from "../../src/chat/work/workItemExceptions.ts";
import { advancedOpen, chosenTarget, startRunBlockedReason, targetHelp } from "../../src/chat/work/workItemRunStartModel.ts";
import {
  defaultScope,
  itemsInScope,
  myWorkMessage,
  myWorkStateFrom,
  needsChoice,
  readStoredScope,
  scopeStorageKey,
} from "../../src/chat/work/myWork/myWorkModel.ts";
import { workflowsHref } from "../../src/chat/work/workTransitionModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (root, id) => root.findAll((node) => node.props["data-testid"] === id);
const flush = () => act(async () => { await new Promise((resolve) => setImmediate(resolve)); });

const item = (overrides = {}) => ({
  id: "wi-1", project_id: "ws-1", source_type: "jira", source_key: "BRD-1", title: "Login fix",
  work_state: "development", sync_state: "unchanged", source_status: "In Progress", assignee: "acc-alex",
  assignee_display: "Jane Doe", priority: "High", labels: [], fix_versions: [], ...overrides,
});
const eligibility = (overrides = {}) => ({
  requested: true, can_start: true, mode: "direct", trigger_label: "", trigger_labels: [], matched_labels: [],
  blocking_reasons: [], review_reasons: [], reason_codes: [], policy_source: "", ...overrides,
});

function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Intl, Promise,
      encodeURIComponent, performance, setTimeout, clearTimeout,
      window: { location: { origin: "http://localhost", assign: () => {} }, localStorage: { getItem: () => null } }, ...extra,
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
  return loadFile(path.join(SRC, relative));
}

function server(routes) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ url: String(url), method: init.method || "GET", body });
    const answer = routes(String(url), init.method || "GET", body);
    return { ok: answer.status < 400, status: answer.status, statusText: "", json: async () => answer.body };
  };
  return { fetch, calls };
}

test("exceptions only: an ordinary item has no badge; blocked, agent, review, sync and unmapped each name themselves", () => {
  assert.deepEqual(workItemExceptions(item()), [], "Human only, unchanged sync and a normal state are no exception");
  assert.deepEqual(workItemExceptions(item({ automation_eligibility: eligibility() })).map((entry) => entry.label), ["Agent may start"]);
  assert.deepEqual(workItemExceptions(item({ automation_eligibility: eligibility({ mode: "needs_review" }) })).map((entry) => entry.label),
    ["Agent may start · review"]);
  assert.deepEqual(workItemExceptions(item({ automation_eligibility: eligibility({ blocking_reasons: ["no_plan"] }) })).map((entry) => entry.key),
    ["blocked"], "a blocked item never also says the agent may start");
  assert.deepEqual(workItemExceptions(item({ sync_state: "removed_from_source_filter", status_mapping: { source: "unmapped" } }))
    .map((entry) => entry.label), ["Removed from the Jira filter", "Status not mapped"]);
  assert.equal(firstException(item({ work_state: "blocked", sync_state: "conflict" })).label, "Blocked");
  assert.equal(firstException(item()), null);
  for (const state of ["done", "Done", "closed", "cancelled"]) {
    assert.deepEqual(workItemExceptions(item({ work_state: state,
      automation_eligibility: eligibility({ mode: "blocked", blocking_reasons: ["missing_acceptance_criteria"] }) })), [],
    `a ${state} item is neither blocked nor startable`);
  }
  assert.deepEqual(workItemExceptions(item({ work_state: "done", sync_state: "conflict" })).map((entry) => entry.key), ["sync"],
    "a finished item still names a sync problem");
  assert.equal(workItemDetailStatus(item()), "Jira: In Progress · development · Priority High");
  assert.equal(workItemDetailStatus(item({ source_status: "", priority: null, work_state: "ready_for_plan" })), "No Jira status · ready for plan");
});

test("rendered board card: key, title, the assignee, and badges only for exceptions; the column names the state", () => {
  const { WorkBoard } = load("chat/work/WorkAreaViews.tsx");
  let view;
  const items = [item(), item({ id: "wi-2", source_key: "BRD-2", automation_eligibility: eligibility() })];
  act(() => { view = TestRenderer.create(createElement(WorkBoard, { items, syncConfigs: [], onOpenItem: () => {}, workflows: [] })); });
  const cards = view.root.findAll((node) => node.type === "button" && node.props.className === "work-card");
  const card = (key) => cards.find((entry) => text(entry).includes(key));
  assert.equal(byTestId(card("BRD-1"), "work-exception").length, 0);
  assert.deepEqual(byTestId(card("BRD-2"), "work-exception").map(text), ["Agent may start"]);
  assert.match(text(card("BRD-1")), /^BRD-1Login fixJane Doe$/, "no state badge: the card's column already names it");
  const column = view.root.findAll((node) => node.type === "section" && node.props.className === "work-board__column")
    .find((section) => text(section).includes("BRD-1"));
  assert.match(text(column.findByType("header")), /^Development/, "our state is the column, never the raw Jira status");
  assert.doesNotMatch(text(view.root), /In Progress/);
  assert.doesNotMatch(text(view.root), /Human only|unchanged/);
  act(() => view.unmount());
});

test("start run: the reason while it cannot start, the run location's sentence, Advanced only opens with a value", () => {
  assert.equal(startRunBlockedReason("", false, "ws-1"), "Choose a workflow first");
  assert.equal(startRunBlockedReason("deliver", false, "ws-1"), null);
  assert.equal(startRunBlockedReason("deliver", true, "ws-1"), "Starting…");
  assert.match(startRunBlockedReason("deliver", false, null), /no Workspace: move it to a Workspace/);
  const targets = { default: "auto", options: [
    { key: "auto", label: "Automatic", target: { kind: "auto" }, help: "Uses a free seat on your device first." },
    { key: "d1", label: "Mac · /src · seat (offline: the run waits for it)", target: { kind: "device", device_id: "d1", folder: "/src" }, online: false },
  ] };
  assert.equal(targetHelp(chosenTarget(targets, "")), "Uses a free seat on your device first.");
  assert.equal(targetHelp(chosenTarget(targets, "d1")), "This device is offline; the run waits for it.");
  assert.equal(advancedOpen("", "", ""), false);
  assert.equal(advancedOpen("", "feature/x", ""), true);
  assert.equal(workflowsHref("ws 1"), "/chat?area=workflows&tab=workflowList&workspace_id=ws+1");
});

test("rendered start run: disabled and neutral with its reason, primary once a workflow is chosen; limits under Advanced", async () => {
  const srv = server((url) => {
    if (url.includes("/startable")) return { status: 200, body: { workflows: [{ key: "deliver", title: "Deliver" }] } };
    if (url.includes("/runtime-targets")) {
      return { status: 200, body: { default: "auto", options: [{ key: "auto", label: "Automatic", target: { kind: "auto" },
        help: "Uses a free seat on your device first." }] } };
    }
    return { status: 404, body: {} };
  });
  const { WorkItemRunStart } = load("chat/work/WorkItemRunStart.tsx", { fetch: srv.fetch });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(WorkItemRunStart, { item: item() })); });
  await flush();
  const start = () => byTestId(view.root, "work-run-start-button")[0];
  assert.equal(start().props.disabled, true);
  assert.equal(start().props.className, "work-area__button", "a button that cannot reach its goal is neutral (A1)");
  assert.equal(text(byTestId(view.root, "work-run-start-reason")[0]), "Choose a workflow first");
  assert.equal(text(byTestId(view.root, "work-run-target-help")[0]), "Uses a free seat on your device first.");
  const advanced = byTestId(view.root, "work-run-advanced")[0];
  assert.equal(advanced.props.open, undefined, "Advanced starts closed");
  assert.deepEqual(advanced.findAll((node) => node.type === "label").map(text), ["Repository", "Branch to review", "Rounds per loop", "Cost budget (USD)"]);
  assert.ok(advanced.findAll((node) => node.type === "input").every((node) => node.props.placeholder.startsWith("e.g. ")));
  const save = advanced.find((node) => node.type === "button" && text(node) === "Save run limits");
  assert.equal(save.props.className, "work-area__button", "Save run limits stays neutral");
  act(() => view.root.find((node) => node.type === "select" && node.props.id === "run-start-wi-1").props.onChange({ target: { value: "deliver" } }));
  assert.equal(start().props.disabled, false);
  assert.equal(start().props.className, "work-area__button work-area__button--primary");
  assert.equal(byTestId(view.root, "work-run-start-reason").length, 0);
  act(() => view.unmount());
});

test("my work state: 404 needs configuration, no choice asks, a choice filters by the Jira account id only", () => {
  assert.deepEqual(myWorkStateFrom(404, { detail: "Not Found" }), { kind: "unavailable" });
  assert.deepEqual(myWorkStateFrom(200, { account_id: null }), { kind: "unset" });
  assert.equal(myWorkStateFrom(422, { detail: { code: "unknown_jira_account", message: "x" } }).message,
    "This person has no Jira items in this Workspace. Choose someone from the list.");
  const set = myWorkStateFrom(200, { source_type: "jira", account_id: "acc-alex", display_name: "Jane Doe" });
  assert.deepEqual(set, { kind: "set", identity: { accountId: "acc-alex", displayName: "Jane Doe" } });
  assert.deepEqual(myWorkStateFrom(500, { detail: { message: "Database busy" } }), { kind: "error", message: "Database busy" });
  // Review: the page opens on My work; without a choice My work asks for it (the next step).
  assert.equal(defaultScope(set), "mine");
  assert.equal(defaultScope({ kind: "unset" }), "mine");
  assert.equal(defaultScope({ kind: "loading" }), "mine");
  assert.equal(defaultScope(set, "all"), "all", "the person's last choice wins");
  assert.equal(defaultScope({ kind: "unset" }, "all"), "all");
  assert.equal(defaultScope({ kind: "unavailable" }, "mine"), "all", "a server that cannot keep the choice opens on all items");
  assert.equal(defaultScope({ kind: "error", message: "x" }), "all");
  assert.equal(readStoredScope("mine"), "mine");
  assert.equal(readStoredScope("everything"), null);
  assert.equal(readStoredScope(null), null);
  assert.equal(scopeStorageKey("ws-1"), "octryx.work.scope.ws-1");
  const items = [item(), item({ id: "wi-2", assignee: "acc-anna", assignee_display: "Jane Doe" })];
  assert.deepEqual(itemsInScope(items, "mine", set).map((entry) => entry.id), ["wi-1"], "same display name, other account: not mine");
  assert.deepEqual(itemsInScope(items, "mine", { kind: "unset" }), [], "no choice, no guess");
  assert.equal(itemsInScope(items, "all", { kind: "unset" }).length, 2);
  assert.equal(needsChoice("mine", { kind: "unavailable" }), true);
  assert.equal(needsChoice("mine", set), false);
  assert.equal(needsChoice("mine", set, true), true, "changing the choice shows the picker again");
  assert.match(myWorkMessage({ kind: "unavailable" }), /^My work needs configuration/);
});

test("rendered my work panel: the person picks their Jira account; the save sends the id; unavailable says so", async () => {
  const srv = server((url, method, body) => {
    if (url === "/api/v1/workspaces/ws-1/work/me" && method === "PUT") {
      return { status: 200, body: { source_type: "jira", account_id: body.account_id, display_name: "Anna" } };
    }
    return { status: 404, body: { detail: "Not Found" } };
  });
  const { WorkMyWorkPanel } = load("chat/work/myWork/WorkMyWork.tsx", { fetch: srv.fetch });
  const chosen = [];
  const myWork = (state) => ({ state, scope: "mine", setScope: () => {}, changing: false, setChanging: () => {}, busy: false,
    choose: async (id) => { chosen.push(id); }, clear: async () => {}, retry: () => {} });
  const items = [item(), item({ id: "wi-2", assignee: "acc-anna", assignee_display: "Anna" })];
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkMyWorkPanel, { myWork: myWork({ kind: "unset" }), items })); });
  assert.match(text(view.root), /Choose who you are in Jira/);
  const select = byTestId(view.root, "work-my-work-person")[0];
  assert.deepEqual(select.findAll((node) => node.type === "option").map(text), ["Choose a person", "Anna", "Jane Doe"]);
  assert.equal(byTestId(view.root, "work-my-work-save")[0].props.disabled, true);
  act(() => select.props.onChange({ target: { value: "acc-anna" } }));
  await act(async () => { byTestId(view.root, "work-my-work-save")[0].props.onClick(); });
  assert.deepEqual(chosen, ["acc-anna"]);
  act(() => view.update(createElement(WorkMyWorkPanel, { myWork: myWork({ kind: "unavailable" }), items })));
  assert.match(text(view.root), /My work is not available.*needs configuration/);
  assert.equal(byTestId(view.root, "work-my-work-person").length, 0, "no picker while the server cannot store the choice");
  act(() => view.unmount());

  const { saveMyWork } = load("chat/work/myWork/myWorkApi.ts", { fetch: srv.fetch });
  assert.deepEqual(JSON.parse(JSON.stringify(await saveMyWork("ws-1", "acc-anna"))), { kind: "set", identity: { accountId: "acc-anna", displayName: "Anna" } });
  assert.deepEqual(srv.calls.at(-1), { url: "/api/v1/workspaces/ws-1/work/me", method: "PUT", body: { source_type: "jira", account_id: "acc-anna" } });
});

test("rendered transition without a workflow: says what to do, with a link to Agents › Workflows", () => {
  const { WorkItemTransition } = load("chat/work/WorkItemTransition.tsx");
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkItemTransition, { item: item(), workflows: [] })); });
  const note = byTestId(view.root, "transition-no-workflow")[0];
  assert.match(text(note), /^No active workflow covers this item yet, so it cannot be moved here\. Publish a workflow for it in Agents › Workflows, then move it here\.$/);
  assert.equal(note.findByType("a").props.href, "/chat?area=workflows&tab=workflowList&workspace_id=ws-1");
  act(() => view.unmount());
});
