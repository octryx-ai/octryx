// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/destructiveRowActions.test.mjs
//
// Destructive actions: a row keeps its main actions; Edit, Pause, Delete and the like sit in its
// ⋯ menu, named after the object, danger items last; destructive actions confirm in the page naming the object and
// say afterwards what happened. Requests are stubs; names invented.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
const button = (view, label) => view.root.findAll((node) => node.type === "button" && text(node) === label)[0];

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
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, ...extra,
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


// One connector of an existing Workspace; the listing is re-read after each change.
const CONNECTOR = {
  connector_key: "jira-shop", kind: "jira", state: "active", running: false, products: [], version: null,
  max_items_per_run: 100, scope: { project_keys: ["SHOP"] }, schedule: { enabled: false, interval_minutes: 60, next_run_at: null },
  cursor: { pass_number: 0, pass_started_at: null, completed_passes: 0, last_completed_at: null }, last_run: null,
};

async function mountWithConnector() {
  const calls = [];
  let connectors = [CONNECTOR];
  const fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method || "GET" });
    if ((init.method || "GET") === "DELETE") { connectors = []; return { ok: true, status: 200, json: async () => ({ retained_sources: 3 }) }; }
    if ((init.method || "GET") === "PUT") { connectors = [{ ...CONNECTOR, state: "paused" }]; return { ok: true, status: 200, json: async () => connectors[0] }; }
    return { ok: true, status: 200, json: async () => ({ connectors, may_author: true, knowledge: { state: "ready" } }) };
  };
  const confirms = [];
  const events = { addEventListener() {}, removeEventListener() {} };
  const load = loader({ fetch, document: events, window: { ...events, confirm: (text) => { confirms.push(text); return true; }, innerWidth: 1400 } });
  const { KnowledgeConnectorsPanel } = load("admin/components/workspaceKnowledge/KnowledgeConnectorsPanel.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(KnowledgeConnectorsPanel, { workspaceId: "ws-1" })); });
  await act(async () => {});
  return { view, calls, confirms };
}

const openRowMenu = async (view, name) => {
  const trigger = view.root.find((node) => node.type === "button" && node.props["aria-label"] === `More actions for ${name}`);
  await act(async () => trigger.props.onClick({ currentTarget: { getBoundingClientRect: () => ({ bottom: 100, right: 900 }) } }));
  return view.root.findAll((node) => node.props.role === "menuitem").map((node) => text(node));
};

test("a source row opens its panel; Sync now, Pause, Edit and Releases sit in its ⋯ menu, Remove last", async () => {
  const { view } = await mountWithConnector();
  const row = view.root.find((node) => node.type === "tr" && node.props["data-row-key"] === "jira-shop");
  assert.equal(row.findAll((node) => node.type === "button" && !node.props["aria-haspopup"]).length, 0, "no buttons in the row itself");
  assert.deepEqual(await openRowMenu(view, "jira-shop"), ["Sync now", "Pause", "Edit", "Releases", "Remove"]);
  act(() => view.unmount());
});

test("Remove confirms in the page naming the source, then says what happened; no browser confirm", async () => {
  const { view, calls, confirms } = await mountWithConnector();
  await openRowMenu(view, "jira-shop");
  await act(async () => view.root.find((node) => node.props.role === "menuitem" && text(node) === "Remove").props.onClick());
  const dialog = view.root.find((node) => node.props.role === "alertdialog");
  assert.match(text(dialog), /^Remove source jira-shop\?/);
  await act(async () => button(view, "Remove jira-shop").props.onClick());
  await act(async () => {});
  assert.ok(calls.some((call) => call.method === "DELETE" && call.url.endsWith("/connectors/jira-shop")));
  assert.match(text(byTestId(view, "action-done")[0]), /^Source jira-shop removed\./);
  assert.equal(view.root.findAll((node) => node.props.role === "alertdialog").length, 0);
  assert.deepEqual(confirms, [], "never window.confirm");
  act(() => view.unmount());
});

test("Pause confirms in the page; nothing is sent before the confirmation", async () => {
  const { view, calls } = await mountWithConnector();
  await openRowMenu(view, "jira-shop");
  await act(async () => view.root.find((node) => node.props.role === "menuitem" && text(node) === "Pause").props.onClick());
  assert.equal(calls.filter((call) => call.method === "PUT").length, 0);
  assert.match(text(view.root.find((node) => node.props.role === "alertdialog")), /^Pause source jira-shop\?/);
  await act(async () => button(view, "Pause jira-shop").props.onClick());
  await act(async () => {});
  assert.equal(calls.filter((call) => call.method === "PUT").length, 1);
  assert.match(text(byTestId(view, "action-done")[0]), /^Source jira-shop paused\./);
  act(() => view.unmount());
});

test("my files hold no browser confirm or alert for destructive actions", () => {
  for (const file of ["admin/components/workspaceKnowledge/KnowledgeConnectorsPanel.tsx", "admin/components/workspaceKnowledge/sources/KnowledgeSourceList.tsx",
    "admin/components/AdminUsersTab.tsx", "admin/components/usersTab/adminRoleActions.ts", "admin/components/usersTab/adminGroupActions.ts",
    "admin/components/usersTab/adminUserActions.tsx", "admin/components/usersTab/AdminUserAccountsTable.tsx"]) {
    const source = fs.readFileSync(path.join(SRC, file), "utf8");
    assert.doesNotMatch(source, /\bconfirm\(|\balert\(/, file);
  }
  const hook = fs.readFileSync(path.join(SRC, "admin/hooks/useAdminBootstrapUserApproval.ts"), "utf8");
  const deactivate = hook.slice(hook.indexOf("const handleDeactivateUser"), hook.indexOf("const handleRoleChange"));
  assert.doesNotMatch(deactivate, /confirm\(|alert\(/);
});

test("a user row keeps Edit; Deactivate sits in the ⋯ menu named after the person", async () => {
  const events = { addEventListener() {}, removeEventListener() {} };
  const load = loader({ window: { ...events, innerWidth: 1400 }, document: events });
  const { AdminUserAccountsTable } = load("admin/components/usersTab/AdminUserAccountsTable.tsx");
  const toggled = [];
  const users = [
    { id: "u1", username: "anna", display_name: "Anna Muster", email: "anna@example.test", roles: ["member"], groups: [], is_active: true },
    { id: "u2", username: "ben", display_name: "", email: "ben@example.test", roles: [], groups: [], is_active: false },
  ];
  let view;
  act(() => { view = TestRenderer.create(createElement(AdminUserAccountsTable, { users, currentUserId: "admin", userActionLoading: null,
    onEditUser: () => {}, onToggleUserStatus: (user) => toggled.push(user.id) })); });
  assert.deepEqual(await openRowMenu(view, "Anna Muster"), ["Deactivate"]);
  await act(async () => view.root.find((node) => node.props.role === "menuitem" && text(node) === "Deactivate").props.onClick());
  assert.deepEqual(toggled, ["u1"]);
  assert.deepEqual(await openRowMenu(view, "ben"), ["Reactivate"], "without a display name the username names the row");
  act(() => view.unmount());
});
