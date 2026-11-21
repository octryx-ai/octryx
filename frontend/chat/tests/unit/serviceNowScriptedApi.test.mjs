// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/serviceNowScriptedApi.test.mjs
//
// ServiceNow password-grant OAuth and Scripted REST endpoints.
// The ServiceNow form gets the method "OAuth (username and password)" (client id and secret, username and
// password, optional scope, a token URL prefilled from the instance URL but editable) and an "API" section: Standard
// Table API or Custom Scripted REST API with the incidents, changes and optional journal paths and the page size. A
// connection test reports each endpoint. No customer value anywhere: fixtures use `servicenow.test`-style names.
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
  defaultServiceNowTokenUrl,
  serviceNowAuthSaveFields,
  serviceNowAuthView,
  serviceNowModeFields,
  storedServiceNowSummary,
} from "../../src/admin/components/connectorsTab/serviceNowAuthModel.ts";
import {
  endpointResults,
  pageSizeProblem,
  scriptedPathProblem,
  serviceNowApiOwnedFields,
  serviceNowApiSaveFields,
  serviceNowApiStyle,
  serviceNowApiView,
  serviceNowSetupView,
} from "../../src/admin/components/connectorsTab/serviceNowApiModel.ts";
import { testCodeHint } from "../../src/admin/components/connectorsTab/oidcClientCredentialsModel.ts";
import { buildConnectorSaveBody } from "../../src/admin/hooks/connectorSaveBody.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const POLICY = { tool_instructions: "", extra_tools: [], disabled_tools: [] };
const INSTANCE = "https://servicenow.test";

const FIELDS = [
  "servicenow_url", "servicenow_auth_mode", "servicenow_client_id", "servicenow_client_secret", "servicenow_token_url",
  "servicenow_oauth_scope", "servicenow_oidc_audience", "servicenow_oidc_client_auth", "servicenow_username",
  "servicenow_password", "servicenow_token", "servicenow_allowed_tables", "servicenow_api_style", "servicenow_incidents_path",
  "servicenow_changes_path", "servicenow_journal_path", "servicenow_page_size",
];

function servicenow({ publicFields = {}, secrets = {}, configured = true } = {}) {
  return {
    tool_name: "servicenow", label: "ServiceNow", description: "ServiceNow tables", fields: FIELDS,
    secret_fields: ["servicenow_client_secret", "servicenow_password", "servicenow_token"], supports_test: true,
    builtin_tools: [], tools: [], tool_policy: POLICY, is_active: true, policy_active: true, configured,
    public_fields: { servicenow_url: INSTANCE, servicenow_allowed_tables: ["incident"], ...publicFields },
    secret_status: { servicenow_client_secret: false, servicenow_password: false, servicenow_token: false, ...secrets },
    db_id: null, policy_id: null,
  };
}

const PASSWORD_DRAFT = {
  servicenow_url: INSTANCE, servicenow_auth_mode: "oauth_password", servicenow_token_url: `${INSTANCE}/oauth_token.do`,
  servicenow_client_id: "client-a", servicenow_client_secret: "cs", servicenow_username: "integration", servicenow_password: "pw",
};

// ---- password grant -------------------------------------------------------------------------------

test("OAuth (username and password): client id, username, both secrets and the token URL are required", () => {
  const fields = serviceNowModeFields("oauth_password");
  assert.equal(fields.label, "OAuth (username and password)");
  assert.deepEqual(fields.principals.map((entry) => entry.field), ["servicenow_client_id", "servicenow_username"]);
  assert.deepEqual(fields.secrets.map((entry) => entry.field), ["servicenow_client_secret", "servicenow_password"]);
  const empty = serviceNowAuthView(servicenow(), { servicenow_url: INSTANCE, servicenow_auth_mode: "oauth_password" });
  assert.deepEqual(Object.keys(empty.errors).sort(),
    ["servicenow_client_id", "servicenow_client_secret", "servicenow_password", "servicenow_token_url", "servicenow_username"]);
  assert.deepEqual(serviceNowAuthView(servicenow(), PASSWORD_DRAFT).errors, {});
  const http = serviceNowAuthView(servicenow(), { ...PASSWORD_DRAFT, servicenow_token_url: "http://servicenow.test/oauth_token.do" });
  assert.equal(http.errors.servicenow_token_url.live, true, "https only (loopback http for tests)");
  assert.deepEqual(serviceNowAuthView(servicenow(), { ...PASSWORD_DRAFT, servicenow_token_url: "http://127.0.0.1:8099/oauth_token.do" }).errors, {});
});

