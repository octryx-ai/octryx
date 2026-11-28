// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminDigestRenderGuards07.test.mjs
//
// Render guards for admin sections, drawers and cards whose long functions are split into smaller parts: each renders
// with representative props, keeps its key labels and test ids, and keeps its whole rendered tree (a digest of the test
// renderer's JSON), so the split draws exactly what the original drew.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement as h } from "react";
import { act, byId, digest, mount, noop, text } from "./adminDigestRenderHarness.mjs";

// --- Connections page -----------------------------------------------------------------------------------------------

const CONNECTION_ROWS = [
  { id: "c-1", type: "jira", name: "Jira Cloud", state: "failing", stateReason: "401", lastTestedAt: null, availableIn: "all", workspaces: [],
    uses: { knowledge: true, tickets: true, agentTools: "read" }, owner: { kind: "platform", workspace: null }, canEdit: false,
    deviationCount: 2, problemsCount: 0 },
  { id: "c-2", type: "github", name: "GitHub", state: "ok", stateReason: "", lastTestedAt: null, availableIn: "some",
    workspaces: [{ id: "w-1", name: "Ops" }], uses: { knowledge: false, tickets: false, agentTools: "none" },
    owner: { kind: "workspace", workspace: null }, canEdit: true, deviationCount: 0, problemsCount: 0 },
];

test("connections page: filters and table, the pending page and the error line", async () => {
  const path = "admin/components/connections/ConnectionsPage.tsx";
  const stubs = (result) => ({
    "/adminNavigation": { useAdminNavigation: () => ({ openAdminTab: noop }) },
    "/AdminHeaderSlot": { AdminHeaderActions: ({ children }) => h("header", null, children) },
    "/connectionsApi": { listConnections: async () => result, loadConnectionTypes: async () => [{ key: "jira", label: "Jira" }] },
    "/ConnectionDetailPanel": { ConnectionDetailPanel: () => null },
    "/AddConnectionPanel": { AddConnectionPanel: (props) => h("aside", { "data-types": props.types.length }) },
  });
  const view = await mount(path, "ConnectionsPage", { projects: [{ id: "w-1", name: "Ops" }] }, { stubs: stubs({ kind: "ok", connections: CONNECTION_ROWS }) });
  assert.equal(byId(view.root, "connections-type-filter").length, 1);
  assert.match(text(view.root), /read only/);
  assert.equal(digest(view), "624f515b51a744d7254389d243b59ec3e273f92b761017e6a2f2da2af3360acf");
  await act(async () => byId(view.root, "connections-add")[0].props.onClick());
  assert.equal(view.root.findAllByType("aside").length, 1);
  assert.equal(digest(view), "78dbe0d37140bb52697c9e4943db43df6855fa773b1ad498ec14bc94b5b609f7");
  const pending = await mount(path, "ConnectionsPage", { projects: [] }, { stubs: stubs({ kind: "needs_configuration" }) });
  assert.equal(byId(pending.root, "connections-pending").length, 1);
  assert.equal(digest(pending), "5505284419acb95e355d30530b7b7b3d6b7feebb2778be36d3a7b33993e43d03");
  const failed = await mount(path, "ConnectionsPage", { projects: [] }, { stubs: stubs({ kind: "error", message: "Server down" }) });
  assert.match(text(failed.root), /Server down/);
  assert.equal(digest(failed), "9016b175449371b3b71f606645289cb12078348816d71f4e0ebf3de7e10f78a6");
});

// --- Custom MCP panel and private hosts -----------------------------------------------------------------------------

