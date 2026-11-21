// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminDigestRenderGuards09.test.mjs
//
// Render guards for admin pages and sections whose long functions are split into smaller parts: each renders with
// representative props, keeps its key labels and test ids, and keeps its whole rendered tree (a digest of the test
// renderer's JSON), so the split draws exactly what the original drew. Child pages are stand-ins that render their
// props as data, so a guard sees every prop the page passes down.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement as h } from "react";
import { act, byId, digest, mount, noop, text, tick } from "./adminDigestRenderHarness.mjs";

const json = (props) => JSON.stringify(props, (key, value) => (typeof value === "function" ? "fn" : key === "children" ? undefined : value));
const part = (name) => Object.assign((props) => h("part", { name, data: json(props) }, props.children), { partName: name });
const parts = (path, ...names) => ({ [path]: Object.fromEntries(names.map((name) => [name, part(name)])) });
const findPart = (view, name) => view.root.find((node) => node.type.partName === name);

// --- Skills page ----------------------------------------------------------------------------------------------------

const SKILL_LIST = { items: [{ id: "s-1", name: "Review" }], counts: { published: 3, drafts: 1, in_review: 2, updates: 1 } };
const skillStubs = (fail = false) => ({
  ...parts("/AdminHeaderSlot", "AdminHeaderActions"), ...parts("/ApprovalRuleBadge", "ApprovalRuleBadge"),
  "/approvalRule/approvalRule": { useApprovalRule: () => ({ mode: "four_eyes" }) },
  "/adminNavigation": { useAdminNavigation: () => ({ openAdminTab: noop }) },
  ...parts("/SegmentedTabs", "SegmentedTabs"), ...parts("/SettingsDrawer", "SettingsDrawer"),
  ...parts("/SkillCatalogList", "SkillCatalogList"), ...parts("/SkillCategoriesTab", "SkillCategoriesTab"),
  ...parts("/SkillDetailPage", "SkillDetailPage"), ...parts("/SkillEditorPage", "SkillEditorPage"),
  ...parts("/SkillImportDrawer", "SkillImportDrawer"), ...parts("/SkillReviewDrawer", "SkillReviewDrawer"),
  ...parts("/SkillSourcesTab", "SkillSourcesTab"), ...parts("/SkillUpdateReview", "SkillUpdateReview"),
  ...parts("/SkillUsageTab", "SkillUsageTab"),
  "/skillCatalogApi": {
    loadSkills: async () => { if (fail) throw new Error("Catalog refused"); return SKILL_LIST; },
    loadCategories: async () => ({ tree: [{ key: "dev" }] }),
  },
});

test("skills page: status card, tabs, detail, editor, update review and the three drawers; loading error", async () => {
  const path = "admin/components/AdminSkillsTab.tsx";
  const view = await mount(path, "AdminSkillsTab", {}, { stubs: skillStubs() });
  assert.match(text(view.root), /3 published/);
  assert.match(text(view.root), /1 update available/);
  const digests = [digest(view)];
  const step = async (name, prop, ...args) => { await act(async () => { findPart(view, name).props[prop](...args); }); await tick(); digests.push(digest(view)); };
  await step("SegmentedTabs", "onChange", "categories");
  await step("SegmentedTabs", "onChange", "sources");
  await step("SegmentedTabs", "onChange", "usage");
  await step("SegmentedTabs", "onChange", "catalog");
  await step("SkillCatalogList", "onImport");
  await step("SkillCatalogList", "onOpen", "s-1", "versions");
  await step("SkillDetailPage", "onOpenReview", "s-1");
  await step("SkillReviewDrawer", "onChanged");
  await step("SkillDetailPage", "onEdit", "s-1");
  await step("SkillEditorPage", "onCancel");
  await step("SkillDetailPage", "onReviewUpdate", "s-1");
  await step("SkillUpdateReview", "onBack");
  await step("SkillDetailPage", "onBack");
  await act(async () => { byId(view.root, "skills-help")[0].props.onClick(); });
  digests.push(digest(view));
  assert.equal(byId(view.root, "skills-help-drawer").length, 1);
  await act(async () => { byId(view.root, "skills-status-card")[0].props.onClick(); });
  digests.push(digest(view));
  assert.equal(digests.join(","), "8c8567f8a2c80f6da7af4ac09c9720558b6a1df73483db1f16fb1b2bfa90076f,f9e0d90142e1b312bb59fe744daf270ddedad6db2720e8dd23a88cbb59d823d3,99ae54f5f2462401e0995092f3db84c3102038642fabe9018cbfec3e743f94c2,9e1b4c2063c08469434a85f55704c6c72945ad26bab8816f62ad20c256d838ba,8c8567f8a2c80f6da7af4ac09c9720558b6a1df73483db1f16fb1b2bfa90076f,6308aaed57a6a59b5a9fd50f7d20de323ab3d1379d257617a58f868c2c433bff,1d55f38eaada544abf3a08eb51f2edcb764d08b99f20aa417bea9c567a69c19e,b869a28dbaba0e1168231b1148b58acd59f683bf81940772f73aa0ac84688b0a,a03dad457285ab6b7c442316f3620e812bd9daf66d14a1598cc43ff444677d77,7f68aa61e3200b4c95410dc731aa63ecf33389a2c28cbb60d81c579f00eaaf22,1e5599193c6ea1e892487c6841e72f920d1b96ba06e5d7e2cfe29e19c8a4ddce,bd9645e39e1c03ac2eb876a4a0492ecbf95e2dc2c31393cdd56336c877f350bc,1e5599193c6ea1e892487c6841e72f920d1b96ba06e5d7e2cfe29e19c8a4ddce,701b5b7693d0442c6982d41001b9eb75af02e7b6f5c36730833b3c934f4c9f9f,0d1024188e27a87cfc6236a7b3d746ee287678525e2ad6e007e254e64bd0352a,1632e18ce39497e069ad31f7e3f34d62b1aa8cd53d70d1d6a8d76e9af6ab0576");
  const failed = await mount(path, "AdminSkillsTab", {}, { stubs: skillStubs(true) });
  assert.equal(byId(failed.root, "skills-error").length, 1);
  assert.equal(digest(failed), "7a476e3015957b3b2aed31f3bb90132be3111400dc69c16a715bf124ccee3da4");
});

