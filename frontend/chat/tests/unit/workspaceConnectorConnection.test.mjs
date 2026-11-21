// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workspaceConnectorConnection.test.mjs
//
// Workspace connector connection (D3): Confluence/Jira in Workspace → Connectors choose "Use global
// connection" or "Own connection for this Workspace". An own connection reuses the sign-in form, tests
// with a transient secret and saves separately; switching back to global is confirmed and sends only
// { mode: "global" }. "Save access" carries enablement and allowlists only, never a credential. A refusal, a
// server error or an unreachable server is an error with Retry, never "uses the global connection".
// A configured but switched-off global entry says "Global connection is disabled" (R5).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { connectionDraft, connectionUrl, ownConnectionReady, parseConnection } from "../../src/admin/components/projectsTab/workspaceConnectionModel.ts";
import { connectionLoadFailure, globalConnectionNote, testResultText } from "../../src/admin/components/projectsTab/workspaceConnectionMessages.ts";
import { rebindFocusField, rebindRefusalOf, rebindRefusalText } from "../../src/admin/components/projectsTab/workspaceConnectionRebind.ts";
import { readJson as adminReadJson } from "../../src/admin/utils/adminPanelHelpers.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
// A connector's Workspace access opens from its table row in the side panel.
const openConnectorRow = async (view, name) => {
  const row = view.root.find((node) => node.type === "tr" && node.props["data-row-key"] === name);
  await act(async () => { row.props.onClick(); });
};

// The backend's shapes (services/admin/project/workspace_connection_service.py, connector_health/service.py).
const OWN = {
  connector_name: "confluence",
  source: "workspace",
  fields: { confluence_url: "https://your-site.atlassian.net/wiki", confluence_auth_mode: "cloud_api_token", confluence_username: "bot@acme.test" },
  secret_status: { confluence_token: true, confluence_password: false },
  global: { configured: true, active: true, fields: {}, secret_status: {} },
  health: { connector_name: "confluence", status: "ok", last_checked: "2026-10-05T09:00:00Z", error: "" },
};
const GLOBAL = { connector_name: "confluence", source: "global", fields: {}, secret_status: {}, global: { configured: false, active: false, fields: {}, secret_status: {} }, health: null };

// ---- model ------------------------------------------------------------------------------------

test("the connection answer is read strictly; drafts never carry a secret", () => {
  assert.equal(parseConnection(null), null);
  assert.equal(parseConnection({ source: "shared" }), null, "an unknown source is not a connection");
  assert.equal(parseConnection({ mode: "own" }), null, "only the backend's `source` field counts");
  const own = parseConnection({ ...OWN, secret_status: { confluence_token: "yes", confluence_password: false } });
  assert.deepEqual(own.secretStatus, { confluence_token: false, confluence_password: false }, "only true counts as stored");
  assert.deepEqual(own.health, { status: "ok", checkedAt: "2026-10-05T09:00:00Z" });
  assert.equal(parseConnection({ ...OWN, health: { status: "error", last_checked: null } }).health.status, "failing");
  assert.equal(parseConnection({ ...OWN, health: { status: "great" } }).health.status, "unknown");
  assert.equal(own.globalConfigured, true);
  assert.equal(parseConnection({ ...OWN, global: undefined }).globalConfigured, false);
  assert.deepEqual(connectionDraft(own), OWN.fields);
  assert.deepEqual(connectionDraft(parseConnection({ ...OWN, fields: { ...OWN.fields, confluence_token: 7 } })), OWN.fields);
  assert.deepEqual(connectionDraft(parseConnection(GLOBAL)), {});
  assert.equal(ownConnectionReady("confluence", own), true);
  assert.equal(ownConnectionReady("confluence", parseConnection(GLOBAL)), false);
  assert.equal(ownConnectionReady("confluence", parseConnection({ ...OWN, fields: { confluence_url: "https://x/wiki" } })), false);
  assert.equal(connectionUrl("ws 1", "confluence", "/test"), "/admin/chat/api/panel/projects/ws%201/connectors/confluence/connection/test");
  assert.deepEqual(testResultText({ ok: true }), { ok: true, text: "Connected." });
  assert.deepEqual(testResultText({ ok: true, summary: "Connected to Confluence." }), { ok: true, text: "Connected to Confluence." });
  assert.deepEqual(testResultText({ ok: false, message: "401 from Confluence" }), { ok: false, text: "401 from Confluence" });
  assert.deepEqual(testResultText("oops"), { ok: false, text: "The test failed." });
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
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, encodeURIComponent,
      window: { setTimeout: () => 0, confirm: () => true }, ...extra,
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

// readJson's failure: its detail as message, the HTTP status as a property (none for a network failure).
const failure = (message, status) => Object.assign(new Error(message), status === undefined ? {} : { status });

function server(initial, { supported = true, testResult = { ok: true }, loadFailures = [], refuse = null } = {}) {
  const calls = [];
  let stored = initial;
  const pending = [...loadFailures];
  const readJson = async (url, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ url, method: init.method || "GET", body });
    if (!supported && url.includes("/connection")) throw failure("Not Found", 404);
    if (url.endsWith("/connection") && !init.method && pending.length) throw pending.shift();
    if (refuse) { const refused = await refuse(url, init); if (refused) throw refused; }
    if (url.endsWith("/connection/test")) {
      if (stored.source === "workspace") stored = { ...stored, health: { status: testResult.ok ? "ok" : "error", last_checked: "2026-10-05T10:00:00Z" } };
      return testResult;
    }
    if (url.endsWith("/connection")) {
      if (init.method === "PUT") {
        const { source, ...fields } = body;
        stored = source === "global" ? GLOBAL : { ...OWN, fields, secret_status: { confluence_token: true } };
      }
      return stored;
    }
    return null;
  };
  return { readJson, calls };
}

