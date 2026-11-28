// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminDigestRenderGuards02.test.mjs
//
// Render guards for admin pages, drawers and cards whose long functions are split into smaller parts: each renders
// with representative props, keeps its key labels and test ids, and keeps its whole rendered tree (a digest of the
// test renderer's JSON), so the split draws exactly what the original drew.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, byId, digest, labels, mount, noop, server, text, tick } from "./adminDigestRenderHarness.mjs";

// --- Agent form -----------------------------------------------------------------------------------------------------

const stubPart = (name) => ({ [name]: (props) => createElement("section", { "data-part": name, "data-value": JSON.stringify(props.value ?? null) }) });

test("agent form: the basics, the setup parts, the group choice, the active switch and the error", async () => {
  const stubs = {
    "/AgentSetupField": stubPart("AgentSetupField"), "/AgentToolSurfaceField": stubPart("AgentToolSurfaceField"),
    "/AgentReplyFormatField": stubPart("AgentReplyFormatField"), "/AgentAdvancedFields": stubPart("AgentAdvancedFields"),
  };
  const ctx = {
    agentBuilderMeta: { agent_groups: [{ id: "g-1", name: "Builders" }] },
    agentFormActive: true, agentFormDescription: "Builds knowledge", agentFormError: "Name is taken", agentFormGoal: "Keep notes",
    agentFormGroupId: "g-1", agentFormLoading: false, agentFormName: "Builder", agentFormReplyFormat: { kind: "text" },
    agentFormSetup: "setup", agentFormToolSurface: "read", closeAgentForm: noop, editingAgent: { name: "Builder", steps: [] },
    handleSaveAgent: noop, readJson: undefined, showAgentForm: true,
    setAgentFormActive: noop, setAgentFormDescription: noop, setAgentFormGoal: noop, setAgentFormGroupId: noop, setAgentFormName: noop,
    setAgentFormError: noop, setAgentFormReplyFormat: noop, setAgentFormSetup: noop, setAgentFormToolSurface: noop,
  };
  const view = await mount("admin/components/agentsTab/AgentFormPanel.tsx", "AgentFormPanel", { ctx }, { stubs });
  assert.deepEqual(labels(view.root, "admin-panel__form-label").map((label) => label.replace(/\s+/g, " ").trim()),
    ["Name *", "Description", "Goal", "Group"]);
  assert.match(text(view.root), /Save agent/);
  assert.match(text(view.root), /Name is taken/);
  assert.equal(digest(view), "bde2d2ac4d38dedfcbb9140c589cd1814345bd9f0a4411634fe3b9d4d8f6d33f");
});

// --- Users tab section switch ---------------------------------------------------------------------------------------

// Every value of the model and the context names itself; every function records its name and arguments when called.
function recordingObject(calls, prefix, explicit = {}) {
  return new Proxy(explicit, {
    get: (target, key) => {
      if (key in target) return target[key];
      if (typeof key !== "string") return undefined;
      if (/^(handle|load|set|open|on|create|save|update|revoke)/.test(key)) return (...args) => { calls.push([`${prefix}.${key}`, ...args]); };
      return `${prefix}:${key}`;
    },
  });
}

test("users tab: each section renders its panel with the same props and handlers", async () => {
  const calls = [];
  const model = recordingObject(calls, "model", {
    identityProviders: recordingObject(calls, "providers"), userApiKeys: recordingObject(calls, "apiKeys"),
  });
  const panel = (name) => ({ [name]: (props) => createElement("panel", { name, props: JSON.stringify(props, (key, value) => (typeof value === "function" ? "fn" : value)) }) });
  const stubs = {
    "/AdminEffectiveAccessPanel": panel("AdminEffectiveAccessPanel"), "/AdminGroupsPanel": panel("AdminGroupsPanel"),
    "/AdminIdentityProvidersPanel": panel("AdminIdentityProvidersPanel"), "/AdminUserAccountsPanel": panel("AdminUserAccountsPanel"),
    "/AdminRolesPanel": panel("AdminRolesPanel"), "/useAdminUsersTabModel": { useAdminUsersTabModel: () => model },
    "/useConfirmAction": { useConfirmAction: () => ({ ask: noop, notice: createElement("i", { id: "notice" }), dialog: createElement("i", { id: "dialog" }) }) },
  };
  const ctx = recordingObject(calls, "ctx", { users: [{ id: "u-1" }, { id: "u-2" }] });
  const lines = [];
  for (const section of ["users", "roles", "groups", "access", "providers"]) {
    const view = await mount("admin/components/AdminUsersTab.tsx", "AdminUsersTab", { ctx, section }, { stubs });
    const shown = view.root.findAll((node) => node.type === "panel");
    assert.equal(shown.length, 1, section);
    lines.push(JSON.stringify(view.toJSON()));
    const handlers = view.root.findAll((node) => node.type !== "panel" && typeof node.type === "function" && /Panel$/.test(node.type.name || ""));
    for (const node of handlers) for (const value of Object.values(node.props)) if (typeof value === "function") value("a", "b");
  }
  lines.push(JSON.stringify(calls));
  const all = { toJSON: () => lines };
  assert.ok(calls.length > 40, "every panel handler reaches the model or the context");
  assert.equal(digest(all), "48bab4f1688e3614caca86bd6275322774807bf53ac9e740af507da872141924");
});

