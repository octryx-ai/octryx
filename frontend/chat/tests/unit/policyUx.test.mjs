// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/policyUx.test.mjs
//
// Policies page (policy UX): the engine status card and drawer, the tabs, the
// draft bar, the policy table with filters and the generated baseline, the policy drawer, and the hand-written Cedar
// editor behind "Advanced". Requests are stubs; the catalog is the backend's real policy_catalog.json.

import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import {
  NO_FILTERS, filterPolicies, policyStatus, readCatalog, readPickerEntities, readPolicyView, readUrlFilters, relativeTime, sentenceText,
} from "../../src/admin/components/policyEngine/policyCatalogModel.ts";
import { highlightCedar } from "../../src/admin/components/policyEngine/cedarHighlight.ts";
import { cedarThemeData } from "../../src/admin/components/policyEngine/cedarTheme.ts";
import { ADMIN_AREA_CONFIGS, resolveAdminAreaForTab, resolveAdminSidebarTab } from "../../src/admin/config/adminPanelAreas.ts";
import { CATALOG, STATUS, act, byTestId, change, click, load, server, text, tick } from "./policyEngineHarness.mjs";
import { ADMIN_ENTRIES, locateAdminPage } from "../../src/admin/config/adminEntries.ts";

const seg = (value, emphasis = null) => ({ text: value, emphasis });
const ITEM = (id, overrides = {}) => ({
  id, name: id, description: "", template: null, source: "hand_written", editable: true, effect: "forbid",
  actions: ["write_connector"], groups: ["Connectors & tools"], points: ["Tool admission (chat & MCP)"],
  text: `@id("${id}")\nforbid (principal, action == Action::"write_connector", resource);`, digest: `d-${id}`,
  sentence: [seg("Block", "verb"), seg(" "), seg("everyone", "value"), seg(" from "), seg("changing data", "value"), seg(".")],
  scope: "All Workspaces", references: { entities: {}, connections: [] }, warnings: [], change: "unchanged",
  last_changed: { version: 2, by: "u-1", by_name: "Ada Admin", at: "2026-10-06T10:00:00" },
  ...overrides,
});
const ITEMS = [
  ITEM("prod-read-only", { name: "Production read-only", source: "builder", scope: "Connection primary", references: { entities: {}, connections: ["c-1"] },
    sentence: [seg("Block", "verb"), seg(" "), seg("everyone", "value"), seg(" from "), seg("changing data", "value"), seg(" on connection "), seg("primary", "value"), seg(".")] }),
  ITEM("contractors-jira", { change: "new", references: { entities: { Group: ["contractors"], ConnectorFamily: ["jira"], Workspace: ["ws-1"] }, connections: [] },
    sentence: [seg("Block", "verb"), seg(" members of group "), seg("contractors", "value"), seg(" from "), seg("changing data", "value"), seg(" in "), seg("Claims", "value"), seg(" (with conditions written in Cedar).")],
    warnings: [{ code: "who_not_effective", message: "Who-conditions are not effective yet for Change data through a connector: that check does not carry the user.", actions: ["write_connector"] }] }),
  ITEM("secret-files", { change: "changed", actions: ["read_path"], groups: ["Coding agent"], points: ["Coding-agent tool check"] }),
  ITEM("legacy", { change: "removed" }),
];
const GENERATED = [
  ITEM("platform:tool-permit", { source: "platform", effect: "permit", change: null, last_changed: null, scope: "Instance", editable: false }),
  ITEM("classification:confidential:seat-not-allowed", { source: "classification", change: null, last_changed: null, editable: false,
    edit_where: "Settings → Governance → Classification policy", actions: ["use_seat"], groups: ["Seats"] }),
];
const DRAFT_TEXT = ITEMS.slice(0, 3).map((item) => item.text).join("\n\n") + "\n";

const THEIRS = '@id("theirs")\nforbid (principal, action == Action::"use_seat", resource);\n';

