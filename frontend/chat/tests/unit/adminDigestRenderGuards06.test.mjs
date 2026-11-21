// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminDigestRenderGuards06.test.mjs
//
// Render guards for admin sections, drawers, cards and flow-builder parts whose long functions are split into smaller
// parts: each renders with representative props, keeps its key labels and test ids, and keeps its whole rendered tree
// (a digest of the test renderer's JSON), so the split draws exactly what the original drew. The flow templates keep
// their whole definition (a digest of their JSON).
import assert from "node:assert/strict";
import crypto from "node:crypto";
import { test } from "node:test";
import { createElement as h } from "react";
import { act, byId, digest, loadModule, mount, noop, text } from "./adminDigestRenderHarness.mjs";

const sha = (value) => crypto.createHash("sha256").update(JSON.stringify(value)).digest("hex");

// --- Flow templates -------------------------------------------------------------------------------------------------

const TEMPLATE_DIGESTS = [
  "ae8bb6ef24f3af933aa97eb1261a456546619946ba322369be94a28c0f8c0273",
  "62b51c60b24e7ff1dbc01f2125b9f1d5391871ca919a5915ddcfa8c94ba20043",
  "ac63d8f9639d7ca616f97f1511a14278f83fceb1f69e60b381d6bc3dac21d879",
  "7edd1d159873cdbf27d77e359eeb2e59c0c7374a17b431cb21bb4f3c2ea7a1a4",
  "af594256c14682931318490a178582b6d7920243bef70ea43cdeb2f137320282",
  "b82362b42548b40573188bb65eec369fbc6a31a6d9e06ccc164721673efba93c",
  "e67aa65decb0f217ba24a3d5fc19ec821a0aa9d03bf96cf0b14782ccf62751ec",
  "7f7193d27cdc1238d4c8161f15e5587b217030ff3b1a85b60c1e7b1935ca6482",
];

test("flow templates: every template keeps its key, nodes and metadata", () => {
  const { FLOW_BUILDER_TEMPLATES } = loadModule("admin/components/flowBuilder/flowBuilderTemplates.ts");
  assert.equal(FLOW_BUILDER_TEMPLATES.map((template) => template.key).slice(0, 2).join(), "person-source-evidence-research,release-analysis");
  assert.equal(FLOW_BUILDER_TEMPLATES[0].definition.nodes.length, 7);
  assert.equal(FLOW_BUILDER_TEMPLATES.map((template) => sha(template)).join(), TEMPLATE_DIGESTS.join());
});

// --- Flow trace panel -----------------------------------------------------------------------------------------------

const TRACE = {
  run: {
    id: "run-1", status: "paused", flow_id: "f-1", flow_version_id: "fv-1",
    plan: { status: "active", steps: [{ id: "s-1", status: "done", label: "Lookup", reason: "found" }, { node_id: "approve", status: "pending", required_action: "Approve" }] },
  },
  node_runs: [
    { id: "nr-1", node_id: "lookup", node_type: "tool_step", status: "completed", attempt: 1, input: { q: "a" }, output: { hits: 2 },
      evidence_summary: { items: 2 }, artifact_refs: [], duration_ms: 12, decision_trace: null, trace_refs: {}, token_usage: { total: 5 } },
    { id: "nr-2", node_id: "approve", node_type: "approval", status: "paused", attempt: 2, input: {}, output: { approval_id: "ap-1" },
      error: "Waiting", evidence_summary: null, artifact_refs: [{ id: "a-1" }], duration_ms: null, decision_trace: { route: "x" } },
  ],
};

test("flow trace panel: outcome, decision buttons, plan and step rows; empty state", async () => {
  const path = "admin/components/flowBuilder/FlowTracePanel.tsx";
  const props = (trace, selectedNodeRunId = "nr-2") => ({
    trace, selectedNodeRunId, running: false, onRefresh: noop, onRecoverInterrupted: noop, onResume: noop, onCancel: noop,
    onSelectNodeRun: noop,
  });
  const view = await mount(path, "FlowTracePanel", props(TRACE));
  assert.match(text(view.root), /Approve & resume/);
  assert.match(text(view.root), /Plan state/);
  assert.equal(view.root.findAll((node) => node.props.role === "listitem" && node.type === "button").length, 2);
  assert.equal(digest(view), "76438df0b5026048b1e878ee39546f426e682ab758c55157c825d397017c2ac6");
  const failed = await mount(path, "FlowTracePanel", props({ run: { ...TRACE.run, status: "failed", plan: {} }, node_runs: [{ ...TRACE.node_runs[0], status: "failed" }] }, null));
  assert.match(text(failed.root), /Recover run/);
  assert.equal(digest(failed), "067a619a6330d8457b9e481bcc007ee64167af1b4ad515d6659f63ad14552634");
  const empty = await mount(path, "FlowTracePanel", props(null));
  assert.match(text(empty.root), /No run yet/);
});

