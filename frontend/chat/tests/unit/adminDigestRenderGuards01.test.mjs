// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminDigestRenderGuards01.test.mjs
//
// Render guards for admin pages, drawers and cards whose long functions are split into smaller parts: each renders
// with representative props, keeps its key labels and test ids, and keeps its whole rendered tree (a digest of the
// test renderer's JSON), so the split draws exactly what the original drew.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, byId, digest, labels, mount, noop, server, text, tick } from "./adminDigestRenderHarness.mjs";

// --- Outbound webhooks ----------------------------------------------------------------------------------------------

const OUTBOUND_HOOK = {
  id: "ow-1", name: "Ticket sink", url: "https://hooks.example/sink", project_id: "p-1", event_types: ["task.completed"],
  is_active: true, created_at: "2026-01-01T00:00:00Z",
};

function outboundProps(overrides = {}) {
  return {
    projects: [{ id: "p-1", name: "Alpha" }], outboundWebhooks: [OUTBOUND_HOOK],
    showCreateOutboundWebhook: false, setShowCreateOutboundWebhook: noop,
    editingOutboundWebhookId: "ow-1", setEditingOutboundWebhookId: noop,
    outboundWebhookFormName: "Ticket sink", setOutboundWebhookFormName: noop,
    outboundWebhookFormUrl: "https://hooks.example/sink", setOutboundWebhookFormUrl: noop,
    outboundWebhookFormProjectId: "p-1", setOutboundWebhookFormProjectId: noop,
    outboundWebhookFormEvents: ["task.completed"], setOutboundWebhookFormEvents: noop,
    outboundWebhookFormLoading: false, setOutboundWebhookFormLoading: noop,
    outboundWebhookFormError: "Name and target URL are required", setOutboundWebhookFormError: noop,
    createdOutboundSigningSecret: null, setCreatedOutboundSigningSecret: noop,
    outboundWebhookEventOptions: ["task.completed", "task.failed"],
    readJson: async () => ({}), reloadWebhooksTab: noop,
    ...overrides,
  };
}

test("outbound webhooks: the header action, the table row and the edit drawer", async () => {
  const view = await mount("admin/components/AdminOutboundWebhooksSection.tsx", "AdminOutboundWebhooksSection", outboundProps());
  assert.equal(text(byId(view.root, "outbound-webhook-new")[0]), "New outbound webhook");
  assert.match(text(view.root), /Ticket sink/);
  assert.match(text(view.root), /Name and target URL are required/);
  assert.equal(digest(view), "d25de6cda27b3065e70260c330deaf64ed542090a2a0b14b5fc047855c330f0c");
});

// --- Database query tool --------------------------------------------------------------------------------------------

test("add query tool: the side panel shows the connector choice, the nine fields and the error", async () => {
  const ctx = {
    showAddDatabaseTool: true, setShowAddDatabaseTool: noop, databaseToolSaving: false, databaseToolError: "SQL is required",
    databaseConnectors: [{ id: "db-1", name: "Orders", db_type: "postgres" }],
    databaseToolForm: {
      connector_id: "db-1", tool_name: "orders_tool", display_name: "Orders", allowed_roles: "admin", max_rows: "100",
      timeout_seconds: "30", description: "Order rows", sql_template: "select 1", parameters_schema: "{}",
      row_level_security_rules: "tenant_id = $user.id",
    },
    setDatabaseToolForm: noop, handleCreateDatabaseTool: async () => {},
  };
  const view = await mount("admin/components/connectorsTab/AddDatabaseToolModal.tsx", "AddDatabaseToolModal", { ctx });
  assert.deepEqual(labels(view.root, "admin-form-field__label"), [
    "Connector", "Tool name", "Display name", "Allowed roles", "Max rows", "Timeout seconds", "Description",
    "SQL template", "Parameter schema JSON", "RLS rules (one per line)",
  ]);
  assert.deepEqual(view.root.findAllByType("option").map(text), ["Select connector", "Orders (postgres)"]);
  assert.match(text(view.root), /SQL is required/);
  assert.equal(digest(view), "7a1b919e7af7cb96956d2e3b3d0853882bdf88773659d7459f6cdd017e760df6");
});

// --- Workspace data classification ----------------------------------------------------------------------------------

const CLASS_EFFECTS = (seat) => ({ reranker_allowed: true, remote_embeddings_allowed: false, seat_mode_allowed: seat, reasons: {} });
const CLASS_LEVELS = [
  { value: "open", label: "Open", description: "Anyone may read it.", effects: CLASS_EFFECTS(true) },
  { value: "vault", label: "Vault", description: "Locked away.", effects: CLASS_EFFECTS(false) },
];

