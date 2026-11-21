// Render guards for the REST API admin parts split into smaller functions: one operation's editor, the connections
// of an API with their form, and the API's side panel render the same structure and call the same endpoints.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, byTestId, text, tick } from "./settingsRenderHarness.mjs";
import { all, buttons, create, createAsync, includesAll, plain } from "./adminGuardRenderers.mjs";
import { loadStubbed, stubs } from "./adminGuardStubLoader.mjs";
import { button, hostCount } from "./adminGuardTreeReaders.mjs";

const operation = (patch = {}) => ({
  id: "op1", op_key: "list_tickets", tool_name: "rest__demo__list_tickets", method: "GET", path: "/tickets", summary: "Lists tickets",
  parameters: [{ name: "group", in: "query", required: false, description: "", schema: { type: "string" } }],
  request_body: null, enabled: true, read_only: true, is_read: true, llm_name: "", llm_description: "", params_overlay: {},
  grants: [], response_select: [], records_path: "", pagination: { type: "none" }, ...patch,
});
const definition = (patch = {}) => ({
  id: "def1", key: "demo", name: "Demo API", description: "", source_kind: "manual", source_url: "", spec_version: "",
  servers: ["https://api.example.com"], auth: { scheme: "basic" }, timeout_seconds: 10, is_active: true, created_at: null,
  updated_at: "2026-01-01T00:00:00Z", operations: [operation(), operation({ id: "op2", op_key: "get_ticket", enabled: false })],
  warnings: ["'list_tickets': offered to nobody"], ...patch,
});
const workspaces = [{ id: "w1", name: "Harbor" }, { id: "w2", name: "Dock" }];

function restApi(calls) {
  const record = (name) => async (...args) => { calls.push([name, ...args]); return null; };
  return {
    updateOperation: record("updateOperation"), deleteOperation: record("deleteOperation"), deleteConnection: record("deleteConnection"),
    createConnection: record("createConnection"), updateConnection: record("updateConnection"), deleteDefinition: record("deleteDefinition"),
    listConnections: async () => { calls.push(["listConnections"]); return [
      { id: "c1", definition_id: "def1", project_id: null, owner: "platform", name: "Main", base_url: "https://api.example.com",
        is_active: true, fields: { username: "svc" }, secret_status: { password: true }, missing_for_auth: [] },
      { id: "c2", definition_id: "def1", project_id: "w1", owner: "workspace", name: "", base_url: "https://h.example.com",
        is_active: false, fields: {}, secret_status: { password: false }, missing_for_auth: ["password"] },
    ]; },
    loadDefinition: async () => { calls.push(["loadDefinition"]); return definition(); },
  };
}

test("the operation editor shows head, tabs, warnings and the save row, and saves or deletes the operation", async () => {
  const calls = [], saved = [], deleted = [];
  const { RestOperationEditor } = loadStubbed("admin/components/restApis/RestOperationEditor.tsx",
    ["/SegmentedTabs", "/StatusLabel", "/ConfirmDialog", "./RestGrantEditor", "./RestOperationSetup", "./RestTestCall"], {},
    { "./restApisApi": restApi(calls) });
  const view = create(createElement(RestOperationEditor, { definition: definition(), operation: operation(), workspaces,
    onBack() {}, onSaved: () => saved.push(1), onDeleted: () => deleted.push(1) }));
  includesAll(text(view.root), ["‹ All operations", "GET", "/tickets", "Read", "rest__demo__list_tickets", "Lists tickets",
    "Calls of this operation ›", "'list_tickets': offered to nobody", "Delete operation…", "Discard", "Save operation"]);
  assert.equal(byTestId(view, "rest-operation-calls")[0].props.href.includes("rest_op=op1"), true);
  assert.deepEqual(plain(stubs(view, "SegmentedTabs")[0].props.tabs.map((tab) => tab.key)), ["setup", "access", "test"]);
  assert.equal(stubs(view, "RestOperationSetup").length, 1);
  assert.equal(byTestId(view, "rest-operation-save")[0].props.disabled, true);
  assert.equal(hostCount(view), 19);
  act(() => stubs(view, "RestOperationSetup")[0].props.onChange({ ...stubs(view, "RestOperationSetup")[0].props.draft, llmName: "tickets" }));
  assert.equal(byTestId(view, "rest-operation-save")[0].props.disabled, false);
  includesAll(text(view.root), ["rest__demo__tickets"]);
  await act(async () => byTestId(view, "rest-operation-save")[0].props.onClick());
  assert.equal(calls[0][0], "updateOperation");
  assert.equal(saved.length, 1);
  assert.equal(byTestId(view, "rest-operation-save")[0].props.disabled, true);
  act(() => stubs(view, "SegmentedTabs")[0].props.onChange("access"));
  assert.equal(stubs(view, "RestGrantEditor").length, 1);
  act(() => stubs(view, "SegmentedTabs")[0].props.onChange("test"));
  assert.equal(stubs(view, "RestTestCall")[0].props.write, false);
  assert.equal(byTestId(view, "rest-operation-save").length, 0);
  act(() => stubs(view, "SegmentedTabs")[0].props.onChange("setup"));
  act(() => byTestId(view, "rest-operation-delete")[0].props.onClick());
  assert.equal(stubs(view, "ConfirmDialog")[0].props.title, "Delete list_tickets?");
  await act(async () => stubs(view, "ConfirmDialog")[0].props.onConfirm());
  assert.deepEqual(calls[1], ["deleteOperation", "def1", "op1"]);
  assert.equal(deleted.length, 1);
});