function pageServer({ state = "draft", refusePublish = null, review = null, conflict = false, singleAdmin = false } = {}) {
  const versions = { 3: { version: 3, state, digest: "sha256:3", policy_ids: ["prod-read-only"], policies: DRAFT_TEXT, approval_id: state === "in_review" ? "ap-1" : null,
    created_by: "u-1", updated_at: new Date().toISOString(),
    test_report: { results: [{ id: "t1", name: "prod write", expected: "deny", actual: "deny", passed: true, determining: ["prod-read-only"] }] } },
  2: { version: 2, state: "published", digest: "sha256:2", policy_ids: ["prod-read-only", "legacy"], policies: '@id("legacy")\nforbid (principal, action, resource);\n' } };
  const saved = { meanwhile: false };
  return server((call) => {
    if (call.url === "/api/v1/admin/governance/approval-rule") {
      return { status: 200, body: { rule: singleAdmin ? "single_admin" : "four_eyes", self_approval_allowed: singleAdmin } };
    }
    if (call.url.startsWith("/api/v1/observability/decisions/policy-counts")) return { status: 200, body: { days: 7, denied: { "prod-read-only": 14 } } };
    const url = call.url.replace("/api/v1/admin/policy-engine", "");
    if (url === "/status") return { status: 200, body: STATUS() };
    if (url === "/mode") return { status: 200, body: STATUS({ mode: call.body.mode }) };
    if (url === "/settings") return { status: 200, body: call.body };
    if (url === "/schema") return { status: 200, body: { schema: "", version: "2026-10-06.2" } };
    if (url === "/catalog") return { status: 200, body: CATALOG };
    if (url === "/catalog/entities") return { status: 200, body: {
      workspaces: [{ id: "ws-1", name: "Claims", classification: "confidential" }],
      named_connections: [{ id: "c-1", name: "primary", connector: "servicenow", scope: "global" }],
      connector_families: [{ id: "servicenow", label: "ServiceNow" }, { id: "jira", label: "Jira" }] } };
    if (url.startsWith("/policies")) {
      return { status: 200, body: { version: versions[3], published_version: 2, author_name: "Ada Admin", items: ITEMS,
        changes: { new: 1, changed: 1, removed: 1 }, ...(url.includes("include_generated=true") ? { generated: GENERATED } : {}) } };
    }
    if (url === "/validate") return { status: 200, body: call.body.policies.includes("permit") ? { valid: false, issues: [{ policy_id: "x", code: "permit_not_allowed", message: "Custom policies may only forbid; the baseline grants." }] } : { valid: true } };
    if (url === "/policy-sets" && call.method === "GET") return { status: 200, body: { items: [
      { ...versions[3], author_name: "Ada Admin", note: "secrets" },
      { ...versions[2], author_name: "Ada Admin", reviewer_name: singleAdmin ? "Ada Admin" : "Rex Reviewer", note: "first", approval_mode: singleAdmin ? "self" : "four_eyes" },
      { version: 1, state: "retired", policy_ids: [], author_name: "Ada Admin" }] } };
    if (url === "/policy-sets/1/rollback") return { status: 201, body: { version: 4, state: "draft" } };
    if (url === "/policy-sets/3" && call.method === "PUT") {
      if (conflict && call.headers["If-Match"] !== "sha256:3b") {
        saved.meanwhile = true; // another admin saved v3 after this page loaded it
        return { status: 409, body: { detail: { code: "policy_set_draft_conflict", digest: "sha256:3b" } } };
      }
      return { status: 200, body: { ...versions[3], policies: call.body.policies, digest: "sha256:3c" } };
    }
    if (url === "/policy-sets/3" && call.method === "PATCH") return { status: 200, body: { ...versions[3], note: call.body.note } };
    if (url === "/policy-sets/3" && saved.meanwhile) return { status: 200, body: { ...versions[3], digest: "sha256:3b", policies: THEIRS, note: "theirs" } };
    if (url === "/policy-sets/3/submit") return { status: 200, body: { ...versions[3], state: "in_review" } };
    if (url === "/policy-sets/3/publish") return refusePublish ?? { status: 200, body: { ...versions[3], state: "published" } };
    if (url === "/policy-sets/3/retire") return { status: 200, body: { ...versions[3], state: "retired" } };
    if (/^\/policy-sets\/3\/impact\?hours=24$/.test(url)) return { status: 200, body: { version: 3, hours: 24, total: 12, policies: {
      "contractors-jira": { count: 12, points: { tool_admission: 12 }, actions: { write_connector: 10, call_tool: 2 }, principals: 3,
        samples: [{ time: "2026-10-07T10:00:00", point: "tool_admission", action: "write_connector", principal: "User::u-1", resource: "Tool::add_jira_comment", workspace_id: "ws-1" }] } } } };
    if (/^\/policy-sets\/\d+\/policies\//.test(url)) return { status: 200, body: { ...ITEMS[0], history: [{ version: 2, state: "published", change: "new", by_name: "Ada Admin", published_at: "2026-10-06T10:00:00" }, { version: 3, state: "draft", change: "unchanged", by_name: "Ada Admin" }] } };
    if (/^\/policy-sets\/\d+$/.test(url)) return { status: 200, body: { ...versions[Number(url.split("/")[2])], review: url.endsWith("/3") ? review : null } };
    if (url.startsWith("/decisions")) return { status: 200, body: { items: [], total: 14 } };
    if (url.startsWith("/entities")) return { status: 200, body: { workspaces: [], users: [], tools: [], actions: ["use_seat"] } };
    if (url.startsWith("/tests")) return { status: 200, body: { items: [] } };
    if (call.url.startsWith("/api/v1/approvals/")) return { status: 200, body: { status: "approved" } };
    return { status: 404, body: { detail: "nope" } };
  });
}

const StubEditor = ({ value, onChange, readOnly, showDiff }) =>
  createElement("textarea", { "data-testid": "stub-editor", value, readOnly, "data-diff": showDiff ? "yes" : "no", onChange: (event) => onChange(event.target.value) });

async function renderPage(srv, props = {}) {
  const { AdminCedarPolicies } = load("admin/components/policyEngine/AdminCedarPolicies.tsx", { fetch: srv.fetch, window: undefined });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AdminCedarPolicies, { editor: StubEditor, search: "", ...props })); });
  for (let index = 0; index < 4; index += 1) await tick();
  return view;
}
const statuses = (view) => byTestId(view, "policy-row-status").map((node) => text(node));

