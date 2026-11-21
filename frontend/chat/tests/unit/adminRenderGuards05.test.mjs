// Render guards for admin list pages split into smaller functions: a REST API's operations with the add form, the
// REST API calls audit with its filters, the Operations costs table, the knowledge bindings of a Workspace and the
// MCP server "allow in Workspaces" drawer render the same structure.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, byTestId, text, tick } from "./settingsRenderHarness.mjs";
import { all, buttons, create, createAsync, includesAll, noop, plain, testIds } from "./adminGuardRenderers.mjs";
import { jsonRoutes, loadStubbed, stubs } from "./adminGuardStubLoader.mjs";

const op = (patch) => ({ id: "o1", op_key: "list", method: "GET", path: "/tickets", tool_name: "rest__demo__list", is_read: true,
  capability: null, enabled: true, grants: [{}], ...patch });

test("the operations list shows each operation and adds one by hand", async () => {
  const added = [];
  const api = { addOperation: async (id, body) => { added.push(["add", id, body]); return { id: "o9" }; },
    updateOperation: async (id, opId, body) => { added.push(["put", id, opId, body]); } };
  const { RestOperationList } = loadStubbed("admin/components/restApis/RestOperationList.tsx", [], {}, { "./restApisApi": api });
  const opened = [];
  let reloads = 0;
  const definition = { id: "d1", operations: [op(), op({ id: "o2", op_key: "close", method: "POST", path: "/tickets/{id}/close",
    is_read: false, capability: "change", enabled: false, grants: [] })] };
  const view = create(createElement(RestOperationList, { definition, onOpen: (id) => opened.push(id), onAdded: () => { reloads += 1; } }));
  includesAll(text(view.root), ["Method", "Path and tool", "Kind", "State", "Grants", "GET", "/tickets", "rest__demo__list", "Read",
    "Write · Change", "On", "Off", "1 grant", "No grants", "Add an operation by hand", "Operation key", "Path", "Query parameters (optional)",
    "Template (optional)", "Summary (optional)", "Add operation"]);
  assert.deepEqual(testIds(view), ["rest-operation-table", "rest-op-kind-list", "rest-op-kind-close", "rest-writes-note", "rest-add-operation",
    "rest-add-operation-template"]);
  assert.equal(all(view, "option").length, 6 + 1 + 3);
  act(() => all(view, "tr")[2].props.onClick());
  assert.deepEqual(opened, ["o2"]);
  const add = () => all(view, "button").find((node) => text(node) === "Add operation");
  assert.equal(add().props.disabled, true);
  const inputs = () => all(view, "input");
  act(() => inputs()[0].props.onChange({ target: { value: "get_one" } }));
  act(() => inputs()[1].props.onChange({ target: { value: "/tickets/{id}" } }));
  act(() => byTestId(view, "rest-add-operation-template")[0].props.onChange({ target: { value: all(view, "option")[8].props.value } }));
  assert.equal(add().props.disabled, false);
  await act(async () => add().props.onClick());
  await tick();
  assert.equal(added.length, 2);
  assert.equal(added[1][2], "o9");
  assert.equal(reloads, 1);
  assert.equal(inputs()[0].props.value, "");
  act(() => all(view, "select")[0].props.onChange({ target: { value: "POST" } }));
  assert.equal(byTestId(view, "rest-add-operation-template").length, 0);

  const empty = create(createElement(RestOperationList, { definition: { id: "d2" }, onOpen: noop, onAdded: noop }));
  assert.deepEqual(testIds(empty), ["rest-operations-empty", "rest-add-operation", "rest-add-operation-template"]);
});

const call = (patch) => ({ id: "c1", tool_name: "rest__demo__list", identity: "svc", status: "succeeded", failure_category: "",
  http_status: 200, scope: { role: "dev", params: { a: 1 } }, records: 4, dropped_out_of_scope: 1, duration_ms: 1500, user_id: "u1",
  workspace_id: "w1", connection_id: null, started_at: "2026-03-04T05:06:07Z", error: "", user_name: "Ann", workspace_name: "Harbor", ...patch });

