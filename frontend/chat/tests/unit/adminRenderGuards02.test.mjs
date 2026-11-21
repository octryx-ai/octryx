// Render guards for admin editors split into smaller functions: a REST operation's grants, the policy builder's
// "what" step and the role assign panel render the same structure after being split up.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { load } from "./adminPartsLoader.mjs";
import { act, byTestId, server, text, tick } from "./settingsRenderHarness.mjs";
import { all, buttons, create, createAsync, includesAll, noop, plain, testIds } from "./adminGuardRenderers.mjs";

const EXPECTED_WHAT_SHAPES = {
  call_tool: ["builder-tool-search", "builder-tools", "builder-tools-chip", "builder-writes", "builder-reads-logs"],
  run_command: ["builder-programs", "builder-programs-input", "builder-programs-add", "builder-prefixes", "builder-prefixes-input",
    "builder-prefixes-add", "builder-arguments", "builder-arguments-input", "builder-arguments-add", "builder-option-values",
    "builder-option-values-input", "builder-option-values-add", "builder-unparseable", "builder-try-command", "builder-command-split",
    "builder-client-tools", "builder-client-tools-chip"],
  call_model: ["builder-model-mode", "builder-models", "builder-models-chip", "builder-models-input", "builder-models-add"],
  read_path: ["builder-paths", "builder-paths-input", "builder-paths-add", "builder-client-tools", "builder-client-tools-chip"],
  use_seat: [],
};

test("a REST operation's grants show role, Workspace, data scope, body scope and the result filter", async () => {
  const srv = server((call) => (call.url.endsWith("/panel/roles") ? { status: 200, body: [{ name: "admin" }] }
    : call.url.endsWith("/work-roles/roles") ? { status: 200, body: { roles: [{ key: "sd", name: "Service desk" }] } } : { status: 200, body: {} }));
  const { RestGrantEditor } = load("admin/components/restApis/RestGrantEditor.tsx", { fetch: srv.fetch });
  const { grantDraft } = load("admin/components/restApis/restOperationEditorModel.ts");
  const changes = [];
  const operation = { id: "op1", method: "POST", path: "/tickets", parameters: [{ name: "group", in: "query" }, { name: "site", in: "query" }],
    request_body: { content_type: "application/json", schema: { type: "object", properties: { assignment_group: { type: "string" } } } } };
  const grant = { ...grantDraft(), role: "sd", scope: [{ param: "group", value: "g1" }], bodyScope: [{ param: "assignment_group", value: "x" }] };
  const draft = { grants: [grant, grantDraft()] };
  const view = await createAsync(createElement(RestGrantEditor, { operation, draft, saved: [grant], onChange: (next) => changes.push(next),
    workspaces: [{ id: "w1", name: "Harbor" }], error: null }));
  const page = text(view.root);
  includesAll(page, ["The API is called with the connection's technical account.", "sd", "New grant", "Role", "Workspace", "Any Workspace",
    "Data scope", "No fixed values: this role may call it with any parameters.", "Add a fixed value", "Result filter: field (optional)", "must equal", "Add grant"]);
  assert.equal(byTestId(view, "rest-grant-0").length, 1);
  assert.equal(byTestId(view, "rest-grant-1").length, 1);
  assert.equal(all(view, "datalist").length, 2);
  assert.equal(byTestId(view, "rest-grant-0-body-scope").length, 1);
  assert.deepEqual(byTestId(view, "rest-grant-0-scope-0-param")[0].findAll((node) => node.type === "option").map((node) => node.props.value), ["", "group", "site"]);
  byTestId(view, "rest-grant-0-add-scope")[0].props.onClick();
  assert.deepEqual(plain(changes[0].grants[0].scope), [{ param: "group", value: "g1" }, { param: "site", value: "" }]);
  byTestId(view, "rest-grant-0-scope-0-value")[0].props.onChange({ target: { value: "g2" } });
  assert.deepEqual(plain(changes[1].grants[0].scope[0]), { param: "group", value: "g2" });
  byTestId(view, "rest-grant-add")[0].props.onClick();
  assert.equal(changes[2].grants.length, 3);
  assert.ok(all(view, "option").some((node) => text(node) === "Work role: Service desk"));
});


