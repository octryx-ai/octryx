// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/classificationPolicy.test.mjs
//
// Classification policy matrix and Workspace policy view.
// Settings → Governance → "Classification policy": one row per level in the server's order, one column per rule with
// plain-language help, models and connector families in a sub-row, "Reset to defaults", and a save that first lists
// every change. Platform admins edit; everybody else sees it read-only. Agents → Governance → "Policy": the
// Workspace's effective policy, read-only for members. The Data classification card links to both. The fixtures use
// made-up level names on purpose: the UI takes names and order from the server only. Requests are stubs.

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import {
  INVALID_STATE_TEXT,
  RULE_COLUMNS,
  policyLoadErrorText,
  readClassificationPolicy,
} from "../../src/admin/components/dataClassification/classificationPolicyModel.ts";
import { cellDisplay, cellOptions, cellValue, matrixRows, setCell as setMatrixCell } from "../../src/admin/components/dataClassification/classificationMatrixRows.ts";
import { draftBarText, readVersions, versionErrorText } from "../../src/admin/components/dataClassification/classificationVersionsModel.ts";
import { budgetLines, readWorkspacePolicy, ruleLines, seatText, toolRuleLine } from "../../src/chat/agents/workspacePolicyModel.ts";
import { agentsPolicyHref, readUrlAgentsView } from "../../src/chat/agents/agentsFocus.ts";
import { effectLines, readWorkspaceClassification } from "../../src/admin/components/dataClassification/dataClassificationModel.ts";
import { seatClassificationRefusal, seatReasonText, seatSwitchDisabled } from "../../src/admin/components/dataClassification/dataClassificationSeat.ts";
import { ADMIN_AREA_CONFIGS, resolveAdminAreaForTab } from "../../src/admin/config/adminPanelAreas.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
const json = (value) => JSON.parse(JSON.stringify(value));

// Made-up levels in a made-up order, in the backend's shape (policy_matrix_admin.policy_payload); `x_future` is a rule
// this UI does not know (it must survive a save). `label` and `admitted_model_aliases` are optional extras.
const rules = (overrides = {}) => ({
  seat_allowed: true, requires_governed_routing: false, allowed_model_aliases: null, reranker_allowed: true,
  remote_embeddings_allowed: true, log_masking_required: false, transcript_retention_days: null,
  connectors: { servicenow: "read_write", jira: "read_write", kubernetes: "read_write" }, x_future: 7, ...overrides,
});
const POLICY = (overrides = {}) => ({
  levels: [
    { level: "open", label: "Open", rules: rules(), admitted_model_aliases: ["eu-sonnet", "eu-opus", "local-llm"] },
    { level: "team", label: "Team", rank: 1, rules: rules({ connectors: { kubernetes: "read_write", jira: "read_write", servicenow: "read_write" } }),
      admitted_model_aliases: ["eu-sonnet", "eu-opus"] },
    { level: "vault", label: "Vault", rank: 2, rules: rules({ seat_allowed: false, allowed_model_aliases: ["eu-opus"] }) },
  ],
  state: "configured", rule_keys: ["seat_allowed"], connector_families: ["servicenow", "jira", "kubernetes"],
  connector_access_values: ["none", "read", "read_write"], can_edit: true,
  defaults: { open: rules(), team: rules(), vault: rules({ seat_allowed: false }) },
  updated_at: "2026-10-06T10:00:00Z", updated_by: "alex@example.test",
  ...overrides,
});

// ---- registration -------------------------------------------------------------------------------

test("the matrix left the navigation for a hidden page of Admin › Rules (E6); Policy stays an Agents → Governance view", () => {
  // Rules is one entry; the classification matrix and today's rule pages are hidden pages under it,
  // reached as views (segments), not menu items. Approval rule stays admin-only.
  const governance = { tabs: ADMIN_AREA_CONFIGS.admin.groups.flatMap((group) => group.tabs)
    .filter((tab) => tab.id === "cedarPolicies" || tab.parent === "cedarPolicies") };
  // Rules opens on Policies; the not yet served rule list (adminRules) is no page.
  assert.deepEqual(governance.tabs.map((tab) => [tab.id, tab.adminOnly ?? false]),
    [["cedarPolicies", false], ["policyTestBench", false],
      ["approvalRule", true], ["policies", false], ["commandSafety", false], ["contentSecurity", false],
      ["classificationPolicy", false]]);
  // Policy UX: the test bench is a tab of the Policies page (a hidden route); decisions live in Observability.
  assert.ok(governance.tabs.filter((tab) => tab.id !== "cedarPolicies").every((tab) => tab.hidden && tab.parent === "cedarPolicies"));
  assert.equal(resolveAdminAreaForTab("classificationPolicy"), "admin");
  assert.equal(governance.tabs.some((tab) => tab.id === "dataClassification"), false, "one home only");
  const { AGENTS_NAV_ITEMS } = load("chat/agents/AgentsAreaNav.tsx");
  assert.deepEqual(json(AGENTS_NAV_ITEMS.filter((item) => item.section === "Governance").map((item) => [item.key, item.label])),
    [["classification", "Seats & data classification"], ["policy", "Policy"]]);
  const tabs = fs.readFileSync(path.join(SRC, "admin/config/areaPagesAdminTabs.tsx"), "utf8");
  assert.match(tabs, /id: "classificationPolicy",\s+label: "Classification",\s+icon:/, "the sidebar has its icon");
  const content = fs.readFileSync(path.join(SRC, "admin/components/AdminPanelContent.tsx"), "utf8");
  assert.match(content, /case "classificationPolicy":\s+return renderLazyTab\(<AdminClassificationPolicy isAdmin=\{isAdmin\} \/>\);/);
});

