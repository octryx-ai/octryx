// Render guards for admin connector, MCP, research-profile and engineering-knowledge pages: each renders with
// representative props and keeps its key labels, test ids and row counts while its long functions are split.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));
const byId = (root, id) => root.findAll((node) => node.props["data-testid"] === id);
const ofType = (root, type) => root.findAll((node) => node.type === type);

const sandbox = {
  JSON, Date, Math, Number, Object, Array, String, Boolean, Error, Promise, Set, Map, console, URL,
  URLSearchParams, encodeURIComponent, setTimeout, clearTimeout,
  window: { innerWidth: 1400, location: { search: "", pathname: "/chat", origin: "http://localhost" }, addEventListener() {}, removeEventListener() {}, open() {} },
  document: { addEventListener() {}, removeEventListener() {}, activeElement: null, getElementById: () => null },
};

function makeLoader(stubs) {
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

async function mount(relative, exportName, props, stubs = {}) {
  const Component = makeLoader(stubs)(relative)[exportName];
  let view;
  await act(async () => { view = TestRenderer.create(createElement(Component, props), { createNodeMock: () => ({ focus() {} }) }); });
  await act(async () => {});
  return view;
}

const labels = (root, className) => root.findAll((node) => node.props.className === className).map(text);
const noop = () => {};

test("GitHub connector: the create-repository form shows its fields, the code-repository backends and the action", async () => {
  const form = {
    name: "platform-api", owner: "", owner_type: "org", visibility: "private", default_branch: "main", local_path: "",
    description: "", create_readme: true, create_gitignore: false, initial_commit: true, register_code_repository: true,
    project_id: "ws_1", index_backend: "auto", semantic_backend: "scip", structure_backend: "auto", graph_backend: "auto",
  };
  const view = await mount("admin/components/connectorsTab/ConfiguredConnectorGithubRepoForm.tsx", "ConfiguredConnectorGithubRepoForm", {
    connector: { configured: true, public_fields: { github_owner: "acme" } },
    ctx: { githubConnectorRepoCreateLoading: false, githubConnectorRepoForm: form, handleCreateGithubConnectorRepository: noop,
      projects: [{ id: "ws_1", name: "Acme Orders" }, { id: "ws_2", name: "Test" }], setGithubConnectorRepoForm: noop },
  });
  assert.deepEqual(labels(view.root, "connector-field__label"), [
    "Repository name", "Owner override", "Owner type", "Visibility", "Default branch", "Local bootstrap path", "Description",
    "Project", "Search backend", "Semantic backend", "Structure backend", "Graph backend",
  ]);
  assert.equal(ofType(view.root, "input").length, 9);
  assert.equal(ofType(view.root, "option").length, 2 + 2 + 3 + 3 + 4 + 3 + 3);
  assert.equal(view.root.findAll((node) => node.type === "input" && node.props.placeholder === "acme").length, 1);
  const button = ofType(view.root, "button")[0];
  assert.equal(text(button), "Create repository");
  assert.equal(button.props.disabled, false);
});

test("Add database: the side panel shows every field, the SQLite file path, the error and both actions", async () => {
  const form = { name: "orders", db_type: "sqlite", host: "", port: "", database: "", username: "", password: "", dsn: "",
    file_path: "/tmp/orders.db", driver: "", description: "" };
  const view = await mount("admin/components/connectorsTab/AddDatabaseConnectorModal.tsx", "AddDatabaseConnectorModal", {
    ctx: { databaseConnectorError: "Name already taken.", databaseConnectorForm: form, databaseConnectorSaving: false,
      handleCreateDatabaseConnector: noop, setDatabaseConnectorForm: noop, setShowAddDatabaseConnector: noop, showAddDatabaseConnector: true },
  });
  assert.equal(byId(view.root, "database-add-panel").length > 0, true);
  assert.deepEqual(labels(view.root, "admin-form-field__label"), [
    "Name", "Type", "Host", "Port", "Database", "Username", "Password", "DSN override", "File path", "Description",
  ]);
  assert.equal(view.root.findAll((node) => node.type === "input" && node.props.value === "/tmp/orders.db").length, 1);
  assert.deepEqual(labels(view.root, "admin-panel__error"), ["Name already taken."]);
  assert.ok(ofType(view.root, "button").map(text).includes("Add database"));
  assert.ok(ofType(view.root, "button").map(text).includes("Cancel"));
});

test("MCP servers: header actions, one server row and the create panels closed", async () => {
  const server = { id: "srv-1", name: "context7", connected: true, transport: "http", status: "running", tools: [], description: "Docs" };
  const ctx = {
    adminProjects: [{ id: "ws_1", name: "Acme Orders" }], mcpWorkspaceId: "ws_1", setMcpWorkspaceId: noop,
    mcpServers: [server], setMcpServers: noop, setMcpCatalog: noop, filteredMcpCatalog: [], showMcpCatalog: false,
    setShowMcpCatalog: noop, mcpCatalogSearch: "", setMcpCatalogSearch: noop, openMcpCatalogInstall: noop,
    selectedMcpCatalog: null, closeMcpCatalogInstall: noop, mcpEditingServerName: null, mcpInstallName: "", setMcpInstallName: noop,
    mcpInstallValues: {}, setMcpInstallValues: noop, mcpInstallAutoStart: true, setMcpInstallAutoStart: noop, mcpInstallError: null,
    mcpInstallLoading: false, handleInstallMcpCatalog: noop, openMcpServerEdit: noop, showAddCustomMcp: false,
    openCustomMcpForm: noop, closeCustomMcpForm: noop, customMcpName: "", setCustomMcpName: noop, customMcpTransport: "http",
    setCustomMcpTransport: noop, customMcpUrl: "", setCustomMcpUrl: noop, customMcpDescription: "", setCustomMcpDescription: noop,
    customMcpAutoStart: true, setCustomMcpAutoStart: noop, customMcpLoading: false, customMcpError: null, handleCreateCustomMcp: noop,
    getMcpIconColor: () => "#000", renderMcpIcon: () => null, readJson: async () => ({}), loadMcpTab: async () => {},
  };
  const view = await mount("admin/components/AdminMcpTab.tsx", "AdminMcpTab", { ctx }, {
    "/useActiveWorkspace": { useActiveWorkspace: () => ["ws_1", noop] },
    "/useMcpAllowStatus": { useMcpAllowStatus: () => ({ status: null, reload: noop }) },
  });
  assert.equal(text(byId(view.root, "mcp-add-custom")[0]), "Add custom MCP");
  assert.equal(text(byId(view.root, "mcp-install")[0]), "Install from catalog");
  assert.equal(byId(view.root, "mcp-install")[0].props.disabled, false);
  assert.match(text(view.root), /context7/);
  assert.equal(byId(view.root, "mcp-empty").length, 0);
});

const VERSION = { id: "v-1", version: 2, status: "draft", notes: "", spec: { allowed_domains: ["example.org"] },
  diagnostics: { status: "valid", errors: [], warnings: [] }, created_at: null };
const PROFILE = { id: "p-1", key: "deep-research", name: "Deep research", lifecycle_status: "active", latest_published_version_id: null,
  versions: [VERSION] };

test("Research profiles: header actions, the table row, the create panel and the editor panel", async () => {
  const state = {
    loading: false, saving: false, error: "", notice: "Saved.", specDraft: JSON.stringify(VERSION.spec), selectedVersion: VERSION,
    selectedProfile: PROFILE, payload: { profiles: [PROFILE] }, showCreateProfile: true, newProfileKey: "custom", newProfileName: "",
    createAsPublished: false, editingProfileId: "p-1", newVersionNotes: "", selectedProjectId: "ws_1", workspacePolicy: null,
    publishedVersions: [], setShowCreateProfile: noop, setSelectedProfileId: noop, setEditingProfileId: noop, setSelectedVersionId: noop,
    setNewProfileKey: noop, setNewProfileName: noop, setCreateAsPublished: noop, setSpecDraft: noop, setNewVersionNotes: noop,
    createProfile: async () => true, loadPolicies: async () => {}, createVersion: async () => {}, publishSelectedVersion: async () => {},
    assignWorkspacePolicy: async () => {}, clearWorkspacePolicy: async () => {},
  };
  const view = await mount("admin/components/AdminResearchPoliciesTab.tsx", "AdminResearchPoliciesTab",
    { projects: [{ id: "ws_1", name: "Acme Orders" }] },
    { "/useAdminResearchPolicies": { useAdminResearchPolicies: () => state } });
  assert.equal(text(byId(view.root, "research-profile-new")[0]), "New profile");
  assert.equal(byId(view.root, "research-profile-create").length > 0, true);
  assert.equal(byId(view.root, "research-profile-panel").length > 0, true);
  assert.equal(byId(view.root, "research-profiles-table").length > 0, true);
  const buttons = ofType(view.root, "button").map(text);
  for (const label of ["Refresh", "Create profile", "Save as draft", "Create published"]) assert.ok(buttons.includes(label), label);
  assert.match(text(view.root), /Deep research/);
  assert.match(text(view.root), /Schema JSON/);
  assert.equal(ofType(view.root, "textarea").length, 6);
});

test("Engineering pack drawer: meta, toolchain profiles, one version with its sources, items and the close action", async () => {
  const pack = {
    id: "pk-1", key: "python", name: "Python pack", stack_key: "python", lifecycle_status: "active", latest_published_version_id: "pv-1",
    toolchain_policy: { profiles: { uv: {}, ruff: {} } },
    versions: [{ id: "pv-1", version: 3, status: "published", quality_status: "passed", source_count: 2, item_count: 1,
      assignment_count: 1, active_assignment_count: 1, source_versions: { pep8: "1" }, target_versions: { python: "3.12" },
      sources: [], items: [{ id: "it-1", title: "Use uv", kind: "rule", content: "Use uv", source_refs: [] }], manifest: null }],
  };
  const ctx = { engineeringKnowledgeBusy: "", engineeringKnowledgeRetrievalLoading: "", engineeringKnowledgeRetrievalResults: {},
    handlePublishEngineeringKnowledgeVersion: noop, handleAssignEngineeringKnowledgeVersion: noop,
    handleRejectEngineeringKnowledgeVersion: noop, searchEngineeringKnowledgeRetrievalIndex: noop };
  const view = await mount("admin/components/EngineeringKnowledgePackDetailDrawer.tsx", "PackDetailDrawer", { pack, onClose: noop, ctx });
  assert.deepEqual(labels(view.root, "user-edit-panel__section-label").slice(0, 2), ["Toolchain Profiles", "Versions"]);
  assert.match(text(view.root), /Python pack/);
  assert.match(text(view.root), /1 version · published/);
  assert.match(text(view.root), /Sources: pep8: 1 · Targets: python: 3\.12/);
  assert.match(text(view.root), /Retrievable Items/);
  assert.equal(view.root.findAll((node) => node.props.className === "admin-panel__badge admin-panel__badge--active" && ["uv", "ruff"].includes(text(node))).length, 2);
  assert.ok(ofType(view.root, "button").map(text).includes("Close"));
});

test("Engineering knowledge review: filters, counts, one fact row and its detail", async () => {
  const node = { id: "n-1", node_type: "package", node_key: "pkg:requests", display_name: "requests", summary: "HTTP client",
    status: "active", scope_type: "platform", trust_level: "silver", classification: "internal", properties: {}, source_refs: [{}] };
  const payload = { items: [node], total: 1, stats: { status_counts: { active: 1 }, trust_counts: { silver: 1 } } };
  const view = await mount("admin/components/AdminEngineeringKnowledgeReviewPanel.tsx", "AdminEngineeringKnowledgeReviewPanel", {}, {
    "/utils/adminPanelHelpers": { readJson: async () => payload },
  });
  assert.match(text(view.root), /Review queue/);
  assert.equal(ofType(view.root, "select").length, 4);
  assert.equal(ofType(view.root, "tbody")[0].findAll((n) => n.type === "tr").length, 1);
  assert.deepEqual(labels(view.root, "admin-panel__hint").slice(0, 3), ["Total 1", "active: 1", "silver: 1"]);
  assert.match(text(view.root), /HTTP client/);
  assert.ok(ofType(view.root, "button").map(text).includes("Search"));
});
