// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/policyLinks.test.mjs
//
// Cross-links to the Policies page: Agents → Governance → Policy lists the platform
// policies of the Workspace; connector cards and named connections link to the list filtered by connector or
// connection; the filter travels in the URL once; the policy drawer names connections and links back.

import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { POLICY_FILTER_PARAMS, clearPolicyFilter, openPolicies, writePolicyFilter } from "../../src/admin/components/policyEngine/policyLinks.ts";
import { readPolicyReferences } from "../../src/admin/components/policyEngine/usePolicyReferences.ts";
import { readWorkspacePolicy } from "../../src/chat/agents/workspacePolicyModel.ts";
import { STATUS, act, byTestId, load, server, text, tick } from "./policyEngineHarness.mjs";

function fakeWindow(href) {
  const env = { location: { href, search: new URL(href).search }, urls: [],
    history: { replaceState: (_data, _unused, url) => { env.urls.push(url); env.location.href = url; env.location.search = new URL(url).search; } } };
  return env;
}
const seg = (value, emphasis = null) => ({ text: value, emphasis });
const REFERENCES = {
  connectors: { servicenow: { count: 2, policies: [{ id: "a", name: "A" }, { id: "b", name: "B" }] } },
  connector_wide: { servicenow: { count: 1, policies: [{ id: "b", name: "B" }] } },
  connections: { "c-1": { count: 1, policies: [{ id: "a", name: "A" }] } },
};

test("links: the filter is written into the URL, the tab opened, and cleared once read", () => {
  const env = fakeWindow("http://x/chat?area=admin&tab=connectors&policyWorkspace=old");
  const opened = [];
  openPolicies((tab) => opened.push(tab), { connection: "c-1" }, env);
  assert.deepEqual(opened, ["cedarPolicies"]);
  const url = new URL(env.location.href);
  assert.equal(url.searchParams.get(POLICY_FILTER_PARAMS.connection), "c-1");
  assert.equal(url.searchParams.has("policyWorkspace"), false, "a stale filter is replaced");
  assert.equal(url.searchParams.get("area"), "admin", "the navigation params are kept");
  clearPolicyFilter(env);
  assert.equal(new URL(env.location.href).searchParams.has("policyConnection"), false);
  const before = env.urls.length;
  clearPolicyFilter(env);
  assert.equal(env.urls.length, before, "nothing to clear, no history entry rewritten");
  writePolicyFilter({}, null);
  assert.deepEqual(readPolicyReferences(REFERENCES).connections["c-1"], { count: 1, policies: [{ id: "a", name: "A" }] });
  assert.deepEqual(readPolicyReferences(null), { connectors: {}, connectorWide: {}, connections: {} });
});

test("agents model: the Workspace summary's platform policies; absent means not stated", () => {
  const read = readWorkspacePolicy({ classification: { effective: "internal" }, platform_policies: { version: 3, items: [
    { id: "p", name: "P", source: "builder", sentence: [seg("Block", "verb")], conditional: false }, { name: "no id" }] } });
  assert.deepEqual(read.platformPolicies, [{ id: "p", name: "P", source: "builder", sentence: [{ text: "Block", emphasis: "verb" }], conditional: false }]);
  assert.equal(readWorkspacePolicy({ classification: { effective: "internal" } }).platformPolicies, null);
});

const SUMMARY = (canEdit, items) => ({
  project_id: "ws-1", classification: { effective: "confidential", source: "workspace" }, rules: null, can_edit: canEdit,
  platform_policies: { version: 3, items },
});
const PLATFORM = [
  { id: "prod", name: "Prod", source: "builder", conditional: false,
    sentence: [seg("Block", "verb"), seg(" "), seg("everyone", "value"), seg(" from "), seg("changing data", "value"), seg(".")] },
  { id: "hand", name: "Hand", source: "hand_written", conditional: true, sentence: [seg("Block", "verb"), seg(" members of group "), seg("contractors", "value"), seg(".")] },
];