test("no level name of the platform is written into the matrix or the policy view", () => {
  for (const file of [
    "admin/components/dataClassification/classificationPolicyModel.ts",
    "admin/components/dataClassification/AdminClassificationPolicy.tsx",
    "admin/components/dataClassification/useClassificationPolicyState.ts",
    "admin/components/dataClassification/ClassificationPolicyDrawers.tsx",
    "admin/components/dataClassification/useClassificationPolicyLoad.ts",
    "admin/components/dataClassification/classificationMatrixRows.ts",
    "admin/components/dataClassification/classificationVersionsModel.ts",
    "admin/components/dataClassification/classificationLevelCatalog.ts",
    "admin/components/dataClassification/classificationEffectsModel.ts",
    "admin/components/dataClassification/classificationOverridesModel.ts",
    "admin/components/dataClassification/ClassificationMatrix.tsx",
    "admin/components/dataClassification/ClassificationCellDrawer.tsx",
    "chat/agents/workspacePolicyModel.ts",
    "chat/agents/AgentsWorkspacePolicy.tsx",
  ]) {
    const source = fs.readFileSync(path.join(SRC, file), "utf8");
    for (const level of ["public", "internal", "confidential", "restricted", "secret"]) {
      assert.doesNotMatch(source, new RegExp(`["'\`]${level}["'\`]`), `${file} names ${level}`);
    }
  }
});

// ---- matrix model -------------------------------------------------------------------------------

test("the matrix keeps the server's level order; the server's can_edit wins over the caller's role", () => {
  const policy = readClassificationPolicy(POLICY({ levels: [...POLICY().levels, { level: "open" }, { value: "spare" }, "junk"] }), true);
  assert.deepEqual(policy.levels.map((level) => [level.level, level.label]), [["open", "Open"], ["team", "Team"], ["vault", "Vault"]]);
  assert.equal(readClassificationPolicy(POLICY({ can_edit: undefined }), true).canEdit, true, "an admin edits when the server does not say");
  assert.equal(readClassificationPolicy(POLICY({ can_edit: undefined }), false).canEdit, false);
  assert.equal(readClassificationPolicy(POLICY({ can_edit: false }), true).canEdit, false, "the server's no wins");
  assert.equal(readClassificationPolicy(POLICY({ can_edit: true }), false).canEdit, true);
  assert.equal(readClassificationPolicy({ levels: [] }, true), null);
  assert.equal(readClassificationPolicy(null, true), null);
  assert.equal(policy.levels[2].admittedAliases, null, "not stated");
  assert.equal(policy.state, "configured");
  assert.equal(readClassificationPolicy(POLICY({ state: "odd" }), true).state, null);
  assert.equal(readClassificationPolicy({ levels: [{ level: "x", rank: 0, rules: {} }] }, true).levels[0].label, "x", "no label: the level itself");
  assert.deepEqual(policy.levels[0].admittedAliases, ["eu-sonnet", "eu-opus", "local-llm"]);
  // Defaults as a list of rows read the same as a map.
  const listed = readClassificationPolicy(POLICY({ defaults: [{ level: "vault", rules: rules({ seat_allowed: false }) }] }), true);
  assert.deepEqual(Object.keys(listed.defaults), ["vault"]);
});

test("the unreadable-matrix text says it fails closed; every rule column explains itself", () => {
  assert.match(INVALID_STATE_TEXT, /fail closed/);
  assert.ok(RULE_COLUMNS.every((column) => column.help.length > 40), "every column explains itself");
  assert.equal(policyLoadErrorText({ status: 404 }), "This server does not offer the classification policy yet.");
});

// ---- governed matrix ---------------------------------------------------------

test("matrix rows: families from the server, the model row derived, retention not enforced, cells as phrases", () => {
  const rows = matrixRows(["servicenow", "jira"]);
  assert.deepEqual(rows.map((row) => row.key), ["models", "gateway", "seat", "device", "reranker", "embeddings",
    "connector:servicenow", "connector:jira", "logs", "retention"]);
  const byKey = Object.fromEntries(rows.map((row) => [row.key, row]));
  assert.equal(byKey.models.derived, true);
  assert.equal(byKey.retention.notEnforced, true);
  assert.deepEqual(cellDisplay(byKey.models, null), { text: "All cleared", tone: "yes" });
  assert.deepEqual(cellDisplay(byKey.models, ["a", "b"]), { text: "2 models", tone: "part" });
  assert.deepEqual(cellDisplay(byKey.seat, false), { text: "Off", tone: "no" });
  assert.deepEqual(cellDisplay(byKey["connector:jira"], "read"), { text: "Read only", tone: "part" });
  assert.deepEqual(cellDisplay(byKey.retention, 180), { text: "180 days", tone: "" }, "not enforced: no colour");
  assert.equal(cellValue(byKey["connector:jira"], rules({ connectors: { jira: "none" } })), "none");
  assert.equal(cellOptions(byKey.retention, 45).at(-1).text, "45 days", "a stored custom value stays selectable");
  const levels = [{ level: "open", rules: rules() }, { level: "team", rules: rules() }];
  const next = setMatrixCell(levels, "team", byKey["connector:jira"], "read");
  assert.equal(next[1].rules.connectors.jira, "read");
  assert.equal(next[1].rules.connectors.servicenow, "read_write", "the other families stay");
  assert.equal(next[0], levels[0], "other levels untouched");
});