test("the connections list shows each connection with its facts and opens the form to add or edit one", async () => {
  const calls = [];
  const { RestConnections } = loadStubbed("admin/components/restApis/RestConnections.tsx", ["/StatusLabel", "/ConfirmDialog"], {},
    { "./restApisApi": restApi(calls) });
  const view = await createAsync(createElement(RestConnections, { definition: definition(), workspaces }));
  includesAll(text(view.root), ["A Workspace's own connection wins", "Name", "Main", "Base URL", "https://api.example.com", "Authentication",
    "User name", "svc", "Password", "Set", "Not set", "Missing for the API's authentication", "Delete…", "Edit", "Add connection"]);
  assert.deepEqual(byTestId(view, "rest-connection-platform").length + byTestId(view, "rest-connection-workspace").length, 2);
  assert.deepEqual(stubs(view, "StatusLabel").map((node) => node.props.label), ["Inactive", "Needs configuration"]);
  assert.equal(hostCount(view), 51);
  act(() => button(view, "Delete…").props.onClick());
  assert.match(stubs(view, "ConfirmDialog")[0].props.title, /^Delete the .* connection\?$/);
  await act(async () => stubs(view, "ConfirmDialog")[0].props.onConfirm());
  assert.deepEqual(calls.filter(([name]) => name === "deleteConnection"), [["deleteConnection", "def1", "c1"]]);

  await act(async () => byTestId(view, "rest-connection-edit")[0].props.onClick());
  includesAll(text(view.root), ["Edit connection", "Used by", "The owner of a connection does not change.", "Name (optional)",
    "Base URL", "Technical account · ", "User name", "Password", "Write-only", "Replace", "Clear", "Cancel", "Save connection"]);
  assert.equal(byTestId(view, "rest-connection-owner")[0].props.disabled, true);
  assert.equal(byTestId(view, "rest-secret-input-password").length, 0);
  act(() => button(view, "Replace").props.onClick());
  assert.equal(byTestId(view, "rest-secret-input-password").length, 1);
  assert.equal(button(view, "Keep the stored one") !== undefined, true);
  act(() => byTestId(view, "rest-secret-input-password")[0].props.onChange({ target: { value: "pw" } }));
  assert.equal(stubs(view, "StatusLabel")[0].props.label, "Will be replaced on save");
  await act(async () => all(view, "form")[0].props.onSubmit({ preventDefault() {} }));
  const update = calls.find(([name]) => name === "updateConnection");
  assert.equal(update[1], "def1");
  assert.equal(update[2], "c1");
  assert.equal(byTestId(view, "rest-connections").length, 1);

  await act(async () => byTestId(view, "rest-connection-add")[0].props.onClick());
  includesAll(text(view.root), ["Add connection", "Platform (every Workspace without its own)", "Workspace Harbor", "Workspace Dock",
    "The API's first server is https://api.example.com."]);
  assert.deepEqual(all(view, "option").map((node) => node.props.disabled), [true, true, false]);
  assert.equal(byTestId(view, "rest-secret-input-password").length, 1);
  assert.deepEqual(buttons(view), ["Cancel", "Add connection"]);
  act(() => button(view, "Cancel").props.onClick());
  assert.equal(byTestId(view, "rest-connections").length, 1);
});

test("the REST API side panel shows tabs, warnings that open an operation, and a confirmed delete", async () => {
  const calls = [], deleted = [];
  const { RestApiDetailPanel } = loadStubbed("admin/components/restApis/RestApiDetailPanel.tsx",
    ["/SidePanel", "/ConfirmDialog", "/ActionMenu", "./RestConnections", "./RestDefinitionDetails", "./RestOperationEditor", "./RestOperationList"],
    {}, { "./restApisApi": restApi(calls) });
  const view = await createAsync(createElement(RestApiDetailPanel, { definitionId: "def1", workspaces, onClose() {}, onDeleted: () => deleted.push(1) }));
  const panel = stubs(view, "SidePanel")[0];
  assert.equal(panel.props.title, "Demo API");
  assert.match(panel.props.subtitle, /^demo · .+ · 1 of 2 operations on$/);
  assert.deepEqual(plain(panel.props.tabs.tabs.map((tab) => [tab.key, tab.count ?? null])), [["operations", 2], ["connections", null], ["details", null]]);
  assert.equal(stubs(view, "RestOperationList").length, 1);
  assert.equal(byTestId(view, "rest-detail-warnings").length, 1);
  assert.equal(hostCount(view), 6);
  act(() => button(view, "'list_tickets': offered to nobody").props.onClick());
  assert.equal(stubs(view, "RestOperationEditor")[0].props.operation.id, "op1");
  assert.equal(byTestId(view, "rest-detail-warnings").length, 0);
  act(() => stubs(view, "RestOperationEditor")[0].props.onBack());
  act(() => stubs(view, "SidePanel")[0].props.tabs.onChange("connections"));
  assert.equal(stubs(view, "RestConnections").length, 1);
  act(() => stubs(view, "SidePanel")[0].props.tabs.onChange("details"));
  assert.equal(stubs(view, "RestDefinitionDetails").length, 1);
  act(() => stubs(view, "SidePanel")[0].props.headerActions.props.items[0].onSelect());
  assert.equal(stubs(view, "ConfirmDialog")[0].props.title, "Delete Demo API?");
  includesAll(text(view.root), ["This also removes its 2 operations"]);
  await act(async () => stubs(view, "ConfirmDialog")[0].props.onConfirm());
  await tick();
  assert.deepEqual(calls.at(-1), ["deleteDefinition", "def1"]);
  assert.equal(deleted.length, 1);
});