// --- Backup and restore ---------------------------------------------------------------------------------------------

test("backup and restore: create a backup shows the job and its download, beside the restore card and the history", async () => {
  const calls = [];
  const readJson = async (url, init) => {
    calls.push([url, init?.method ?? "GET", init?.body ?? null]);
    if (url.endsWith("/exports")) return { id: "job 1", status: "completed", file_size_bytes: 3 * 1024 * 1024 };
    return { items: [] };
  };
  const projects = [{ id: "p-1", name: "Alpha" }, { id: "p-2", name: "Beta" }];
  const view = await mount("admin/components/AdminBackupRestoreTab.tsx", "AdminBackupRestoreTab", { projects, readJson });
  const select = view.root.findAll((node) => node.type === "select")[0];
  await act(async () => select.props.onChange({ target: { value: "p-2" } }));
  await act(async () => view.root.find((node) => node.type === "button" && text(node) === "Create backup").props.onClick());
  await tick();
  assert.match(text(view.root), /Beta backup is completed\. Size: 3\.0 MB\./);
  assert.equal(view.root.findAll((node) => node.type === "a" && text(node) === "Download JSON").length, 1);
  calls.push(JSON.stringify(view.toJSON()));
  const all = { toJSON: () => calls };
  assert.equal(digest(all), "705247c60eaeffa263574eb6d13667711387eb7cab257e245452a4b3078abe6f");
});

// --- Action card header ---------------------------------------------------------------------------------------------

test("action card header: status dot, badges, last run and the row actions, in a panel and as a card", async () => {
  const task = {
    id: "t-1", name: "Nightly report", description: "Sends the report", is_active: false, running_count: 0, task_type: "scheduled",
    agent_type: "research", step_count: 2, dependency_count: 1, dependent_count: 3, queued_count: 2, next_queue_priority: 5,
    last_run_status: "failed", last_run_at: null, trigger_type: "manual",
  };
  const props = {
    task, isExpanded: true, inPanel: true, triggeringTask: null, onExpandTask: noop, onTriggerTask: noop, onOpenTaskForm: noop,
    setShowTaskForm: noop, onToggleTask: noop, onDeleteTask: noop, agentModeNameByKey: new Map([["research", "Researcher"]]),
    statusColor: { failed: "#f00" },
  };
  const panel = await mount("admin/components/AdminTaskCardHeader.tsx", "AdminTaskCardHeader", props);
  assert.equal(byId(panel.root, "action-started-by").length, 1);
  assert.match(text(panel.root), /Paused/);
  assert.match(text(panel.root), /2 queued · p5/);
  assert.equal(digest(panel), "86551b33eb4dd513e80dae34c4688df9e85e2b2c911830dc10903dbc06600fc4");
  const card = await mount("admin/components/AdminTaskCardHeader.tsx", "AdminTaskCardHeader",
    { ...props, inPanel: false, task: { ...task, is_active: true, running_count: 1, last_run_status: null, step_count: 1 } });
  assert.equal(card.root.findAllByType("svg").length, 1);
  assert.match(text(card.root), /Never executed/);
  assert.equal(digest(card), "503291f9993d9e82e1412d7bc92ee199c3f2ae2d3aef2586ffc16d7f6aff5cae");
});

// --- Limits and budgets ---------------------------------------------------------------------------------------------

