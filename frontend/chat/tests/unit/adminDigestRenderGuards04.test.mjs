// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminDigestRenderGuards04.test.mjs
//
// Render guards for admin panels, cards and inspectors whose long functions are split into smaller parts: each renders
// with representative props, keeps its key labels and test ids, and keeps its whole rendered tree (a digest of the
// test renderer's JSON), so the split draws exactly what the original drew.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement as h } from "react";
import { act, byId, digest, labels, mount, noop, server, text, tick } from "./adminDigestRenderHarness.mjs";

// --- Databases tab --------------------------------------------------------------------------------------------------

test("databases tab: the filter, both tables, the open database's panel and the remove confirmation", async () => {
  const path = "admin/components/databases/AdminDatabasesTab.tsx";
  const Null = () => null;
  const stubs = {
    "/AutomationIcon": { AutomationIcon: Null },
    "/ManagedDatabaseConnectorCard": { ManagedDatabaseConnectorCard: () => "managed-card" },
    "/AddDatabaseConnectorModal": { AddDatabaseConnectorModal: Null },
    "/AddDatabaseToolModal": { AddDatabaseToolModal: Null },
  };
  const QUERY = { id: "q-1", tool: "orders", database: "Shop", status: "failed", failure_category: "timeout", rows: 0, limit_reached: false,
    who: "dana", workspace: "Ops", started_at: null };
  const ctx = {
    databaseConnectors: [
      { id: "db-1", name: "Shop", db_type: "postgres", is_active: true, tool_count: 2, health: { status: "ok" } },
      { id: "db-2", name: "Legacy", db_type: "mysql", is_active: false, tool_count: 0 },
    ],
    expandedDatabaseConnector: "db-1", readJson: async () => [QUERY],
  };
  const view = await mount(path, "AdminDatabasesTab", { ctx }, { stubs });
  assert.equal(byId(view.root, "database-panel").length, 1);
  assert.match(text(view.root), /orders/);
  assert.equal(digest(view), "46446b9a46763c55822f332fa4e937930dc22dc4c8e6f1f08c379f1b8d5e86a7");
  await act(async () => byId(view.root, "database-remove")[0].props.onClick());
  assert.match(text(view.root), /Remove Shop\?/);
  assert.equal(digest(view), "4d0d50127fb2f79402e954f6ca5f3524852ecf9f6a35567652e0081bfc9d69f7");
  const empty = await mount(path, "AdminDatabasesTab", { ctx: { readJson: async () => { throw new Error("x"); } } }, { stubs });
  assert.equal(byId(empty.root, "database-empty").length, 1);
  assert.equal(digest(empty), "140f0b59bfc45d112dca6d40223f219f27c0cf94e1e28f22b8a6b151d5b5f3f0");
});

// --- Workspaces list ------------------------------------------------------------------------------------------------

test("workspaces list: toolbar, every optional column, class cells, the row menu and the empty table", async () => {
  const path = "admin/components/AdminProjectsSummarySection.tsx";
  const adminProjects = [
    { id: "p-1", name: "Petclinic", description: "Spring demo", is_active: true, class: "confidential", member_count: 4,
      updated_at: "2026-11-06T10:00:00+00:00" },
    { id: "p-2", name: "Archived test", description: "", is_active: false, template_key: "tpl" },
    { id: "p-0", name: "Default", description: "", is_active: true, is_system: true, is_default: true },
  ];
  const props = {
    adminProjects, handleOpenProjectQualityForm: noop, projectActionLoading: "archive:p-1", onCreateWorkspace: noop,
    onArchiveProject: noop, onRestoreProject: noop, onMakeDefaultProject: noop, onDeleteProject: noop, highlightedProjectId: "p-1",
    problemCounts: { "p-1": { total: 3, problem: 1 }, "p-0": { total: 0, problem: 0 } },
    workspaceClasses: { "p-1": { level: "confidential", label: "Confidential" } }, onOpenClassification: noop,
  };
  const view = await mount(path, "AdminProjectsSummarySection", props);
  assert.equal(byId(view.root, "workspace-create").length, 1);
  assert.match(text(view.root), /Petclinic/);
  assert.equal(digest(view), "2e3ffeff2b2f81f89be7e8ed2152b7c51133418210542fa6aa9fcc573486a68d");
  const plain = await mount(path, "AdminProjectsSummarySection", { adminProjects: [], handleOpenProjectQualityForm: noop });
  assert.match(text(plain.root), /No workspaces yet\./);
  assert.equal(digest(plain), "30ebfb07e4551635458fb8e89782efa987513cb63117b51bce4b15f2db6796fd");
});