test("versions in words: the draft bar says what is open and what it needs", () => {
  assert.equal(draftBarText(readVersions({ published_version: 3, draft: null, versions: [] })), "No changes against published version 3");
  assert.equal(draftBarText(readVersions({ published_version: null, draft: null, versions: [] })), "No changes against the live policy");
  const draft = { version: 4, state: "draft", changes: [{ level: "team", rule: "seat_allowed", text: "x" }], levels: [],
    test_report: { total: 6, failed: 0, ok: true }, policy_diff: { added: ["p"], removed: [] }, affected_workspaces: 2 };
  assert.equal(draftBarText(readVersions({ published_version: 3, draft, versions: [] })),
    "1 change against published version 3 · 6/6 test cases pass · needs a second admin");
  assert.match(draftBarText(readVersions({ published_version: 3, draft, versions: [], self_approval: true })), /publish it yourself/);
  const review = { ...draft, state: "in_review", review: { status: "pending", can_approve: false } };
  assert.equal(draftBarText(readVersions({ draft: review, versions: [] })), "Submitted for review · waiting for a second admin");
  assert.equal(versionErrorText({ status: 409, code: "classification_draft_tests_failed" }),
    "Not done: a saved policy test case fails with this draft.");
});

// ---- rendered -----------------------------------------------------------------------------------

function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl, JSON,
      encodeURIComponent, FormData, setInterval, clearInterval, setTimeout, CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
      ...extra,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return loadFile(path.join(SRC, relative));
}

const windowStub = (search = "") => ({
  location: { origin: "http://localhost", search, href: `http://localhost/chat${search}` },
  localStorage: { getItem: () => null, setItem: () => {} },
  history: { state: null, replaceState: () => {} },
  addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => {}, setTimeout: () => 0,
});
const documentStub = () => ({ visibilityState: "visible", addEventListener: () => {}, removeEventListener: () => {} });

function server(answer) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const call = { url: String(url), method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null };
    calls.push(call);
    const { status, body } = answer(call);
    return { ok: status < 400, status, statusText: "", json: async () => body };
  };
  return { fetch, calls };
}
const tick = (ms = 0) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });
const click = (view, id) => act(async () => { byTestId(view, id)[0].props.onClick(); });
const change = (view, id, value) => act(async () => { byTestId(view, id)[0].props.onChange({ target: { value, checked: value } }); });

// The governed classification API, like the server: a draft follows the PUTs; submit/approve move it.
function versionsServer({ initial = POLICY(), reviewer = false, selfApproval = false } = {}) {
  const policy = json(initial);
  let versions = { published_version: 2, draft: null, versions: [], approval_rule: "four_eyes", self_approval: selfApproval,
    effect_catalog: [
      { key: "web_search", label: "Web search", description: "Agents may search the public web.", param: "none", enforced: true, enforced_at: "Web search" },
      { key: "mcp_server", label: "MCP server access", description: "Per server.", param: "server", enforced: true, enforced_at: "MCP" },
      { key: "export", label: "Export & download", description: "Needs an enforcement point first (planned).", param: "none", enforced: false },
    ],
    effect_rules: [], mcp_servers: ["docs-search"] };
  return server((call) => {
    if (call.url.endsWith("/policy-engine/status")) return { status: 200, body: { mode: "shadow" } };
    if (call.url.includes("/data-classification/default")) {
      return { status: 200, body: { classification: "team", levels: ["open", "team", "vault"], unclassified_count: 1, source: "admin" } };
    }
    if (call.url.includes("/policy/generated")) {
      return { status: 200, body: { policies: [{ id: "classification:team:seat-not-allowed", text: "forbid (principal, action, resource);" }] } };
    }
    if (call.url.includes("/policy/workspaces")) return { status: 200, body: { workspaces: [] } };
    if (call.url.endsWith("/policy/draft") && call.method === "PUT") {
      versions = { ...versions, draft: { version: 3, state: "draft", levels: call.body.levels, default_level: call.body.default_level,
        effect_rules: call.body.effect_rules ?? [],
        changes: [{ level: "team", rule: "seat_allowed", text: "team · Claude Code seat: allowed → off" }],
        policy_diff: { added: ["classification:team:seat-not-allowed"], removed: [] }, affected_workspaces: 1 } };
      return { status: 200, body: versions };
    }
    if (call.url.endsWith("/policy/draft/submit")) {
      versions = { ...versions, draft: { ...versions.draft, state: "in_review", test_report: { total: 1, failed: 0, ok: true },
        review: { status: "pending", can_approve: reviewer || selfApproval } } };
      return { status: 200, body: versions };
    }
    if (call.url.endsWith("/approve")) {
      versions = { ...versions, published_version: 3, draft: null };
      return { status: 200, body: versions };
    }
    if (call.url.endsWith("/policy/versions")) return { status: 200, body: versions };
    return { status: 200, body: policy };
  });
}

async function renderMatrix(srv, isAdmin = true) {
  const { AdminClassificationPolicy } = load("admin/components/dataClassification/AdminClassificationPolicy.tsx", { fetch: srv.fetch, window: windowStub(),
    document: { activeElement: null, addEventListener: () => {}, removeEventListener: () => {} } });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AdminClassificationPolicy, { isAdmin })); });
  await tick();
  return view;
}