// ---- model -----------------------------------------------------------------------------------------------------

test("model: the per-policy view, status labels against the published version, filters and deep links", () => {
  const view = readPolicyView({ version: { version: 3, state: "draft" }, published_version: 2, items: [...ITEMS, { nope: 1 }], changes: { new: 1 } });
  assert.equal(view.items.length, 4);
  assert.equal(view.generated, null);
  assert.equal(sentenceText(view.items[0].sentence), "Block everyone from changing data on connection primary.");
  assert.deepEqual(view.items.map((item) => policyStatus(item, "draft").label), ["Published", "Draft · new", "Draft · changed", "Draft · removed"]);
  assert.deepEqual(view.items.map((item) => policyStatus(item, "in_review").label), ["Published", "In review · new", "In review · changed", "In review · removed"]);
  assert.equal(policyStatus(readPolicyView({ items: GENERATED }).items[0], "draft").label, "Generated");
  const ids = (filters) => filterPolicies(view.items, { ...NO_FILTERS, ...filters }, "draft", readPickerEntities({ named_connections: [{ id: "c-1", connector: "servicenow" }] }).namedConnections).map((item) => item.id);
  assert.deepEqual(ids({ query: "CONTRACTORS" }), ["contractors-jira"]);
  assert.deepEqual(ids({ query: "primary" }), ["prod-read-only"], "the sentence (names) is searchable");
  assert.deepEqual(ids({ status: "draft" }), ["contractors-jira", "secret-files", "legacy"]);
  assert.deepEqual(ids({ status: "published" }), ["prod-read-only"]);
  assert.deepEqual(ids({ group: "Coding agent" }), ["secret-files"]);
  assert.deepEqual(ids({ workspace: "ws-1" }), ["contractors-jira"]);
  assert.deepEqual(ids({ connection: "c-1" }), ["prod-read-only"]);
  assert.deepEqual(ids({ connector: "servicenow" }), ["prod-read-only"], "through its connection");
  assert.deepEqual(ids({ connector: "jira" }), ["contractors-jira"], "through its connector family");
  assert.deepEqual(readUrlFilters("?policyConnection=c-1&policyWorkspace=ws-1&policyConnector=<x>"), { workspace: "ws-1", connection: "c-1" });
  assert.equal(relativeTime("2026-10-07T10:00:00", new Date("2026-10-07T10:10:00Z")), "10 min ago", "naive server times are UTC");
  assert.equal(relativeTime("2026-10-07T10:00:00+02:00", new Date("2026-10-07T08:10:00Z")), "10 min ago");
  assert.equal(relativeTime("2026-10-01T10:00:00Z", new Date("2026-10-07T10:10:00Z")), "6 d ago");
  assert.equal(relativeTime("", new Date()), "");
});