test("limits and budgets: the limit rows, overrides, technical limits, budget periods and the save button", async () => {
  const srv = server((call) => {
    if (call.url.endsWith("/runtime-settings")) return { status: 200, body: { agent_session_cost_limit_usd: 0, max_output_tokens_default: 4096 } };
    if (call.url.endsWith("/limits/overview")) {
      return { status: 200, body: {
        gateway_daily_baseline_usd: 5, workspace_overrides: { agent_session_cost_limit_usd: [{ workspace_id: "p-1", name: "Alpha", value: "3" }] },
        environment_limits: [{ key: "rate", label: "Rate limit", value: "60/min" }],
        budgets: [{ id: "b-1", scope_label: "Platform", period: "monthly", amount_usd: "100", used_usd: "40", block_at_percent: 100 }],
        workspaces: [], users: [],
      } };
    }
    return { status: 200, body: {} };
  });
  const view = await mount("admin/components/limits/AdminLimitsAndBudgets.tsx", "AdminLimitsAndBudgets", {}, { globals: { fetch: srv.fetch } });
  await tick();
  assert.equal(byId(view.root, "budget-table").length, 1);
  const overrides = view.root.findAll((node) => node.type === "button" && node.props["aria-expanded"] === false);
  assert.ok(overrides.length >= 1);
  await act(async () => overrides[0].props.onClick());
  assert.equal(byId(view.root, "limit-overrides").length, 1);
  assert.equal(digest(view), "cf381a1866d8a130c2f2c2d8bf0991e215b973f88185cb1a8bca55a28b9494ba");
});

// --- Agent step form ------------------------------------------------------------------------------------------------

test("agent step form: name, type, instructions, criteria, tools, the open JSON configuration and the enabled switch", async () => {
  const ctx = {
    agentBuilderMeta: { step_type_options: ["llm", "tdd_cycle"], tool_options: [{ name: "search", label: "Search" }] },
    agentStepFormAllowedTools: "search", agentStepFormConfig: "{ not json", agentStepFormEnabled: true, agentStepFormError: "Check the step",
    agentStepFormFor: "agent-1", agentStepFormInstructions: "Find it", agentStepFormLoading: false, agentStepFormName: "Find",
    agentStepFormSuccessCriteria: "Found", agentStepFormType: "tdd_cycle", closeAgentStepForm: noop, editingAgentStep: { name: "Find" },
    handleSaveAgentStep: noop, setAgentStepFormAllowedTools: noop, setAgentStepFormConfig: noop, setAgentStepFormEnabled: noop,
    setAgentStepFormInstructions: noop, setAgentStepFormName: noop, setAgentStepFormSuccessCriteria: noop, setAgentStepFormType: noop,
  };
  const view = await mount("admin/components/agentsTab/AgentStepFormPanel.tsx", "AgentStepFormPanel", { agentId: "agent-1", ctx });
  assert.equal(view.root.findByType("details").props.open, true);
  assert.match(text(view.root), /Save step/);
  assert.match(text(view.root), /Check the step/);
  assert.equal(digest(view), "3bff374d0a2fde4ce818be7e7c46b6ffd95152e47985adb3abefbb1d51295409");
});

// --- Schedulers -----------------------------------------------------------------------------------------------------

class FixedDate extends Date {
  constructor(...args) { if (args.length) super(...args); else super("2026-11-20T10:00:00Z"); }
  static now() { return new FixedDate().getTime(); }
}

test("schedulers: header action, status bar, the table with its columns and menus, and an open row's panel", async () => {
  const scheduler = (id, extra) => ({
    id, name: `Job ${id}`, description: "", cron_expression: "0 8 * * *", schedule_words: "Every day at 08:00", task_id: "t-1",
    task_name: "Nightly sync", is_active: true, read_only: false, next_run_at: "2099-01-05T08:00:00Z", last_run_at: null, ...extra,
  });
  const ctx = {
    schedulers: [scheduler("a", { worker_application: { status: "applied", next_run_at: "2099-01-05T08:00:00Z", timezone: "UTC" } }),
      scheduler("b", { is_active: false, read_only: true })],
    setSchedulers: noop, tasks: [{ id: "t-1", name: "Nightly sync" }], showSchedulerForm: false, editingScheduler: null,
    schedulerFormName: "", setSchedulerFormName: noop, schedulerFormDesc: "", setSchedulerFormDesc: noop, schedulerFormCron: "",
    setSchedulerFormCron: noop, schedulerFormTaskId: "", setSchedulerFormTaskId: noop, schedulerFormLoading: false,
    schedulerFormError: null, onCreateScheduler: noop, onOpenSchedulerForm: noop, onCloseSchedulerForm: noop, onSaveScheduler: noop,
    onToggleScheduler: noop, onDeleteScheduler: noop,
  };
  const view = await mount("admin/components/AdminSchedulersTab.tsx", "AdminSchedulersTab", { ctx },
    { globals: { Date: FixedDate, fetch: server(() => ({ status: 200, body: {} })).fetch } });
  assert.equal(byId(view.root, "schedulers-table").length, 1);
  assert.equal(byId(view.root, "scheduler-state-a").length, 1);
  const row = view.root.findAll((node) => node.type === "tr" && node.props["data-row-key"] === "a")[0];
  await act(async () => row.props.onClick({ target: {}, currentTarget: {} }));
  assert.equal(digest(view), "efcbe5c2c7e0714a4cc073d707c41d60ef1b48f4d9ac521c279e8c4030be98ac");
});