// --- Policy lists ---------------------------------------------------------------------------------------------------

const POLICY_LISTS = {
  lists: [
    { list_id: "weak_coding_model_families", key: "weak-models", version: 2, seed_key: "seed-1", matches_seed: false,
      record_state: "unreadable", title: "Weak models", description: "Model families", values: ["gemma", "qwen"], pinned: ["gemma"] },
    { list_id: "model_capabilities", key: "caps", version: 1, seed_key: "seed-2", matches_seed: true, title: "Capabilities",
      description: "Caps", values: [{ key: "vision", label: "Vision" }], pinned: [] },
    { list_id: "unknown_list", key: "unknown", version: 1, values: [] },
  ],
};

test("policy lists: cards with seed state, pinned entries and the text editor", async () => {
  const stubs = { "/utils/adminPanelHelpers": { readJson: async () => POLICY_LISTS } };
  const view = await mount("admin/components/AdminPolicyListsSection.tsx", "AdminPolicyListsSection", {}, { stubs });
  assert.match(text(view.root), /edited \(seed seed-1\) · stored record unreadable, seed live/);
  assert.match(text(view.root), /Pinned by code/);
  assert.equal(view.root.findAllByType("pre").length, 2);
  assert.equal(digest(view), "4c57fcf6664a79b848fbd3487d0ab76a71ad5ec02483770aa5db57aa6de79a0c");
  const edit = view.root.findAll((node) => node.type === "button" && text(node) === "Edit")[0];
  await act(async () => edit.props.onClick());
  assert.equal(view.root.findAllByType("textarea")[0].props.value, "gemma\nqwen");
  assert.equal(digest(view), "ec52bb108f56d08eb75dcec5efe58b72f767706ff708fe0b1d6ebdfb3a979cc5");
});

// --- Problem alerts -------------------------------------------------------------------------------------------------

const ALERT_ROWS = [
  { id: "s-1", user_id: null, project_id: "p-1", event_type: "problem.raised", channel_type: "email", channel_config_id: null,
    target: "ops@example.test", template_id: null, is_active: true, created_at: null },
  { id: "s-2", user_id: null, project_id: "p-2", event_type: "problem.raised", channel_type: "slack", channel_config_id: 7,
    target: "#alerts", template_id: null, is_active: false, created_at: null },
];

test("problem alerts: table rows, the add form and the remove confirmation", async () => {
  const stubs = {
    "/adminNavigation": { useAdminNavigation: () => ({ openAdminTab: noop }) },
    "/problemAlertsApi": { loadSubscriptions: async () => ALERT_ROWS, removeSubscription: async () => {}, saveSubscription: async () => {}, sendTest: async () => {} },
    "/ProblemAlertForm": { ProblemAlertForm: (props) => h("form", { "data-title": props.title, "data-primary": props.primaryLabel }) },
  };
  const props = { channels: [{ id: 7, name: "Slack Ops", plugin_id: "slack", enabled: true }], projects: [{ id: "p-1", name: "Ops" }, { id: "p-2", name: "Dev" }] };
  const view = await mount("admin/components/AdminProblemAlertsSection.tsx", "AdminProblemAlertsSection", props, { stubs });
  assert.match(text(view.root), /Run and device problems \(2\)/);
  assert.match(text(view.root), /Slack Ops/);
  assert.equal(digest(view), "f7cb4156c7e68e6a33e4e0403da4df21295d760406b46d3f1cf5ee99693c9fd8");
  await act(async () => byId(view.root, "problem-alert-add")[0].props.onClick());
  assert.equal(view.root.findAllByType("form")[0].props["data-title"], "Add alert");
  const menu = view.root.findAll((node) => Array.isArray(node.props.items) && node.props.row)[0];
  await act(async () => menu.props.items[3].onSelect());
  assert.match(text(view.root), /Problems in this Workspace are no longer sent to/);
  assert.equal(digest(view), "02a7e759f7892f4cfa95dc1904c8ebd02304aa6965731e3bb997ee313bf1fc95");
});

// --- Outbound webhook drawer ----------------------------------------------------------------------------------------

