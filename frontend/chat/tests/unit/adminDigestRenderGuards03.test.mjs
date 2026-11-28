// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminDigestRenderGuards03.test.mjs
//
// Render guards for admin panels, cards and inspectors whose long functions are split into smaller parts: each renders
// with representative props, keeps its key labels and test ids, and keeps its whole rendered tree (a digest of the
// test renderer's JSON), so the split draws exactly what the original drew.
import assert from "node:assert/strict";
import { test } from "node:test";
import { act, byId, digest, labels, mount, noop, server, text, tick } from "./adminDigestRenderHarness.mjs";

// --- Engineering knowledge packs + builder runs ---------------------------------------------------------------------

const EK_PACK = {
  id: "pk-1", name: "Java Spring", stack_key: "java-spring", versions: [{ id: "v1" }, { id: "v2" }],
  toolchain_policy: { profiles: { jdk21: {}, jdk25: {} } }, lifecycle_status: "published",
};
const EK_RUN = {
  id: "run-1", status: "completed", stack_key: "java-spring", source_versions: { java: "21" }, target_versions: { java: "25" },
  completed_at: "2026-01-02T03:04:05Z",
};

function packsCtx(overrides = {}) {
  return {
    engineeringKnowledgeAllowNetwork: true, engineeringKnowledgeBuildRuns: [EK_RUN], engineeringKnowledgeBusy: false,
    engineeringKnowledgeError: "Target version required", engineeringKnowledgeLoading: false, engineeringKnowledgePackTotal: 1,
    engineeringKnowledgePacks: [EK_PACK],
    engineeringKnowledgeBuildVersions: { java: { source: "21", target: "25" }, spring_boot: { source: "", target: "" }, python: { source: "", target: "" } },
    handleCreateEngineeringKnowledgeBuildRun: async () => {}, handleDeleteEngineeringKnowledgePack: async () => {},
    loadEngineeringKnowledgePackDetail: async () => EK_PACK, refreshEngineeringKnowledgePacks: async () => {},
    selectedEngineeringKnowledgePack: null, setEngineeringKnowledgeAllowNetwork: noop, setEngineeringKnowledgeBuildVersions: noop,
    ...overrides,
  };
}

test("engineering packs: header, pack rows, the builder form and its runs; empty states", async () => {
  const path = "admin/components/AdminEngineeringKnowledgePacksPanel.tsx";
  const view = await mount(path, "AdminEngineeringKnowledgePacksPanel", { ctx: packsCtx() });
  assert.match(text(view.root), /\(1 packs\)/);
  assert.match(text(view.root), /jdk21, jdk25/);
  assert.match(text(view.root), /Target version required/);
  assert.equal(view.root.findAllByType("input").length > 0, true);
  assert.equal(digest(view), "d7fc39df5469b5c413d70143ae00b9d0f0cb41780cc6731ca348ac732a748e36");
  const empty = await mount(path, "AdminEngineeringKnowledgePacksPanel", {
    ctx: packsCtx({ engineeringKnowledgePacks: [], engineeringKnowledgeBuildRuns: [], engineeringKnowledgeError: null, engineeringKnowledgeBusy: true }),
  });
  assert.match(text(empty.root), /No Engineering Knowledge Packs yet/);
  assert.match(text(empty.root), /No builder runs yet/);
  assert.equal(digest(empty), "10b240a30ef8ee5a28181f303dc229ac9e5e89e83b0a9a08e7f84fd734929ca3");
});

// --- Inbound webhook drawer -----------------------------------------------------------------------------------------

const INBOUND_EVENT = {
  id: "ev-1", webhook_id: "wh-1", received_at: "2026-01-02T03:04:05Z", outcome: "started", title: "CPU high", message: "",
  error: "", is_test: false, task_run_id: null, session_id: null,
};
const INBOUND_HOOK = {
  id: "wh-1", name: "Grafana alerts", project_id: "p-1", workspace_name: "Ops", source_type: "grafana", source_label: "Grafana",
  polled: false, is_active: true, has_secret: true, trigger_path: "/hooks/in/wh-1", task_id: null,
  action: { id: "a-1", name: "Analyse", workflow: "incident" }, result_to: { kind: "chat", label: "Chat" }, state: "active",
  setup_gap: null, setup_message: "", alert_filter: "", group_window_minutes: 10, rate_limit_per_hour: 30,
  week: { alerts: 3, grouped: 1, started: 2 }, last_event: INBOUND_EVENT,
};

