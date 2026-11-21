// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/namedConnectionsGlobal.test.mjs
//
// Named connections, delivery 2: Automation → Connectors lists the global connections of Confluence, Jira
// and ServiceNow ("Default" plus each named one) with its immutable id (copyable), base URL, sign-in, bound keys,
// secret presence (never a value), last test and who uses it; add/edit/test/delete go to the global API; the delete
// confirmation names every user first. A Workspace shows the global connections read-only with the keys served and
// overridden there. A Knowledge connector can pin a connection by id, and every save (also pause/resume) keeps it.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { D, DESCRIPTORS } from "./namedConnectorDescriptors.mjs";
import { formatDateTime } from "../../src/admin/utils/dateTime.ts";
import { authModeLabel, connectionTarget, deleteConsequence, lastTestText, usageLines } from "../../src/admin/components/namedConnections/namedConnectionsText.ts";
import { namedConnectionsUrl, parseNamedConnections } from "../../src/admin/components/namedConnections/namedConnectionsParse.ts";
import { configOf } from "../../src/admin/components/workspaceKnowledge/connectorConfig.ts";
import { reasonText } from "../../src/admin/components/workspaceKnowledge/connectorReasons.ts";
import { initialForm, resetScope, validate } from "../../src/admin/components/workspaceKnowledge/connectorFormModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const SECRET = "fake-secret-never-shown";

const USAGE = {
  workspaces: [{ id: "ws-1", name: "Acme Orders", scopes: ["TEAM"] }],
  knowledge_connectors: [
    { workspace_id: "ws-1", workspace_name: "Acme Orders", connector_key: "wiki", scopes: ["TEAM"], pinned: true,
      pin_mismatch: false },
  ],
};
const GLOBAL_TEAM = {
  id: "0f3c2a1e-5b7d-4c8e-9a10-1b2c3d4e5f60", name: "client-a", connector_name: "confluence", scope: "global",
  bound_scopes: ["TEAM"],
  fields: { confluence_url: "https://wiki.example.test/wiki", confluence_auth_mode: "oidc_client_credentials" },
  secret_status: { confluence_oidc_client_secret: true },
  last_test: { ok: false, at: "2026-10-06T09:15:00", summary: "Token endpoint refused the client" },
  usage: USAGE,
};
const GLOBAL_LIST = {
  connector_name: "confluence", descriptor: DESCRIPTORS.confluence, scope: "global",
  default: { id: "default", name: "default", configured: true, active: true,
    fields: { confluence_url: "https://default.example.test/wiki", confluence_auth_mode: "basic" },
    secret_status: { confluence_password: true } },
  connections: [GLOBAL_TEAM],
};