test("outbound webhook drawer: fields, events, error and the one-time secret; hidden when closed", async () => {
  const path = "admin/components/AdminOutboundWebhookDrawer.tsx";
  const props = (overrides = {}) => ({
    show: true, isEditing: true, entry: { id: "w-1", name: "Ops hook" }, projects: [{ id: "p-1", name: "Ops" }], name: "Ops hook",
    setName: noop, url: "https://example.test/hook", setUrl: noop, projectId: "p-1", setProjectId: noop,
    eventOptions: ["run.completed", "problem.raised"], selectedEvents: ["problem.raised"], setSelectedEvents: noop, error: "Bad URL",
    loading: false, signingSecret: "whsec_1", onSave: noop, onClose: noop, ...overrides,
  });
  const view = await mount(path, "AdminOutboundWebhookDrawer", props());
  assert.match(text(view.root), /Edit Ops hook/);
  assert.match(text(view.root), /Save changes/);
  assert.equal(view.root.findAll((node) => node.type === "input" && node.props.type === "checkbox").length, 2);
  assert.equal(digest(view), "8f44e9e5dd1b80cf063d4ed737ab8548270d922fdd480fa06674cabe0ab8930c");
  const fresh = await mount(path, "AdminOutboundWebhookDrawer", props({ isEditing: false, entry: null, error: null, signingSecret: null, loading: true }));
  assert.match(text(fresh.root), /Saving…/);
  assert.equal(digest(fresh), "d68c25aed7b4935a28d634eb9d804a131fb30af1505dc9b9aa4741053715e6e3");
  const closed = await mount(path, "AdminOutboundWebhookDrawer", props({ show: false }));
  assert.equal(closed.toJSON(), null);
});

// --- Engineering knowledge export preview + retrieval ---------------------------------------------------------------

test("export preview: the form and, after a preview, the decision table", async () => {
  const payload = {
    node_count: 2, missing_node_ids: ["n-9"], counts: {}, preview: [],
    decisions: [
      { fact_id: "f-1", fact_key: "db.url", fact_type: "config", action: "redacted", labels: ["pii"], reasons: ["user handle"],
        redacted_paths: [], redaction_types: ["username"], original_classification: "internal", export_classification: "public" },
      { fact_id: "f-2", fact_key: "", fact_type: "fact", action: "exportable", labels: [], reasons: [], redacted_paths: [],
        redaction_types: [], original_classification: "public" },
    ],
  };
  const stubs = { "/utils/adminPanelHelpers": { readJson: async () => payload } };
  const path = "admin/components/AdminEngineeringKnowledgeExportPreviewPanel.tsx";
  const view = await mount(path, "AdminEngineeringKnowledgeExportPreviewPanel", { onError: noop }, { stubs });
  assert.match(text(view.root), /Export-control preview/);
  assert.equal(digest(view), "9e0945654bcbbb8598e65ce493d2679ca4df314975091e194f71d2f14d6dc1c7");
  await act(async () => view.root.findByType("textarea").props.onChange({ target: { value: "n-1, n-9" } }));
  const preview = view.root.findAll((node) => node.type === "button" && text(node) === "Preview export")[0];
  await act(async () => preview.props.onClick());
  assert.match(text(view.root), /Missing nodes: n-9/);
  assert.equal(view.root.findAllByType("tr").length, 3);
  assert.equal(digest(view), "3b4972a89e13f5bc364129459b61f48e50aaccb28d85c6cdf286a9eda350df39");
});

test("retrieval panel: index facts, the search bar and the result records", async () => {
  const path = "admin/components/AdminEngineeringKnowledgeRetrievalPanel.tsx";
  const version = { id: "v-1", quality_report: { retrieval_index: { active: true, indexed_record_count: 4, record_kind_counts: { fact: 3, source: 1 } } } };
  const result = { records: [
    { record_id: "r-1", title: "Spring Boot 3", record_kind: "fact", fact_id: "f-1", summary: "Upgrade", source_key: "docs", canonical_uri: "https://x" },
    { record_id: "r-2", title: "Readme", record_kind: "source", content: "", archive_path: "a/b" },
  ] };
  const view = await mount(path, "AdminEngineeringKnowledgeRetrievalPanel", { version, loading: false, result, onSearch: async () => result });
  assert.match(text(view.root), /Status: active/);
  assert.equal(view.root.findAllByType("details").length, 2);
  assert.equal(digest(view), "9b4c034371d039d0726d53e5413116b4148a8ddda8e8925db337ea750ddc0431");
  const idle = await mount(path, "AdminEngineeringKnowledgeRetrievalPanel", { version: { id: "v-2" }, loading: true, result: { records: [] }, onSearch: async () => ({}) });
  assert.match(text(idle.root), /No indexed records matched this query/);
  assert.equal(digest(idle), "66a277d52c8b8883318a8ae4a25155adc0cf24f3903dc9f2e3666ab59313119c");
});

// --- Actions list ---------------------------------------------------------------------------------------------------

const TASK_ROWS = [
  { id: "t-1", name: "Nightly sync", description: "Sync tickets", task_type: "scheduled", is_active: true, running_count: 1,
    last_run_status: "completed_with_warnings", last_run_at: null, trigger_type: "schedule", schedule_cron: "0 2 * * *" },
  { id: "t-2", name: "Paused job", description: "", task_type: "manual", is_active: false, running_count: 0, last_run_status: null },
];