test("inbound webhook drawer: sections, the footer toggle and both confirmations", async () => {
  const path = "admin/components/inboundWebhooks/InboundWebhookDetailDrawer.tsx";
  const props = (initialConfirm) => ({
    webhook: INBOUND_HOOK, source: { key: "grafana", label: "Grafana", polled: false, samples: [{ key: "cpu", label: "CPU alert" }] },
    actions: [{ id: "a-1", name: "Analyse", project_id: "p-1" }], readJson: async () => [INBOUND_EVENT], onChanged: noop, onClose: noop,
    initialConfirm,
  });
  const options = { stubs: { "/AutomationIcon": { AutomationIcon: () => null } } };
  const view = await mount(path, "InboundWebhookDetailDrawer", props(null), options);
  assert.equal(text(byId(view.root, "inbound-webhook-toggle")[0]), "Pause");
  assert.match(text(view.root), /Recent alerts/);
  assert.match(text(view.root), /CPU high/);
  assert.equal(digest(view), "a369754de955437bd8759104eb7616437845c70b2e0351278f81afc648d7b04d");
  const removing = await mount(path, "InboundWebhookDetailDrawer", props("remove"), options);
  assert.match(text(removing.root), /Remove Grafana alerts\?/);
  assert.equal(digest(removing), "2675b3768825f9d144b73ae874d6ba084ff2de87f3a211e9cd1b36d9d779d407");
});

// --- Configured connector card --------------------------------------------------------------------------------------

const CONNECTOR_POLICY = { tool_instructions: "", extra_tools: [], disabled_tools: [] };
const connectorOf = (tool_name, fields, publicFields) => ({
  tool_name, label: tool_name, description: `${tool_name} connector`, fields, secret_fields: [], supports_test: true,
  builtin_tools: [], tools: [{ name: `${tool_name}_search`, description: "Search" }], tool_policy: CONNECTOR_POLICY,
  is_active: true, policy_active: true, configured: true, public_fields: publicFields, secret_status: {}, db_id: null, policy_id: null,
});

test("configured connector card: a guided (Confluence) card, a plain card and the drawer body", async () => {
  const path = "admin/components/connectorsTab/ConfiguredConnectorCard.tsx";
  const Null = () => null;
  const options = { stubs: { "/ConfiguredConnectorHeader": { ConfiguredConnectorHeader: Null } } };
  const ctx = (tool) => ({
    CONNECTOR_COLORS: {}, connectorHealthHistory: {}, connectorTestResult: {}, connectorSaving: null, connectorTesting: null,
    expandedConnector: tool, getConnectorDraft: () => ({ confluence_url: "https://wiki.acme.test", base_url: "https://x.test" }),
    setConnectorField: noop, handleSaveConnector: async () => ({ state: "saved" }), handleTestConnector: async () => {},
  });
  const guided = connectorOf("confluence", ["confluence_url", "confluence_auth_mode"], { confluence_url: "https://wiki.acme.test" });
  const view = await mount(path, "ConfiguredConnectorCard", { connector: guided, ctx: ctx("confluence") }, options);
  assert.match(text(view.root), /Test saved connection/);
  assert.equal(digest(view), "73519a1b3f8ec46fbe6d35227354aadee294374814638ad8441a703732020a2f");
  const plain = connectorOf("sentry", ["base_url"], { base_url: "https://x.test" });
  const card = await mount(path, "ConfiguredConnectorCard", { connector: plain, ctx: ctx("sentry") }, options);
  assert.match(text(card.root), /sentry connector/);
  assert.equal(digest(card), "464b6bfd549b1dbc84a348e94489e30055f8e5d9e24a91efd381693f06c005bb");
  const drawer = await mount(path, "ConfiguredConnectorCard", { connector: plain, ctx: ctx("other"), inDrawer: true }, options);
  assert.doesNotMatch(text(drawer.root), /sentry connector/);
  assert.equal(digest(drawer), "22537a91b45510dadf81a78b7866a7486905f99e32aef6cc665cb0aede8a32a9");
});

