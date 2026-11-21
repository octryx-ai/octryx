// E5 Problems (backend): one table of what is broken with the one place to fix it.
// Counts ignore the kind/severity filters; refusals read as one sentence; fix links stay inside the app.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import {
  countText,
  kindTabs,
  problemsQuery,
  readProblems,
  refusalText,
  safeFixHref,
  severityTabs,
} from "../../src/admin/components/problems/problemsModel.ts";
import { connectorToFocus, focusedConnectorName } from "../../src/admin/components/connectorsTab/connectorFocus.ts";
import { ADMIN_PAGE_PURPOSE } from "../../src/admin/config/pagePurpose.ts";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));

const PAYLOAD = {
  problems: [
    { key: "connection:c1:auth", kind: "connection", severity: "problem", title: "Jira Cloud: sign-in fails",
      since: "2026-11-06T08:12:00+00:00", last_seen: "2026-11-06T10:00:00+00:00", count: 14,
      workspace: { id: "ws_1", name: "Acme Orders" }, object: { type: "connection", id: "c1", name: "Jira Cloud" },
      fix: { label: "Open the connection", href: "/chat?area=admin&tab=connectors&connector=jira&workspace_id=ws_1" } },
    { key: "rule_denial:r1:deny", kind: "rule_denial", severity: "attention", title: "Agent may not push: 3 denials",
      since: "2026-11-05T08:00:00+00:00", last_seen: null, count: 3, workspace: null, object: null,
      fix: { label: "Open the rule", href: "https://evil.example/steal" } },
    { key: "", title: "dropped without key" },
  ],
  counts: { problem: 4, attention: 7, by_kind: { connection: 2, rule_denial: 5, run: 4, sync: 0 } },
};

test("the model reads the contract, drops foreign fix links and rows without a key", () => {
  const { problems, counts } = readProblems(PAYLOAD);
  assert.equal(problems.length, 2);
  assert.deepEqual(problems[0].fix, { label: "Open the connection", href: "/chat?area=admin&tab=connectors&connector=jira&workspace_id=ws_1" });
  assert.equal(problems[1].fix, null, "an absolute URL is not followed");
  assert.equal(problems[1].workspace, null);
  assert.deepEqual(counts, { problem: 4, attention: 7, byKind: { connection: 2, rule_denial: 5, run: 4, sync: 0 } });
  for (const bad of ["https://x.test", "//x.test/a", "/\\x.test", "javascript:alert(1)", ""]) assert.equal(safeFixHref(bad), null, bad);
  assert.equal(safeFixHref("/chat?area=work"), "/chat?area=work");
  assert.equal(countText(14), "14×");
  assert.equal(countText(1), "once");
  assert.ok(ADMIN_PAGE_PURPOSE.adminProblems);
});

test("segments use the server's totals, which ignore the filters; the query leaves empty filters out", () => {
  const { counts } = readProblems(PAYLOAD);
  assert.deepEqual(kindTabs(counts).map((tab) => `${tab.label}:${tab.count}`), ["All:11", "Connections:2", "Runs:4", "Rule denials:5"]);
  assert.deepEqual(severityTabs(counts).map((tab) => tab.count), [11, 4, 7]);
  const labels = [...kindTabs(counts), ...severityTabs(counts)].map((tab) => tab.label);
  assert.equal(labels.filter((label) => label === "All").length, 1, "one All across both groups");
  assert.equal(problemsQuery({}), "");
  assert.equal(problemsQuery({ workspaceId: "ws_1", kind: "run", severity: "" }), "?workspace_id=ws_1&kind=run");
});

test("refusals read as one sentence", () => {
  assert.equal(refusalText(403, "admin_required", "x"), "Only admins can see the problems of the platform.");
  assert.equal(refusalText(404, "workspace_not_found", "x"), "This Workspace is not visible to you.");
  assert.equal(refusalText(422, "invalid_filter", "x"), "This filter is not known. Choose All to see every problem.");
  assert.equal(refusalText(404, "problem_not_found", "x"), "This problem is no longer open.");
  assert.equal(refusalText(500, "", "Database is down."), "Database is down.");
});