async function mountConnection(srv, { document } = {}) {
  const { WorkspaceConnectorConnection } = load("admin/components/projectsTab/WorkspaceConnectorConnection.tsx", document ? { document } : {});
  const ready = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(WorkspaceConnectorConnection, {
      projectId: "ws-1", connectorName: "confluence", product: "confluence", label: "Confluence",
      readJson: srv.readJson, onReadyChange: (value) => ready.push(value),
    }));
  });
  const id = (field) => `connector-field-confluence-${field}`;
  const find = (predicate) => view.root.findAll(predicate)[0] ?? null;
  const radio = (name, value) => find((node) => node.type === "input" && node.props.type === "radio" && node.props.name === name && node.props.value === value);
  const ui = {
    view, ready,
    all: () => text(view.root),
    radio,
    choose: (name, value) => act(() => radio(name, value).props.onChange()),
    type: (field, value) => act(() => find((node) => node.type === "input" && node.props.id === id(field)).props.onChange({ target: { value } })),
    click: async (label) => { await act(async () => { find((node) => node.type === "button" && text(node).trim() === label).props.onClick(); }); },
    has: (testId) => Boolean(find((node) => node.props["data-testid"] === testId)),
    message: () => text(find((node) => node.props["data-testid"] === "workspace-connection-message") ?? { children: [] }),
  };
  return ui;
}

test("a 404 of the connection route is a load error, no global claim and no form", async () => {
  const ui = await mountConnection(server(GLOBAL, { supported: false }));
  assert.ok(ui.has("workspace-connection-load-error"));
  assert.doesNotMatch(ui.all(), /uses the global/);
  assert.equal(ui.view.root.findAll((node) => node.type === "input").length, 0, "no own-connection form");
});

