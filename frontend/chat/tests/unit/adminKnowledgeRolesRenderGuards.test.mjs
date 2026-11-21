// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminKnowledgeRolesRenderGuards.test.mjs
//
// Render guards for admin components that had no render test: the Jira releases drawer, the role editor and a
// Workspace's roles. Each renders with representative props and checks
// the key text and structure. Heavy children, hooks and APIs are replaced by stubs, matched by module name at any
// depth, so the guards hold however the components are split into modules. Names invented.
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
const stubs = (view, name) => view.root.findAll((node) => node.props["data-stub"] === name);
const events = () => ({ addEventListener() {}, removeEventListener() {} });

// Transpiles a component with its relative imports into one VM; `mocks` replaces modules by their last path segment.
function loader(mocks = {}, globals = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl, JSON,
      encodeURIComponent, setTimeout, clearTimeout, Set, Map, window: { ...events() }, document: events(), ...globals,
      require: (name) => {
        const key = name.split("/").at(-1);
        if (key in mocks) return mocks[key];
        if (name in mocks) return mocks[name];
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts", "/index.ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return (relative) => loadFile(path.join(SRC, relative));
}

const stub = (name) => (props) => createElement("div", { "data-stub": name }, props.children ?? null);

async function mount(Component, props) {
  let view;
  await act(async () => { view = TestRenderer.create(createElement(Component, props)); });
  await act(async () => {});
  return view;
}

test("the Jira releases drawer shows the stored block: badges, the four sections and the footer", async () => {
  const connector = {
    connector_key: "jira-shop", kind: "jira", state: "paused", max_items_per_run: 100,
    scope: { project_keys: ["SHOP"], releases: { products: { SHOP: "shop" }, version_name_prefixes: ["Release "], sections: [{ title: "Fixes", issue_types: ["Bug"], labels: [] }], blocker_priorities: ["Blocker"] } },
    release_sync: { state: "active" },
  };
  const fetch = async () => ({ ok: true, status: 200, json: async () => ({ connectors: [connector], may_author: true }) });
  const { KnowledgeJiraReleasesDrawer } = loader({}, { fetch })("admin/components/workspaceKnowledge/KnowledgeJiraReleasesDrawer.tsx");
  const view = await mount(KnowledgeJiraReleasesDrawer, { workspaceId: "ws-1", connectorKey: "jira-shop", onClose() {}, onSaved() {} });
  const all = text(view.root);
  assert.match(all, /Jira connector · releases/);
  assert.match(all, /connector paused/);
  assert.equal(view.root.findAll((node) => node.props.className === "kr-section").length, 4);
  assert.deepEqual(view.root.findAll((node) => node.props.className === "kr-eyebrow").map(text).slice(1),
    ["Products", "Version name prefixes", "Sections", "Blocker priorities"]);
  const buttons = view.root.findAllByType("button").map(text);
  assert.deepEqual(buttons.slice(-3), ["Cancel", "Switch off", "Save"]);
  act(() => view.unmount());
});

test("the Jira releases drawer without a block offers to set up release notes", async () => {
  const connector = { connector_key: "jira-ops", kind: "jira", state: "active", scope: { project_keys: [] } };
  const fetch = async () => ({ ok: true, status: 200, json: async () => ({ connectors: [connector] }) });
  const { KnowledgeJiraReleasesDrawer } = loader({}, { fetch })("admin/components/workspaceKnowledge/KnowledgeJiraReleasesDrawer.tsx");
  const view = await mount(KnowledgeJiraReleasesDrawer, { workspaceId: "ws-1", connectorKey: "jira-ops", onClose() {}, onSaved() {} });
  assert.match(text(view.root), /No releases block configured\./);
  assert.ok(view.root.findAllByType("button").some((node) => text(node) === "Set up release notes"));
  act(() => view.unmount());
});

const ROLE = {
  id: "r-1", key: "reviewer", name: "Reviewer", description: "Reviews changes", workspace_id: null, built_in: false, is_active: true,
  function_keys: ["read"], delivery_connections: "selected", connection_ids: [], trusted: false, trusted_changed_by: null,
  trusted_changed_at: null, command_policy: { allow: [], deny: [] }, version: 1, assignment_count: 0,
};
const FUNCTIONS = [
  { id: "f-1", key: "read", name: "Read", description: "Reads code.", workspace_id: null, built_in: true, tools: [], tools_version: 1, version: 1, role_keys: [] },
  { id: "f-2", key: "write", name: "Write", description: "Writes code.", workspace_id: null, built_in: true, tools: [], tools_version: 1, version: 1, role_keys: [] },
];
const roleMocks = {
  connectionsApi: { listConnections: async () => ({ kind: "ok", connections: [{ id: "c-1", name: "Shop Git" }] }) },
};

test("the role editor of an existing role shows its sections, connections and footer", async () => {
  const { RoleEditorPanel } = loader(roleMocks)("admin/components/workRoles/RoleEditorPanel.tsx");
  const view = await mount(RoleEditorPanel, { role: ROLE, functions: FUNCTIONS, workspaces: [{ id: "ws-1", name: "Shop" }], canEdit: true, onClose() {}, onSaved() {} });
  const all = text(view.root);
  for (const title of ["Role", "Functions", "Write connections", "Command rules", "Trust and status"]) assert.match(all, new RegExp(title));
  assert.match(all, /Shop Git/);
  assert.equal(byTestId(view, "role-name")[0].props.value, "Reviewer");
  assert.equal(byTestId(view, "role-key").length, 0);
  assert.equal(byTestId(view, "role-function-read").length + byTestId(view, "role-function-write").length > 0, true);
  assert.equal(text(byTestId(view, "role-save")[0]), "Save");
  assert.equal(byTestId(view, "role-delete").length, 1);
  assert.equal(byTestId(view, "role-trusted").length, 1);
  act(() => view.unmount());
});

test("the role editor for a new role asks for a key and the Workspace", async () => {
  const { RoleEditorPanel } = loader(roleMocks)("admin/components/workRoles/RoleEditorPanel.tsx");
  const view = await mount(RoleEditorPanel, { role: null, functions: FUNCTIONS, workspaces: [{ id: "ws-1", name: "Shop" }], canEdit: true, onClose() {}, onSaved() {} });
  assert.equal(byTestId(view, "role-key").length, 1);
  assert.match(text(view.root), /Only Shop/);
  assert.equal(text(byTestId(view, "role-save")[0]), "Create role");
  assert.equal(byTestId(view, "role-delete").length, 0);
  assert.doesNotMatch(text(view.root), /Trust and status/);
  act(() => view.unmount());
});

test("a Workspace's roles list the switch, the assignments and the preview picker", async () => {
  const data = {
    workspace_id: "ws-1", settings: { role_based_tools: true, version: 2, updated_by: null, updated_at: null }, roles: [ROLE],
    assignments: [{ id: "a-1", workspace_id: "ws-1", role_id: "r-1", role_key: "reviewer", role_name: "Reviewer", subject: { kind: "user", user_id: "u-1", label: "Mira" }, members: 1, is_active: true, version: 1 }],
    members_without_role: [{ user_id: "u-2", label: "Tavi" }], can_edit: true,
  };
  const { WorkspaceRolesSection } = loader({
    workRolesApi: { listSsoProviders: async () => [], loadWorkspaceRoles: async () => data, revokeAssignment: async () => {}, saveRoleBasedTools: async () => data.settings },
    adminPanelHelpers: { readJson: async () => ({ assignments: [], available_users: [], group_assignments: [] }) },
  }, { window: { ...events(), innerWidth: 1400 } })("admin/components/workRoles/WorkspaceRolesSection.tsx");
  const view = await mount(WorkspaceRolesSection, { workspaceId: "ws-1", workspaceName: "Shop" });
  assert.equal(byTestId(view, "workspace-roles").length, 1);
  assert.equal(byTestId(view, "role-based-tools-switch").length, 1);
  assert.match(text(byTestId(view, "members-without-role")[0]), /Tavi/);
  assert.match(text(byTestId(view, "role-assignments")[0]), /Mira/);
  assert.match(text(byTestId(view, "role-assignments")[0]), /Roles in Shop/);
  assert.equal(byTestId(view, "assign-person").length, 1);
  assert.equal(byTestId(view, "assign-sso").length, 1);
  assert.deepEqual(byTestId(view, "preview-member")[0].findAllByType("option").map(text), ["Choose a member", "Mira", "Tavi"]);
  act(() => view.unmount());
});