test("the REST API calls page lists the audited calls with filters", async () => {
  const lists = [];
  const api = {
    listCalls: async (query) => { lists.push(query); return [call(), call({ id: "c2", status: "failed", http_status: null, error: "boom",
      user_id: null, user_name: null, workspace_id: "w9", workspace_name: null, scope: { role: null }, approval_id: "ap-123456789" })]; },
    listDefinitions: async () => [{ id: "d1", name: "Tickets" }],
    loadDefinition: async () => ({ operations: [{ id: "o1", op_key: "list", llm_name: "" }] }),
  };
  const { RestApiCallsPage } = loadStubbed("admin/components/restApis/RestApiCallsPage.tsx", [], { window: { location: { search: "?rest_api=d1" } } },
    { "./restApisApi": api });
  const view = await createAsync(createElement(RestApiCallsPage));
  includesAll(text(view.root), ["All APIs", "Tickets", "All operations", "list", "Writes only", "Reload", "Time and duration", "1.5 s",
    "User and Workspace", "Ann", "Harbor", "Unknown", "Removed Workspace", "demo › list", "Succeeded", "Failed", "boom", "Admitted by",
    "Approval ›", "ap-12345", "4 / 1", "dev · 1 limit", "None applied", "Every call runs as the connection's technical account"]);
  assert.deepEqual(testIds(view), ["rest-calls-page", "rest-calls-api", "rest-calls-operation", "rest-calls-writes-only", "rest-calls-reload",
    "rest-calls-table", "rest-call-error", "rest-call-admission"]);
  assert.equal(all(view, "tr").length, 3);
  assert.equal(lists[0], "limit=200&definition_id=d1");
  act(() => byTestId(view, "rest-calls-writes-only")[0].props.onChange({ target: { checked: true } }));
  assert.equal(all(view, "tr").length, 2);
  await act(async () => byTestId(view, "rest-calls-api")[0].props.onChange({ target: { value: "" } }));
  await tick();
  assert.equal(lists.at(-1), "limit=200");
  assert.equal(byTestId(view, "rest-calls-operation")[0].props.disabled, true);
  await act(async () => byTestId(view, "rest-calls-reload")[0].props.onClick());
  await tick();
  assert.equal(lists.length, 3);

  const none = await createAsync(createElement(loadStubbed("admin/components/restApis/RestApiCallsPage.tsx", [], {},
    { "./restApisApi": { ...api, listCalls: async () => { throw new Error("nope"); } } }).RestApiCallsPage));
  assert.ok(byTestId(none, "rest-calls-empty").length === 1);
  assert.ok(text(none.root).includes("No REST API calls yet."));
});

test("the costs page shows the views, the filters and the cost table with a total row", async () => {
  const assigned = [];
  const row = (key, label, cost) => ({ key, label, runs: 2, delivered: 1, pullRequests: 1, costUsd: cost, costPerDeliveredUsd: cost, seat: {} });
  const report = { days: 30, from: null, to: null, group: "workflow", rows: [row("r1", "Run one", 1.5), row("", "No run", 0)],
    totals: row("total", "Total", 1.5) };
  const requests = [];
  const mocks = {
    "./operationsApi": { loadCosts: async (query) => { requests.push(query); return report; }, loadRunSession: async () => "s-1" },
    "./useSeatUsage": { useSeatUsage: () => ({ report: null, error: "", missing: false, reload: noop }) },
    "useActiveWorkspace": { useActiveWorkspace: () => ["w1"] },
  };
  const window = { location: { search: "", assign: (href) => assigned.push(href) } };
  const { OperationsCostsPage } = loadStubbed("admin/components/operations/OperationsCostsPage.tsx",
    ["./SeatUsageView", "/SeatCell", "/ChooseWorkspaceLine"], { window }, mocks);
  const view = await createAsync(createElement(OperationsCostsPage, { projects: [{ id: "w1", name: "Harbor" }], isAdmin: true }));
  includesAll(text(view.root), ["API cost", "Seats by person", "Harbor", "All workspaces", "7 days", "30 days", "Workflow", "Run",
    "Run one", "No run", "Total", "$1.50", "2", "1 of 2", "Pull requests", "API cost per delivered run", "Runs started in the last 30 days"]);
  assert.deepEqual(testIds(view), ["operations-costs", "costs-view", "costs-scope", "costs-period", "costs-group", "costs-table", "costs-period-text"]);
  assert.equal(all(view, "tr").length, 4);
  assert.deepEqual(plain(requests[0]), { workspaceId: "", days: 30, group: "workflow" });
  await act(async () => all(view, "button").find((node) => text(node) === "Run").props.onClick());
  await tick();
  assert.equal(requests.at(-1).group, "run");
  await act(async () => all(view, "button").find((node) => text(node) === "Run one").props.onClick());
  await tick();
  assert.deepEqual(assigned.length, 1);
  await act(async () => all(view, "button").find((node) => text(node) === "Seats by person").props.onClick());
  assert.equal(stubs(view, "SeatUsageView").length, 1);
  assert.equal(byTestId(view, "costs-group").length, 0);

  const member = await createAsync(createElement(OperationsCostsPage, { projects: [], isAdmin: false }));
  assert.equal(stubs(member, "ChooseWorkspaceLine").length, 1);
  assert.deepEqual(buttons(member), []);
});

const binding = (patch) => ({ id: "b1", workspace_id: "w2", workspace_name: "Library", products: [], state: "active", effective: "active",
  inert_reason: null, reason: "", created_at: null, revoked_at: null, ...patch });