test("global → own: the sign-in form, a transient test, then a save of only the chosen method", async () => {
  const srv = server(GLOBAL);
  const ui = await mountConnection(srv);
  assert.equal(ui.radio("confluence-connection", "global").props.checked, true);
  assert.match(ui.all(), /not set up yet, so the connector cannot run here/, "the reported global state is stated");
  assert.doesNotMatch(ui.all(), /Where Confluence runs/, "no credential form while global is used");
  ui.choose("confluence-connection", "own");
  assert.match(ui.all(), /Where Confluence runs/);
  await ui.click("Save connection");
  assert.equal(srv.calls.filter((call) => call.method !== "GET").length, 0, "an incomplete form sends nothing");
  assert.match(ui.all(), /Not saved: fix the highlighted fields\./);

  ui.choose("connector-field-confluence-confluence_auth_mode", "cloud");
  ui.type("confluence_url", "https://your-site.atlassian.net/wiki");
  ui.type("confluence_username", "bot@acme.test");
  ui.type("confluence_token", "api-token");
  await ui.click("Test connection");
  const testCall = srv.calls.filter((call) => call.method === "POST").at(-1);
  assert.deepEqual([testCall.method, testCall.url], ["POST", "/admin/chat/api/panel/projects/ws-1/connectors/confluence/connection/test"]);
  assert.deepEqual(testCall.body, {
    source: "workspace", confluence_url: "https://your-site.atlassian.net/wiki", confluence_auth_mode: "cloud_api_token",
    confluence_username: "bot@acme.test", confluence_token: "api-token",
  });
  assert.equal(ui.message(), "Connected.");
  assert.equal(srv.calls.filter((call) => call.method === "PUT").length, 0, "a test never saves");

  await ui.click("Save connection");
  const put = srv.calls.at(-1);
  assert.deepEqual([put.method, put.body.source, put.body.confluence_token], ["PUT", "workspace", "api-token"]);
  assert.equal("confluence_password" in put.body, false, "never another method's secret");
  assert.match(ui.message(), /Saved this Workspace's own Confluence connection/);
  assert.equal(ui.ready.at(-1), true, "the card learns the own connection can serve runtime access");
});

test("a saved own connection tests without retyping its secret; switching back to global is confirmed first", async () => {
  const srv = server(OWN, { testResult: { ok: false, message: "Confluence answered 401: check the API token." } });
  const ui = await mountConnection(srv);
  assert.equal(ui.radio("confluence-connection", "own").props.checked, true);
  assert.match(text(ui.view.root.find((node) => node.props["data-testid"] === "workspace-connection-health")), /^Last test: connected/);
  await ui.click("Test connection");
  assert.equal("confluence_token" in srv.calls.filter((call) => call.method === "POST").at(-1).body, false,
    "the stored secret is used by the server, not resent");
  assert.equal(ui.message(), "Confluence answered 401: check the API token.");
  assert.match(text(ui.view.root.find((node) => node.props["data-testid"] === "workspace-connection-health")), /^Last test: failed/,
    "the recorded health of the saved connection is refreshed after the test");

  ui.choose("confluence-connection", "global");
  assert.ok(ui.has("workspace-connection-confirm-global"));
  assert.equal(srv.calls.filter((call) => call.method === "PUT").length, 0, "choosing alone changes nothing");
  await ui.click("Keep own connection");
  assert.equal(ui.radio("confluence-connection", "own").props.checked, true);
  ui.choose("confluence-connection", "global");
  await ui.click("Use global connection");
  const put = srv.calls.at(-1);
  assert.deepEqual([put.method, put.body], ["PUT", { source: "global" }], "only the source, no credential field");
  assert.equal(ui.ready.at(-1), false);
});

test("Save access carries enablement and allowlists only; an own connection counts as runtime-ready", async () => {
  const { ProjectConnectorSettingsSection } = load("admin/components/projectsTab/ProjectConnectorSettingsSection.tsx");
  const { AdminNavigationContext } = load("admin/adminNavigation.ts");
  const access = {
    connector_name: "confluence", label: "Confluence", description: "", limit_fields: ["confluence_allowed_spaces", "confluence_allowed_pages"],
    global_configured: false, global_active: false, project_enabled: true, project_limits: { confluence_allowed_spaces: ["DEMO"] },
    inherited_limits: {}, effective_limits: {}, inherits_global_limits: false,
  };
  const calls = [];
  const readJson = async (url, init = {}) => {
    calls.push({ url, method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null });
    if (url.endsWith("/connection")) return OWN;
    return { project_id: "ws-1", connectors: [access] };
  };
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(AdminNavigationContext.Provider, { value: { openAdminTab: () => {} } },
      createElement(ProjectConnectorSettingsSection, { ctx: { configuringProjectQuality: { id: "ws-1" }, readJson } })));
  });
  await openConnectorRow(view, "confluence");
  const all = text(view.root);
  assert.doesNotMatch(all, /cannot run here|Global setup required/, "the own connection serves runtime access");
  assert.match(all, /On in this Workspace/);
  const toggle = view.root.find((node) => node.type === "input" && node.props["data-testid"] === "workspace-connector-enabled");
  assert.equal(toggle.parent.props.className, "admin-panel__checkbox workspace-data__toggle", "the enable choice is a labelled checkbox");
  await act(async () => { view.root.find((node) => node.type === "button" && text(node).trim() === "Save access").props.onClick(); });
  const save = calls.find((call) => call.method === "PUT" && !call.url.endsWith("/connection"));
  assert.deepEqual(Object.keys(save.body).sort(), ["is_active", "limits"]);
  assert.equal(JSON.stringify(save.body).includes("confluence_url") || JSON.stringify(save.body).includes("token"), false);
  assert.equal(calls.some((call) => call.method === "PUT" && call.url.endsWith("/connection")), false, "Save access never writes the connection");
});

