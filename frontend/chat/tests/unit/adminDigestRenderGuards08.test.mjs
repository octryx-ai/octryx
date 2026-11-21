// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminDigestRenderGuards08.test.mjs
//
// Render guards for admin sections, cards and panels whose long functions are split into smaller parts: each renders
// with representative props, keeps its key labels and test ids, and keeps its whole rendered tree (a digest of the
// test renderer's JSON), so the split draws exactly what the original drew.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement as h } from "react";
import { byId, digest, mount, noop, text } from "./adminDigestRenderHarness.mjs";

// --- Corporate identity template section ----------------------------------------------------------------------------

const CORP_PROFILE = {
  id: "cp-1", name: "Acme",
  templates: { pptx: [
    { template_id: "t-1", display_name: "Board deck", source_file_name: "board.pptx", description: "Old text" },
    { template_id: "t-2", display_name: "", source_file_name: "weekly.pptx", description: "" },
  ] },
};
const corpState = (overrides = {}) => ({
  corpIdentityDetail: { templates: { pptx: [{ template_id: "t-1", description: "Detail text" }] } },
  corpIdentityActionBusy: "update:t-2", corpIdentitySelectedId: "cp-1", corpIdentityUploadBusy: false,
  handleUpdateTemplate: async () => {}, handleDeleteTemplate: async () => {}, ...overrides,
});

test("corporate template section: template cards, the add prompt, the add button and the empty state", async () => {
  const path = "admin/components/corpIdentity/CorpTemplateSection.tsx";
  const props = { docType: "pptx", profile: CORP_PROFILE, state: corpState(), addingTemplateTo: null, setAddingTemplateTo: noop,
    mergeInputRef: { current: null } };
  const view = await mount(path, "CorpTemplateSection", props);
  assert.match(text(view.root), /\(2\)/);
  assert.match(text(view.root), /Detail text/);
  assert.match(text(view.root), /\+ Add .* Template/);
  assert.equal(digest(view), "7b5fa829b7c6969c5b9dd691485057ec3330c559f4369e731fd28ee513b807c6");
  const adding = await mount(path, "CorpTemplateSection", { ...props, addingTemplateTo: "cp-1", state: corpState({ corpIdentityUploadBusy: true }) });
  assert.match(text(adding.root), /Uploading…/);
  assert.equal(digest(adding), "585249320eac6495973ff11de78b63207ec243ca6df4bb6c31abcd39b5306bd3");
  const empty = await mount(path, "CorpTemplateSection", { ...props, docType: "docx" });
  assert.match(text(empty.root), /template yet\./);
  assert.equal(digest(empty), "abdb7443187a826ce65d30c75a739440d323cf4a294a36b46b73b2bb4d707ecf");
  const emptyAdding = await mount(path, "CorpTemplateSection", { ...props, docType: "xlsx", addingTemplateTo: "cp-1" });
  assert.equal(digest(emptyAdding), "742a78af5fded57501903f6d1a10e6e27aeb8b985e104766174e13f4994a823c");
});

// --- Add connector panel --------------------------------------------------------------------------------------------

const CATALOG = [
  { tool_name: "jira", label: "Jira", description: "Issues", secret_fields: ["api_token"], tools: [{}, {}] },
  { tool_name: "sentry", label: "Sentry", description: "Errors", secret_fields: [], tools: [{}] },
];
const addCtx = (overrides = {}) => ({
  CONNECTOR_COLORS: { jira: "#0052CC" }, CONNECTOR_ICONS: { jira: h("i", { "data-icon": "jira" }) },
  availableConnectors: CATALOG, connectorCatalogSearch: "", filteredAvailableConnectors: CATALOG,
  handleExpandConnector: noop, setConnectorCatalogSearch: noop, setShowAddConnector: noop, showAddConnector: true, ...overrides,
});

test("add connector panel: search, catalog cards, no match, everything configured and closed", async () => {
  const path = "admin/components/connectorsTab/AddConnectorModal.tsx";
  const view = await mount(path, "AddConnectorModal", { ctx: addCtx() });
  assert.equal(view.root.findAll((node) => node.props.className === "admin-option-card" && node.type === "button").length, 2);
  assert.match(text(view.root), /Sentry/);
  assert.equal(digest(view), "f710a6a14636af51ee7790bc188d5f8d4b9f61f78fe101f0e6839a995481fdd0");
  const none = await mount(path, "AddConnectorModal", { ctx: addCtx({ connectorCatalogSearch: "zzz", filteredAvailableConnectors: [] }) });
  assert.match(text(none.root), /No connectors match your search\./);
  assert.equal(digest(none), "c3c679ad3be1714aa4f2c698f801c01bc8430faeba98b3332d927dde5d5a13f1");
  const all = await mount(path, "AddConnectorModal", { ctx: addCtx({ availableConnectors: [] }) });
  assert.match(text(all.root), /All available connectors are already configured\./);
  assert.equal(digest(all), "649f073abe35969de68a6316deeedcbb3893edf9475597e812079c3b1a0d3666");
  const closed = await mount(path, "AddConnectorModal", { ctx: addCtx({ showAddConnector: false }) });
  assert.equal(closed.toJSON(), null);
});