test("custom MCP panel: fields, auto-start switch, error; hidden when closed", async () => {
  const path = "admin/components/AdminMcpCustomModal.tsx";
  const props = (overrides = {}) => ({
    open: true, workspaceName: "Ops", close: noop, customMcpName: "docs", setCustomMcpName: noop, customMcpTransport: "http",
    setCustomMcpTransport: noop, customMcpUrl: "https://mcp.example.test", setCustomMcpUrl: noop, customMcpDescription: "Docs",
    setCustomMcpDescription: noop, customMcpAutoStart: true, setCustomMcpAutoStart: noop, customMcpLoading: false,
    customMcpError: "Name taken", onCreate: async () => {}, ...overrides,
  });
  const view = await mount(path, "AdminMcpCustomModal", props());
  assert.match(text(view.root), /Workspace Ops/);
  assert.equal(view.root.findAll((node) => node.props.role === "switch" && typeof node.type === "string")[0].props["aria-checked"], true);
  assert.equal(digest(view), "87cedcae9b28ef1a3823cb2c791cba4ade4a262400705a43d0377e6c7deb4f53");
  const saving = await mount(path, "AdminMcpCustomModal", props({ customMcpLoading: true, customMcpError: null, customMcpAutoStart: false }));
  assert.equal(digest(saving), "9f33b5e00b722614f75be184a6a0c5ff6e2e0955dd12356d0d8cd09ed851d714");
  assert.equal((await mount(path, "AdminMcpCustomModal", props({ open: false }))).toJSON(), null);
});

test("private host card: rows with refusals, the add form and the input refusal; empty card", async () => {
  const path = "admin/components/connectorsTab/PrivateHostConnectionCard.tsx";
  const state = (overrides = {}) => ({
    drafts: [], loading: false, loadError: null, inputs: { bitbucket: "10.0.0.5:7990" }, inputRefusals: { bitbucket: "invalid_entry" },
    savingConnection: null, reload: noop, setInput: noop, add: noop, remove: noop, discard: noop, save: async () => {}, ...overrides,
  });
  const draft = {
    connection: "bitbucket", saved: ["10.0.0.1:7990"], dirty: true, listRefusal: "too_many",
    rows: [{ key: "r-1", value: "10.0.0.1:7990", refusal: null }, { key: "r-2", value: "10.0.0.2:22", refusal: { reason: "port" } },
      { key: "r-3", value: "10.0.0.3:443", refusal: null }],
  };
  const view = await mount(path, "PrivateHostConnectionCard", { draft, state: state() });
  assert.match(text(view.root), /Unsaved/);
  assert.match(text(view.root), /Not added: invalid_entry/);
  assert.equal(view.root.findAllByType("tr").length, 4);
  assert.equal(digest(view), "fbfa36e21711c0d7ba6ab97e47d8d1152e7f532f82d94d26eeed9fd0cd9ca57c");
  const empty = await mount(path, "PrivateHostConnectionCard", {
    draft: { connection: "jira", saved: [], rows: [], listRefusal: null, dirty: false }, state: state({ savingConnection: "jira", inputRefusals: {} }),
  });
  assert.match(text(empty.root), /No private hosts allowed/);
  assert.equal(digest(empty), "ec875ef3408e4ad8aa276cd5ea96b9e6722f7e9c40e60de2e3146ae2a1bb83b5");
});

// --- Agent workspace page and advanced fields -----------------------------------------------------------------------

test("agent workspace page: header, revision with the publish confirmation, overview facts", async () => {
  const path = "admin/components/agentsTab/AgentWorkspacePage.tsx";
  const revision = {
    state: "ready", revision: { status: "draft", revision_number: 3 }, execution: { mode: "draft" }, publishing: false,
    message: "Saved", publish: async () => {},
  };
  const stubs = {
    "/useAgentRevision": { useAgentRevision: () => revision },
    "/AgentTestAction": { AgentTestAction: (props) => h("button", { "data-blocked": props.blockedReason }, "Test") },
    "/AgentStepsSection": { AgentStepsSection: (props) => h("section", { "data-steps": props.steps.length }) },
    "/AgentReferencesSection": { AgentReferencesSection: () => null },
  };
  const agent = {
    id: "ag-1", name: "Coder", description: "Writes code", goal: "", capabilityCeiling: "write", defaultWorkflowKey: "", builtinKey: "",
    runtimeTargetId: "rt-1", groupName: "", thinkingLevel: "deep", requireSelfReview: true, branchPrefix: "", systemPrompt: "Be brief",
    outputPrompt: "", steps: [{ id: "s-1" }],
  };
  const props = {
    agent, ctx: { agentBuilderMeta: { runtime_options: [{ value: "rt-1", label: "Local GPU" }] } },
    readiness: { active: true, workspace: "Ops" }, workspaces: [], onBack: noop, onEdit: noop, onDelete: noop,
  };
  const view = await mount(path, "AgentWorkspacePage", props, { stubs });
  assert.match(text(view.root), /Draft revision 3 · not published/);
  assert.match(text(view.root), /Local GPU/);
  assert.equal(digest(view), "390f14e3b1abfaee7c9483f5713577e6441111ba8ac63bf40f88a3d0dbb93e74");
  const publish = view.root.findAll((node) => node.type === "button" && text(node) === "Publish draft…")[0];
  await act(async () => publish.props.onClick());
  assert.match(text(view.root), /Publish revision 3\?/);
  assert.equal(digest(view), "e908d7fb6d6c60d50395e666e8c84477464a2151515154212938f954c63cb10f");
});