test("the global API path, facts in words, last test, usage and the delete consequence", () => {
  assert.equal(namedConnectionsUrl(null, "confluence", "c 1", "/test"),
    "/admin/chat/api/panel/connectors/confluence/named-connections/c%201/test");
  assert.equal(namedConnectionsUrl(null, "jira"), "/admin/chat/api/panel/connectors/jira/named-connections");
  const parsed = parseNamedConnections(GLOBAL_LIST);
  const [connection] = parsed.connections;
  assert.equal(connection.scope, "global");
  assert.deepEqual(connection.lastTest, { ok: false, at: "2026-10-06T09:15:00", summary: "Token endpoint refused the client" });
  assert.equal(parsed.defaultSecretStatus.confluence_password, true);
  assert.deepEqual(parsed.inherited, []);
  assert.equal(connectionTarget(D.confluence, connection.publicFields), "https://wiki.example.test/wiki");
  assert.equal(connectionTarget(D.jira, {}), null);
  assert.equal(authModeLabel(D.confluence, connection.publicFields), "OpenID Connect (client credentials)");
  assert.equal(authModeLabel(D.servicenow, { servicenow_auth_mode: "future_mode" }), "future_mode");
  assert.equal(authModeLabel(D.jira, {}), "Sign-in not set");
  assert.equal(lastTestText(null), "Not tested since the last change");
  // The UI's one date format (browser time), never the raw ISO time.
  assert.equal(lastTestText(connection.lastTest), `Last test failed (${formatDateTime("2026-10-06T09:15:00")}): Token endpoint refused the client`);
  assert.doesNotMatch(lastTestText(connection.lastTest), /UTC|T09/);
  assert.equal(lastTestText({ ok: true, at: null, summary: "" }), "Last test passed");
  assert.deepEqual(usageLines(connection.usage, D.confluence), [
    'Workspace "Acme Orders" (spaces: TEAM)',
    'Knowledge connector "wiki" in "Acme Orders" (spaces: TEAM), pinned',
  ]);
  const mismatch = { ...connection.usage, knowledgeConnectors: [{ ...connection.usage.knowledgeConnectors[0], scopes: [], pinMismatch: true }] };
  assert.match(usageLines(mismatch, D.confluence)[1], /"wiki" in "Acme Orders", pinned — runs refused/);
  const consequence = deleteConsequence(connection, D.confluence);
  assert.match(consequence, new RegExp(`Delete "client-a" \\(${GLOBAL_TEAM.id}\\)`));
  assert.match(consequence, /Used by: Workspace "Acme Orders" \(spaces: TEAM\); Knowledge connector "wiki"/);
  assert.match(consequence, /a Workspace's default connection only where that allows them/);
  assert.match(consequence, /pinned to it are refused until/);
  assert.match(deleteConsequence({ ...connection, usage: null, scope: "workspace" }, D.jira),
    /Nothing uses it right now\. Its projects then use the default connection only if it allows them\.$/);
  // A malformed usage entry is dropped, never shown half.
  const odd = parseNamedConnections({ ...GLOBAL_LIST, connections: [{ ...GLOBAL_TEAM, usage: {
    workspaces: [{ name: "no id" }], knowledge_connectors: [{ connector_key: "x" }] } }] });
  assert.deepEqual(odd.connections[0].usage, { workspaces: [], knowledgeConnectors: [], workIntakes: [] });
});

function load(relative, extraGlobals = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, encodeURIComponent,
      window: { setTimeout: () => 0 }, ...extraGlobals,
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

function server(initial, { testResult = { ok: true, summary: "Connected." }, tested = null } = {}) {
  const calls = [];
  let stored = structuredClone(initial);
  const registryReads = [];
  const readJson = async (url, init = {}) => {
    if (url === "/admin/chat/api/panel/named-connection-descriptors") {
      registryReads.push(url);  // the cards' one registry read, kept apart from the connection calls
      return { connectors: Object.values(DESCRIPTORS) };
    }
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ url, method: init.method || "GET", body });
    if (url.endsWith("/test")) {
      if (tested) stored = tested(stored);
      return testResult;
    }
    if (init.method === "POST") {
      const created = { id: "new-id-1", name: body.name, scope: "global", bound_scopes: body.bound_scopes,
        fields: { confluence_url: body.confluence_url, confluence_auth_mode: body.confluence_auth_mode },
        secret_status: { confluence_token: Boolean(body.confluence_token) }, last_test: null,
        usage: { workspaces: [], knowledge_connectors: [] } };
      stored = { ...stored, connections: [...stored.connections, created] };
      return created;
    }
    if (init.method === "DELETE") {
      stored = { ...stored, connections: stored.connections.filter((item) => !url.endsWith(`/${item.id}`)) };
      return { status: "deleted" };
    }
    return stored;
  };
  return { readJson, calls, registryReads };
}

async function mount(srv, { projectId = null, connector = "confluence", globals = {} } = {}) {
  const { NamedConnections } = load("admin/components/namedConnections/NamedConnections.tsx", globals);
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(NamedConnections, {
      projectId, connector, label: "Confluence", readJson: srv.readJson,
    }));
  });
  const find = (predicate) => view.root.findAll(predicate)[0] ?? null;
  const id = (field) => `connector-field-${connector}-named-${field}`;
  const byTestId = (testId) => view.root.findAll((node) => node.props["data-testid"] === testId);
  return {
    all: () => text(view.root),
    byTestId,
    type: (field, value) => act(() => find((node) => node.type === "input" && node.props.id === id(field)).props.onChange({ target: { value } })),
    radio: (value) => act(() => find((node) => node.type === "input" && node.props.type === "radio" && node.props.value === value).props.onChange()),
    click: async (label, index = 0) => {
      const buttons = view.root.findAll((node) => node.type === "button" && text(node).trim() === label);
      assert.ok(buttons[index], `button "${label}" #${index}`);
      await act(async () => { await buttons[index].props.onClick(); });
    },
    buttons: (within) => within.findAll((node) => node.type === "button").map((node) => text(node).trim()),
  };
}