test("the knowledge bindings panel lists both directions and binds another Workspace in a side panel", async () => {
  const calls = [];
  const overview = { workspace_id: "w1", may_author: true, reads_from: [binding(), binding({ id: "b2", workspace_name: "Old",
    effective: "inert", inert_reason: "beyond_binding_limit", products: ["spring"], reason: "docs" })], read_by: [] };
  const knowledge = { bindings: async (id) => { calls.push(["get", id]); return overview; },
    bind: async (id, body) => { calls.push(["bind", id, body]); return overview; },
    unbind: async (id, bindingId) => { calls.push(["unbind", id, bindingId]); return { ...overview, reads_from: [] }; } };
  const { KnowledgeBindingsPanel } = loadStubbed("admin/components/workspaceKnowledge/KnowledgeBindingsPanel.tsx", [], {}, {
    "./workspaceKnowledgeApi": { workspaceKnowledgeApi: knowledge, splitProducts: (value) => value.split(",").map((part) => part.trim()).filter(Boolean) } });
  const projects = [{ id: "w1", name: "Self" }, { id: "w2", name: "Library" }, { id: "w3", name: "Docs" }];
  const view = await createAsync(createElement(KnowledgeBindingsPanel, { workspaceId: "w1", projects }));
  includesAll(text(view.root), ["Read another Workspace", "This Workspace reads from (2)", "Library", "All", "active", "Old", "spring",
    "inert", "beyond the maximum number of bindings", "docs", "Revoke", "Read by (0)", "No other Workspace reads this one."]);
  assert.equal(all(view, "table").length, 1);
  assert.equal(buttons(view).filter((label) => label === "Revoke").length, 2);
  act(() => byTestId(view, "bindings-add")[0].props.onClick());
  const panel = byTestId(view, "bindings-add-panel")[0];
  includesAll(text(panel), ["Binding", "Source Workspace", "Choose a Workspace…", "Docs", "Products (optional)", "Reason (optional)", "Cancel", "Bind"]);
  assert.equal(panel.findAll((node) => node.type === "option").length, 2);
  act(() => all(view, "select")[0].props.onChange({ target: { value: "w3" } }));
  act(() => all(view, "input")[0].props.onChange({ target: { value: "a, b" } }));
  await act(async () => all(view, "form")[0].props.onSubmit({ preventDefault: noop }));
  await tick();
  assert.deepEqual(plain(calls[1]), ["bind", "w1", { source_workspace_id: "w3", products: ["a", "b"], reason: "" }]);
  assert.equal(byTestId(view, "bindings-add-panel").length, 0);
  assert.ok(text(view.root).includes("Bound. Search, changes and code impact now read that Workspace too."));
  await act(async () => all(view, "button").find((node) => text(node) === "Revoke").props.onClick());
  await tick();
  assert.deepEqual(calls[2], ["unbind", "w1", "b1"]);
  assert.equal(byTestId(view, "bindings-empty").length, 1);
});

test("the MCP allow drawer ticks Workspaces and tools and saves them", async () => {
  const { readJson, calls } = jsonRoutes({ "/api/v1/admin/mcp-servers/": (init) => (init.method === "PUT" ? {} : {
    server_id: "s1", name: "Files", connected: true, tools: ["read", "write"],
    workspaces: [{ workspace_id: "w1", name: "Harbor", allowed: true, tools: ["read"] }, { workspace_id: "w2", name: "Docs", allowed: false }] }) });
  const { McpAllowDrawer } = loadStubbed("admin/components/mcpAllow/McpAllowDrawer.tsx", [], {}, { "/adminPanelHelpers": { readJson } });
  let saved = 0;
  const view = await createAsync(createElement(McpAllowDrawer, { serverId: "s 1", serverName: "Files", onClose: noop, onSaved: () => { saved += 1; } }));
  includesAll(text(view.root), ["Allow Files in Workspaces", "Saved in each Workspace's Connectors section.", "Workspaces", "Harbor", "Docs",
    "Tools exposed", "All tools", "Including ones the server adds later.", "Selected tools", "Only the tools ticked below.", "read", "write",
    "Approval and policy rules still apply per tool"]);
  assert.equal(calls[0].url, "/api/v1/admin/mcp-servers/s%201/allow");
  const boxes = () => all(view, "input").filter((node) => node.props.type === "checkbox");
  assert.deepEqual(boxes().map((node) => node.props.checked), [true, false, true, false]);
  act(() => boxes()[1].props.onChange({ target: { checked: true } }));
  act(() => boxes()[2].props.onChange({ target: { checked: false } }));
  await act(async () => byTestId(view, "mcp-allow-save")[0].props.onClick());
  await tick();
  assert.equal(saved, 0);
  assert.ok(text(view.root).includes("Select at least one tool, or expose all tools."));
  act(() => all(view, "input").filter((node) => node.props.type === "radio")[0].props.onChange());
  assert.equal(boxes().length, 2);
  await act(async () => byTestId(view, "mcp-allow-save")[0].props.onClick());
  await tick();
  assert.equal(saved, 1);
  assert.deepEqual(plain(calls.at(-1).body), { workspace_ids: ["w1", "w2"], tools: null });

  const failed = await createAsync(createElement(loadStubbed("admin/components/mcpAllow/McpAllowDrawer.tsx", [], {}, {
    "/adminPanelHelpers": { readJson: async () => { throw new Error("x"); } } }).McpAllowDrawer, { serverId: "s", serverName: "F", onClose: noop, onSaved: noop }));
  assert.ok(text(failed.root).includes("The Workspaces could not be loaded."));
  assert.equal(byTestId(failed, "mcp-allow-save")[0].props.disabled, true);
});