// --- MCP install panel ----------------------------------------------------------------------------------------------

test("MCP install panel: install and edit, select, secret and text fields, auto-start and the error", async () => {
  const path = "admin/components/AdminMcpInstallModal.tsx";
  const preset = {
    name: "GitHub", default_name: "github", description: "GitHub tools",
    fields: [
      { name: "mode", label: "Mode", type: "select", options: ["read", "write"], default: "read", required: true },
      { name: "token", label: "Token", type: "password", required: true },
      { name: "org", label: "Organisation", type: "text", placeholder: "acme" },
    ],
  };
  const props = (editingServerName, extra = {}) => ({
    selectedPreset: preset, editingServerName, workspaceName: "Ops", close: noop, mcpInstallName: "github", setMcpInstallName: noop,
    mcpInstallValues: { org: "acme-org" }, setMcpInstallValues: noop, mcpInstallAutoStart: true, setMcpInstallAutoStart: noop,
    mcpInstallError: "Name taken", mcpInstallLoading: false, handleInstallMcpCatalog: async () => {}, ...extra,
  });
  const install = await mount(path, "AdminMcpInstallModal", props(null));
  assert.match(text(install.root), /New registrations start inactive\./);
  assert.equal(digest(install), "b63c8af84ca476ee13f2a3b5f8fb69f90bb8db4d26508ed687ac7b2d8f96414f");
  const edit = await mount(path, "AdminMcpInstallModal", props("github", { mcpInstallLoading: true, mcpInstallError: null, mcpInstallAutoStart: false }));
  assert.match(text(edit.root), /Saving…/);
  assert.equal(digest(edit), "4045b9f0f53cc3f78c2ecb8134d11a6340a294f2ceae58e728714455a7c17bce");
  const none = await mount(path, "AdminMcpInstallModal", props(null, { selectedPreset: null }));
  assert.equal(none.toJSON(), null);
});

// --- Knowledge graph canvas -----------------------------------------------------------------------------------------

// React Flow is replaced by a recorder: it draws every node and edge through the canvas's own node and edge types, so
// the digest covers the computed positions, states, labels and edge looks as well as the drawn markup.
function flowStub(calls) {
  const flow = {
    fitView: (options) => calls.push(["fitView", options?.nodes?.length ?? 0]), zoomIn: () => {}, zoomOut: () => {},
    getViewport: () => ({ x: 0, y: 0, zoom: 1 }), setViewport: () => {},
  };
  const plain = (name) => (props) => h(name, { "data-props": JSON.stringify(props, (key, value) => (key === "children" ? undefined : value)) }, props.children);
  return {
    ReactFlowProvider: ({ children }) => children,
    useReactFlow: () => flow,
    ReactFlow: (props) => h("rf", { fitview: JSON.stringify(props.fitViewOptions), minimap: String(props.onlyRenderVisibleElements) },
      ...props.nodes.map((node) => h("rf-node", { key: node.id, json: JSON.stringify({ ...node, data: undefined }) },
        h(props.nodeTypes[node.type], { id: node.id, data: node.data }))),
      ...props.edges.map((edge) => h("rf-edge", { key: edge.id, json: JSON.stringify({ ...edge, data: undefined }) },
        h(props.edgeTypes[edge.type], { id: edge.id, sourceX: 0, sourceY: 0, targetX: 30, targetY: 40, data: edge.data }))),
      props.children),
    Controls: plain("rf-controls"), MiniMap: plain("rf-minimap"), Handle: plain("rf-handle"), BaseEdge: plain("rf-base-edge"),
    EdgeLabelRenderer: ({ children }) => h("rf-edge-label", null, children), Position: { Top: "top" },
  };
}