test("rendered Classification (admin): a cell change goes into the draft; submit opens the review; the author cannot approve", async () => {
  const srv = versionsServer();
  const view = await renderMatrix(srv);
  try {
    assert.equal(text(byTestId(view, "classification-draft-text")[0]), "No changes against published version 2");
    assert.equal(byTestId(view, "classification-default-level")[0].props.value, "team");
    assert.match(text(byTestId(view, "matrix-row-models")[0]), /From Model catalog/);
    assert.match(text(byTestId(view, "matrix-row-retention")[0]), /Not enforced yet/);
    assert.equal(text(byTestId(view, "matrix-cell-seat-team")[0]), "Allowed");
    await click(view, "matrix-cell-seat-team");
    await tick();
    assert.match(text(byTestId(view, "cell-policy")[0]), /forbid/);
    await change(view, "cell-value", "1");
    await click(view, "cell-save");
    await tick();
    const put = srv.calls.find((call) => call.method === "PUT");
    assert.ok(put.url.endsWith("/api/v1/admin/data-classification/policy/draft"));
    assert.equal(put.body.levels.find((level) => level.level === "team").rules.seat_allowed, false);
    assert.equal(put.body.default_level, "team");
    assert.match(text(byTestId(view, "classification-draft-text")[0]), /^1 change against published version 2/);
    assert.equal(text(byTestId(view, "matrix-cell-seat-team")[0]), "Off");
    await click(view, "classification-submit");
    await tick();
    assert.equal(text(byTestId(view, "classification-draft-text")[0]), "Submitted for review · waiting for a second admin");
    assert.equal(byTestId(view, "classification-approve").length, 0, "four-eyes: not the author");
    assert.equal(byTestId(view, "classification-withdraw").length, 1);
  } finally { act(() => view.unmount()); }
});

test("rendered Classification: a reviewer (or single admin) approves and publishes", async () => {
  const srv = versionsServer({ selfApproval: true });
  const view = await renderMatrix(srv);
  try {
    await click(view, "matrix-cell-seat-team");
    await tick();
    await change(view, "cell-value", "1");
    await click(view, "cell-save");
    await tick();
    await click(view, "classification-submit");
    await tick();
    await click(view, "classification-approve");
    await tick();
    assert.ok(srv.calls.some((call) => call.method === "POST" && call.url.endsWith("/policy/versions/3/approve")));
    assert.equal(text(byTestId(view, "classification-draft-text")[0]), "No changes against published version 3");
  } finally { act(() => view.unmount()); }
});

test("rendered Classification (not an admin): the published matrix read-only, no draft, nothing can be sent", async () => {
  const srv = versionsServer({ initial: POLICY({ can_edit: false }) });
  const view = await renderMatrix(srv, false);
  try {
    assert.equal(byTestId(view, "classification-draftbar").length, 0);
    assert.equal(byTestId(view, "classification-header").length, 0);
    assert.ok(byTestId(view, "policy-readonly").length);
    await click(view, "matrix-cell-seat-team");
    await tick();
    assert.equal(byTestId(view, "cell-save").length, 0);
    assert.ok(srv.calls.every((call) => call.method === "GET"));
    assert.ok(!srv.calls.some((call) => call.url.includes("/policy/versions")), "versions are for admins only");
  } finally { act(() => view.unmount()); }
  const missing = await renderMatrix(server(() => ({ status: 404, body: { detail: "Not Found" } })));
  try {
    assert.equal(text(byTestId(missing, "policy-error")[0]), "This server does not offer the classification policy yet.");
  } finally { act(() => missing.unmount()); }
});

// ---- Workspace policy view ----------------------------------------------------------------------

// The backend's shape (workspace_policy_summary.py): what a rule applies to sits in `target`.
const SUMMARY = {
  project_id: "ws-1",
  classification: { effective: "team", source: "workspace" },
  matrix_state: "configured",
  rules: rules({ seat_allowed: true, log_masking_required: true, transcript_retention_days: 1 }),
  seat: { seat_mode: "allowed", in_effect: false, reason: "seat_classification_too_sensitive" },
  agent_gateway_policy: {
    state: "ok", reason: null, source: "workspace",
    tool_rules: [
      { id: "kubectl-requires-context", kind: "command_requires_argument", target: { command: ["kubectl"], argument: "--context" } },
      { id: "no-kubectl-delete", kind: "command_prefix_denied", target: { command: ["kubectl", "delete"] } },
      { id: "no-force-push", kind: "command_argument_denied", target: { command: ["git", "push"], argument: "--force" } },
      { id: "no-env-files", kind: "path_denied", target: { tools: ["Read", "Edit"], glob: "**/.env" } },
      { id: "later", kind: "network_denied", target: { host: "example.test" } },
    ],
    client_permissions: { deny: ["Bash(git push origin main:*)"], ask: ["Bash(terraform apply:*)"] },
  },
  models: { allowed_aliases: ["eu-sonnet", "eu-opus"], denied: [{ alias: "local-llm", reason: "model_alias_not_allowed_for_classification" },
    { alias: "us-model", reason: "model_alias_new_reason" }] },
  budgets: {
    per_user_daily_usd: { value_usd: 50, source: "workspace" },
    session_cost_limit_usd: { value_usd: 100, source: "global" },
    request_cost_limit_usd: { value_usd: 10, source: "default" },
  },
  connectors: { kubernetes: "none", jira: "read" },
};