test("data classification card: the level choice, its effects, both seat switches and the policy links", async () => {
  const srv = server((call) => {
    if (call.url.endsWith("/agent-gateway/seat-mode")) {
      return { status: 200, body: { seat_mode: "allowed", seat_mode_set: true, codex_seat_mode: "forbidden", can_loosen: false } };
    }
    if (call.url.endsWith("/engines")) return { status: 200, body: { effective: { allowed: ["claude"] } } };
    return { status: 200, body: {
      effective: "open", source: "workspace", cleared: false, levels: CLASS_LEVELS, effects: CLASS_EFFECTS(true),
      can_edit: true, instance_default: { classification: "open", state: "configured" },
    } };
  });
  const view = await mount("admin/components/dataClassification/WorkspaceDataClassificationCard.tsx",
    "WorkspaceDataClassificationCard", { projectId: "ws-1", onOpenPolicy: noop, onOpenMatrix: noop }, { globals: { fetch: srv.fetch } });
  await tick();
  assert.equal(byId(view.root, "classification-card").length, 1);
  assert.equal(byId(view.root, "classification-select")[0].props.value, "open");
  assert.equal(byId(view.root, "seat-toggle")[0].props.checked, true);
  assert.equal(byId(view.root, "codex-seat").length, 1);
  assert.equal(digest(view), "c96e09cfdba1f0b813b309549413f6b2e431f12c0e23cd5748c1be6dd9b3296f");
});

// --- Workflows list -------------------------------------------------------------------------------------------------

const WORKFLOWS_OVERVIEW = {
  usage_window_days: 14,
  flows: [
    { flow_id: "fl-1", key: "intake", title: "Intake", status: "draft", node_count: 4, execution_kind: "phased" },
    { flow_id: "fl-2", key: "bugfix", title: "Bug fix", status: "published", version: 2, used: 3, node_count: 3, execution_kind: "flow" },
  ],
};

test("workflows list: toolbar, filters, rows and the designer start page", async () => {
  const readJson = async () => WORKFLOWS_OVERVIEW;
  const view = await mount("admin/components/agentsWorkflows/workflows/WorkflowsPage.tsx", "WorkflowsPage", { view: "list", readJson });
  await tick();
  assert.equal(byId(view.root, "workflow-active-hint").length, 1);
  const button = (label) => view.root.findAll((node) => node.type === "button" && text(node) === label)[0];
  assert.ok(button("New flow"));
  await act(async () => button("Filters").props.onClick());
  assert.match(text(view.root), /Bug fix/);
  assert.match(text(view.root), /Intake/);
  assert.equal(digest(view), "e73526ea6de0256e39e5ff7a75fc0d110bc84ea9ac439d92b34f704a8196c306");

  const designer = await mount("admin/components/agentsWorkflows/workflows/WorkflowsPage.tsx", "WorkflowsPage", { view: "designer", readJson });
  assert.equal(byId(designer.root, "designer").length, 1);
  assert.equal(digest(designer), "68136df7920af31410e7cd0ec1e38610d3adfab03be9c29d881f182d75475a6a");
});

// --- Effective setup ------------------------------------------------------------------------------------------------

const SETUP_OPTIONS = {
  projects: [{ id: "p-1", name: "Alpha" }], users: [{ id: "u-1", username: "dana" }], agents: [{ id: "a-1", name: "Coder" }],
  workflows: [{ key: "bugfix", title: "Bug fix", capability: "code_change" }],
};
const SETUP = {
  runtime: "chat", summary: { capability: { class: "code_change" }, workflow_key: "bugfix", profile_status: "ready" },
  parts: [
    { id: "system", title: "System prompt", source: { label: "Prompts", tab: "prompts" }, version: "v3", enforced: "guidance", tokens: 120 },
    { id: "workflow", title: "Workflow", source: { label: "Bug fix" }, enforced: "enforced", tokens: 40 },
  ],
  budget: { total: 160, limit: 1000, groups: [{ key: "prompt", label: "Prompt", tokens: 120 }, { key: "wf", label: "Workflow", tokens: 40 }] },
  turn: { trace_id: "abcd1234" }, comparison: { matches: false, changed: 2, same: 1, keys: [] },
};