test("OAuth (username and password) saves only its fields; a cleared stored scope is sent empty", () => {
  const body = serviceNowAuthSaveFields(servicenow(), { ...PASSWORD_DRAFT, servicenow_token: "t", servicenow_oidc_audience: "aud",
    servicenow_oidc_client_auth: "client_secret_basic", servicenow_oauth_scope: " useraccount " });
  assert.deepEqual(body, {
    servicenow_url: INSTANCE, servicenow_auth_mode: "oauth_password", servicenow_token_url: `${INSTANCE}/oauth_token.do`,
    servicenow_oauth_scope: "useraccount", servicenow_client_id: "client-a", servicenow_username: "integration",
    servicenow_client_secret: "cs", servicenow_password: "pw",
  });
  const stored = servicenow({ publicFields: { servicenow_auth_mode: "oauth_password", servicenow_oauth_scope: "s" },
    secrets: { servicenow_client_secret: true, servicenow_password: true } });
  const kept = serviceNowAuthView(stored, { ...PASSWORD_DRAFT, servicenow_client_secret: "", servicenow_password: "" });
  assert.deepEqual([kept.keepable.servicenow_client_secret, kept.keepable.servicenow_password, kept.secretKeepable], [true, true, true]);
  assert.deepEqual(kept.errors, {});
  const saved = serviceNowAuthSaveFields(stored, { ...PASSWORD_DRAFT, servicenow_client_secret: "", servicenow_password: "" });
  assert.equal("servicenow_client_secret" in saved || "servicenow_password" in saved, false, "blank secrets are kept, not sent");
  assert.equal(saved.servicenow_oauth_scope, "");
});

test("switching needs the secrets again; only stored ones of this method are kept", () => {
  const fromBasic = servicenow({ publicFields: { servicenow_auth_mode: "basic", servicenow_username: "u" }, secrets: { servicenow_password: true } });
  const switched = serviceNowAuthView(fromBasic, { ...PASSWORD_DRAFT, servicenow_password: "", servicenow_client_secret: "" });
  assert.equal(switched.switching, true);
  assert.match(switched.errors.servicenow_password.message, /^Enter a new password: the sign-in method changes/);
  assert.match(switched.errors.servicenow_client_secret.message, /^Enter a new client secret/);
  const unset = servicenow({ publicFields: { servicenow_username: "u" }, secrets: { servicenow_password: true } });
  assert.equal(serviceNowAuthView(unset, { ...PASSWORD_DRAFT, servicenow_password: "" }).keepable.servicenow_password, true,
    "choosing the first method keeps its stored secret");
});

test("the token URL prefill is <instance URL>/oauth_token.do, nothing else; the summary names what is missing", () => {
  assert.equal(defaultServiceNowTokenUrl("https://servicenow.test/"), "https://servicenow.test/oauth_token.do");
  assert.equal(defaultServiceNowTokenUrl(" https://servicenow.test "), "https://servicenow.test/oauth_token.do");
  assert.equal(defaultServiceNowTokenUrl("http://servicenow.test"), null);
  assert.equal(defaultServiceNowTokenUrl(""), null);
  const stored = servicenow({ publicFields: { servicenow_auth_mode: "oauth_password", servicenow_client_id: "c" }, secrets: { servicenow_client_secret: true } });
  assert.equal(storedServiceNowSummary(stored), "Saved: OAuth (username and password), incomplete (missing token endpoint URL and username and password).");
});