test("a Problems link opens the named connector", () => {
  assert.equal(focusedConnectorName("?area=admin&tab=connectors&connector=jira"), "jira");
  assert.equal(focusedConnectorName(""), "");
  const connectors = [{ tool_name: "confluence" }, { tool_name: "jira" }];
  assert.deepEqual(connectorToFocus(connectors, "?connector=jira"), { tool_name: "jira" });
  assert.equal(connectorToFocus(connectors, "?connector=github"), null);
});

function makeLoader(stubs, sandbox) {
  const cache = new Map();
  const load = (file) => {
    if (cache.has(file)) return cache.get(file);
    const exports = {};
    cache.set(file, exports);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    vm.runInNewContext(output, { exports, ...sandbox, require: (name) => resolve(name, path.dirname(file)) });
    return exports;
  };
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name.endsWith(suffix));
    if (stub) return stub[1];
    if (!name.startsWith(".")) return require(name);
    const base = path.resolve(dir, name);
    const file = [".tsx", ".ts"].map((ext) => base + ext).find((candidate) => fs.existsSync(candidate));
    return load(file);
  };
  return (relative) => load(path.join(SRC, relative));
}

function server(handler) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url, method: init.method ?? "GET" });
    const [status, body] = handler(url, init);
    return { ok: status >= 200 && status < 300, status, json: async () => body };
  };
  return { fetch, calls };
}

const sandboxWith = (fetch) => ({
  fetch,
  window: { innerWidth: 1400, addEventListener() {}, removeEventListener() {}, location: { search: "" } },
  document: { addEventListener() {}, removeEventListener() {}, activeElement: null },
  console, Error, Promise, Set, Map, URLSearchParams, setTimeout, clearTimeout,
});

const actionMenuStub = { ActionMenu: ({ items }) => createElement("span", { "data-testid": "row-menu" },
  items.map((item) => createElement("button", { key: item.label, type: "button", onClick: item.onSelect }, item.label))) };

// The active Workspace the global switch sets; "" = none chosen.
let activeWorkspace = "";
const activeWorkspaceStub = { useActiveWorkspace: () => [activeWorkspace, () => {}] };
const chooseStub = { ChooseWorkspaceLine: () => createElement("p", { "data-testid": "choose-workspace" }, "Choose a workspace") };

async function render(handler, component = "AdminProblemsPage", props = { projects: [{ id: "ws_1", name: "Acme Orders" }], isAdmin: true }) {
  const srv = server(handler);
  const load = makeLoader({ "/workflowSurfaces/ActionMenu": actionMenuStub, "/chat/useActiveWorkspace": activeWorkspaceStub,
    "/workspace/ChooseWorkspaceLine": chooseStub }, sandboxWith(srv.fetch));
  const module = component === "AdminProblemsPage"
    ? load("admin/components/problems/AdminProblemsPage.tsx") : load("admin/components/problems/ProblemsView.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(module[component], props)); });
  await act(async () => {});
  return { view, srv };
}

const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);