async function renderAgents(canEdit, items, env) {
  const srv = server(() => ({ status: 200, body: SUMMARY(canEdit, items) }));
  const { AgentsWorkspacePolicy } = load("chat/agents/AgentsWorkspacePolicy.tsx", { fetch: srv.fetch, window: env });
  const opened = [];
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsWorkspacePolicy, { projectId: "ws-1", onOpenAdminTab: (tab) => opened.push(tab) })); });
  await tick();
  return { view, opened };
}

test("agents: the platform policies of the Workspace as sentences; admins open the filtered list or the bench", async () => {
  const env = fakeWindow("http://x/chat?area=agents");
  const { view, opened } = await renderAgents(true, PLATFORM, env);
  assert.equal(text(byTestId(view, "workspace-platform-policies-count")[0]), "2 apply");
  const rows = byTestId(view, "workspace-platform-policy").map(text);
  assert.equal(rows[0], "● Block everyone from changing data.");
  assert.equal(rows[1], "● Block members of group contractors. Hand-written");
  await act(async () => { byTestId(view, "workspace-platform-policies-open")[0].props.onClick(); });
  assert.deepEqual(opened, ["cedarPolicies"]);
  assert.equal(new URL(env.location.href).searchParams.get("policyWorkspace"), "ws-1");
  await act(async () => { byTestId(view, "workspace-platform-policies-test")[0].props.onClick(); });
  assert.deepEqual(opened, ["cedarPolicies", "policyTestBench"]);

  const member = await renderAgents(false, [], fakeWindow("http://x/chat?area=agents"));
  assert.equal(text(byTestId(member.view, "workspace-platform-policies-none")[0]), "No platform policy blocks anything here.");
  assert.equal(byTestId(member.view, "workspace-platform-policies-open").length, 0, "members get no admin links");
});

async function renderLoaded(relative, component, props, answer, env) {
  const srv = server(answer);
  const loaded = load(relative, { fetch: srv.fetch, window: env });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(loaded[component], props)); });
  await tick();
  await tick();
  return { view, srv };
}

test("connector card: a policy badge opens the list filtered by the connector; none for non-admins", async () => {
  const ctx = { CONNECTOR_ICONS: {}, connectorHealthStatusClass: () => "", formatConnectorHealthStatus: () => "Healthy", formatRelativeTime: () => "",
    handleDeleteConnector() {}, handleExpandConnector() {} };
  const connector = { tool_name: "servicenow", label: "ServiceNow", tools: [], configured: true };
  const env = fakeWindow("http://x/chat?area=admin&tab=connectors");
  const { view } = await renderLoaded("admin/components/connectorsTab/ConfiguredConnectorHeader.tsx", "ConfiguredConnectorHeader",
    { connector, health: null, iconColor: "#000", isOpen: false, ctx }, () => ({ status: 200, body: REFERENCES }), env);
  const badge = byTestId(view, "connector-policies-badge")[0];
  assert.equal(text(badge), "2 policies");
  let stopped = false;
  await act(async () => { badge.props.onClick({ stopPropagation: () => { stopped = true; } }); });
  assert.equal(stopped, true, "the badge does not toggle the card");
  assert.equal(new URL(env.location.href).searchParams.get("policyConnector"), "servicenow");
  const refused = await renderLoaded("admin/components/connectorsTab/ConfiguredConnectorHeader.tsx", "ConfiguredConnectorHeader",
    { connector, health: null, iconColor: "#000", isOpen: false, ctx }, () => ({ status: 403, body: {} }), fakeWindow("http://x/"));
  assert.equal(byTestId(refused.view, "connector-policies-badge").length, 0);
});