// ---- API style ------------------------------------------------------------------------------------

test("the API style defaults to the Table API; paths and the page size follow the backend's rules", () => {
  assert.equal(serviceNowApiStyle(servicenow(), {}), "table");
  assert.equal(serviceNowApiStyle(servicenow({ publicFields: { servicenow_api_style: "scripted" } }), {}), "scripted");
  assert.equal(serviceNowApiStyle(servicenow({ publicFields: { servicenow_api_style: "scripted" } }), { servicenow_api_style: "table" }), "table");
  assert.equal(scriptedPathProblem("/api/a/v1/incidents"), null);
  assert.match(scriptedPathProblem("https://servicenow.test/api/x"), /without https:\/\/ or a host/);
  assert.match(scriptedPathProblem("//servicenow.test/api/x"), /without https:\/\/ or a host/);
  assert.match(scriptedPathProblem("/now/table/incident"), /must begin with \/api\//);
  assert.match(scriptedPathProblem("/api/x?sysparm_limit=1"), /Remove the query string/);
  assert.match(scriptedPathProblem("/api/x#y"), /Remove the query string/);
  assert.match(scriptedPathProblem("/api/x/../y"), /must not contain/);
  assert.match(scriptedPathProblem("/api/x//y"), /must not contain/);
  assert.match(scriptedPathProblem("/api/<namespace>/<api>/incidents"), /Use only letters/);
  assert.match(scriptedPathProblem(`/api/${"a".repeat(300)}`), /longer than 300/);
  assert.equal(pageSizeProblem(""), null);
  assert.equal(pageSizeProblem("200"), null);
  assert.equal(pageSizeProblem("1"), null);
  assert.match(pageSizeProblem("201"), /between 1 and 200/);
  assert.match(pageSizeProblem("0"), /between 1 and 200/);
  assert.match(pageSizeProblem("1.5"), /whole number/);
});

test("scripted needs the incidents or the changes path; the table style needs nothing", () => {
  const base = { servicenow_api_style: "scripted" };
  assert.deepEqual(serviceNowApiView(servicenow(), {}).errors, {});
  assert.match(serviceNowApiView(servicenow(), base).errors.servicenow_incidents_path.message, /incidents path, the changes path or both/);
  assert.deepEqual(serviceNowApiView(servicenow(), { ...base, servicenow_changes_path: "/api/x/changes" }).errors, {});
  assert.deepEqual(serviceNowApiView(servicenow(), { ...base, servicenow_incidents_path: "/api/x/incidents" }).errors, {});
  assert.deepEqual(Object.keys(serviceNowApiView(servicenow(), { ...base, servicenow_incidents_path: "/api/x/incidents",
    servicenow_journal_path: "/x", servicenow_page_size: "500" }).errors).sort(), ["servicenow_journal_path", "servicenow_page_size"]);
  const setup = serviceNowSetupView(servicenow(), { ...base, servicenow_auth_mode: "basic" });
  assert.ok(setup.errors.servicenow_incidents_path && setup.errors.servicenow_username, "both sections stop the save");
});

test("API save: untouched sends nothing; scripted sends paths and a numeric page size; cleared stored values are emptied", () => {
  assert.deepEqual(serviceNowApiSaveFields(servicenow(), {}), {});
  assert.deepEqual(serviceNowApiSaveFields(servicenow(), { servicenow_api_style: "table", servicenow_incidents_path: "/api/x" }),
    { servicenow_api_style: "table" }, "the Table API never sends paths");
  assert.deepEqual(serviceNowApiSaveFields(servicenow(), {
    servicenow_api_style: "scripted", servicenow_incidents_path: " /api/x/incidents ", servicenow_changes_path: "/api/x/changes", servicenow_page_size: "50",
  }), { servicenow_api_style: "scripted", servicenow_incidents_path: "/api/x/incidents", servicenow_changes_path: "/api/x/changes", servicenow_page_size: 50 });
  const stored = servicenow({ publicFields: { servicenow_api_style: "scripted", servicenow_journal_path: "/api/x/journal", servicenow_page_size: 100 } });
  assert.deepEqual(serviceNowApiSaveFields(stored, { servicenow_api_style: "scripted", servicenow_incidents_path: "/api/x/incidents" }), {
    servicenow_api_style: "scripted", servicenow_incidents_path: "/api/x/incidents", servicenow_journal_path: "", servicenow_page_size: "",
  });
  assert.deepEqual(serviceNowApiOwnedFields(), ["servicenow_api_style", "servicenow_incidents_path", "servicenow_changes_path", "servicenow_journal_path", "servicenow_page_size"]);
});

test("the connection test reports each endpoint: OK with its total, or the coded failure with its HTTP status", () => {
  assert.deepEqual(endpointResults({ ok: true, summary: "Connected." }), []);
  assert.deepEqual(endpointResults(null), []);
  assert.deepEqual(endpointResults({ endpoints: [
    { endpoint: "incidents", ok: true, total: 42 },
    { endpoint: "changes", ok: false, code: "servicenow_endpoint_http_status", http_status: 403 },
    { endpoint: "journal", ok: true, total: 1 },
    { name: "custom", ok: false, code: "servicenow_endpoint_unexpected_shape" },
    { ok: true },
  ] }).map((line) => [line.label, line.ok, line.text]), [
    ["Incidents", true, "OK, 42 records in total"],
    ["Changes", false, "the endpoint answered with an error status (HTTP 403)"],
    ["Journal", true, "OK, 1 record in total"],
    ["custom", false, "the answer has no single record list under result; check that the path is the list endpoint"],
  ]);
  assert.deepEqual(endpointResults({ endpoints: { incidents: { ok: true }, changes: { ok: false, code: "x_new", status: 500 } } })
    .map((line) => line.text), ["OK", "refused (x_new) (HTTP 500)"]);
  assert.equal(endpointResults({ endpoints: { changes: { ok: false, summary: "Server said no." } } })[0].text, "Server said no.");
  for (const code of ["servicenow_endpoint_empty_answer", "servicenow_endpoint_unreachable", "servicenow_endpoint_not_configured"]) {
    assert.doesNotMatch(endpointResults({ endpoints: { incidents: { ok: false, code } } })[0].text, /refused/, code);
  }
  for (const code of ["oauth_invalid_client", "oauth_invalid_grant", "oauth_unauthorized_client", "oauth_token_endpoint_redirect", "oauth_bad_response"]) {
    assert.ok(testCodeHint(code), code);
  }
  assert.match(testCodeHint("oauth_invalid_grant"), /username or password of the integration user/);
});

test("no customer value in the ServiceNow sources: neutral placeholders only", () => {
  for (const file of ["serviceNowAuthModel.ts", "serviceNowApiModel.ts", "ServiceNowApiFields.tsx", "ServiceNowConnectorSetupFields.tsx"]) {
    const source = fs.readFileSync(path.join(SRC, "admin/components/connectorsTab", file), "utf8");
    assert.doesNotMatch(source, /[a-z0-9-]+\.(com|net|io|de|ch|org|cloud|service-now)\b/i, `${file} names a host`);
    assert.doesNotMatch(source, /\/api\/x_[a-z0-9]/i, `${file} names a namespace`);
    // Literal placeholders only (an expression such as the stored-secret hint is not a value).
    for (const [, placeholder] of source.matchAll(/placeholder(?:=|: )"([^"]*)"/g)) {
      assert.ok(["", "https://"].includes(placeholder) || /^\/api\/<namespace>\/<api>\/[a-z]+$/.test(placeholder), `${file}: ${placeholder}`);
    }
  }
});