test("agent advanced fields: open with values, closed without", async () => {
  const path = "admin/components/agentsTab/AgentAdvancedFields.tsx";
  const stubs = { "/AgentSkillPreferencesField": { AgentSkillPreferencesField: (props) => h("fieldset", { "data-preferred": props.preferredSkillIds.join() }) } };
  const ctx = {
    agentBuilderMeta: { thinking_levels: ["off", "deep"], runtime_options: [{ value: "", label: "Automatic" }, { value: "rt-1", label: "GPU" }] },
    agentFormBranchPrefix: "bot", agentFormBlockedSkillIds: [], agentFormOutputPrompt: "Short", agentFormPreferredSkillIds: ["s-1"],
    agentFormRequireSelfReview: true, agentFormRuntimeId: "rt-1", agentFormSystemPrompt: "Be brief", agentFormThinking: "deep",
  };
  const view = await mount(path, "AgentAdvancedFields", { ctx, skillOptions: [] }, { stubs });
  assert.equal(view.root.findByType("details").props.open, true);
  assert.equal(digest(view), "54d8a6b08752f7c1b231364705b9657c338a5b84ab2000134d9b79671307cbc0");
  const closed = await mount(path, "AgentAdvancedFields", { ctx: { agentFormThinking: "light" }, skillOptions: [] }, { stubs });
  assert.equal(closed.root.findByType("details").props.open, undefined);
  assert.equal(digest(closed), "ee1f7cc5d0e1a4d54255d6a9077fa1197f47ebe6fa31165a313bebdb814d21ba");
});

// --- Call sessions --------------------------------------------------------------------------------------------------

test("call sessions: rows with status, duration and start; the empty states", async () => {
  const now = Date.parse("2026-03-04T10:00:00Z");
  class FixedDate extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
  }
  const sessions = [
    { id: "cs-1234567890abcdef-1", call_id: "call-1234567890abcdef", project_name: "Ops", status: "completed", turns: 4, last_error: null,
      started_at: "2026-03-04T09:00:00Z", ended_at: "2026-03-04T09:02:05Z" },
    { id: "cs-2234567890abcdef-2", call_id: "", project_name: "", status: "active", turns: 1, last_error: "STT failed",
      started_at: "2026-03-01T10:00:00Z", ended_at: null },
    { id: "cs-3234567890abcdef-3", call_id: "", project_name: "Dev", status: "ringing", turns: 0, last_error: null, started_at: null, ended_at: null },
  ];
  const path = "admin/components/AdminCallSessionsSection.tsx";
  const respond = (body) => ({ globals: { Date: FixedDate, fetch: async () => ({ ok: true, status: 200, json: async () => body }) } });
  const view = await mount(path, "AdminCallSessionsSection", { teamsConfigured: true, onSetUpChannel: noop }, respond(sessions));
  assert.equal(view.root.findAllByType("tr").length, 4);
  assert.match(text(view.root), /2m 5s/);
  assert.equal(digest(view), "842a77b7a4bb875afcc6492e573f5a7e6616665febb7793a6edd0552716f283d");
  const none = await mount(path, "AdminCallSessionsSection", { teamsConfigured: false, onSetUpChannel: noop }, respond([]));
  assert.match(text(none.root), /Set up a channel/);
  assert.equal(digest(none), "acb934eb3ea844e0de3b6c80a9c19de4378fb318f73f4fb733477f432dfe3ac1");
});

// --- Steps canvas node ----------------------------------------------------------------------------------------------