test("effective setup: the pickers, the parts, the summary, the budget and the compare drawer", async () => {
  const srv = server((call) => ({ status: 200, body: call.url.includes("/options") ? SETUP_OPTIONS : SETUP }));
  const view = await mount("admin/components/agentsWorkflows/effectiveSetup/EffectiveSetupPage.tsx", "EffectiveSetupPage", {},
    { globals: { fetch: srv.fetch } });
  await tick();
  assert.equal(byId(view.root, "effective-setup-parts")[0].findAll((node) => node.type === "details").length, 2);
  assert.match(text(view.root), /2 text\(s\) changed since turn abcd…/);
  assert.equal(digest(view), "67fe877c9922bcb04b8c563b3953396d4f59196aec03999b4ea615953e17af1b");
  await act(async () => view.root.find((node) => node.type === "button" && text(node) === "Compare with a past turn").props.onClick());
  assert.match(text(view.root), /Session ID/);
  assert.equal(digest(view), "71a6270cdb9d1c5705e77969de17ae22244fe46b5440d96db59fea3cd27c47ca");
});

// --- Inbound webhooks -----------------------------------------------------------------------------------------------

const INBOUND_HOOK = {
  id: "in-1", name: "Pager alerts", project_id: "p-1", workspace_name: "Ops", source_type: "generic", source_label: "Generic",
  polled: false, is_active: true, has_secret: true, trigger_path: "/hooks/in-1", task_id: "t-1",
  action: { id: "t-1", name: "Triage", workflow: "triage" }, result_to: { kind: "chat", label: "Chat" }, state: "needs_setup",
  setup_gap: "secret", setup_message: "Add the secret", alert_filter: "", group_window_minutes: 5, rate_limit_per_hour: 10,
  week: { alerts: 3, grouped: 1, started: 2 }, last_event: null,
};

test("inbound webhooks: the header action, one table row with its state and the latest alerts", async () => {
  const readJson = async (url) => (url.endsWith("/webhooks") ? [INBOUND_HOOK] : url.endsWith("/catalog") ? { sources: [] } : []);
  const view = await mount("admin/components/inboundWebhooks/InboundWebhooksPage.tsx", "InboundWebhooksPage",
    { projects: [{ id: "p-1", name: "Ops" }], readJson }, { stubs: { "/AutomationIcon": { AutomationIcon: () => null } } });
  await tick();
  assert.equal(byId(view.root, "inbound-webhook-new").length, 1);
  assert.equal(byId(view.root, "inbound-state-in-1").length, 1);
  assert.match(text(view.root), /Triage → Chat/);
  assert.equal(digest(view), "c84c730a7aed3297d4363558c6d6e464ac160ad27b26e498ccab05aa344c280d");
});

// --- Instruction drawer ---------------------------------------------------------------------------------------------

const INSTRUCTION_VERSION = {
  id: "iv-2", version: 2, state: "draft", tokenEstimate: 12, body: "Always run the tests.", findingsAccepted: false,
  findings: [{ code: "tool_forbidden_by_policy", names: ["deploy"], policy: "Tool policy deny list", detail: "deny deploy" }],
};
const INSTRUCTION_ROW = {
  id: "in-1", key: "run-tests", title: "Run tests", scopeType: "workspace", scopeId: "p-1", scopeName: "Alpha", binding: "workflow",
  workflowKey: "bugfix", layer: "workflow", layerBudget: 1500, status: "draft", published: null, latest: INSTRUCTION_VERSION,
  versions: [INSTRUCTION_VERSION],
};

test("instruction drawer: the fields, the binding cards, the token line and the conflict findings", async () => {
  const options = { projects: [{ id: "p-1", label: "Alpha" }], users: [], agents: [], workflows: [{ key: "bugfix", title: "Bug fix", capability: "code_change" }] };
  const readJson = async () => ({ findings: INSTRUCTION_VERSION.findings });
  const props = { row: INSTRUCTION_ROW, options, readJson, onClose: noop, onChanged: noop };
  const view = await mount("admin/components/agentsWorkflows/instructions/InstructionDrawer.tsx", "InstructionDrawer", props,
    { globals: { fetch: server(() => ({ status: 200, body: {} })).fetch } });
  assert.equal(view.root.findAll((node) => node.type === "input" && node.props.type === "radio").length, 3);
  assert.match(text(view.root), /Accept these findings for review \(audited\)/);
  assert.equal(digest(view), "142c0893d11f830a917224ae69861dac3a98111df0599071d1d85e120475ded6");
  const blank = await mount("admin/components/agentsWorkflows/instructions/InstructionDrawer.tsx", "InstructionDrawer",
    { ...props, row: null }, { globals: { fetch: server(() => ({ status: 200, body: {} })).fetch } });
  assert.match(text(blank.root), /Runs when a draft is saved\./);
  assert.equal(digest(blank), "6d0793257fa8d1ca5b966264e257cfeeaa73bf9b45fd3ab149fb40e7464452c5");
});

// --- Personality ----------------------------------------------------------------------------------------------------