// --- Scenario basic section -----------------------------------------------------------------------------------------

test("scenario basic section: name, scope, priority, status and description, active and inactive", async () => {
  const path = "admin/components/ScenarioBasicSection.tsx";
  const props = {
    projects: [{ id: "p-1", name: "Claims" }], scenarioName: "Jira research", setScenarioName: noop, scenarioProjectId: "p-1",
    setScenarioProjectId: noop, scenarioPriority: 7, setScenarioPriority: noop, scenarioActive: true, setScenarioActive: noop,
    scenarioDescription: "Heavy Jira use", setScenarioDescription: noop,
  };
  const view = await mount(path, "ScenarioBasicSection", props);
  assert.match(text(view.root), /Active — participates in matching/);
  assert.equal(digest(view), "21292276a8c76d6ff8cce2d61ec0731d04439ec11d161ac2476ec9632e6eda39");
  const inactive = await mount(path, "ScenarioBasicSection", { ...props, scenarioActive: false, projects: [] });
  assert.match(text(inactive.root), /Inactive — ignored/);
  assert.equal(digest(inactive), "558aea11f62bc3cec5f041b03f2b2d05481463c0ea7acc0f95facf26bc95be6d");
});

// --- Tool catalog ---------------------------------------------------------------------------------------------------

const TOOL_CATALOG = [
  { name: "knowledge_search", description: "Search knowledge", is_core: true, source: "platform" },
  { name: "jira_issue_update", description: "", is_core: false, source: "connector", connector: "jira", requires_change: true },
];

test("tool catalog: counts, toolbar, the table and the empty filter result", async () => {
  const path = "admin/components/AdminToolCatalogTab.tsx";
  const stubs = { ...parts("/AdminDefaultToolSetsSection", "AdminDefaultToolSetsSection"), ...parts("/AreaPurpose", "AreaPurpose") };
  const ctx = { connectorCatalogSearch: "", filteredToolCatalog: TOOL_CATALOG, setConnectorCatalogSearch: noop, toolCatalog: TOOL_CATALOG };
  const view = await mount(path, "AdminToolCatalogTab", { ctx }, { stubs });
  assert.match(text(view.root), /Tools \(2\/2\) · 1 core · 1 discoverable/);
  assert.equal(view.root.findAllByType("tr").length, 3);
  assert.equal(digest(view), "404cd7519d79c42e68ffea69d1ae5e9cbb5ed9d2f71270cac9244a4cfe3bed63");
  const none = await mount(path, "AdminToolCatalogTab", { ctx: { ...ctx, filteredToolCatalog: [], connectorCatalogSearch: "zz" } }, { stubs });
  assert.match(text(none.root), /No tools match the current search and filters\./);
  assert.equal(digest(none), "9f96b87e48db0f73428a1a5606f265f1ab8c7c258193a35c5d5b8caa7980eee3");
  const bare = await mount(path, "AdminToolCatalogTab", { ctx: { setConnectorCatalogSearch: noop } }, { stubs });
  assert.equal(digest(bare), "19294a13fd1d0eee9793bc43fd39f690763061aac3ba0a90f39c0b22525da84b");
});

// --- Agents overview ------------------------------------------------------------------------------------------------

const AGENTS_CTX = {
  agentBuilderMeta: {
    projects: [{ id: "p-1", name: "Claims" }],
  },
  handleOpenAgentForm: noop, setSelectedAgentPanelId: noop,
  panelAgents: [{ id: "a-1", name: "Writer", description: "Writes", projectId: "p-1", capabilityCeiling: "change", isActive: true }],
  readJson: async () => ({ builtins: [{ key: "coder", name: "Coder", description: "Built-in", capability_ceiling: "deliver",
    default_workflow_key: "bugfix", row: true }], usage_window_days: 14, usage: { "a-1": 5 } }),
};