test("knowledge graph canvas: nodes, cluster names, labels, edges and the minimap; with and without a selection", async () => {
  const path = "admin/components/entityGraph/KnowledgeGraphCanvas.tsx";
  const nodes = Array.from({ length: 34 }, (_, index) => ({
    id: `n${index}`, node_type: index % 3 ? "Service" : "Team", display_name: `Entity ${index}`, description: "", degree: index % 4,
    trust_level: "high",
  }));
  const edges = nodes.slice(1).map((node, index) => ({
    id: `e${index}`, source: nodes[index].id, target: node.id, edge_type: index % 2 ? "depends_on" : "owns", description: "",
  }));
  const positions = new Map(nodes.map((node, index) => [node.id, { x: (index % 6) * 120, y: Math.floor(index / 6) * 110, r: 8 + (index % 3) * 4,
    cluster: node.node_type, hub: index % 7 === 0 }]));
  const props = {
    nodes, edges, positions, slots: new Map([["Team", 0], ["Service", 1]]), selectedId: "", matches: new Set(["n4"]),
    clusters: [{ type: "Team", x: 100, y: 100, r: 80, size: 12 }, { type: "Service", x: 500, y: 300, r: 140, size: 22 }],
    fresh: new Set(["n2"]), faintIds: new Set(["n30"]), onSelect: noop, onExpand: noop, onClear: noop,
  };
  const calls = [];
  const options = { stubs: { "@xyflow/react": flowStub(calls) } };
  const idle = await mount(path, "default", props, options);
  assert.equal(idle.root.findAll((node) => node.props["data-testid"] === "kg-node" && typeof node.type === "string").length, 34);
  assert.equal(digest(idle), "4d39b0835659ffacc530163b2d1f3c59014cfa5afedaea4e2fe72d80cd526102");
  const selected = await mount(path, "default", { ...props, selectedId: "n6", mode: "ego", labelPool: new Set(["n0"]), fitIds: ["n0", "n6"] }, options);
  await tick(80);
  assert.ok(calls.some(([name, count]) => name === "fitView" && count > 0), "a selection fits its neighbourhood");
  assert.equal(digest(selected), "535c28d407189f41d7ef37afc463ee104066cc3a0de37d61fa0f5837a8d27fbb");
});

// --- Channels tab ---------------------------------------------------------------------------------------------------

test("channels tab: overview with an open channel, outbound, sessions and the config modal", async () => {
  let pick = noop;
  const stubs = {
    "/AdminHeaderSlot": { AdminHeaderActions: ({ children }) => children },
    "/AdminChannelSectionTabs": { AdminChannelSectionTabs: ({ value, onChange }) => { pick = onChange; return h("nav", { "data-section": value }); } },
    "/AdminProblemAlertsSection": { AdminProblemAlertsSection: () => "alerts" },
    "/AdminCallSessionsSection": { AdminCallSessionsSection: ({ teamsConfigured }) => `calls ${teamsConfigured}` },
  };
  const channels = [
    { id: 1, plugin_id: "msteams", name: "Teams Ops", description: "Ops bot", project_id: "p1", project_name: "Ops", enabled: true,
      config: {}, status: "running", updated_at: null, config_fields: [] },
    { id: 2, plugin_id: "slack", name: "Slack Dev", description: "", project_id: null, project_name: null, enabled: false, config: {},
      status: "stopped", updated_at: null, config_fields: [] },
  ];
  const ctx = new Proxy({
    channels, channelSessions: [], channelDeliveryTargets: [], channelDeliveryLogs: [], projects: [{ id: "p1", name: "Ops" }],
    availableChannels: [], filteredAvailableChannels: [], configuringChannel: { ...channels[1], config_fields: [{ name: "token" }] },
    showAddChannel: false, channelFormValues: {}, channelConfigJson: "{}", channelFormName: "Slack Dev", channelFormProjectId: "",
    channelDeliveryProjectId: "", channelDeliveryEventType: "approval.requested", channelDeliveryChannelId: "", channelDeliveryTarget: "",
    channelCatalogSearch: "", availableLoading: true, channelFormError: "Token missing",
    getChannelIconColor: () => "inherit", renderChannelIcon: () => null, formatRelativeTime: () => "just now", readJson: async () => ({}),
  }, { get: (target, key) => (key in target ? target[key] : noop) });
  const view = await mount("admin/components/AdminChannelsTab.tsx", "AdminChannelsTab", { ctx }, { stubs });
  assert.equal(text(byId(view.root, "channel-add")[0]), "Loading…");
  const row = view.root.findAll((node) => node.type === "tr" && node.props["data-row-key"] === "1")[0];
  await act(async () => row.props.onClick());
  assert.equal(byId(view.root, "channel-panel").length, 1);
  assert.equal(digest(view), "4faded15533536f536de22e6c875718d11fdfb1315c9b2b0bfa9f233aa155de9");
  await act(async () => pick("outbound"));
  assert.equal(digest(view), "79fe1ed3ce1f7991d67c0e6c225d633f6635e0e6489039e26e764083fbecdc19");
  await act(async () => pick("sessions"));
  assert.match(text(view.root), /calls true/);
  assert.equal(digest(view), "672c059aba83c5ef91fbde98449cef3a20d4d828b5c917eb76b87738c30b3900");
  await act(async () => pick("alerts"));
  assert.equal(digest(view), "994bc949827b8984d2a68a5cb6d1a6aeeddc3062417cbdb82d9c71ba893c42ac");
});