test("the Workspace policy in words: tool rules readable, every fact stated by the server, nothing guessed", () => {
  const policy = readWorkspacePolicy(SUMMARY);
  assert.equal(policy.classification, "team");
  assert.equal(policy.classificationSource, "workspace");
  assert.deepEqual(policy.rules.map((line) => [line.label, line.allowed, line.value]), [
    ["Seat sessions", true, "allowed"],
    ["Governed routing only", null, "not required"],
    ["Company models", null, "All admitted"],
    ["Reranker", true, "allowed"],
    ["Remote embeddings", true, "allowed"],
    ["Log masking", null, "required"],
    ["Transcript retention", null, "1 day"],
  ]);
  assert.deepEqual(policy.toolRules.map((line) => `${line.subject} ${line.text}`), [
    "kubectl only with --context",
    "kubectl delete blocked",
    "git push --force blocked",
    ".env files blocked for Read, Edit",
    "later rule (network_denied)",
  ]);
  // The stored policy's own shape (fields on the rule) reads the same.
  assert.equal(toolRuleLine({ id: "p", kind: "command_prefix_denied", prefix: ["git", "push", "origin", "main"] }, 0).subject, "git push origin main");
  assert.deepEqual(json(policy.gateway), { ok: true, reason: null, source: "workspace" });
  assert.deepEqual(json(policy.deniedModels), [{ alias: "local-llm", reason: "not in the classification policy's list for this level" },
    { alias: "us-model", reason: "model_alias_new_reason" }], "an unknown reason is named as sent");
  assert.deepEqual(budgetLines({ session_cost_limit_usd: { value_usd: 0, source: "global" } }).map((line) => line.value), ["off"], "0 is off");
  assert.equal(policy.matrixInvalid, false);
  assert.equal(readWorkspacePolicy({ ...SUMMARY, matrix_state: "invalid" }).matrixInvalid, true);
  assert.deepEqual(json(readWorkspacePolicy({ agent_gateway_policy: { state: "needs_configuration", reason: "policy_invalid", source: "workspace",
    tool_rules: [], client_permissions: { deny: [], ask: [] } } }).gateway), { ok: false, reason: "policy_invalid", source: "workspace" });
  assert.deepEqual(policy.clientPermissions.map((line) => `${line.subject} ${line.text}`),
    ["Bash(git push origin main:*) denied in the agent client", "Bash(terraform apply:*) asks first in the agent client"]);
  assert.deepEqual(policy.models, ["eu-sonnet", "eu-opus"]);
  assert.deepEqual(policy.budgets.map((line) => `${line.label}: ${line.value} (${line.source})`), [
    "Per user and day: $50 (set for this Workspace)",
    "Per session: $100 (instance-wide setting)",
    "Per request: $10 (built-in default)",
  ]);
  assert.deepEqual(policy.connectors.map((line) => `${line.label}: ${line.mode}`), ["Kubernetes: none", "Jira: read only"]);
  assert.equal(seatText(policy.seat), "The Workspace allows seat sessions; seat sessions are refused here: the data classification is too sensitive for them.");
  assert.equal(seatText({ mode: "forbidden", inEffect: false, reason: "seat_mode_forbidden" }),
    "The Workspace does not allow seat sessions; seat sessions are refused here: this Workspace does not allow them.");
  assert.equal(seatText({ mode: "allowed", inEffect: true, reason: null }), "The Workspace allows seat sessions; seat sessions can run here.");
  assert.equal(seatText(null), "The server did not state the seat state.");
  // An unset switch (seat_mode_set false) is the default: open at public/internal, closed above; a stored one wins.
  const unsetOpen = readWorkspacePolicy({ seat: { seat_mode: "forbidden", seat_mode_set: false, in_effect: true, reason: null } });
  assert.equal(unsetOpen.seat.set, false);
  assert.equal(seatText(unsetOpen.seat), "The Workspace allows seat sessions by default (public/internal data); seat sessions can run here.");
  assert.match(seatText({ mode: "forbidden", set: false, inEffect: false, reason: "seat_mode_forbidden" }),
    /^The Workspace does not allow seat sessions by default \(confidential data or above\); seat sessions are refused here/);  // Unstated parts stay unstated.
  const bare = readWorkspacePolicy({});
  assert.deepEqual([bare.toolRules, bare.models, bare.budgets, bare.connectors, bare.seat, bare.rules], [null, null, null, null, null, []]);
  assert.equal(readWorkspacePolicy("nope"), null);
  assert.deepEqual(budgetLines([{ key: "session_cost_limit_usd", value_usd: null, source: "default" }, { key: "x", value_usd: "a" }])
    .map((line) => [line.label, line.value]), [["Per session", "no limit"]]);
  assert.equal(toolRuleLine("junk", 0), null);
  assert.equal(toolRuleLine({ kind: "path_denied", glob: "~/.aws/**" }, 2).id, "rule-3");
  assert.deepEqual(ruleLines({ seat_allowed: "yes" }), [], "a non-boolean switch is not shown as ✓ or ✗");
});

test("the Policy view is reachable by address; links from outside the Agents area use it", () => {
  assert.equal(readUrlAgentsView("?area=agents&agents_view=policy"), "policy");
  assert.equal(readUrlAgentsView("?agents_view=classification"), "classification");
  assert.equal(readUrlAgentsView("?agents_view=install"), "install", "every Agents page has an address (help links)");
  assert.equal(readUrlAgentsView("?agents_view=nope"), null);
  assert.equal(agentsPolicyHref("ws 1"), "/chat?area=agents&workspace_id=ws+1&agents_view=policy");
});