test("named connections: per connection 'Policies affecting this connection', on the default entry the connector-wide ones", async () => {
  const env = fakeWindow("http://x/chat?area=admin");
  const named = await renderLoaded("admin/components/policyEngine/ConnectionPolicies.tsx", "ConnectionPolicies",
    { connector: "servicenow", connectionId: "c-1" }, () => ({ status: 200, body: REFERENCES }), env);
  assert.equal(text(byTestId(named.view, "connection-policies")[0]), "Policies affecting this connection (1)");
  await act(async () => { byTestId(named.view, "connection-policies")[0].props.onClick(); });
  assert.equal(new URL(env.location.href).searchParams.get("policyConnection"), "c-1");
  const wide = await renderLoaded("admin/components/policyEngine/ConnectionPolicies.tsx", "ConnectionPolicies",
    { connector: "servicenow" }, () => ({ status: 200, body: REFERENCES }), env);
  assert.equal(text(byTestId(wide.view, "connection-policies")[0]), "Connector-wide policies (1)");
  const none = await renderLoaded("admin/components/policyEngine/ConnectionPolicies.tsx", "ConnectionPolicies",
    { connector: "jira", connectionId: "c-9" }, () => ({ status: 200, body: REFERENCES }), env);
  assert.equal(text(byTestId(none.view, "connection-policies-none")[0]), "No policies");
  const member = await renderLoaded("admin/components/policyEngine/ConnectionPolicies.tsx", "ConnectionPolicies",
    { connector: "servicenow", connectionId: "c-1" }, () => ({ status: 403, body: {} }), env);
  assert.equal(member.view.toJSON(), null, "nothing for non-admins");
});

test("policies page: a deep-link filter applies once (removed from the URL) and the drawer names connections with a link back", async () => {
  const env = fakeWindow("http://x/chat?area=admin&tab=cedarPolicies&policyConnection=c-1");
  const item = { id: "prod", name: "Prod", source: "builder", editable: true, effect: "forbid", actions: ["write_connector"], groups: ["Connectors & tools"],
    points: [], text: "", digest: "d", sentence: [seg("Block", "verb")], scope: "Connection primary", references: { entities: {}, connections: ["c-1", "gone"] },
    warnings: [], change: "unchanged", last_changed: null, model: null };
  const srv = server((call) => {
    const url = call.url.replace("/api/v1/admin/policy-engine", "");
    if (url === "/status") return { status: 200, body: STATUS() };
    if (url.startsWith("/policies")) return { status: 200, body: { version: { version: 2, state: "published" }, published_version: 2, items: [item], changes: {}, edit_target: { version: 2, digest: "x", creates_draft: true } } };
    if (url === "/policy-sets") return { status: 200, body: { items: [{ version: 2, state: "published" }] } };
    if (/^\/policy-sets\/\d+$/.test(url)) return { status: 200, body: { version: 2, state: "published", policies: "" } };
    if (url === "/catalog/entities") return { status: 200, body: { named_connections: [{ id: "c-1", name: "primary", connector: "servicenow" }] } };
    if (url.startsWith("/decisions")) return { status: 200, body: { items: [], total: 0 } };
    if (/\/policies\//.test(url)) return { status: 200, body: { history: [] } };
    return { status: 404, body: {} };
  });
  const { AdminCedarPolicies } = load("admin/components/policyEngine/AdminCedarPolicies.tsx", { fetch: srv.fetch, window: env });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AdminCedarPolicies, { search: env.location.search })); });
  for (let index = 0; index < 4; index += 1) await tick();
  assert.match(text(byTestId(view, "policy-active-filters")[0]), /Connection: primary/);
  assert.equal(new URL(env.location.href).searchParams.has("policyConnection"), false, "consumed");
  await act(async () => { byTestId(view, "policy-row")[0].props.onClick(); });
  await tick();
  assert.equal(text(byTestId(view, "policy-drawer-connections")[0]), "Connectionsprimary · servicenow, unknown connection gone · Open connectors");
  assert.equal(byTestId(view, "policy-drawer-open-connectors").length, 1);
});