test("the builder's what step shows the action cards and the detail blocks the chosen actions support", async () => {
  const { CATALOG } = await import("./policyEngineHarness.mjs");
  const { readCatalog, readPickerEntities } = load("admin/components/policyEngine/policyCatalogModel.ts");
  const { blankModel } = load("admin/components/policyEngine/policyBuilderModel.ts");
  const { WhatPane } = load("admin/components/policyEngine/BuilderWhatPane.tsx");
  const catalog = readCatalog(CATALOG);
  const entities = readPickerEntities({ tools: [{ name: "jira_create", connector_family: "jira" }, { name: "plain_tool" }],
    model_aliases: [{ alias: "m1", data_policy_class: "internal" }], connector_families: [{ id: "jira", label: "Jira" }] });
  const changes = [];
  const render = (actions) => create(createElement(WhatPane, { model: { ...blankModel(), actions }, onChange: (next) => changes.push(next), catalog, entities, required: ["what.models"] }));
  const none = render([]);
  assert.ok(text(none.root).includes("Pick at least one action."));
  assert.equal(byTestId(none, "builder-no-action").length, 1);
  const actionCards = catalog.actions.map((action) => `builder-action-${action.id}`);
  assert.deepEqual(testIds(none), ["builder-pane-what", ...actionCards, "builder-no-action"]);
  const shapes = {};
  for (const actions of [["call_tool"], ["run_command"], ["call_model"], ["read_path"], ["use_seat"]]) {
    const view = render(actions);
    shapes[actions[0]] = testIds(view).filter((id) => !actionCards.includes(id) && id !== "builder-pane-what");
    if (actions[0] === "use_seat") assert.ok(text(view.root).includes("The personal seat is decided per Workspace."));
    if (actions[0] === "run_command") assert.ok(byTestId(view, "builder-command-split")[0].children.length > 3);
  }
  assert.deepEqual(plain(shapes), EXPECTED_WHAT_SHAPES);
  const tool = render(["call_tool"]);
  byTestId(tool, "builder-action-call_tool")[0].props.onClick();
  assert.deepEqual(plain(changes.at(-1).actions), []);
});

test("the assign panel picks a person or an SSO value and the roles to assign", () => {
  const { AssignPanel } = load("admin/components/workRoles/AssignPanel.tsx");
  const roles = [{ id: "r1", key: "dev", name: "Developer", description: "Writes code", trusted: false },
    { id: "r2", key: "rel", name: "Release", description: "Ships", trusted: true }];
  const props = { workspaceId: "w1", workspaceName: "Harbor", roles, people: [{ id: "u1", label: "Anna" }], groups: [],
    providers: [{ id: "idp", name: "Corp SSO", known_groups: ["eng", "ops"], known_roles: ["admin"] }], onClose: noop, onDone: noop };
  const person = create(createElement(AssignPanel, { ...props, mode: "person" }));
  includesAll(text(person.root), ["Assign person", "Harbor", "Who", "Person", "Workspace group", "Choose a person", "Anna", "Roles",
    "Developer", "Writes code", "Release", "Cancel", "Assign"]);
  assert.equal(byTestId(person, "assign-target").length, 1);
  assert.equal(byTestId(person, "assign-save")[0].props.disabled, true);
  act(() => byTestId(person, "assign-target")[0].props.onChange({ target: { value: "u1" } }));
  act(() => byTestId(person, "assign-role-dev")[0].findByType("input").props.onChange({ target: { checked: true } }));
  act(() => byTestId(person, "assign-role-rel")[0].findByType("input").props.onChange({ target: { checked: true } }));
  assert.equal(text(byTestId(person, "assign-save")[0]), "Assign 2 roles");
  assert.equal(byTestId(person, "assign-save")[0].props.disabled, false);

  const sso = create(createElement(AssignPanel, { ...props, mode: "sso" }));
  includesAll(text(sso.root), ["Assign SSO group or role", "SSO group", "SSO role", "Identity provider", "Corp SSO",
    "SSO group (as in the groups claim)", "2 known from sign-ins."]);
  assert.deepEqual(all(sso, "datalist")[0].findAll((node) => node.type === "option").map((node) => node.props.value), ["eng", "ops"]);
  const empty = create(createElement(AssignPanel, { ...props, mode: "sso", providers: [] }));
  assert.ok(text(empty.root).includes("No value seen in a sign-in yet."));
});