async function renderArea({ isPlatformAdmin, summary = SUMMARY, search = "" }) {
  const opened = [];
  const srv = server((call) => {
    if (call.url.endsWith("/policy-summary")) return summary;
    if (call.url.endsWith("/agent-gateway/seat-mode")) return { status: 200, body: { seat_mode: "allowed" } };
    if (call.url.endsWith("/data-classification")) {
      return { status: 200, body: { effective: "team", source: "workspace", levels: [{ value: "team", label: "Team" }], can_edit: false } };
    }
    return { status: 200, body: { items: [] } };
  });
  const { AgentsAreaWorkspace } = load("chat/agents/AgentsAreaWorkspace.tsx", { fetch: srv.fetch, window: windowStub(search), document: documentStub() });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsAreaWorkspace, {
    projects: [{ id: "ws-1", name: "Acme Orders" }], fallbackWorkspaceId: "ws-1", isPlatformAdmin, pollMs: 10_000,
    onOpenAdminTab: (tab) => opened.push(tab) })); });
  await tick();
  return { view, srv, opened };
}

test("rendered Policy view (admin): everything shown read-only; links open the matrix and Limits & budgets", async () => {
  // The Policy view left the Agents menu (Admin › Rules links it); its address still opens it.
  const { view, srv, opened } = await renderArea({ isPlatformAdmin: true, summary: { status: 200, body: { ...SUMMARY, can_edit: true } }, search: "?agents_view=policy" });
  try {
    await tick();
    assert.ok(srv.calls.some((call) => call.url.endsWith("/api/v1/workspaces/ws-1/policy-summary")));
    assert.match(text(byTestId(view, "workspace-policy-classification")[0]), /^Classification: teamSource: set for this Workspace/);
    assert.match(text(byTestId(view, "workspace-policy-rules")[0]), /^✓Seat sessions: allowed·Governed routing only: not required/);
    assert.equal(text(byTestId(view, "workspace-policy-models")[0]), "eu-sonnet, eu-opus");
    assert.equal(byTestId(view, "workspace-policy-tool-rules")[0].findAllByType("li").length, 5);
    assert.equal(text(byTestId(view, "workspace-policy-tool-rules")[0].findAllByType("li")[1]), "kubectl delete blocked");
    assert.equal(text(byTestId(view, "workspace-policy-connectors")[0]), "Kubernetes: noneJira: read only");
    assert.equal(view.root.findAll((node) => ["input", "select", "textarea"].includes(node.type)).filter((node) => !node.props.disabled
      && node.props["data-testid"] !== undefined).length, 0, "nothing to edit");
    await click(view, "workspace-policy-open-limits");
    await click(view, "workspace-policy-open-matrix");
    assert.deepEqual(opened, ["runtimeLimits", "classificationPolicy"]);
    assert.equal(srv.calls.filter((call) => call.method !== "GET").length, 0);
  } finally { act(() => view.unmount()); }
});

test("rendered Policy view (member): no admin links; a non-member's 404 is explained; opened by address", async () => {
  const { view, opened } = await renderArea({ isPlatformAdmin: false, summary: { status: 200, body: { ...SUMMARY, can_edit: true } }, search: "?area=agents&agents_view=policy" });
  try {
    assert.equal(byTestId(view, "workspace-policy").length, 1, "the address opened the view");
    assert.equal(byTestId(view, "workspace-policy-open-matrix").length + byTestId(view, "workspace-policy-open-limits").length, 0);
    assert.equal(opened.length, 0);
  } finally { act(() => view.unmount()); }
  // The server's can_edit is the matrix's rule (platform admin); without it no admin link shows, whatever the caller's role.
  const { view: denied } = await renderArea({ isPlatformAdmin: true, summary: { status: 200, body: { ...SUMMARY, can_edit: false } }, search: "?agents_view=policy" });
  try {
    assert.equal(byTestId(denied, "workspace-policy").length, 1);
    assert.equal(byTestId(denied, "workspace-policy-open-matrix").length + byTestId(denied, "workspace-policy-open-limits").length, 0);
  } finally { act(() => denied.unmount()); }
  const { view: refused } = await renderArea({ isPlatformAdmin: false, summary: { status: 404, body: { detail: "Not Found" } }, search: "?agents_view=policy" });
  try {
    assert.equal(text(byTestId(refused, "workspace-policy-error")[0]),
      "No policy is shown: this server does not offer it yet, or you are not a member of this Workspace.");
  } finally { act(() => refused.unmount()); }
});

test("rendered Data classification card: links to the Policy view for everyone, to the matrix for admins only", async () => {
  const { view, opened } = await renderArea({ isPlatformAdmin: true, summary: { status: 200, body: SUMMARY }, search: "?agents_view=classification" });
  try {
    const links = () => byTestId(view, "classification-links")[0].findAllByType("button");
    assert.deepEqual(links().map(text), ["See this Workspace's policy", "What each level allows (classification policy)"]);
    await act(async () => { links()[1].props.onClick(); });
    assert.deepEqual(opened, ["classificationPolicy"]);
    await act(async () => { links()[0].props.onClick(); });
    await tick();
    assert.equal(byTestId(view, "workspace-policy").length, 1);
  } finally { act(() => view.unmount()); }
  const { view: member } = await renderArea({ isPlatformAdmin: false, summary: { status: 200, body: SUMMARY }, search: "?agents_view=classification" });
  try {
    assert.deepEqual(byTestId(member, "classification-links")[0].findAllByType("button").map(text), ["See this Workspace's policy"]);
  } finally { act(() => member.unmount()); }
  // Outside the Agents area (Workspace settings) the Policy link is an address.
  const card = load("admin/components/dataClassification/WorkspaceDataClassificationCard.tsx", {
    fetch: server((call) => (call.url.endsWith("/seat-mode") ? { status: 200, body: { seat_mode: "forbidden" } }
      : { status: 200, body: { effective: "team", source: "workspace", levels: [{ value: "team" }], can_edit: true } })).fetch, window: windowStub() });
  let settings;
  await act(async () => { settings = TestRenderer.create(createElement(card.WorkspaceDataClassificationCard, { projectId: "ws-1", policyHref: agentsPolicyHref("ws-1") })); });
  await tick();
  try {
    const anchor = byTestId(settings, "classification-links")[0].findByType("a");
    assert.deepEqual([anchor.props.href, text(anchor)], ["/chat?area=agents&workspace_id=ws-1&agents_view=policy", "See this Workspace's policy"]);
  } finally { act(() => settings.unmount()); }
  const source = fs.readFileSync(path.join(SRC, "admin/components/projectsTab/ProjectSettingsSectionContent.tsx"), "utf8");
  assert.match(source, /<WorkspaceDataClassificationCard projectId=\{project\.id\} policyHref=\{agentsPolicyHref\(project\.id\)\}\s+onOpenMatrix=\{\(\) => openAdminTab\("classificationPolicy"\)\} \/>/);
});