// --- Content security -----------------------------------------------------------------------------------------------

const CS_OVERVIEW = {
  coverage: {
    categories: [{ id: "secrets", label: "Credentials" }, { id: "pii", label: "Personal data" }],
    rows: [{ key: "prompt", label: "User prompt", sub: "gateway", cells: [
      { category: "secrets", outcome: "refuse", text: "Refuse", tone: "refuse" }, { category: "pii", outcome: "none", text: "Not scanned", tone: "none" }] }],
    mode: "enforce", detectors: 8, custom_detectors: 1, content_policies: 1, published_version: 4,
    platform_policies: [{ id: "platform:email-masked", label: "Email addresses are masked", outcome: "mask" }],
  },
  edit_target: { version: 4, digest: "sha256:x", creates_draft: true },
  approved_models: [
    { alias: "eu-model", cleared_up_to: "internal", approved_for: ["pii"], levels: ["public", "internal"] },
    { alias: "plain-model", cleared_up_to: "secret", approved_for: [], levels: [] },
  ],
  levels: [{ key: "public", label: "Public", color: "public" }, { key: "internal", label: "Internal", color: "internal" }],
};

test("content security: overview and approved models tabs", async () => {
  const srv = server(() => ({ status: 200, body: CS_OVERVIEW }));
  const view = await mount("admin/components/contentSecurity/ContentSecurityPage.tsx", "ContentSecurityPage", {}, { globals: { fetch: srv.fetch } });
  await tick();
  assert.match(text(view.root), /1 content policy/);
  assert.equal(digest(view), "45bdfdd8595619f2b5b90eeb72f626005e62e7a011a91665c475b5fbcd037624");
  const tab = (id) => view.root.findAll((node) => typeof node.type === "string" && node.props["data-testid"] === `subtab-${id}`)[0];
  await act(async () => tab("models").props.onClick());
  assert.equal(byId(view.root, "content-models")[0].findAllByType("tr").length, 3);
  assert.equal(digest(view), "707fe8620ea77f4972eb0d08a9e7c58e5bfa5843eb3a6d398a96f99e970d24dc");
});

// --- Action card: header, dependencies, step list, runs -------------------------------------------------------------

const TASK_ROW = {
  id: "task-1", name: "Nightly digest", description: "", task_type: "agent_run", agent_type: "diagnosis", schedule: null,
  is_active: true, step_count: 3, project_id: "ws-1", run_count: 1, running_count: 0, last_run_status: "success",
  last_run_at: null, config: {},
};
const stepRow = (position, overrides) => ({
  id: `s-${position}`, task_id: "task-1", position, name: `Step ${position}`, step_type: "analysis", connector: null,
  connector_action: null, connector_params: {}, instructions: "", runtime_selector: {}, context_fields: [], max_fix_attempts: 2,
  agent_timeout_seconds: 60, is_enabled: true, ...overrides,
});
const TASK_STEPS = [
  stepRow(2, { step_type: "verification", runtime_selector: { runtime_target_id: "rt-gpu" }, connector_params: { agent_definition_id: "" } }),
  stepRow(1, { connector: "jira", connector_action: "search", connector_params: { agent_definition_id: "agent-1" },
    context_fields: ["issue", "project"], instructions: "x".repeat(90) }),
  stepRow(3, { is_enabled: false, step_type: "unknown", connector_params: { agent_definition_id: "abcdef123456" } }),
];