test("model: the catalog drives groups, actions and blocks (never hard-coded in the UI)", () => {
  const catalog = readCatalog({ ...CATALOG, condition_blocks: CATALOG.condition_blocks.map((block) => ({ ...block, actions: ["call_model"] })) });
  assert.deepEqual(catalog.actionGroups, ["Connectors & tools", "Models", "Tool results", "Coding agent", "Knowledge", "Seats", "Devices"]);
  assert.equal(catalog.actions.length, 12);
  assert.equal(catalog.blocks.find((block) => block.id === "who.not_admin").clause, "unless");
  assert.deepEqual(catalog.clientTools, ["Bash", "Read", "Edit", "Write", "MultiEdit", "NotebookEdit"]);
  assert.equal(catalog.templates.length, 12);
  assert.deepEqual(catalog.templates[0].placeholders.map((item) => item.field), ["where.connections"]);
});

test("model: read-only Cedar colouring and the editor theme from the design tokens", () => {
  const tokens = highlightCedar('@id("a") // note\nforbid (principal, action, resource) when { resource.path like "*.env" };');
  assert.deepEqual(tokens.filter((token) => token.kind !== "plain").map((token) => [token.kind, token.text]), [
    ["annotation", "@id"], ["string", '"a"'], ["comment", "// note"], ["keyword", "forbid"], ["keyword", "principal"], ["keyword", "action"],
    ["keyword", "resource"], ["keyword", "when"], ["keyword", "resource"], ["keyword", "like"], ["string", '"*.env"'],
  ]);
  assert.equal(tokens.map((token) => token.text).join(""), '@id("a") // note\nforbid (principal, action, resource) when { resource.path like "*.env" };');
  const colors = { "--bg": "#0e100f", "--muted": "#898f86", "--muted-strong": "#cbc7bc", "--text": "#efece4", "--status-error-ink": "#fca5a5", "--status-active-ink": "#9ae6b4", "--status-running-ink": "#bae6fd" };
  const dark = cedarThemeData("dark", (name) => colors[name]);
  assert.equal(dark.base, "vs-dark");
  assert.equal(dark.colors["editor.background"], "#0e100f", "the editor sits on the dark code surface, not white");
  assert.deepEqual(dark.rules.find((rule) => rule.token === "keyword"), { token: "keyword", foreground: "fca5a5" });
  assert.equal(cedarThemeData("light", (name) => colors[name]).base, "vs");
});

test("Policies is a view of Rules (N1, two tab levels); the test bench stays with it", () => {
  const rules = ADMIN_ENTRIES.find((entry) => entry.label === "Rules");
  assert.deepEqual(rules.views.map((view) => view.pages.map((page) => page.tab)),
    [["cedarPolicies"], ["approvalRule"], ["policies"], ["commandSafety"], ["contentSecurity"], ["classificationPolicy"]]);
  for (const tab of ["cedarPolicies", "policyTestBench"]) {
    assert.equal(resolveAdminAreaForTab(tab), "admin");
    assert.equal(resolveAdminSidebarTab("admin", tab), "cedarPolicies", "Rules opens on Policies");
    assert.equal(locateAdminPage(tab).page.tab, "cedarPolicies");
  }
});

// ---- rendered page ---------------------------------------------------------------------------------------------

test("page: status card in one line, three tabs, the draft bar, and the policy table with status, sentence and warnings", async () => {
  const srv = pageServer();
  const view = await renderPage(srv);
  const card = text(byTestId(view, "policy-engine-card")[0]);
  assert.match(card, /Shadow.*1 mismatches · 24 h.*v2 published.*Enforce not ready/);
  // The decision log is Observability → Decisions, no tab of the Policies page.
  assert.deepEqual(["list", "bench", "decisions"].map((id) => byTestId(view, `policies-tab-${id}`).length), [1, 1, 0]);
  assert.equal(byTestId(view, "policies-tab-list")[0].props["aria-selected"], true);
  const bar = text(byTestId(view, "policy-draft-bar")[0]);
  assert.match(bar, /Draft v3/);
  assert.match(bar, /3 changes against published v2/);
  assert.match(bar, /1\/1 test cases pass/);
  assert.deepEqual(statuses(view), ["Published", "Draft · new", "Draft · changed", "Draft · removed"]);
  assert.equal(byTestId(view, "policy-row-warning").length, 1);
  const firstRow = byTestId(view, "policy-row")[0];
  assert.ok(firstRow.findAll((node) => node.type === "b").some((node) => text(node) === "primary"), "values are bold");
  assert.ok(firstRow.findAll((node) => node.props.className === "policies__verb").length, "the verb is marked");
  assert.match(text(firstRow), /Ada Admin/);
  assert.equal(byTestId(view, "policy-row")[3].props.className.includes("admin-panel__row--inactive"), true, "a removed policy is greyed");
});