test("a Workspace Bitbucket served by its named connection needs no global entry and is never 'Global setup required'", async () => {
  const { ProjectConnectorSettingsSection } = load("admin/components/projectsTab/ProjectConnectorSettingsSection.tsx");
  const { AdminNavigationContext } = load("admin/adminNavigation.ts");
  const { DESCRIPTORS } = await import("./namedConnectorDescriptors.mjs");
  const access = {
    connector_name: "bitbucket", label: "Bitbucket", description: "", limit_fields: ["bitbucket_allowed_repos"],
    global_configured: false, global_active: false, project_enabled: true, project_limits: {},
    inherited_limits: {}, effective_limits: {}, inherits_global_limits: true,
  };
  const named = (connections) => ({
    connector_name: "bitbucket", scope: "workspace", descriptor: DESCRIPTORS.bitbucket, inherited: [],
    default: { id: "default", name: "default", configured: false, active: true, fields: {}, secret_status: {} },
    connections,
  });
  const render = async (connections) => {
    const readJson = async (url) => {
      if (url.endsWith("/named-connection-descriptors")) return { connectors: Object.values(DESCRIPTORS) };
      if (url.endsWith("/bitbucket/named-connections")) return named(connections);
      return { project_id: "ws-1", connectors: [access] };
    };
    let view;
    await act(async () => {
      view = TestRenderer.create(createElement(AdminNavigationContext.Provider, { value: { openAdminTab: () => {} } },
        createElement(ProjectConnectorSettingsSection, { ctx: { configuringProjectQuality: { id: "ws-1" }, readJson } })));
    });
    await openConnectorRow(view, "bitbucket");
    return text(view.root);
  };
  const served = await render([{ id: "c1", name: "Bitbucket-Cloud", scope: "workspace", bound_scopes: ["acme/payments"],
    fields: { bitbucket_deployment: "cloud", bitbucket_url: "https://bitbucket.org" }, secret_status: {}, last_test: null }]);
  assert.doesNotMatch(served, /Global setup required|cannot run here/);
  assert.match(served, /On in this Workspace/);
  assert.match(await render([]), /Global setup required/, "without any connection the Workspace still needs one");
});

// ---- R5 / R6 ------------------------------------------------------------------------------------

test("Every failed load is an error with its reason: 404s, refusals, server errors and no answer", () => {
  for (const detail of ["Not Found", "Project not found", "Unknown Workspace connection"]) {
    assert.equal(connectionLoadFailure(failure(detail, 404)), `This Workspace's connection could not be loaded (404: ${detail}).`);
  }
  assert.equal(connectionLoadFailure(failure("Forbidden", 403)), "You are not allowed to see this Workspace's connection.");
  assert.equal(connectionLoadFailure(failure("Unauthorized", 401)), "You are not allowed to see this Workspace's connection.");
  assert.equal(connectionLoadFailure(failure("Internal Server Error", 500)), "This Workspace's connection could not be loaded (500: Internal Server Error).");
  assert.match(connectionLoadFailure(new TypeError("Failed to fetch")), /^The server could not be reached/);
  assert.match(connectionLoadFailure("boom"), /^The server could not be reached/);
});