test("personality: four choices, timezone, the custom prompt and the save button with the loaded values", async () => {
  const readJson = async () => ({ language: "de", detail_level: "detailed", communication_style: "friendly", output_format: "bullets",
    custom_prompt: "Be brief.", timezone: "Europe/Zurich" });
  const view = await mount("admin/components/AdminPersonalityTab.tsx", "AdminPersonalityTab", { readJson });
  await tick();
  assert.deepEqual(labels(view.root, "admin-form-field__label"),
    ["Language", "Detail level", "Communication style", "Output format", "Timezone", "Custom personality prompt"]);
  assert.deepEqual(view.root.findAllByType("select").map((node) => node.props.value), ["de", "detailed", "friendly", "bullets"]);
  assert.equal(digest(view), "3e8d94cd43321806adddc9e9d7bb14e4ebd5268459fd4ecf3f64dba6c35ac00c");
});

// --- Branding -------------------------------------------------------------------------------------------------------

test("branding: name, upload, logo URL and SVG fields, the preview and the save state", async () => {
  const ctx = {
    brandingConfig: { app_name: "Acme Ops", logo_url: "https://example.com/logo.png", logo_svg: "" }, setBrandingConfig: noop,
    brandingFormError: "Logo too large", brandingFormSaved: true, brandingFormLoading: false, onSaveBranding: noop,
  };
  const view = await mount("admin/components/AdminBrandingTab.tsx", "AdminBrandingTab", { ctx });
  assert.deepEqual(labels(view.root, "admin-form-field__label"), ["App name", "Upload logo", "Logo URL", "Logo SVG", "Preview"]);
  assert.equal(view.root.findByType("img").props.src, "https://example.com/logo.png");
  assert.match(text(view.root), /Saved successfully\./);
  assert.equal(digest(view), "17ecd95a8d454a11d4b518fdb6edd5ac6d5092f31ab56482bd08ba232d906fcb");
  const empty = await mount("admin/components/AdminBrandingTab.tsx", "AdminBrandingTab", { ctx: { ...ctx, brandingConfig: null } });
  assert.equal(empty.root.findAllByType("svg").length, 1);
  assert.equal(digest(empty), "ba3e8a9c510ed25a5ae3eded5b480d63617b79a1d4107b23850d3c84eb125809");
});

// --- Corporate identity profile drawer ------------------------------------------------------------------------------

test("corporate identity drawer: brand facts, colours, template sections, example deck and profile actions", async () => {
  const stubs = {
    "/CorpTemplateSection": { CorpTemplateSection: ({ docType }) => createElement("section", { "data-doc": docType }) },
    "/CorpIdentityBrandSheet": { CorpIdentityBrandSheet: () => createElement("section", { "data-part": "sheet" }) },
    "/CorpStudioLocks": { CorpStudioLocks: () => createElement("section", { "data-part": "locks" }) },
  };
  const state = {
    corpIdentityDetail: { name: "Acme", summary: { theme_name: "Acme Light", font_family: "Inter", colors: [{ token: "accent1", hex: "#0055AA" }] } },
    corpIdentityBrief: null, corpIdentityActionBusy: null, corpIdentitySelectedId: "cp-1",
    handleClearExampleDeck: noop, handleAttachExampleDeck: noop, handleSetDefaultCorpIdentity: noop, handleReextractCorpIdentity: noop,
  };
  const profile = { id: "cp-1", name: "Acme", is_default: false, example_deck_file: "deck.pptx", example_deck_layouts_learned: 7 };
  const props = { profile, state, addingTemplateTo: null, setAddingTemplateTo: noop, mergeInputRef: { current: null }, onClose: noop };
  const view = await mount("admin/components/corpIdentity/CorpProfileDrawer.tsx", "CorpProfileDrawer", props, { stubs });
  assert.deepEqual(view.root.findAll((node) => node.props["data-doc"] && typeof node.type === "string").map((node) => node.props["data-doc"]),
    ["pptx", "docx", "xlsx"]);
  assert.match(text(view.root), /deck\.pptx · 7 layouts learned/);
  assert.match(text(view.root), /Set as Default/);
  assert.equal(digest(view), "eed06e40291a323182c64acf194541c522c94066cae32bae4f2ef928ef64cac9");
  const plain = await mount("admin/components/corpIdentity/CorpProfileDrawer.tsx", "CorpProfileDrawer",
    { ...props, profile: { id: "cp-1", name: "Acme", is_default: true } }, { stubs });
  assert.match(text(plain.root), /No example deck\./);
  assert.equal(digest(plain), "420a9769b6240f42b83e2931e25828abf0ee0882c5638336ff47f7ab8c02219f");
});