test("page: search and filters narrow the table; the generated baseline loads on demand and is read-only", async () => {
  const srv = pageServer();
  const view = await renderPage(srv);
  await change(view, "policy-search", "contractors");
  assert.equal(byTestId(view, "policy-row").length, 1);
  await change(view, "policy-search", "");
  await change(view, "policy-filter-status", "draft");
  assert.equal(byTestId(view, "policy-row").length, 3);
  await change(view, "policy-filter-status", "");
  await change(view, "policy-filter-group", "Coding agent");
  assert.equal(byTestId(view, "policy-row").length, 1);
  await change(view, "policy-filter-group", "");
  assert.equal(srv.calls.some((call) => call.url.includes("include_generated=true")), false);
  await act(async () => { byTestId(view, "policy-show-generated")[0].props.onChange({ target: { checked: true } }); });
  await tick();
  await tick();
  assert.ok(srv.calls.some((call) => call.url.includes("include_generated=true")));
  assert.equal(byTestId(view, "policy-generated-row").length, 2);
  await act(async () => { byTestId(view, "policy-generated-row")[1].props.onClick(); });
  await tick();
  assert.match(text(byTestId(view, "policy-drawer-generated")[0]), /Read-only here — edit it at Settings → Governance → Classification policy/);
  assert.equal(byTestId(view, "policy-edit-source").length, 1);
  assert.equal(byTestId(view, "policy-drawer-effect").length, 0, "generated rows have no decision count");
});

test("page: a deep link from a connector filters by its connection and shows a removable chip", async () => {
  const srv = pageServer();
  const view = await renderPage(srv, { search: "?policyConnection=c-1" });
  assert.equal(text(byTestId(view, "policy-active-filters")[0]), "Connection: primary✕");
  assert.equal(byTestId(view, "policy-row").length, 1);
  const clear = byTestId(view, "policy-active-filters")[0].findByType("button");
  await act(async () => { clear.props.onClick(); });
  assert.equal(byTestId(view, "policy-row").length, 4);
});

test("page: the policy drawer shows the sentence, denials in 7 days with a link to Decisions, test cases, history and Cedar", async () => {
  const srv = pageServer();
  const view = await renderPage(srv);
  await act(async () => { byTestId(view, "policy-row")[0].props.onClick(); });
  await tick();
  await tick();
  assert.equal(text(byTestId(view, "policy-drawer-sentence")[0]), "Block everyone from changing data on connection primary.");
  // Shadow mode: Cedar's deny blocked nothing, so the count says "would have denied" (not "blocked").
  assert.match(text(byTestId(view, "policy-drawer-effect")[0]), /Would have denied 14 requests in the last 7 days/);
  assert.ok(srv.calls.some((call) => call.url === "/api/v1/observability/decisions/policy-counts?days=7"));
  assert.match(text(byTestId(view, "policy-drawer-cases")[0]), /1 reference this policy · all pass/);
  assert.match(text(byTestId(view, "policy-drawer-history")[0]), /v2 · new · Published · by Ada Admin/);
  assert.ok(srv.calls.some((call) => call.url.endsWith("/policy-sets/3/policies/prod-read-only")));
  assert.match(text(byTestId(view, "policy-drawer-cedar")[0]), /@id\("prod-read-only"\)/);
  await click(view, "policy-drawer-decisions");
  await tick();
  assert.equal(byTestId(view, "policy-drawer-effect").length, 0, "the drawer closes and Decisions opens");
});