test("A configured but switched-off global entry is 'disabled', not 'not set up yet'", () => {
  const withGlobal = (global) => parseConnection({ ...GLOBAL, global: { fields: {}, secret_status: {}, ...global } });
  assert.equal(withGlobal({ configured: true, active: false }).globalActive, false);
  assert.equal(globalConnectionNote(withGlobal({ configured: true, active: false })), " (Global connection is disabled, so the connector cannot use it here)");
  assert.equal(globalConnectionNote(withGlobal({ configured: false, active: false })), " (not set up yet, so the connector cannot run here)");
  assert.equal(globalConnectionNote(withGlobal({ configured: true, active: true })), "");
  assert.equal(withGlobal({ configured: true, active: "no" }).globalActive, false, "only true is switched on");
  assert.equal(globalConnectionNote(null), "");
});

test("rendered R6: a refused load shows an error with Retry, no global claim and no form; Retry recovers", async () => {
  const srv = server(GLOBAL, { loadFailures: [failure("Forbidden", 403)] });
  const ui = await mountConnection(srv);
  assert.ok(ui.has("workspace-connection-load-error"));
  assert.doesNotMatch(ui.all(), /uses the global/);
  assert.match(ui.all(), /You are not allowed to see this Workspace's connection\. Nothing was changed\./);
  assert.equal(ui.view.root.findAll((node) => node.type === "input").length, 0);
  await ui.click("Retry");
  assert.ok(!ui.has("workspace-connection-load-error"));
  assert.ok(ui.has("workspace-connection"));
  assert.equal(srv.calls.filter((call) => call.method === "GET").length, 2);
  for (const error of [failure("Internal Server Error", 500), new TypeError("Failed to fetch"), failure("Project not found", 404),
    failure("Not Found", 404)]) {
    const other = await mountConnection(server(GLOBAL, { loadFailures: [error] }));
    assert.ok(other.has("workspace-connection-load-error"), error.message);
  }
});

test("rendered R5: the global option says the global connection is disabled", async () => {
  const ui = await mountConnection(server({ ...GLOBAL, global: { configured: true, active: false, fields: {}, secret_status: {} } }));
  assert.match(ui.all(), /Use global connection · the URL and account set in Connector settings \(Global connection is disabled, so the connector cannot use it here\)\./);
  assert.doesNotMatch(ui.all(), /not set up yet/);
});

test("readJson keeps the HTTP status on its error (R6 reads it)", async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () => ({ ok: false, status: 404, statusText: "Not Found", json: async () => ({ detail: "Not Found" }) });
    await assert.rejects(adminReadJson("/admin/chat/api/panel/projects/p/connectors/confluence/connection"), (error) => error.status === 404 && error.message === "Not Found");
    globalThis.fetch = async () => ({ ok: false, status: 403, statusText: "", json: async () => { throw new Error("no json"); } });
    await assert.rejects(adminReadJson("/admin/x"), (error) => error.status === 403 && error.message === "Request failed");
  } finally { globalThis.fetch = original; }
});

// ---- R1/R2 follow-up ----------------------------------------------------------------------------

// The error readJson really throws for an answer: the shared admin helper against a stubbed fetch.
async function answerError(status, detail) {
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, status, statusText: "", json: async () => ({ detail }) });
  try {
    await adminReadJson("/admin/x", { method: "POST", body: "{}" });
  } catch (error) {
    return error;
  } finally { globalThis.fetch = original; }
  throw new Error("expected a refusal");
}
const REBIND = { state: "secret_rebind_required", tool_name: "confluence", changed_target_fields: ["confluence_url"],
  kept_fields: ["confluence_token"], remediation: "Re-enter the listed secrets for the new target, or confirm the rebind explicitly." };

test("model: the rebind refusal is read by shape, names only; the chosen method's secret gets the focus", async () => {
  const error = await answerError(409, REBIND);
  assert.deepEqual(rebindRefusalOf(error), { changedTargetFields: ["confluence_url"], keptFields: ["confluence_token"] });
  assert.equal(rebindRefusalOf(await answerError(409, { state: "conflict" })), null, "another 409 is not a rebind");
  assert.equal(rebindRefusalOf(new Error("x")), null);
  assert.deepEqual(rebindRefusalOf({ refusal: { changedTargetFields: ["Bad Name", "confluence_url"], keptFields: "x" } }),
    { changedTargetFields: ["confluence_url"], keptFields: [] });
  const refusal = { changedTargetFields: ["confluence_url"], keptFields: ["confluence_password", "confluence_token"] };
  assert.equal(rebindFocusField(refusal, "confluence_token"), "confluence_token");
  assert.equal(rebindFocusField(refusal, "jira_token"), "confluence_password");
  assert.equal(rebindFocusField({ changedTargetFields: [], keptFields: [] }, "confluence_token"), "confluence_token");
  assert.equal(rebindRefusalText("test", "Confluence", "API token"),
    "Not tested: the Confluence URL changed, so the stored API token is not sent to the new address. Enter the API token again for the new URL, then test again.");
  assert.match(rebindRefusalText("save", "Jira", "Personal access token"), /^Not saved: .*stored personal access token .* then save again\.$/);
});