test("Automation → Connectors: default and each global connection with id, URL, sign-in, keys, secret, last test, users", async () => {
  const srv = server(GLOBAL_LIST);
  const ui = await mount(srv);
  assert.equal(srv.calls[0].url, "/admin/chat/api/panel/connectors/confluence/named-connections");
  const all = ui.all();
  assert.match(all, /Default · the connector settings aboveID default/);
  assert.match(all, /https:\/\/default\.example\.test\/wiki · Username and password · every other space its allowlist allows · Credential stored/);
  assert.match(all, new RegExp(`client-aID ${GLOBAL_TEAM.id}Copy ID`));
  assert.ok(all.includes(`https://wiki.example.test/wiki · OpenID Connect (client credentials) · Spaces: TEAM · Credential stored · Last test failed (${formatDateTime("2026-10-06T09:15:00")}): Token endpoint refused the client`));
  assert.match(all, /Used by: Workspace "Acme Orders" \(spaces: TEAM\); Knowledge connector "wiki" in "Acme Orders" \(spaces: TEAM\), pinned\./);
  assert.match(all, /Global connections apply in every Workspace whose Confluence connector is on/);
  assert.equal(ui.byTestId("named-connections-inherited").length, 0, "the global page has nothing inherited");
  assert.doesNotMatch(all, /secret_ref|oidc_client_credentials|fake-/);
});

test("Automation → Connectors also lists every Workspace's own connections, read-only", async () => {
  const srv = server({ ...GLOBAL_LIST, workspace_connections: [
    { workspace_id: "ws-t", workspace_name: "Test", id: "default", name: "default", active: true, bound_scopes: ["DOCS"],
      fields: { confluence_url: "https://site.example.test/wiki", confluence_auth_mode: "cloud_api_token" } },
    { workspace_id: "ws-t", workspace_name: "Test", id: "conn-7", name: "Docs-site", active: true, bound_scopes: ["OPS"],
      fields: { confluence_url: "https://site.example.test/wiki", confluence_auth_mode: "cloud_api_token" },
      confluence_token_secret_ref: "fake-ref" },
  ] });
  const ui = await mount(srv);
  const rows = ui.byTestId("named-connection-workspace-row").map(text);
  assert.equal(rows.length, 2);
  assert.match(rows[0], /^Test · Workspace default connectionID defaulthttps:\/\/site\.example\.test\/wiki · .* · Spaces: DOCS$/);
  assert.match(rows[1], /^Test · Docs-siteID conn-7https:\/\/site\.example\.test\/wiki · .* · Spaces: OPS$/);
  for (const row of ui.byTestId("named-connection-workspace-row")) {
    assert.equal(row.findAll((node) => node.type === "button").length, 0, "read-only");
  }
  assert.doesNotMatch(ui.all(), /fake-ref/);
  const workspace = await mount(server({ ...GLOBAL_LIST, scope: "workspace", inherited: [] }), { projectId: "ws-t" });
  assert.equal(workspace.byTestId("named-connections-workspaces").length, 0, "a Workspace page does not list them");
});