// --- Managed database fields ----------------------------------------------------------------------------------------

test("managed database fields: the eight fields, stored secrets and the SQLite file path", async () => {
  const path = "admin/components/connectorsTab/ManagedDatabaseConnectorFields.tsx";
  const draft = { description: "Reports", db_type: "postgresql", host: "db", port: "5432", database: "app", username: "ro", password: "",
    dsn: "", driver: "psycopg", file_path: "/x.db" };
  const stored = await mount(path, "ManagedDatabaseConnectorFields", {
    connector: { id: "db-1", secret_status: { password: true, dsn: true } }, draft, setDatabaseConnectorDraftField: noop });
  assert.equal(labels(stored.root, "connector-field__label").at(-1), "Driver");
  assert.equal(digest(stored), "68f1681cd0407055ab5b487881067165fdf0fd5f5beaff595cf950f137141227");
  const sqlite = await mount(path, "ManagedDatabaseConnectorFields", {
    connector: { id: "db-2", secret_status: {} }, draft: { ...draft, db_type: "sqlite" }, setDatabaseConnectorDraftField: noop });
  assert.equal(labels(sqlite.root, "connector-field__label").at(-1), "File path");
  assert.equal(digest(sqlite), "4b26ddf3b5b07c1941767b80df630cf68e42b3caa432781adfa5f27f4a73c4f6");
});

// --- Default tool sets ----------------------------------------------------------------------------------------------

test("default tool sets: the cards (seeded and edited), one in edit, and the error of a refused save", async () => {
  const payload = { source: "db", override_supported: true, sets: [
    { capability_type: "diagnosis", key: "diagnosis.v2", version: 2, seed_key: "diagnosis.v1", matches_seed: false, title: "Diagnosis",
      description: "Read-only tools", families: [{ name: "logs", tools: ["read_logs", "grep"] }, { name: "code", tools: ["read_file"] }],
      unregistered_tools: ["ghost"], history: [{ key: "diagnosis.v2", action: "policy_list.update", actor: "dana", at: null }],
      capability_classes: ["diagnosis"] },
    { capability_type: "change", key: "change.v1", version: 1, seed_key: "change.v1", matches_seed: true, title: "Change",
      description: "", families: [{ name: "edit", tools: ["write_file"] }], capability_classes: ["code_change"] },
    { capability_type: "plan", key: "plan.v1", version: 1, seed_key: "plan.v1", matches_seed: true, families: [], capability_classes: [] },
  ] };
  const srv = server((call) => (call.method === "GET" ? { status: 200, body: payload } : { status: 409, body: { detail: "conflict" } }));
  const view = await mount("admin/components/AdminDefaultToolSetsSection.tsx", "AdminDefaultToolSetsSection", {}, { globals: { fetch: srv.fetch } });
  await tick();
  assert.match(text(view.root), / · 3 sets/);
  assert.equal(digest(view), "d289927fff68045a404fbb15ea7941e766539fec49189e0b88777677d1f45b9d");
  const edit = view.root.findAll((node) => node.type === "button" && text(node) === "Edit")[0];
  await act(async () => edit.props.onClick());
  assert.equal(view.root.findAllByType("textarea").length, 1);
  const save = view.root.findAll((node) => node.type === "button" && text(node) === "Save as next version")[0];
  await act(async () => save.props.onClick());
  await tick();
  assert.equal(srv.calls.filter((call) => call.method === "PUT").length, 1);
  assert.equal(view.root.findAll((node) => node.props.className === "admin-panel__error" && typeof node.type === "string").length, 1);
  assert.equal(digest(view), "fa78e776c6acb2be16bca616d3c4acb8c81eb3d11b8cc9be658676b916e3ebf3");
});