test("steps canvas node: label, sub-label, badges and the selection", async () => {
  const path = "admin/components/flowBuilder/FlowNode.tsx";
  const stubs = { "@xyflow/react": { Handle: (props) => h("i", { "data-handle": props.type, className: props.className }), Position: { Left: "left", Right: "right" } } };
  const datas = [
    { id: "s", type: "tool_step", label: "Search", subLabel: "jira_search", badges: [{ label: "Strict", kind: "active" }] },
    { id: "c", type: "evaluation", label: "", subLabel: "Check", selected: true, badges: [{ label: "Blocking", kind: "danger" }] },
    { id: "r", type: "output", label: "Result", subLabel: "Answer" },
  ];
  const digests = [];
  for (const data of datas) digests.push(digest(await mount(path, "FlowNode", { data, selected: false }, { stubs })));
  assert.equal(digest({ toJSON: () => digests }), "b35eaa31b07e033da81661ea574d7f8c93d7b191f6fc1a1c11042b7db9c9f736");
});

// --- Corporate identity template card -------------------------------------------------------------------------------

test("corporate template card: read view and the inline editor", async () => {
  const path = "admin/components/corpIdentity/CorpTemplateCard.tsx";
  const template = { id: "tp-1", type: "pptx", display_name: "Board deck", source_file_name: "board.pptx", description: "Quarterly" };
  const view = await mount(path, "TemplateCard", { template, isBusy: true, onUpdate: noop, onDelete: noop });
  assert.match(text(view.root), /Board deck/);
  assert.equal(digest(view), "61cbece76d18befe0921d08bd79fe4c0dd18e800ffaf4f95f00ce18b837cb97f");
  const edit = view.root.findAll((node) => node.type === "button" && node.props.title === "Edit name/description")[0];
  await act(async () => edit.props.onClick());
  assert.equal(view.root.findByType("input").props.value, "Board deck");
  assert.equal(digest(view), "13561535a4e66883da1b09d970dd9a92cff7808ca251db41e8bff1f1b6f6f277");
  const bare = await mount(path, "TemplateCard", { template: { ...template, display_name: "", description: "" }, isBusy: false, onUpdate: noop, onDelete: noop });
  assert.equal(digest(bare), "2e634eceda5ef4e6208b056ee782c41270133f9de444d0ae5ffd25c4d7086a85");
});

// --- Classification add rule drawer ---------------------------------------------------------------------------------

test("classification add rule: the three steps", async () => {
  const path = "admin/components/dataClassification/ClassificationRuleDrawer.tsx";
  const stubs = { "/adminNavigation": { useAdminNavigation: () => ({ openAdminTab: noop }) } };
  const catalog = [
    { key: "mcp_off", label: "MCP off", description: "Turns MCP servers off", param: "server", enforced: true, enforcedAt: "tool call" },
    { key: "later", label: "Later", description: "Not yet", param: "none", enforced: false, enforcedAt: "" },
  ];
  const levels = [
    { key: "public", rank: 0, label: "Public" }, { key: "internal", rank: 1, label: "Internal" }, { key: "secret", rank: 2, label: "Secret" },
  ];
  const props = {
    catalog, levels, servers: ["docs", "jira"], existing: [{ effect: "mcp_off", param: "docs", from_level: "internal" }],
    workspaceLevels: ["public", "secret", null], levelLabel: (key) => key.toUpperCase(), onClose: noop, onSave: noop,
  };
  const view = await mount(path, "ClassificationAddRuleDrawer", props, { stubs });
  const digests = [digest(view)];
  await act(async () => byId(view.root, "rule-effect-mcp_off")[0].props.onChange());
  digests.push(digest(view));
  await act(async () => byId(view.root, "rule-next")[0].props.onClick());
  assert.equal(byId(view.root, "rule-param")[0].props.value, "docs");
  digests.push(digest(view));
  await act(async () => byId(view.root, "rule-next")[0].props.onClick());
  assert.match(text(view.root), /This rule is already in the draft/);
  assert.match(text(view.root), /1 Workspace affected/);
  digests.push(digest(view));
  assert.equal(digest({ toJSON: () => digests }), "18ebfac99a85b72fb711ebf6b5e3d6fa58fe2f41e1356a00cda1543d05d8d864");
});