test("page: a new policy has no decisions yet; its warnings are shown", async () => {
  const srv = pageServer();
  const view = await renderPage(srv);
  await act(async () => { byTestId(view, "policy-row")[1].props.onClick(); });
  await tick();
  assert.match(text(byTestId(view, "policy-drawer-effect")[0]), /Not published yet/);
  assert.match(text(byTestId(view, "policy-drawer-warning")[0]), /not effective yet/);
  assert.equal(srv.calls.filter((call) => call.url.includes("/decisions?")).length, 0);
});

test("page: the engine drawer guards enforce, explains why, and saves the window and retention", async () => {
  const srv = pageServer();
  const view = await renderPage(srv);
  await click(view, "policy-engine-card");
  assert.equal(byTestId(view, "policy-engine-mode-enforce")[0].props.disabled, true);
  assert.match(text(byTestId(view, "policy-engine-blockers")[0]), /shadow period is not over/);
  assert.match(text(byTestId(view, "policy-engine-summary")[0]), /14 agreements, 1 disagreements/);
  assert.equal(byTestId(view, "policy-engine-mode-save")[0].props.disabled, true, "nothing changed");
  await change(view, "policy-engine-retention", "60");
  await click(view, "policy-engine-mode-off");
  await click(view, "policy-engine-mode-save");
  await tick();
  assert.deepEqual(srv.calls.find((call) => call.url.endsWith("/settings")).body, { enforce_window_hours: 24, decision_log_retention_days: 60 });
  assert.deepEqual(srv.calls.find((call) => call.url.endsWith("/mode")).body, { mode: "off" });
  assert.equal(text(byTestId(view, "policy-engine-message")[0]), "Saved.");
});

const REVIEW = (overrides = {}) => ({ approval_id: "ap-1", status: "pending", requested_by: { id: "u-1", name: "Ada Admin" }, requested_at: "2026-10-07T10:00:00",
  decided_by: null, comment: "", author: { id: "u-1", name: "Ada Admin" }, submitter: { id: "u-1", name: "Ada Admin" },
  approver_candidates: [{ id: "u-2", name: "Rex Reviewer" }], viewer: { is_author: false, is_submitter: false, can_approve: true },
  rule: "A platform admin other than the author and the submitter must approve before anyone can publish.", ...overrides });

test("lifecycle: the draft bar opens the drawer — changes, Cedar diff, checks, history with author and reviewer", async () => {
  const srv = pageServer();
  const view = await renderPage(srv);
  assert.equal(text(byTestId(view, "draft-next")[0]), "Submit for review");
  await click(view, "draft-review");
  await tick();
  assert.equal(byTestId(view, "policy-lifecycle").length, 1);
  assert.deepEqual(byTestId(view, "lifecycle-change").map(text), ["New contractors-jira", "Changed secret-files", "Removed legacy"]);
  const diff = text(byTestId(view, "lifecycle-diff")[0]);
  assert.match(diff, /^- @id\("legacy"\)$/m);
  assert.match(diff, /^\+ @id\("prod-read-only"\)$/m);
  assert.match(text(byTestId(view, "lifecycle-checks")[0]), /✓ 1\/1 saved test cases pass/);
  assert.deepEqual(byTestId(view, "lifecycle-history-row").map((row) => text(row)), [
    "v3DraftsecretsAda Admin", "v2PublishedfirstAda Admin · Rex ReviewerRetire (via review)", "v1Retired—Ada AdminRoll back"]);
  assert.equal(byTestId(view, "lifecycle-rollback-1")[0].props.disabled, true, "one open draft at a time");
  assert.equal(byTestId(view, "lifecycle-retire-2")[0].props.disabled, true);
  await click(view, "lifecycle-discard");
  assert.ok(srv.calls.some((call) => call.url.endsWith("/policy-sets/3/retire")));
});