test("global add, test and delete go to the global API; delete names every user before anything is sent", async () => {
  const srv = server(GLOBAL_LIST, {
    tested: (stored) => ({ ...stored, connections: stored.connections.map((item) => ({ ...item,
      last_test: { ok: true, at: "2026-10-06T10:00:00", summary: "Connected as svc-a" } })) }),
  });
  const ui = await mount(srv);
  await ui.click("Add connection");
  ui.type("name", "Client-A");
  ui.type("scopes", "DOC17 ");
  await ui.click("Save connection");
  assert.match(ui.all(), /Another connection already has this name\./, "names are unique regardless of case");
  ui.type("name", "client-b");
  ui.type("confluence_url", "https://wiki.example.test/wiki");
  ui.radio("own");
  ui.radio("bearer_pat");
  ui.type("confluence_token", SECRET);
  await ui.click("Save connection");
  const post = srv.calls.find((call) => call.method === "POST");
  assert.equal(post.url, "/admin/chat/api/panel/connectors/confluence/named-connections");
  assert.equal(post.body.confluence_token, SECRET, "a typed secret is sent once");
  assert.match(ui.all(), /Saved the Confluence connection "client-b" \(new-id-1\)\./);
  assert.doesNotMatch(ui.all(), new RegExp(SECRET));

  const gets = srv.calls.filter((call) => call.method === "GET").length;
  await ui.click("Test");
  const testCall = srv.calls.find((call) => call.url.endsWith("/test"));
  assert.equal(testCall.url, `/admin/chat/api/panel/connectors/confluence/named-connections/${GLOBAL_TEAM.id}/test`);
  assert.equal(srv.calls.filter((call) => call.method === "GET").length, gets + 1, "the list is reloaded after a test");
  assert.ok(ui.all().includes(`Last test passed (${formatDateTime("2026-10-06T10:00:00")}): Connected as svc-a`));

  await ui.click("Delete");
  const [confirm] = ui.byTestId("named-connection-confirm-delete");
  assert.match(text(confirm), /Used by: Workspace "Acme Orders" \(spaces: TEAM\); Knowledge connector "wiki"/);
  assert.match(text(confirm), /pinned to it are refused/);
  assert.equal(srv.calls.filter((call) => call.method === "DELETE").length, 0, "nothing deleted before confirming");
  await ui.click("Delete connection");
  assert.equal(srv.calls.find((call) => call.method === "DELETE").url,
    `/admin/chat/api/panel/connectors/confluence/named-connections/${GLOBAL_TEAM.id}`);
  assert.doesNotMatch(ui.all(), new RegExp(GLOBAL_TEAM.id));
});

test("a Workspace shows the global connections read-only with the keys served and overridden there", async () => {
  const workspaceList = {
    connector_name: "confluence", descriptor: DESCRIPTORS.confluence, scope: "workspace",
    default: { id: "default", name: "default", configured: true, active: true, fields: {}, secret_status: {} },
    connections: [{ id: "own-1", name: "own-team", scope: "workspace", bound_scopes: ["TEAM"], fields: {},
      secret_status: {}, last_test: null, usage: { workspaces: [], knowledge_connectors: [] } }],
    inherited: [
      { ...GLOBAL_TEAM, bound_scopes: ["TEAM", "DOC17"], usage: undefined, served_here: ["DOC17"], overridden_here: ["TEAM"] },
      { ...GLOBAL_TEAM, id: "g-2", name: "ops-only", bound_scopes: ["OPS"], usage: undefined, served_here: [], overridden_here: ["OPS"] },
      { ...GLOBAL_TEAM, id: "g-3", name: "octryx", bound_scopes: [], usage: undefined, served_here: [], overridden_here: [] },
    ],
  };
  const srv = server(workspaceList);
  const ui = await mount(srv, { projectId: "ws-1" });
  assert.equal(srv.calls[0].url, "/admin/chat/api/panel/projects/ws-1/connectors/confluence/named-connections");
  const [section] = ui.byTestId("named-connections-inherited");
  assert.match(text(section), /Global connections \(read-only\)/);
  assert.match(text(section), new RegExp(`client-a · global, read-onlyID ${GLOBAL_TEAM.id}`));
  assert.match(text(section), /Serves here: DOC17\. Overridden by this Workspace: TEAM\./);
  assert.match(text(section), /ops-only.*Serves nothing here: every space it binds is bound by a Workspace connection\. Overridden by this Workspace: OPS\./);
  // Unbound (Confluence-Octryx in the Coffee Workspaces): the default here, not "serves nothing".
  assert.match(text(section), /octryx.*Spaces: not bound.*Not bound to any space: here it is the default and reads this Workspace's allowed spaces/);
  assert.deepEqual(ui.buttons(section), ["Copy ID", "Copy ID", "Copy ID"], "no edit, test or delete on an inherited connection");
  assert.match(ui.all(), /Default · the Workspace connection above/);
});

test("Copy ID writes the immutable id; without a clipboard it says so", async () => {
  const written = [];
  const clipboard = { writeText: async (value) => { written.push(value); } };
  const ui = await mount(server(GLOBAL_LIST), { globals: { navigator: { clipboard } } });
  await ui.click("Copy ID");
  assert.deepEqual(written, [GLOBAL_TEAM.id]);
  assert.match(ui.all(), /Copied/);

  const bare = await mount(server(GLOBAL_LIST));
  await bare.click("Copy ID");
  assert.match(bare.all(), /Copy is not available here; select the id\./);
});

async function mountCard(toolName, srv) {
  const { ConfiguredConnectorCard } = load("admin/components/connectorsTab/ConfiguredConnectorCard.tsx");
  const ctx = {
    CONNECTOR_COLORS: {}, CONNECTOR_ICONS: {}, connectorHealthHistory: {}, connectorTestResult: {},
    connectorSaving: null, connectorTesting: null, connectorHealthLoading: null, expandedConnector: toolName,
    getConnectorDraft: () => ({}), handleSaveConnector: async () => {}, handleTestConnector: () => {},
    handleDeleteConnector: () => {}, handleExpandConnector: () => {}, setConnectorField: () => {},
    connectorHealthStatusClass: () => "", formatConnectorHealthStatus: () => "", formatRelativeTime: () => "",
    readJson: srv.readJson,
    // The GitHub card's own repository panel.
    githubConnectorRepoError: null, githubConnectorRepositories: [], githubConnectorRepositoriesLoading: false,
    handleLoadGithubConnectorRepositories: () => {}, githubConnectorRepoCreateLoading: false,
    githubConnectorRepoForm: { name: "", description: "", private: true, project_id: "" }, projects: [],
    handleCreateGithubConnectorRepository: () => {}, setGithubConnectorRepoForm: () => {},
  };
  const connector = { tool_name: toolName, label: toolName, configured: true, description: "", public_fields: {},
    secret_status: {}, tools: [], fields: [] };
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(ConfiguredConnectorCard, { connector, ctx }));
  });
  return view;
}