// ---- rendered -----------------------------------------------------------------------------------

function makeLoader(stubs) {
  const cache = new Map();
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name.endsWith(suffix));
    if (stub) return stub[1];
    if (name.startsWith(".")) {
      const base = path.resolve(dir, name);
      for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return load(base + ext);
    }
    return require(name);
  };
  const load = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, URL, URLSearchParams, console, Date, Error, encodeURIComponent,
      requestAnimationFrame: (callback) => callback(), document: { getElementById: () => null },
      window: { setTimeout: () => 0, confirm: () => true },
      require: (name) => resolve(name, path.dirname(file)),
    });
    return module.exports;
  };
  return (relative) => load(path.join(SRC, relative));
}

const Null = () => null;
const loadModule = makeLoader({
  "/ConfiguredConnectorHeader": { ConfiguredConnectorHeader: Null },
  "/ConfiguredConnectorHealthTools": { ConfiguredConnectorHealthTools: Null },
  "/ConfiguredConnectorToolList": { ConfiguredConnectorToolList: Null },
  "/ConfiguredConnectorGithubPanel": { ConfiguredConnectorGithubPanel: Null },
});

function mountCard(connector, testResult = null) {
  const { ConfiguredConnectorCard } = loadModule("admin/components/connectorsTab/ConfiguredConnectorCard.tsx");
  let draft = {};
  for (const [key, value] of Object.entries(connector.public_fields)) draft[key] = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  const saves = [];
  let view;
  const ctx = {
    CONNECTOR_COLORS: {}, connectorHealthHistory: {}, connectorTestResult: testResult ? { [connector.tool_name]: testResult } : {},
    connectorSaving: null, connectorTesting: null, expandedConnector: connector.tool_name,
    getConnectorDraft: () => draft,
    setConnectorField: (_tool, field, value) => { draft = { ...draft, [field]: value }; act(() => view.update(render())); },
    handleSaveConnector: async (_toolName, saved, confirmedBody) => { saves.push(confirmedBody || buildConnectorSaveBody(saved, draft, POLICY)); return { state: "saved" }; },
    handleTestConnector: async () => {},
  };
  const render = () => createElement(ConfiguredConnectorCard, { connector, ctx });
  act(() => { view = TestRenderer.create(render()); });
  const id = (field) => `connector-field-servicenow-${field}`;
  const input = (field) => view.root.findAll((node) => (node.type === "input" || node.type === "select") && node.props.id === id(field))[0] ?? null;
  const radio = (name, value) => view.root.find((node) => node.type === "input" && node.props.type === "radio" && node.props.name === id(name) && node.props.value === value);
  return {
    root: () => view.root, input, radio, draft: () => draft,
    choose: (name, value) => act(() => radio(name, value).props.onChange()),
    type: (field, value) => act(() => input(field).props.onChange({ target: { value } })),
    save: async () => { await act(async () => { view.root.find((node) => node.type === "button" && text(node) === "Save").props.onClick(); }); },
    saves,
  };
}