test("the classification policy's governed-routing seat refusal is the classification's doing", () => {
  const reason = "seat_classification_requires_governed_routing";
  assert.equal(seatReasonText(reason), "the classification policy requires governed routing for this level");
  const model = readWorkspaceClassification({ effective: "team", source: "workspace", levels: [{ value: "team" }], can_edit: true,
    effects: { seat_mode_allowed: false, reasons: { seat_mode_allowed: reason } } });
  assert.equal(seatClassificationRefusal(model), reason, "the Agents area links to the card");
  assert.equal(seatSwitchDisabled(model, "forbidden"), true, "the switch cannot be turned on");
  // The matrix's own reranker / remote embeddings refusals read as the policy's, not as a data-policy class.
  const forbidden = readWorkspaceClassification({ effective: "team", source: "workspace", levels: [{ value: "team" }],
    effects: { reranker_allowed: false, reranker_state: "denied", remote_embeddings_allowed: false,
      reasons: { reranker_allowed: "classification_policy_reranker_forbidden", remote_embeddings_allowed: "classification_policy_remote_embeddings_forbidden" } } });
  assert.deepEqual(effectLines(forbidden.effects).map((line) => line.detail),
    ["the classification policy forbids it for this level", "the classification policy forbids it for this level"]);
});

test("rendered Policy view: denied models, an invalid gateway policy, an unreadable matrix, an unclassified Workspace", async () => {
  const body = { ...SUMMARY, matrix_state: "invalid",
    agent_gateway_policy: { state: "needs_configuration", reason: "policy_invalid", source: "workspace", tool_rules: [], client_permissions: { deny: [], ask: [] } } };
  const { view } = await renderArea({ isPlatformAdmin: false, summary: { status: 200, body }, search: "?agents_view=policy" });
  try {
    assert.equal(text(byTestId(view, "workspace-policy-denied-models")[0]),
      "✗local-llm not allowed here (not in the classification policy's list for this level)✗us-model not allowed here (model_alias_new_reason)");
    assert.match(text(byTestId(view, "workspace-policy-gateway-invalid")[0]), /needs configuration \(policy_invalid\), so no tool rule can be shown\.$/);
    assert.match(text(byTestId(view, "workspace-policy-matrix-invalid")[0]), /locked down until a platform admin fixes it/);
    assert.match(text(view.root.find((node) => node.props["aria-label"] === "Models and budgets")),
      /Per user and day: \$50 \(set for this Workspace\)Per session: \$100 \(instance-wide setting\)Per request: \$10 \(built-in default\)$/);
  } finally { act(() => view.unmount()); }
  const unclassified = { ...SUMMARY, classification: { effective: null, source: "unset" }, rules: null, connectors: null };
  const { view: bare } = await renderArea({ isPlatformAdmin: false, summary: { status: 200, body: unclassified }, search: "?agents_view=policy" });
  try {
    assert.match(text(byTestId(bare, "workspace-policy-unclassified")[0]), /^No classification is set, so no level's rules apply/);
    assert.match(text(byTestId(bare, "workspace-policy-classification")[0]), /^Classification: not setSource: not set/);
    assert.equal(byTestId(bare, "workspace-policy-rules").length, 0);
    assert.equal(text(bare.root.find((node) => node.props["aria-label"] === "Connectors")), "ConnectorsThe server did not state the connectors.");
  } finally { act(() => bare.unmount()); }
});


// ---- levels as data -----------------------------------------------------------------------------

test("a new level: key from the name, a free rank between its neighbours, checks in words", async () => {
  const { levelKeyFrom, positionOptions, rankAfter, newLevelChecks, readCatalog, levelInUseText } =
    await import("../../src/admin/components/dataClassification/classificationLevelCatalog.ts");
  const catalog = readCatalog([
    { key: "team", rank: 200, label: "Team" }, { key: "open", rank: 100, label: "Open" }, { key: "vault", rank: 300, label: "Vault" },
  ]);
  assert.deepEqual(catalog.map((level) => level.key), ["open", "team", "vault"], "ordered by rank");
  assert.equal(levelKeyFrom(" Partner shared "), "partner_shared");
  assert.equal(levelKeyFrom("9 lives"), "l_9_lives");
  assert.deepEqual(positionOptions(catalog).map((option) => option.text), ["Between Open and Team", "Between Team and Vault", "After Vault"]);
  assert.equal(rankAfter(catalog, 1), 250);
  assert.equal(rankAfter(catalog, 2), 400);
  assert.equal(rankAfter([{ key: "a", rank: 1 }, { key: "b", rank: 2 }], 0), null);
  const checks = newLevelChecks(catalog, "team", "Team", 1);
  assert.equal(checks.find((check) => check.text.includes("already exists")).state, "bad");
  assert.ok(newLevelChecks(catalog, "partner", "Partner", 1).every((check) => check.state !== "bad"));
  assert.equal(levelInUseText({ code: "classification_level_in_use", references: [{ kind: "workspace", name: "Atlas" }] }),
    "The level is still in use: Workspace Atlas. Move these to another level first.");
  assert.equal(levelInUseText({ code: "other" }), null);
});

test("rendered Classification: Add level copies the next stricter level's rules into the draft with the catalog", async () => {
  const catalogPolicy = POLICY({ levels: POLICY().levels.map((level, index) => ({ ...level, rank: (index + 1) * 100, color: "custom", builtin: true })) });
  const srv = versionsServer({ initial: catalogPolicy });
  const view = await renderMatrix(srv);
  try {
    await click(view, "classification-add-level");
    await tick();
    await change(view, "level-name", "Partner");
    await change(view, "level-position", "1");
    assert.equal(byTestId(view, "level-key")[0].props.value, "partner");
    assert.equal(byTestId(view, "level-copy")[0].props.value, "vault", "next stricter");
    await click(view, "level-save");
    await tick();
    const put = srv.calls.find((call) => call.method === "PUT");
    assert.deepEqual(put.body.level_catalog.map((level) => [level.key, level.rank]),
      [["open", 100], ["team", 200], ["partner", 250], ["vault", 300]]);
    const partner = put.body.levels.find((level) => level.level === "partner");
    assert.equal(partner.rules.seat_allowed, false, "copied from Vault");
    assert.equal("allowed_model_aliases" in partner.rules, false, "the model list is derived, never copied");
  } finally { act(() => view.unmount()); }
});

// ---- added rules and Workspace overrides ---------------------------------------------------------

test("overrides: only stricter values can be picked; equal to the level stores nothing", async () => {
  const { matrixRows } = await import("../../src/admin/components/dataClassification/classificationMatrixRows.ts");
  const { overrideChips, overrideOptions, setOverride } = await import("../../src/admin/components/dataClassification/classificationOverridesModel.ts");
  const { effectApplies, effectPolicyText, effectRuleSentence } = await import("../../src/admin/components/dataClassification/classificationEffectsModel.ts");
  const rows = matrixRows(["jira"]);
  const byKey = Object.fromEntries(rows.map((row) => [row.key, row]));
  assert.deepEqual(overrideOptions(byKey.seat, true).map((option) => [option.text, option.allowed, option.level]),
    [["Allowed", true, true], ["Off", true, false]]);
  assert.deepEqual(overrideOptions(byKey.seat, false).map((option) => option.allowed), [false, true], "Allowed is looser");
  assert.deepEqual(overrideOptions(byKey["connector:jira"], "read").map((option) => option.allowed), [false, true, true]);
  assert.deepEqual(overrideOptions(byKey.retention, 90).map((option) => [option.text, option.allowed]),
    [["Unlimited", false], ["365 days", false], ["180 days", false], ["90 days", true], ["30 days", true]]);
  let overrides = setOverride({}, byKey["connector:jira"], "none", "read");
  overrides = setOverride(overrides, byKey.seat, false, true);
  assert.deepEqual(overrides, { connectors: { jira: "none" }, seat_allowed: false });
  assert.deepEqual(setOverride(overrides, byKey.seat, true, true), { connectors: { jira: "none" } }, "back to the level");
  assert.deepEqual(overrideChips(rows, overrides), ["Claude Code seat: off", "Jira: none"]);
  const catalog = [{ key: "open", rank: 100, label: "Open" }, { key: "team", rank: 200, label: "Team" }];
  const rule = { effect: "web_search", param: "off", from_level: "team" };
  assert.equal(effectApplies(rule, catalog[1], catalog), true);
  assert.equal(effectApplies(rule, catalog[0], catalog), false);
  assert.equal(effectRuleSentence(rule, [{ key: "web_search", label: "Web search" }], (key) => key === "team" ? "Team" : key),
    "In Workspaces at Team or above, Web search is off. Below Team nothing changes.");
  assert.match(effectPolicyText(rule, catalog, "x"), /classification_rank >= 200/);
});

test("rendered Classification: Add rule offers only enforceable effects and sends the rule with the draft", async () => {
  const srv = versionsServer();
  const view = await renderMatrix(srv);
  try {
    await click(view, "classification-add-rule");
    await tick();
    assert.equal(byTestId(view, "rule-effect-export")[0].props.disabled, true);
    await act(async () => { byTestId(view, "rule-effect-mcp_server")[0].props.onChange(); });
    await click(view, "rule-next");
    assert.equal(byTestId(view, "rule-param")[0].props.value, "docs-search");
    await change(view, "rule-from", "team");
    await click(view, "rule-next");
    assert.match(text(byTestId(view, "rule-sentence")[0]), /In Workspaces at Team or above, MCP server access \(docs-search\) is off/);
    await click(view, "rule-next");
    await tick();
    const put = srv.calls.find((call) => call.method === "PUT");
    assert.deepEqual(put.body.effect_rules, [{ effect: "mcp_server", param: "docs-search", from_level: "team" }]);
    assert.equal(text(byTestId(view, "matrix-row-effect:mcp_server:docs-search")[0]).includes("Off"), true);
  } finally { act(() => view.unmount()); }
});