test("rendered Admin › Problems: table, fix link, filters send their query, hide reloads", async () => {
  let hidden = false;
  const { view, srv } = await render((url, init) => {
    if (url.includes("/acknowledge")) { hidden = true; return [200, { key: "connection:c1:auth", acknowledged: true }]; }
    return [200, hidden ? { problems: [PAYLOAD.problems[1]], counts: PAYLOAD.counts } : PAYLOAD];
  });
  const table = byTestId(view, "problems-table")[0];
  assert.match(text(table), /ProblemJira Cloud: sign-in failsAcme Orders/);
  assert.match(text(table), /14×/);
  assert.match(text(table), /AttentionAgent may not push: 3 denialsPlatform/);
  const fixes = byTestId(view, "problems-fix");
  assert.equal(fixes.length, 1, "the foreign link is not rendered");
  assert.equal(fixes[0].props.href, "/chat?area=admin&tab=connectors&connector=jira&workspace_id=ws_1");
  assert.equal(srv.calls[0].url, "/api/v1/admin/problems");

  // No own Workspace dropdown: without an active Workspace a platform admin sees all.
  assert.equal(byTestId(view, "problems-workspace").length, 0);

  const hide = view.root.findAll((node) => node.type === "button" && text(node) === "Hide until it happens again")[0];
  await act(async () => { hide.props.onClick(); });
  await act(async () => {});
  assert.equal(srv.calls.find((call) => call.method === "POST").url, "/api/v1/admin/problems/connection%3Ac1%3Aauth/acknowledge");
  assert.match(text(byTestId(view, "problems-notice")[0]), /^Hidden until it happens again: Jira Cloud/);
  assert.doesNotMatch(text(byTestId(view, "problems-table")[0]), /sign-in fails/);
  act(() => view.unmount());
});

test("Problems follows the active Workspace; only platform admins can widen it to All workspaces", async () => {
  activeWorkspace = "ws_1";
  try {
    const admin = await render(() => [200, PAYLOAD]);
    assert.equal(admin.srv.calls[0].url, "/api/v1/admin/problems?workspace_id=ws_1");
    const tabs = byTestId(admin.view, "problems-scope")[0].findAll((node) => node.props.role === "tab");
    assert.deepEqual(tabs.map(text), ["Acme Orders", "All workspaces"]);
    await act(async () => { tabs[1].props.onClick(); });
    await act(async () => {});
    assert.equal(admin.srv.calls.at(-1).url, "/api/v1/admin/problems");
    act(() => admin.view.unmount());

    const member = await render(() => [200, PAYLOAD], "AdminProblemsPage", { projects: [{ id: "ws_1", name: "Acme Orders" }] });
    assert.equal(member.srv.calls[0].url, "/api/v1/admin/problems?workspace_id=ws_1");
    assert.equal(byTestId(member.view, "problems-scope").length, 0, "no All workspaces for a Workspace admin");
    act(() => member.view.unmount());
  } finally {
    activeWorkspace = "";
  }
  const none = await render(() => [200, PAYLOAD], "AdminProblemsPage", { projects: [{ id: "ws_1", name: "Acme Orders" }] });
  assert.equal(none.srv.calls.length, 0, "nothing is guessed");
  assert.equal(byTestId(none.view, "choose-workspace").length, 1);
  act(() => none.view.unmount());
});

test("rendered states: no problems is one line; a refusal is one sentence with Try again", async () => {
  const empty = await render(() => [200, { problems: [], counts: { problem: 0, attention: 0, by_kind: {} } }]);
  assert.equal(text(byTestId(empty.view, "problems-empty")[0]), "No problems.");
  act(() => empty.view.unmount());

  const denied = await render(() => [403, { detail: { code: "admin_required", message: "Admins only." } }]);
  assert.match(text(byTestId(denied.view, "problems-error")[0]), /^Only admins can see the problems of the platform\.Try again$/);
  act(() => denied.view.unmount());
});

test("rendered Workspace problems: members' endpoint, no Workspace column, no hide menu", async () => {
  const { view, srv } = await render(() => [200, PAYLOAD], "WorkspaceProblems", { workspaceId: "ws_1" });
  assert.equal(srv.calls[0].url, "/api/v1/workspaces/ws_1/problems");
  assert.doesNotMatch(text(byTestId(view, "problems-table")[0]), /Acme Orders|Platform/);
  assert.equal(byTestId(view, "row-menu").length, 0);
  act(() => view.unmount());

  const missing = await render(() => [404, { detail: { code: "workspace_not_found", message: "x" } }], "WorkspaceProblems", { workspaceId: "ws_x" });
  assert.match(text(byTestId(missing.view, "problems-error")[0]), /^This Workspace is not visible to you\./);
  act(() => missing.view.unmount());
});