test("rendered: OAuth (username and password) prefills the token URL from the instance URL, editable, and saves its fields", async () => {
  const card = mountCard(servicenow({ configured: false }));
  card.choose("servicenow_auth_mode", "oauth_password");
  assert.equal(card.input("servicenow_token_url").props.value, "https://servicenow.test/oauth_token.do");
  for (const field of ["servicenow_client_id", "servicenow_client_secret", "servicenow_username", "servicenow_password", "servicenow_oauth_scope"]) {
    assert.ok(card.input(field), field);
  }
  for (const field of ["servicenow_token", "servicenow_oidc_audience"]) assert.equal(card.input(field), null, field);
  assert.equal(card.input("servicenow_password").props.type, "password");
  assert.equal(card.input("servicenow_client_secret").props.type, "password");
  // The prefill follows the instance URL until the admin edits it.
  card.type("servicenow_url", "https://other.servicenow.test");
  assert.equal(card.input("servicenow_token_url").props.value, "https://other.servicenow.test/oauth_token.do");
  card.type("servicenow_token_url", "https://other.servicenow.test/custom_token.do");
  card.type("servicenow_url", "https://third.servicenow.test");
  assert.equal(card.input("servicenow_token_url").props.value, "https://other.servicenow.test/custom_token.do", "an edited token URL stays");
  card.type("servicenow_client_id", "client-a");
  card.type("servicenow_client_secret", "cs");
  card.type("servicenow_username", "integration");
  card.type("servicenow_password", "pw");
  await card.save();
  const body = card.saves.at(-1);
  assert.deepEqual([body.servicenow_auth_mode, body.servicenow_token_url, body.servicenow_username, body.servicenow_password],
    ["oauth_password", "https://other.servicenow.test/custom_token.do", "integration", "pw"]);
  assert.equal("servicenow_api_style" in body, false, "an untouched API section changes nothing");
  // Changing the method clears the secrets typed for this one.
  card.choose("servicenow_auth_mode", "basic");
  assert.equal(card.draft().servicenow_password, "");
  assert.equal(card.draft().servicenow_client_secret, "");
});