// --- Admin panel shell ----------------------------------------------------------------------------------------------

test("admin panel shell: sidebar groups with an open entry's sub-pages, the header and the body, with and without close", async () => {
  const shell = (props) => mount("admin/components/AdminPanelShell.tsx", "AdminPanelShell", {
    tab: "workflowDesigner", setTab: noop, currentTabLabel: "Workflow designer", area: "workflows", children: createElement("main", null, "page"),
    externalNav: [{ key: "repos", label: "Repositories", group: "Workflows", onSelect: noop, icon: null }], ...props,
  });
  const workflows = await shell({});
  assert.ok(workflows.root.findAll((node) => node.props.className === "admin-panel__tab-group" && typeof node.type === "string").length > 1);
  assert.equal(digest(workflows), "42eb11f1436ae9b1f82047f4862eeb7030831aee628a27152785ae24df24b3d9");
  const admin = await shell({ area: "admin", tab: "adminConnections", currentTabLabel: "Connections", onClose: noop });
  assert.equal(admin.root.findAll((node) => node.props["aria-label"] === "Close settings" && node.type === "button").length, 1);
  assert.equal(digest(admin), "0d296b965c43b7313da11a8fb3a6ed58ebef62957c88a292059b1c4deb6b6801");
});

// --- Engineering knowledge federation -------------------------------------------------------------------------------

test("knowledge federation: the summary tiles, the feed form, the tables and the review actions of a pending import", async () => {
  const json = (value) => JSON.stringify(value, (key, item) => (typeof item === "function" ? "fn" : item));
  const part = (name) => (props) => createElement("section", { "data-part": name, "data-props": json(props) });
  const stubs = {
    "/AdminEngineeringKnowledgeExportPreviewPanel": { AdminEngineeringKnowledgeExportPreviewPanel: part("export") },
    "/AdminEngineeringKnowledgeFederationFeedTable": { AdminEngineeringKnowledgeFederationFeedTable: part("feeds") },
    "/AdminEngineeringKnowledgeFederationOperationsPanel": { AdminEngineeringKnowledgeFederationOperationsPanel: part("operations") },
    "/AdminEngineeringKnowledgeFederationFeedForm": { AdminEngineeringKnowledgeFederationFeedForm: part("form") },
    "/AdminEngineeringKnowledgeFederationPackageTables": {
      AdminEngineeringKnowledgeFederationPackagesTable: ({ packages, renderReviewActions }) =>
        createElement("section", { "data-part": "packages" }, packages.map((item) => createElement("div", { key: item.id }, renderReviewActions(item)))),
      AdminEngineeringKnowledgeFederationSyncRunsTable: part("runs"),
    },
  };
  const payload = {
    summary: { feed_count: 2, package_count: 3, pending_review_count: 1, failed_sync_count: 0 }, operations: { queued: 1 },
    feeds: [{ id: "f-1" }], sync_runs: [],
    packages: [{ id: "k-1", direction: "imported", review_status: "pending_review" }, { id: "k-2", direction: "exported", review_status: "accepted" }],
  };
  const srv = server(() => ({ status: 200, body: payload }));
  const view = await mount("admin/components/AdminEngineeringKnowledgeFederationPanel.tsx", "AdminEngineeringKnowledgeFederationPanel", {},
    { stubs, globals: { fetch: srv.fetch } });
  await tick();
  assert.deepEqual(view.root.findAll((node) => node.type === "button").map(text), ["Reload", "Accept", "Lower trust", "Quarantine", "Reject"]);
  assert.match(text(view.root), /Pending review1/);
  assert.equal(digest(view), "c4ee7b612ac6c2afd1690a88adae7556cacffa3178e6fc2de8a98b7b900cb30c");
});

// --- Managed database connector -------------------------------------------------------------------------------------