test("rendered R1: a refused test says the URL changed, focuses the secret field and is never retried", async () => {
  const focused = [];
  const document = { getElementById: (id) => ({ focus: () => focused.push(id) }) };
  const refusal = await answerError(409, REBIND);
  const srv = server(OWN, { refuse: (url, init) => (url.endsWith("/connection/test") && init.method === "POST" ? refusal : null) });
  const ui = await mountConnection(srv, { document });
  ui.type("confluence_url", "https://other.atlassian.net/wiki");
  await ui.click("Test connection");
  const posts = srv.calls.filter((call) => call.method === "POST");
  assert.equal(posts.length, 1, "no silent retry");
  assert.equal("confirm_secret_rebind" in posts[0].body, false, "no confirmation is sent on the author's behalf");
  assert.equal("confluence_token" in posts[0].body, false);
  assert.equal(ui.message(), "Not tested: the Confluence URL changed, so the stored API token is not sent to the new address. Enter the API token again for the new URL, then test again.");
  assert.deepEqual(focused, ["connector-field-confluence-confluence_token"]);
  ui.type("confluence_token", "new-token");
  assert.equal(ui.message(), "", "typing the secret clears the refusal");
});

test("rendered R1: a refused save says the same and focuses the secret field", async () => {
  const focused = [];
  const document = { getElementById: (id) => ({ focus: () => focused.push(id) }) };
  const refusal = await answerError(409, REBIND);
  const srv = server(OWN, { refuse: (url, init) => (url.endsWith("/connection") && init.method === "PUT" ? refusal : null) });
  const ui = await mountConnection(srv, { document });
  ui.type("confluence_url", "https://other.atlassian.net/wiki");
  await ui.click("Save connection");
  assert.equal(srv.calls.filter((call) => call.method === "PUT").length, 1, "no silent retry");
  assert.match(ui.message(), /^Not saved: the Confluence URL changed, so the stored API token is not sent to the new address\./);
  assert.deepEqual(focused, ["connector-field-confluence-confluence_token"]);
});

test("rendered R2: a refused access save shows the server's message in its panel", async () => {
  const { ProjectConnectorSettingsSection } = load("admin/components/projectsTab/ProjectConnectorSettingsSection.tsx");
  const { AdminNavigationContext } = load("admin/adminNavigation.ts");
  const access = {
    connector_name: "confluence", label: "Confluence", description: "", limit_fields: ["confluence_allowed_spaces"],
    global_configured: true, global_active: true, project_enabled: true, project_limits: {}, inherited_limits: {},
    effective_limits: {}, inherits_global_limits: true,
  };
  const refusal = await answerError(422, { code: "connector_access_invalid", message: "confluence_allowed_spaces: 'bad key!' is not a space key." });
  const readJson = async (url, init = {}) => {
    if (url.endsWith("/connection")) return GLOBAL;
    if (init.method === "PUT") throw refusal;
    return { project_id: "ws-1", connectors: [access] };
  };
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(AdminNavigationContext.Provider, { value: { openAdminTab: () => {} } },
      createElement(ProjectConnectorSettingsSection, { ctx: { configuringProjectQuality: { id: "ws-1" }, readJson } })));
  });
  await openConnectorRow(view, "confluence");
  await act(async () => { view.root.find((node) => node.type === "button" && text(node).trim() === "Save access").props.onClick(); });
  const alert = view.root.find((node) => node.props["data-testid"] === "connector-access-error");
  assert.equal(text(alert), "Access not saved: confluence_allowed_spaces: 'bad key!' is not a space key.");
  assert.equal(alert.props.role, "alert");
  assert.doesNotMatch(text(view.root), /Connector access saved/);
});