test("rendered: the API section switches between Table and Scripted REST; scripted paths are validated and saved", async () => {
  const card = mountCard(servicenow({ publicFields: { servicenow_auth_mode: "bearer_token" }, secrets: { servicenow_token: true } }));
  assert.equal(card.radio("servicenow_api_style", "table").props.checked, true);
  assert.equal(card.input("servicenow_incidents_path"), null);
  card.choose("servicenow_api_style", "scripted");
  assert.equal(card.input("servicenow_incidents_path").props.placeholder, "/api/<namespace>/<api>/incidents");
  assert.equal(card.input("servicenow_changes_path").props.placeholder, "/api/<namespace>/<api>/changes");
  assert.equal(card.input("servicenow_journal_path").props.placeholder, "/api/<namespace>/<api>/journal");
  assert.equal(card.input("servicenow_page_size").props.placeholder, "100");
  assert.match(text(card.root()), /Custom Scripted REST API/);
  await card.save();
  assert.equal(card.saves.length, 0, "no path: not saved");
  assert.match(text(card.root()), /Enter the incidents path, the changes path or both\./);
  card.type("servicenow_incidents_path", "https://servicenow.test/api/a");
  assert.match(text(card.root()), /Enter only the path, without https:\/\/ or a host/, "shown while typing");
  card.type("servicenow_incidents_path", "/api/a/v1/incidents");
  card.type("servicenow_changes_path", "/api/a/v1/changes");
  card.type("servicenow_page_size", "150");
  await card.save();
  assert.deepEqual(Object.fromEntries(Object.entries(card.saves[0]).filter(([key]) => /api_style|_path|page_size/.test(key))), {
    servicenow_api_style: "scripted", servicenow_incidents_path: "/api/a/v1/incidents", servicenow_changes_path: "/api/a/v1/changes", servicenow_page_size: 150,
  });
  assert.doesNotMatch(text(card.root()), /servicenow api style|servicenow incidents path/, "no raw API field in the generic panel");
  card.choose("servicenow_api_style", "table");
  assert.equal(card.input("servicenow_incidents_path"), null);
});

test("rendered: a Scripted REST connection test lists each endpoint", () => {
  const card = mountCard(servicenow({ publicFields: { servicenow_api_style: "scripted" } }), {
    ok: false, summary: "ServiceNow: one endpoint failed.",
    endpoints: [{ endpoint: "incidents", ok: true, total: 12 }, { endpoint: "changes", ok: false, code: "servicenow_endpoint_empty_answer" }],
  });
  const lines = card.root().find((node) => node.props["data-testid"] === "connector-test-endpoints").findAllByType("li");
  assert.deepEqual(lines.map((line) => [line.props["data-ok"], text(line)]), [
    ["yes", "✓ Incidents: OK, 12 records in total"],
    ["no", "✗ Changes: the endpoint answered without content"],
  ]);
});