test("lifecycle: submitting saves a changed note first; in review the viewer approves when allowed, then publishes", async () => {
  const srv = pageServer();
  const view = await renderPage(srv);
  await click(view, "draft-next");
  await change(view, "lifecycle-note", "Secrets blocked");
  await click(view, "lifecycle-submit");
  assert.equal(srv.calls.some((call) => call.method === "PUT"), false, "the note is saved without re-sending the text");
  const saved = srv.calls.find((call) => call.method === "PATCH" && call.url.endsWith("/policy-sets/3"));
  assert.deepEqual(saved.body, { note: "Secrets blocked" });
  assert.ok(srv.calls.findIndex((call) => call.url.endsWith("/submit")) > srv.calls.indexOf(saved), "saved, then submitted");
  assert.match(text(byTestId(view, "cedar-message")[0]), /another platform admin must approve/);

  const pending = pageServer({ state: "in_review", review: REVIEW() });
  const reviewView = await renderPage(pending);
  assert.match(text(byTestId(reviewView, "policy-draft-bar")[0]), /In review v3.*waiting for another platform admin/);
  assert.deepEqual(statuses(reviewView).slice(1), ["In review · new", "In review · changed", "In review · removed"]);
  await click(reviewView, "draft-next");
  await tick();
  assert.match(text(byTestId(reviewView, "lifecycle-review")[0]), /Submitted by Ada Admin.*status pending.*May approve: Rex Reviewer/);
  assert.equal(byTestId(reviewView, "lifecycle-publish")[0].props.disabled, true, "not approved yet");
  await click(reviewView, "lifecycle-approve");
  assert.ok(pending.calls.some((call) => call.url === "/api/v1/approvals/ap-1/approve"));

  const own = pageServer({ state: "in_review", review: REVIEW({ viewer: { is_author: true, is_submitter: true, can_approve: false } }) });
  const ownView = await renderPage(own);
  await click(ownView, "draft-next");
  await tick();
  assert.equal(byTestId(ownView, "lifecycle-approve")[0].props.disabled, true);
  assert.match(text(byTestId(ownView, "lifecycle-four-eyes")[0]), /^You wrote or submitted this version — another platform admin must approve it\./);

  const approved = pageServer({ state: "in_review", review: REVIEW({ status: "approved", decided_by: { id: "u-2", name: "Rex Reviewer" } }),
    refusePublish: { status: 409, body: { detail: { code: "policy_set_self_approval" } } } });
  const approvedView = await renderPage(approved);
  await click(approvedView, "draft-next");
  await tick();
  await click(approvedView, "lifecycle-publish");
  assert.deepEqual(approved.calls.find((call) => call.url.endsWith("/publish")).body, { governance_approval_id: "ap-1" });
  assert.match(text(byTestId(approvedView, "lifecycle-problem")[0]), /Four-eyes/);
});

test("approval rule: four-eyes by default; single admin publishes a draft in one step, recorded as self-approved", async () => {
  const fourEyes = await renderPage(pageServer());
  assert.equal(text(byTestId(fourEyes, "approval-rule-badge")[0]), "Four-eyes approval");

  const srv = pageServer({ singleAdmin: true });
  const view = await renderPage(srv);
  assert.equal(text(byTestId(view, "approval-rule-badge")[0]), "Single admin: self-approval on");
  assert.equal(text(byTestId(view, "draft-next")[0]), "Publish");
  await click(view, "draft-next");
  await tick();
  assert.equal(byTestId(view, "lifecycle-submit").length, 0, "no separate review step");
  assert.match(text(byTestId(view, "lifecycle-history-row")[1]), /Ada Admin · Ada Admin \(self-approved\)/);
  await click(view, "lifecycle-publish-own");
  const submit = srv.calls.findIndex((call) => call.url.endsWith("/policy-sets/3/submit"));
  const publish = srv.calls.findIndex((call) => call.url.endsWith("/policy-sets/3/publish"));
  assert.ok(submit >= 0 && publish > submit, "submitted, then published");
  assert.deepEqual(srv.calls[publish].body, { self_approve: true });
  assert.match(text(byTestId(view, "cedar-message")[0]), /Version 3 published \(self-approved\)/);
});

test("page: Advanced → hand-written Cedar: refused text shows issues and is not saved; a valid text saves the draft", async () => {
  const srv = pageServer();
  const view = await renderPage(srv);
  await click(view, "policy-advanced-cedar");
  await tick();
  assert.equal(byTestId(view, "stub-editor")[0].props.value, DRAFT_TEXT);
  assert.equal(byTestId(view, "policy-table").length, 0, "the editor replaces the tabs");
  await change(view, "stub-editor", '@id("x") permit (principal, action, resource);');
  await click(view, "cedar-save");
  assert.match(text(byTestId(view, "cedar-issues")[0]), /may only forbid/);
  assert.equal(srv.calls.some((call) => call.method === "PUT"), false);
  await change(view, "stub-editor", DRAFT_TEXT + '\n@id("y")\nforbid (principal, action == Action::"use_seat", resource);\n');
  await click(view, "cedar-save");
  const saved = srv.calls.find((call) => call.method === "PUT" && call.url.endsWith("/policy-sets/3"));
  assert.match(saved.body.policies, /@id\("y"\)/);
  assert.equal(saved.headers["If-Match"], "sha256:3", "the save carries the digest the text started from");
  assert.equal(byTestId(view, "cedar-versions").length, 0, "the versions live in the lifecycle drawer");
  await click(view, "cedar-back");
  assert.equal(byTestId(view, "policy-table").length, 1);
});