test("the global card renders the named connections for every connector the server describes, and no other", async () => {
  for (const tool of Object.keys(DESCRIPTORS)) {
    const srv = server({ ...GLOBAL_LIST, connector_name: tool, descriptor: DESCRIPTORS[tool], connections: [] });
    const view = await mountCard(tool, srv);
    assert.equal(view.root.findAll((node) => node.props["data-testid"] === "named-connections").length, 1, tool);
    assert.equal(srv.calls[0].url, `/admin/chat/api/panel/connectors/${tool}/named-connections`);
    assert.equal(srv.registryReads.length, 1, "the registry is read once");
  }
  const srv = server(GLOBAL_LIST);
  const other = await mountCard("pagerduty", srv);
  assert.equal(other.root.findAll((node) => node.props["data-testid"] === "named-connections").length, 0);
  assert.equal(srv.calls.length, 0);
  assert.equal(srv.registryReads.length, 1);
});

test("a Knowledge connector pins a connection by id; every save and pause/resume keeps it", () => {
  const stored = {
    connector_key: "wiki", kind: "confluence", scope: { spaces: ["TEAM"], connection_id: GLOBAL_TEAM.id },
    products: [], version: null, max_items_per_run: 100, state: "active", cursor: {}, running: false, last_run: null,
  };
  const form = initialForm(stored);
  assert.equal(form.connectionId, GLOBAL_TEAM.id);
  assert.equal(validate(form).config.connection_id, GLOBAL_TEAM.id);
  assert.equal(validate({ ...form, connectionId: "" }).config.connection_id, null, "an empty pin is sent as cleared");
  assert.match(validate({ ...form, connectionId: "../x" }).problem, /connection id/);
  assert.equal(validate({ ...form, connectionId: "default" }).config.connection_id, "default");
  assert.equal(resetScope("jira").connectionId, "");
  const git = { ...initialForm(null), ...resetScope("git_repository"), key: "repo",
    repositoryUrl: "https://github.com/a/b", ref: "main", connectionId: "" };
  assert.ok(!("connection_id" in validate(git).config), "a public repository has no connection");
  // A repository added "From a connection" is read through it: every save sends it (knowledgeConnectionRepositories).
  assert.equal(validate({ ...git, connectionId: "x" }).config.connection_id, "x");

  assert.equal(configOf(stored, "paused").connection_id, GLOBAL_TEAM.id, "pausing never unpins");
  assert.equal(configOf({ ...stored, kind: "jira", scope: { project_keys: ["OPS"], connection_id: "default" } }).connection_id, "default");
  assert.ok(!("connection_id" in configOf({ ...stored, scope: { spaces: ["TEAM"] } })));
  assert.match(reasonText("connection_pin_mismatch"), /pinned to a connection that does not serve/);
  assert.match(reasonText("connection_not_configured_for_scope"), /no connection serves this space/);
  assert.match(reasonText("scope_spans_connections"), /one connector per connection/);
});