// Handlers are left out: the guards compare what is drawn, and the digest skips functions.
function taskCardProps(overrides = {}) {
  return {
    task: TASK_ROW, isExpanded: true, runs: [], triggeringTask: null, agentModeNameByKey: new Map(), panelAgents: [{ id: "agent-1", name: "Coder" }],
    taskDependencies: { "task-1": {
      dependencies: [{ id: "d-1", task_id: "task-1", depends_on_task_id: "t-0", condition: "success", task_name: "Nightly digest", depends_on_task_name: "Import" }],
      dependents: [{ id: "d-2", task_id: "t-9", depends_on_task_id: "task-1", condition: "always", task_name: "Report", depends_on_task_name: "Nightly digest" }],
      available_tasks: [{ id: "t-5", name: "Cleanup" }],
    } },
    taskDependencyTarget: {}, taskDependencyCondition: {}, taskSteps: { "task-1": TASK_STEPS }, showStepForm: null, editingStep: null,
    stepFormName: "", stepFormType: "analysis", stepFormConnector: "", stepFormConnectorAction: "", stepFormInstructions: "",
    stepFormAgentId: "", stepFormContextFields: "", stepFormConnectorParams: "{}",
    stepFormMaxFix: 2, stepFormTimeout: 60, stepFormError: null, stepFormLoading: false, runsLoading: false, expandedRun: null,
    cancellingRun: null, ...overrides,
  };
}

test("action card: expanded with dependencies, sorted steps and their actions; empty dependency and step lists", async () => {
  const path = "admin/components/AdminTaskCard.tsx";
  const view = await mount(path, "AdminTaskCard", taskCardProps());
  assert.deepEqual(view.root.findAll((node) => node.props.className === "step-item__name" && typeof node.type === "string").map(text),
    ["Import", "Report", "Step 1", "Step 2", "Step 3"]);
  assert.match(text(view.root), /agent: Coder/);
  assert.match(text(view.root), /agent: suppressed/);
  assert.match(text(view.root), /rt-gpu/);
  assert.equal(digest(view), "6f7e6a1b8f52899a83341f3281b44dbb1b2a632b5924924d44802b26916e8743");
  const empty = await mount(path, "AdminTaskCard", taskCardProps({ taskDependencies: {}, taskSteps: {} }));
  assert.match(text(empty.root), /No upstream dependencies\./);
  assert.match(text(empty.root), /No steps yet\. Add one above\./);
  assert.equal(digest(empty), "284b319fc4d605f555f65d6001d5486d3ba26428afba78b648f69c6a748d2620");
});

// --- Channel config fields ------------------------------------------------------------------------------------------

test("channel config fields: every field type, secrets with and without a stored value, and the raw JSON fallback", async () => {
  const path = "admin/components/AdminChannelConfigFields.tsx";
  const configFields = [
    { name: "enabled_flag", type: "boolean", required: true, description: "Turns it on" },
    { name: "max_items", type: "number", description: "How many" },
    { name: "mode", type: "select", options: ["a", "b"] },
    { name: "allowed_ids", type: "list", required: true },
    { name: "bot_token", type: "string" },
    { name: "api_key", type: "string" },
    { name: "team_name", type: "string", secret: true },
    { name: "plain_text" },
  ];
  const props = {
    configFields, channelConfigJson: "{}", setChannelConfigJson: noop, setChannelFormValues: noop,
    channelFormValues: { enabled_flag: true, max_items: 5, mode: "b", allowed_ids: ["x", "y"], bot_token: "", plain_text: null },
    secretFields: { bot_token: { has_value: true } },
  };
  const view = await mount(path, "AdminChannelConfigFields", props);
  assert.deepEqual(labels(view.root, "admin-form-field__label").length, 7);
  assert.equal(view.root.findAll((node) => node.props.type === "password" && typeof node.type === "string").length, 3);
  assert.equal(digest(view), "4024b3cbfd48de037b5d441bcd64ae4502a731094c17ddaca7d4cbfa69bbf752");
  const raw = await mount(path, "AdminChannelConfigFields", { ...props, configFields: [] });
  assert.equal(raw.root.findAllByType("textarea").length, 1);
  assert.equal(digest(raw), "3a6e4ab22ebe3ce64d132352ea4cc4e2c0efa6b0b2a062934e12960cc11e3175");
});