test("page: hand-written Cedar — a draft saved meanwhile by someone else keeps my text and offers load or overwrite", async () => {
  const srv = pageServer({ conflict: true });
  const view = await renderPage(srv);
  await click(view, "policy-advanced-cedar");
  await tick();
  const mine = DRAFT_TEXT + '\n@id("mine")\nforbid (principal, action == Action::"use_seat", resource);\n';
  await change(view, "stub-editor", mine);
  await click(view, "cedar-save");
  await tick();
  assert.match(text(byTestId(view, "cedar-conflict")[0]), /Someone else saved draft v3/);
  assert.match(text(byTestId(view, "cedar-message")[0]), /Someone else changed the draft/);
  assert.equal(byTestId(view, "stub-editor")[0].props.value, mine, "my text is kept");
  await click(view, "cedar-conflict-overwrite");
  await tick();
  const puts = srv.calls.filter((call) => call.method === "PUT");
  assert.deepEqual(puts.map((call) => call.headers["If-Match"]), ["sha256:3", "sha256:3b"], "overwrite names the version it replaces");
  assert.equal(byTestId(view, "cedar-conflict").length, 0);
  assert.match(text(byTestId(view, "cedar-message")[0]), /Draft saved/);

  const other = pageServer({ conflict: true });
  const otherView = await renderPage(other);
  await click(otherView, "policy-advanced-cedar");
  await tick();
  await change(otherView, "stub-editor", mine);
  await click(otherView, "cedar-save");
  await tick();
  await click(otherView, "cedar-conflict-load");
  await tick();
  assert.equal(byTestId(otherView, "stub-editor")[0].props.value, THEIRS, "their version replaces mine");
  assert.equal(byTestId(otherView, "cedar-note")[0].props.value, "theirs");
  assert.equal(other.calls.filter((call) => call.method === "PUT").length, 1, "nothing was overwritten");
});

test("status card: the draft shadow's own latency shows only while a draft is evaluated", async () => {
  const { readStatus } = load("admin/components/policyEngine/policyEngineStatus.ts");
  const status = readStatus(STATUS({ draft_latency: { samples: 5, p50_ms: 0.3, p95_ms: 0.7 } }));
  assert.equal(status.draftP95Ms, 0.7);
  assert.equal(status.draftSamples, 5);
  assert.equal(readStatus(STATUS()).draftSamples, 0);
});

test("draft shadow (G8): a draft policy's drawer shows what it would have blocked in live traffic", async () => {
  const srv = pageServer();
  const view = await renderPage(srv);
  assert.ok(srv.calls.some((call) => call.url.endsWith("/policy-sets/3/impact?hours=24")));
  await act(async () => { byTestId(view, "policy-row")[1].props.onClick(); });
  await tick();
  assert.equal(text(byTestId(view, "draft-traffic")[0].findAll((node) => node.props.className === "policies__summary")[0]),
    "In the last 24 h it would have blocked 12 requests (10 × write_connector, 2 × call_tool) by 3 users.");
  assert.match(text(byTestId(view, "draft-traffic-samples")[0]), /write_connector · Tool::add_jira_comment · User::u-1/);
  await act(async () => { byTestId(view, "policy-row")[2].props.onClick(); });
  await tick();
  assert.equal(text(byTestId(view, "draft-traffic-none")[0]), "In the last 24 h no live request would have been blocked by it.");
  await act(async () => { byTestId(view, "policy-row")[0].props.onClick(); });
  await tick();
  assert.equal(byTestId(view, "draft-traffic").length + byTestId(view, "draft-traffic-none").length, 0, "an unchanged published policy shows the decision log instead");
});