test("agents overview: list with workspace and built-in rows and the empty search", async () => {
  const path = "admin/components/agentsTab/AgentsOverviewPage.tsx";
  const view = await mount(path, "AgentsOverviewPage", { ctx: AGENTS_CTX });
  assert.equal(byId(view.root, "agent-row-a-1").length, 1);
  assert.match(text(view.root), /Used \(14 d\)/);
  const digests = [digest(view)];
  await act(async () => { view.root.find((node) => node.props["aria-label"] === "Search agents").props.onChange({ target: { value: "zzz" } }); });
  assert.match(text(view.root), /No agent matches this search\./);
  digests.push(digest(view));
  assert.equal(digests.join(","), "7449b0113606a45d06e17fe721a81ab113d7b5078a31994b9ec80d5016e9ff5b,78d246de81ed04e379f57912e4bcf1f9bd7b9d0d116f026ae348db31c1aef97a");
  const bare = await mount(path, "AgentsOverviewPage", { ctx: { projects: [] } });
  assert.equal(digest(bare), "52316f6100c06f9d5976f13f10307db6b38f9ec7631f68fbcbaa683f0a69af2b");
});

// --- Corporate identity page ----------------------------------------------------------------------------------------

const corpIdentityState = (overrides = {}) => ({
  corpIdentityProfiles: [{ id: "cp-1", name: "Acme" }], corpIdentitySelectedId: "cp-1", corpIdentityError: "Upload refused",
  corpIdentityUploadBusy: false, handleUploadCorpIdentity: async () => {}, loadCorpIdentityDetail: async () => {},
  refreshCorpIdentities: async () => {}, ...overrides,
});
const corpStubs = (state) => ({
  "/useAdminCorpIdentity": { useAdminCorpIdentity: () => state },
  ...parts("/CorpProfileDrawer", "CorpProfileDrawer"), ...parts("/CorpProfilesTable", "CorpProfilesTable"),
  ...parts("/AdminPresentationFallbackSection", "AdminPresentationFallbackSection"),
});

test("corporate identity page: header, table, drawer and the new-profile panel; the empty page", async () => {
  const path = "admin/components/AdminCorpIdentityTab.tsx";
  const view = await mount(path, "AdminCorpIdentityTab", { projects: [] }, { stubs: corpStubs(corpIdentityState()) });
  assert.match(text(view.root), /Profiles \(1\)/);
  const digests = [digest(view)];
  await act(async () => { byId(view.root, "corp-new-profile")[0].props.onClick(); });
  assert.equal(byId(view.root, "corp-new-profile-panel").length > 0, true);
  digests.push(digest(view));
  await act(async () => { findPart(view, "CorpProfileDrawer").props.setAddingTemplateTo("cp-1"); });
  digests.push(digest(view));
  assert.equal(digests.join(","), "a3500cf3fe8c361e614393dedb1b0f276ad67095b0d358600e9c3606cc5b0fc0,99405f3b59ec2b195c1e12e3fa265cc73a05db82ba4fdb40366ffe32712867e9,290e3b49d15e120594ad19f206ed598d96f9ea1d0dbe2e2946b7dd952f85b1c1");
  const empty = await mount(path, "AdminCorpIdentityTab", { projects: [] },
    { stubs: corpStubs(corpIdentityState({ corpIdentityProfiles: [], corpIdentitySelectedId: null, corpIdentityError: null })) });
  assert.equal(byId(empty.root, "corp-empty").length > 0, true);
  assert.equal(digest(empty), "395c05a1057eb5b3e1681296be6f66cceb2de2b5f84269fa7666263b55dffd0e");
});

// --- Inbound webhook setup ------------------------------------------------------------------------------------------

test("inbound webhook setup: action choice, filters, repeats, limits and the error", async () => {
  const path = "admin/components/inboundWebhooks/InboundWebhookSetupSections.tsx";
  const webhook = { task_id: "a-1", result_to: { label: "Chat" }, alert_filter: "", group_window_minutes: 45, rate_limit_per_hour: 20,
    workspace_name: "Ops" };
  const props = { webhook, workspaceActions: [{ id: "a-1", name: "Analyse" }], busy: false, error: "Save failed", save: async () => {} };
  const view = await mount(path, "InboundWebhookSetup", props);
  assert.match(text(view.root), /Runs as the Ops automation identity/);
  assert.equal(digest(view), "8b7163a2076f667531be130c18fec31d4735fc6786061198f32a410d1cc57df5");
  const plain = await mount(path, "InboundWebhookSetup", { ...props, busy: true, error: null, webhook: { ...webhook, task_id: null, group_window_minutes: 30 } });
  assert.equal(digest(plain), "0c98a2bfa44d10107543ac0e1cee5a534b2a677aba0f12af0a99e36e32b22c56");
});