// --- Configured connector header ------------------------------------------------------------------------------------

const headerCtx = {
  CONNECTOR_ICONS: {}, connectorHealthStatusClass: (status) => `health--${status}`,
  formatConnectorHealthStatus: (status) => `Status ${status}`, formatRelativeTime: () => "5 min ago", handleExpandConnector: noop,
};
const headerConnector = (overrides = {}) => ({
  tool_name: "sentry", label: "Sentry", tools: [{ name: "a" }], configured: true, supports_test: true, fields: ["base_url"],
  secret_fields: [], public_fields: { base_url: "https://x.test" }, secret_status: {}, ...overrides,
});

test("configured connector header: checked, failing, unchecked and not configured cards", async () => {
  const path = "admin/components/connectorsTab/ConfiguredConnectorHeader.tsx";
  const props = { connector: headerConnector(), health: { status: "ok", last_checked: "2026-01-01T00:00:00Z" }, iconColor: "#123", isOpen: false, ctx: headerCtx };
  const view = await mount(path, "ConfiguredConnectorHeader", props);
  assert.match(text(view.root), /Checked 5 min ago/);
  assert.equal(byId(view.root, "connector-health-badge").length, 1);
  assert.equal(digest(view), "004944991ee560a25ad2923b2e3acee930444ce0b8db2afb81f56e4e74d6b088");
  const failing = await mount(path, "ConfiguredConnectorHeader", { ...props, isOpen: true,
    connector: headerConnector({ tools: [{}, {}] }), health: { status: "error", error: "Timeout" } });
  assert.equal(digest(failing), "d5947accfeb9528b4bb853aa99f1205f42b54733b1a678a3c1aea96eb9dd9516");
  const unconfigured = await mount(path, "ConfiguredConnectorHeader", { ...props, health: null,
    connector: headerConnector({ configured: false, workspace_connections: 2, supports_test: false }) });
  assert.equal(digest(unconfigured), "c178f98bf44f50e9dd412ea8db8ed5a9b55c37b871fbb0928a007d25b5a90d8d");
  const bare = await mount(path, "ConfiguredConnectorHeader", { ...props, health: null, connector: headerConnector({ configured: false }) });
  assert.equal(digest(bare), "6d4af089f195d82f8418f6b754a7ada949aa689a745da3bdd50fd6e00c680f14");
});

// --- Engineering knowledge fact detail ------------------------------------------------------------------------------

const FACT = {
  node_type: "service", node_key: "svc-1", display_name: "Billing", summary: "Bills customers", status: "candidate",
  trust_level: "silver", classification: "internal",
  properties: { lifecycle: { state: "retracted", reason: "Outdated", source: "review", event_ref: "ev-1", changed_at: "2026-01-02" } },
  source_refs: [{ source_type: "git", source_ref: "repo/a.py", title: "a.py", url: "https://git/a.py", observed_at: "2026-01-01" },
    { source_type: "doc", source_ref: "wiki/x" }],
  related_edges: [{ id: "e1", direction: "out", edge_type: "calls", related_node: { display_name: "Ledger", node_key: "led" } },
    { id: "e2", direction: "in", edge_type: "uses", related_node: { node_key: "api" } }],
};

test("engineering knowledge fact detail: facts, lifecycle, review buttons, evidence and relations; a bare fact", async () => {
  const path = "admin/components/EngineeringKnowledgeFactDetail.tsx";
  const view = await mount(path, "EngineeringKnowledgeFactDetail", { selected: FACT, busyAction: "", review: async () => {} });
  assert.match(text(view.root), /reason: Outdated/);
  assert.equal(view.root.findAllByType("button").length, 5);
  assert.equal(digest(view), "b2c9b35dae594498a1881bc73efa3265704014e36bbac2ada0134158948cc6d0");
  const bare = await mount(path, "EngineeringKnowledgeFactDetail", {
    selected: { node_type: "x", node_key: "k", status: "s", trust_level: "t", classification: "c" }, busyAction: "promote", review: async () => {},
  });
  assert.match(text(bare.root), /No source refs\./);
  assert.match(text(bare.root), /No related graph facts\./);
  assert.equal(digest(bare), "9c0f7e63bd9d9ac6275584ff6a8c300fb5c6e1e0a8416af2539eb86b885d3c31");
});