test("managed database card: header facts, test result, and the open body with tools and actions, in a card and a drawer", async () => {
  const stubs = { "/ManagedDatabaseConnectorFields": { ManagedDatabaseConnectorFields: (props) => createElement("fieldset", { "data-draft": JSON.stringify(props.draft) }) } };
  const connector = {
    id: "db-1", name: "Orders", db_type: "postgresql", tool_count: 1, is_active: true, health: { status: "ok" }, description: "",
    public_fields: { host: "db.internal" }, secret_status: { password: true, dsn: false },
  };
  const ctx = {
    databaseConnectorError: "Host unreachable", databaseConnectorSaving: false, databaseConnectorTestBusy: null,
    databaseConnectorTestResult: { "db-1": { ok: false, summary: "Timeout", details: "after 5 s" } },
    databaseTools: [{ id: "t-1", connector_id: "db-1", tool_name: "orders_tool", description: "", max_rows: 100, timeout_seconds: 30,
      row_level_security_rules: ["tenant_id = $user.id"] }],
    expandedDatabaseConnector: "db-1", getDatabaseConnectorDraft: () => ({ host: "db.internal" }), handleDeleteDatabaseTool: noop,
    handleExpandDatabaseConnector: noop, handleSaveDatabaseConnector: noop, handleTestDatabaseConnector: noop,
    openCreateDatabaseTool: noop, setDatabaseConnectorDraftField: noop,
  };
  const card = await mount("admin/components/connectorsTab/ManagedDatabaseConnectorCard.tsx", "ManagedDatabaseConnectorCard",
    { connector, ctx }, { stubs });
  assert.match(text(card.root), /Failed · Timeout · after 5 s/);
  assert.match(text(card.root), /RLS: tenant_id = \$user\.id/);
  assert.equal(digest(card), "0cf91146d9c23d88de709d021c727940be5b500dfe040576a931b11817b66060");
  const drawer = await mount("admin/components/connectorsTab/ManagedDatabaseConnectorCard.tsx", "ManagedDatabaseConnectorCard",
    { connector, ctx: { ...ctx, databaseTools: [], databaseConnectorError: null }, inDrawer: true }, { stubs });
  assert.match(text(drawer.root), /No query tools registered yet\./);
  assert.equal(digest(drawer), "efc515467e8eda7d132cc41f06059b7c4ecaa0820a6422b69d57d419bd1826c0");
});

// --- Channel configuration ------------------------------------------------------------------------------------------

test("channel configuration: name, workspace, webhook URL, the enable switch, the form or raw JSON, and the error", async () => {
  const stubs = { "/AdminChannelConfigFields": { AdminChannelConfigFields: (props) => createElement("fieldset", { "data-fields": JSON.stringify(props.configFields) }) } };
  const channel = { id: 7, name: "Teams", plugin_id: "teams", webhook_url: "https://hooks.example/teams", config_fields: [{ name: "tenant" }],
    secret_fields: [], enabled: true, config: {}, status: "running", updated_at: null };
  const props = {
    channel, onClose: noop, projects: [{ id: "p-1", name: "Alpha" }], channelFormName: "Teams", setChannelFormName: noop,
    channelFormProjectId: "p-1", setChannelFormProjectId: noop, channelFormEnabled: true, setChannelFormEnabled: noop,
    channelShowRawJson: false, setChannelShowRawJson: noop, channelConfigJson: "{}", setChannelConfigJson: noop,
    channelFormValues: { tenant: "x" }, setChannelFormValues: noop, channelFormError: "Tenant missing", channelFormLoading: false, onSave: noop,
  };
  const form = await mount("admin/components/AdminChannelConfigModal.tsx", "AdminChannelConfigModal", props, { stubs });
  assert.deepEqual(labels(form.root, "admin-form-field__label"), ["Channel name", "Workspace", "Webhook URL"]);
  assert.equal(form.root.findAll((node) => node.props.role === "switch" && typeof node.type === "string").length, 1);
  assert.equal(digest(form), "5d68bb3355ece4f5937ba0c4dc78e74ed06ca576e6ad5d88a33c6c3eaca18268");
  const raw = await mount("admin/components/AdminChannelConfigModal.tsx", "AdminChannelConfigModal",
    { ...props, channel: { ...channel, id: null, webhook_url: "" }, channelShowRawJson: true, channelFormError: null }, { stubs });
  assert.equal(raw.root.findAllByType("textarea").length, 1);
  assert.equal(digest(raw), "6d0f62b768fefad44cdd0a691ed965a6d1e397303dd1018fb05051d5887a2b49");
});