test("actions list: the table and the open action's card with every passed prop", async () => {
  // Every context value is a token naming its key, so the card stub shows which value reaches which prop.
  const ctx = new Proxy({ tasks: TASK_ROWS, expandedTask: "t-1", taskRuns: { "t-1": ["run"] }, taskRunsErrors: { "t-1": "boom" } },
    { get: (target, key) => (key in target ? target[key] : `ctx.${String(key)}`) });
  const stubs = {
    "/AdminTaskCard": { AdminTaskCard: (props) => h("pre", null, JSON.stringify(Object.keys(props).sort().map((key) => [key, typeof props[key] === "function" ? "fn" : props[key]]))) },
  };
  const path = "admin/components/AdminTasksList.tsx";
  const view = await mount(path, "AdminTasksList", { ctx }, { stubs });
  assert.equal(byId(view.root, "action-detail-panel").length, 1);
  assert.match(text(view.root), /Completed with warnings/);
  assert.match(text(view.root), /"stepFormTimeout","ctx.stepFormTimeout"/);
  assert.equal(digest(view), "73a40cead1f043567c18fcfdd98c7818d34450aa4c5bfb0d7fca2d819a01c138");
  const closed = await mount(path, "AdminTasksList", { ctx: { ...ctx, tasks: [], expandedTask: null, taskRuns: {}, onOpenTaskForm: noop } }, { stubs });
  assert.equal(byId(closed.root, "actions-empty").length > 0, true);
  assert.equal(digest(closed), "cc3e4657fcb59c55b3ef1a4613adc350febe7b183b3f42e5ba3afd1201b0bb59");
});

// --- Confluence page picker -----------------------------------------------------------------------------------------

test("confluence page picker: spaces, an opened tree level, the nothing-chosen confirmation; unreadable draft", async () => {
  const path = "admin/components/connectorsTab/ConfluencePagePicker.tsx";
  const readJson = async () => ({ pages: [{ id: "1", title: "Home", has_children: true }, { id: "2", title: "Team" }], next_start: 25 });
  const props = { spaces: ["DOC", "ENG"], draftValue: undefined, readJson, servedBy: { ENG: "eng-conn" }, onApply: noop, onClose: noop };
  const view = await mount(path, "ConfluencePagePicker", props);
  assert.match(text(view.root), /via eng-conn/);
  assert.equal(digest(view), "204ec635076f9e21e445b4054a8ed2016a3b7993ecd962eaecee4deca9755222");
  const toggle = view.root.findAll((node) => node.type === "button" && node.props["aria-label"] === "Open space DOC")[0];
  await act(async () => toggle.props.onClick());
  assert.match(text(view.root), /More pages/);
  for (const space of ["DOC", "ENG"]) {
    const radio = view.root.findAll((node) => node.type === "input" && node.props.name === `page-picker-mode-${space}` && node.props.value === "pages")[0];
    await act(async () => radio.props.onChange());
  }
  const apply = view.root.findAll((node) => node.type === "button" && text(node) === "Apply")[0];
  await act(async () => apply.props.onClick());
  assert.match(text(view.root), /Make the whole spaces readable/);
  assert.equal(digest(view), "5777cc89ae2bc7a93fd27d00c98e7101e1daa29e43adb8ecbde6822a36932ba1");
  const broken = await mount(path, "ConfluencePagePicker", { ...props, draftValue: "{\"not\": \"a list\"}" });
  assert.equal(digest(broken), "137f62a869cd089d6d3f44bca546482b83140920f220a85f08e3cf9618fa7b4b");
});

// --- Step type fields -----------------------------------------------------------------------------------------------

test("step type fields: each step type shows its own fields", async () => {
  const path = "admin/components/AdminTaskStepTypeFields.tsx";
  const props = (stepFormType) => ({
    stepFormType, stepFormAgentId: "a-1", setStepFormAgentId: noop, panelAgents: [{ id: "a-1", name: "Coder" }],
    stepFormContextFields: "steps.1.output", setStepFormContextFields: noop, stepFormConnectorParams: "{}", setStepFormConnectorParams: noop,
    stepFormMaxFix: 2, setStepFormMaxFix: noop, stepFormTimeout: 300, setStepFormTimeout: noop,
  });
  const digests = [];
  for (const type of ["sub_agent_spawn", "verification", "connector_fetch", "output", "analysis"]) {
    const view = await mount(path, "AdminTaskStepTypeFields", props(type));
    digests.push(digest(view));
  }
  const verification = await mount(path, "AdminTaskStepTypeFields", props("verification"));
  assert.match(text(verification.root), /Max fix attempts/);
  assert.equal(digest({ toJSON: () => digests }), "266760bb6eada0f1ee96ef0c06da9dd096f62de90ba4acfb9f1aefc3c71bccca");
});
