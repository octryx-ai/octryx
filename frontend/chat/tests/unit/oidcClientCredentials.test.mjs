// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/oidcClientCredentials.test.mjs
//
// OpenID Connect client credentials as a connector sign-in method.
// Confluence and Jira (global form and Workspace own connection) get a third own-instance method with
// token endpoint URL, client id, client secret, optional scope and audience and an advanced client authentication.
// ServiceNow gets an explicit method choice (OIDC/OAuth client credentials, bearer token, username and password); a
// connector without a saved method needs one chosen. Only the chosen method's fields are shown and sent; placeholders are neutral or
// empty; a connection test shows the coded hints. Fixtures use neutral `.example`/`.test` hosts only.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { atlassianAuthSaveFields, storedAuthSummary } from "../../src/admin/components/connectorsTab/atlassianAuthModel.ts";
import { atlassianAuthView } from "../../src/admin/components/connectorsTab/atlassianAuthView.ts";
import { authModeFields, authOwnedFields } from "../../src/admin/components/connectorsTab/atlassianAuthModes.ts";
import {
  SERVICENOW_OIDC_FIELDS,
  atlassianOidcFields,
  testCodeHint,
  testResultHint,
  tokenUrlProblem,
} from "../../src/admin/components/connectorsTab/oidcClientCredentialsModel.ts";
import {
  serviceNowAuthSaveFields,
  serviceNowAuthView,
  serviceNowOwnedFields,
  serviceNowUrlProblem,
  storedServiceNowMode,
  storedServiceNowSummary,
} from "../../src/admin/components/connectorsTab/serviceNowAuthModel.ts";
import { testResultText } from "../../src/admin/components/projectsTab/workspaceConnectionMessages.ts";
import { buildConnectorSaveBody } from "../../src/admin/hooks/connectorSaveBody.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const POLICY = { tool_instructions: "", extra_tools: [], disabled_tools: [] };
const TOKEN_URL = "https://idp.example/token";

const OIDC_DRAFT = {
  jira_url: "https://jira.example", jira_auth_mode: "oidc_client_credentials", jira_oidc_token_url: TOKEN_URL,
  jira_oidc_client_id: "client-a", jira_oidc_client_secret: "s3cret",
};

function jira({ publicFields = {}, secrets = {} } = {}) {
  return {
    tool_name: "jira", configured: true,
    public_fields: { jira_url: "https://jira.example", ...publicFields },
    secret_status: { jira_token: false, jira_password: false, jira_oidc_client_secret: false, ...secrets },
  };
}

const SERVICENOW_FIELDS = [
  "servicenow_url", "servicenow_auth_mode", "servicenow_client_id", "servicenow_client_secret", "servicenow_token_url",
  "servicenow_oauth_scope", "servicenow_oidc_audience", "servicenow_oidc_client_auth", "servicenow_username",
  "servicenow_password", "servicenow_token", "servicenow_allowed_tables",
];

function servicenow({ publicFields = {}, secrets = {}, configured = true } = {}) {
  return {
    tool_name: "servicenow", label: "ServiceNow", description: "ServiceNow tables", fields: SERVICENOW_FIELDS,
    secret_fields: ["servicenow_client_secret", "servicenow_password", "servicenow_token"], supports_test: true,
    builtin_tools: [], tools: [], tool_policy: POLICY, is_active: true, policy_active: true, configured,
    public_fields: { servicenow_url: "https://sn.example", servicenow_allowed_tables: ["incident"], ...publicFields },
    secret_status: { servicenow_client_secret: false, servicenow_password: false, servicenow_token: false, ...secrets },
    db_id: null, policy_id: null,
  };
}

// ---- model --------------------------------------------------------------------------------------

test("the token endpoint must be https (http only on loopback), without user info or fragment", () => {
  assert.equal(tokenUrlProblem(TOKEN_URL), null);
  assert.equal(tokenUrlProblem("https://idp.example/realms/x/protocol/openid-connect/token?tenant=1"), null);
  assert.equal(tokenUrlProblem("http://127.0.0.1:8099/token"), null);
  assert.equal(tokenUrlProblem("http://localhost/token"), null);
  assert.match(tokenUrlProblem("http://idp.example/token"), /must use https:\/\/; http is accepted only for a local test endpoint/);
  assert.match(tokenUrlProblem("https://user:pw@idp.example/token"), /Remove the user name or password/);
  assert.match(tokenUrlProblem("https://:pw@idp.example/token"), /Remove the user name or password/);
  assert.match(tokenUrlProblem("https://idp.example/token#x"), /Remove the fragment/);
  assert.match(tokenUrlProblem("idp.example/token"), /Enter the full token endpoint URL/);
  assert.match(tokenUrlProblem("ftp://idp.example/token"), /must start with https:\/\//);
});

test("Atlassian OIDC: its own principal and secret; token URL, client id and secret are required", () => {
  const fields = authModeFields("jira", "oidc_client_credentials");
  assert.deepEqual([fields.principal, fields.secret, fields.label], ["jira_oidc_client_id", "jira_oidc_client_secret", "OpenID Connect (client credentials)"]);
  assert.deepEqual(atlassianOidcFields("confluence").tokenUrl, "confluence_oidc_token_url");
  for (const field of ["jira_oidc_token_url", "jira_oidc_client_id", "jira_oidc_client_secret", "jira_oidc_scope", "jira_oidc_audience", "jira_oidc_client_auth"]) {
    assert.ok(authOwnedFields("jira").includes(field), `${field} is owned by the guided sign-in`);
  }
  const empty = atlassianAuthView("jira", jira(), { jira_url: "https://jira.example", jira_auth_mode: "oidc_client_credentials" });
  assert.deepEqual(Object.keys(empty.errors).sort(), ["jira_oidc_client_id", "jira_oidc_client_secret", "jira_oidc_token_url"]);
  assert.equal(empty.location, "own");
  assert.deepEqual(atlassianAuthView("jira", jira(), OIDC_DRAFT).errors, {});
  const bad = atlassianAuthView("jira", jira(), { ...OIDC_DRAFT, jira_oidc_token_url: "http://idp.example/token", jira_oidc_client_auth: "private_key_jwt" });
  assert.deepEqual(Object.keys(bad.errors).sort(), ["jira_oidc_client_auth", "jira_oidc_token_url"]);
  assert.equal(bad.errors.jira_oidc_token_url.live, true, "a wrong URL shows while typing");
});

test("Atlassian OIDC save: only this method's fields; optional ones when set, cleared ones as an explicit empty value", () => {
  assert.deepEqual(atlassianAuthSaveFields("jira", jira({ publicFields: { jira_username: "svc" }, secrets: { jira_password: true } }), {
    ...OIDC_DRAFT, jira_username: "svc", jira_password: "typed-elsewhere", jira_oidc_scope: " read ",
  }), {
    jira_url: "https://jira.example", jira_auth_mode: "oidc_client_credentials", jira_oidc_client_id: "client-a",
    jira_oidc_client_secret: "s3cret", jira_oidc_token_url: TOKEN_URL, jira_oidc_scope: "read",
  });
  const stored = jira({
    publicFields: { jira_auth_mode: "oidc_client_credentials", jira_oidc_token_url: TOKEN_URL, jira_oidc_client_id: "client-a",
      jira_oidc_audience: "api", jira_oidc_client_auth: "client_secret_basic" },
    secrets: { jira_oidc_client_secret: true },
  });
  const kept = { ...OIDC_DRAFT, jira_oidc_client_secret: "", jira_oidc_audience: "", jira_oidc_client_auth: "client_secret_basic" };
  assert.equal(atlassianAuthView("jira", stored, kept).secretKeepable, true, "the stored secret is kept when left blank");
  assert.deepEqual(atlassianAuthView("jira", stored, kept).errors, {});
  const body = atlassianAuthSaveFields("jira", stored, kept);
  assert.equal("jira_oidc_client_secret" in body, false, "a blank secret is never sent");
  assert.equal(body.jira_oidc_audience, "", "a removed audience is cleared, not kept silently");
  assert.equal(body.jira_oidc_client_auth, "client_secret_basic");
  assert.equal("jira_oidc_scope" in body, false, "an optional field never stored and still empty is not sent");
  // Switching from a personal access token: the stored token is not reused as the client secret.
  const fromPat = jira({ publicFields: { jira_auth_mode: "bearer_pat" }, secrets: { jira_token: true } });
  const switched = atlassianAuthView("jira", fromPat, { ...OIDC_DRAFT, jira_oidc_client_secret: "" });
  assert.equal(switched.switching, true);
  assert.match(switched.errors.jira_oidc_client_secret.message, /^Enter a new client secret: the sign-in method changes/);
});

test("the stored summary names a missing token endpoint", () => {
  const stored = jira({ publicFields: { jira_auth_mode: "oidc_client_credentials", jira_oidc_client_id: "client-a" }, secrets: { jira_oidc_client_secret: true } });
  assert.equal(storedAuthSummary("jira", stored), "Saved: Own instance · OpenID Connect (client credentials), incomplete (missing token endpoint URL).");
  const complete = jira({ publicFields: { ...stored.public_fields, jira_oidc_token_url: TOKEN_URL }, secrets: { jira_oidc_client_secret: true } });
  assert.equal(storedAuthSummary("jira", complete), "Saved: Own instance · OpenID Connect (client credentials).");
});

test("ServiceNow: explicit, none and unknown are distinct; a connector without a saved method needs one chosen", () => {
  for (const mode of ["bearer_token", "basic", "oidc_client_credentials"]) {
    assert.equal(storedServiceNowMode(servicenow({ publicFields: { servicenow_auth_mode: mode } })), mode);
  }
  assert.equal(storedServiceNowMode(servicenow({ publicFields: { servicenow_client_id: "c" } })), "none", "credentials without a mode name no method");
  assert.equal(storedServiceNowMode(servicenow({ secrets: { servicenow_token: true } })), "none");
  assert.equal(storedServiceNowMode(servicenow()), "none");
  assert.equal(storedServiceNowMode(servicenow({ publicFields: { servicenow_auth_mode: "oauth" } })), "unknown");
  const unset = servicenow({ publicFields: { servicenow_username: "svc" }, secrets: { servicenow_password: true } });
  const view = serviceNowAuthView(unset, { servicenow_url: "https://sn.example", servicenow_username: "svc" });
  assert.deepEqual(view.errors, { servicenow_auth_mode: { message: "Choose how ServiceNow signs in.", live: false } });
  assert.deepEqual(serviceNowAuthView(unset, { servicenow_url: "https://sn.example", servicenow_auth_mode: "basic", servicenow_username: "svc" }).errors,
    {}, "the chosen method keeps its stored password");
  assert.equal(storedServiceNowSummary(unset), "No sign-in method is saved yet.");
  assert.match(serviceNowAuthView(servicenow({ publicFields: { servicenow_auth_mode: "oauth" } }), { servicenow_url: "https://sn.example" }).errors.servicenow_auth_mode.message, /not recognised/);
  assert.match(serviceNowAuthView(servicenow(), { servicenow_url: "https://sn.example" }).errors.servicenow_auth_mode.message, /Choose how ServiceNow signs in/);
});

test("ServiceNow: each method sends only its own fields; OIDC keeps the stored field names", () => {
  const empty = servicenow();
  assert.deepEqual(serviceNowAuthSaveFields(empty, {
    servicenow_url: "https://sn.example", servicenow_auth_mode: "bearer_token", servicenow_token: "tok", servicenow_username: "svc", servicenow_client_id: "c",
  }), { servicenow_url: "https://sn.example", servicenow_auth_mode: "bearer_token", servicenow_token: "tok" });
  assert.deepEqual(serviceNowAuthSaveFields(empty, {
    servicenow_url: "https://sn.example", servicenow_auth_mode: "basic", servicenow_username: "svc", servicenow_password: "pw", servicenow_token: "tok",
  }), { servicenow_url: "https://sn.example", servicenow_auth_mode: "basic", servicenow_username: "svc", servicenow_password: "pw" });
  const oidc = {
    servicenow_url: "https://sn.example", servicenow_auth_mode: "oidc_client_credentials", servicenow_token_url: TOKEN_URL,
    servicenow_client_id: "client-a", servicenow_client_secret: "s3cret", servicenow_oidc_audience: "api", servicenow_password: "pw",
  };
  assert.deepEqual(serviceNowAuthView(empty, oidc).errors, {});
  assert.deepEqual(serviceNowAuthSaveFields(empty, oidc), {
    servicenow_url: "https://sn.example", servicenow_auth_mode: "oidc_client_credentials", servicenow_token_url: TOKEN_URL,
    servicenow_client_id: "client-a", servicenow_oidc_audience: "api", servicenow_client_secret: "s3cret",
  });
  // An explicit OIDC mode requires the token URL; nothing is prefilled for it.
  assert.match(serviceNowAuthView(empty, { ...oidc, servicenow_token_url: "" }).errors.servicenow_token_url.message, /Enter the token endpoint URL/);
  assert.deepEqual(SERVICENOW_OIDC_FIELDS.scope, "servicenow_oauth_scope");
  assert.deepEqual(serviceNowOwnedFields().sort(), SERVICENOW_FIELDS.filter((field) => field !== "servicenow_allowed_tables").sort());
});

test("ServiceNow: a changed method needs a new secret; the URL is https (http only on loopback)", () => {
  const oidc = servicenow({
    publicFields: { servicenow_auth_mode: "oidc_client_credentials", servicenow_client_id: "c" },
    secrets: { servicenow_client_secret: true, servicenow_token: true },
  });
  const view = serviceNowAuthView(oidc, { servicenow_url: "https://sn.example", servicenow_auth_mode: "bearer_token" });
  assert.equal(view.secretKeepable, false);
  assert.match(view.errors.servicenow_token.message, /^Enter a new bearer token: the sign-in method changes/);
  const single = servicenow({ secrets: { servicenow_token: true } });
  assert.equal(serviceNowAuthView(single, { servicenow_url: "https://sn.example", servicenow_auth_mode: "bearer_token" }).secretKeepable, true);
  assert.equal(serviceNowUrlProblem("https://sn.example"), null);
  assert.equal(serviceNowUrlProblem("http://127.0.0.1:8098"), null);
  assert.match(serviceNowUrlProblem("http://sn.example"), /must start with https:\/\//);
  assert.match(serviceNowUrlProblem("https://sn.example/?x=1"), /Remove the query string/);
  assert.match(serviceNowAuthView(single, { servicenow_url: "" }).errors.servicenow_url.message, /Enter the ServiceNow instance URL/);
});

test("connection tests: coded failures get plain-words hints; the Workspace connection appends them", () => {
  assert.match(testCodeHint("oidc_invalid_client"), /refused the client\. Check the client id, the client secret/);
  assert.match(testCodeHint("connector_unauthorized"), /technical user may lack access in the target system/);
  assert.match(testCodeHint("oidc_token_endpoint_redirect"), /never sent to a redirect target/);
  for (const code of ["oidc_token_endpoint_unreachable", "oidc_unauthorized_client", "oidc_bad_response", "oidc_token_url_invalid"]) assert.ok(testCodeHint(code), code);
  assert.equal(testCodeHint("something_else"), null);
  // The backend's shape (connector_test/collab.py): `auth_code` with the fixed message in summary and auth_hint.
  assert.equal(testResultHint({ ok: false, summary: "Jira: no access token.", auth_code: "oidc_bad_response", auth_hint: "no access token." }), testCodeHint("oidc_bad_response"));
  assert.equal(testResultHint({ ok: false, summary: `Failed. ${testCodeHint("oidc_bad_response")}`, auth_code: "oidc_bad_response" }), null, "never twice");
  assert.equal(testResultHint({ ok: false, summary: "Failed.", code: "oidc_bad_response" }), null, "only the backend's auth_code counts");
  assert.equal(testResultHint(null), null);
  assert.deepEqual(testResultText({ ok: false, summary: "The identity provider refused the token request.", auth_code: "oidc_invalid_client" }), {
    ok: false, text: `The identity provider refused the token request. ${testCodeHint("oidc_invalid_client")}`,
  });
});

test("no real host, realm or client id in the new sign-in sources; placeholders are neutral or empty", () => {
  for (const file of ["oidcClientCredentialsModel.ts", "OidcClientCredentialsFields.tsx", "serviceNowAuthModel.ts", "ServiceNowConnectorSetupFields.tsx"]) {
    const source = fs.readFileSync(path.join(SRC, "admin/components/connectorsTab", file), "utf8");
    assert.doesNotMatch(source, /[a-z0-9-]+\.(com|net|io|de|ch|org|cloud)\b/i, `${file} names a host`);
    assert.doesNotMatch(source, /realms\//, `${file} names a realm path`);
    for (const [, placeholder] of source.matchAll(/placeholder="([^"]*)"/g)) assert.ok(["", "https://"].includes(placeholder), `${file}: ${placeholder}`);
  }
});

// ---- rendered -----------------------------------------------------------------------------------

function makeLoader(stubs, extra = {}) {
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
      window: { setTimeout: () => 0, confirm: () => true }, ...extra,
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

function openedDraft(connector) {
  const draft = {};
  for (const [key, value] of Object.entries(connector.public_fields)) draft[key] = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  return draft;
}

function mountCard(connector, testResult = null) {
  const { ConfiguredConnectorCard } = loadModule("admin/components/connectorsTab/ConfiguredConnectorCard.tsx");
  let draft = openedDraft(connector);
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
  const id = (field) => `connector-field-${connector.tool_name}-${field}`;
  const input = (field) => view.root.findAll((node) => (node.type === "input" || node.type === "select") && node.props.id === id(field))[0] ?? null;
  const radio = (name, value) => view.root.find((node) => node.type === "input" && node.props.type === "radio" && node.props.name === id(name) && node.props.value === value);
  return {
    root: () => view.root, input, radio,
    choose: (name, value) => act(() => radio(name, value).props.onChange()),
    type: (field, value) => act(() => input(field).props.onChange({ target: { value } })),
    save: async () => { await act(async () => { view.root.find((node) => node.type === "button" && text(node) === "Save").props.onClick(); }); },
    saves,
  };
}

const CONFLUENCE = {
  tool_name: "confluence", label: "Confluence", description: "Confluence", supports_test: true,
  fields: ["confluence_url", "confluence_auth_mode", "confluence_username", "confluence_password", "confluence_token", "confluence_allowed_spaces"],
  secret_fields: ["confluence_password", "confluence_token"], builtin_tools: [], tools: [], tool_policy: POLICY, is_active: true,
  policy_active: true, configured: false, public_fields: { confluence_url: "", confluence_allowed_spaces: [] },
  secret_status: {}, db_id: null, policy_id: null,
};

test("rendered Confluence: own instance offers OpenID Connect with only its fields, neutral placeholders, and saves them", async () => {
  const card = mountCard(CONFLUENCE);
  card.type("confluence_url", "https://wiki.example");
  card.choose("confluence_auth_mode", "own");
  assert.deepEqual(card.root().findAll((node) => node.type === "input" && node.props.name === "connector-field-confluence-__confluence_auth_location")
    .map((node) => node.props.value), ["basic", "bearer_pat", "oidc_client_credentials"]);
  card.choose("__confluence_auth_location", "oidc_client_credentials");
  const shown = ["confluence_oidc_token_url", "confluence_oidc_client_id", "confluence_oidc_client_secret", "confluence_oidc_scope",
    "confluence_oidc_audience", "confluence_oidc_client_auth"];
  for (const field of shown) assert.ok(card.input(field), field);
  for (const field of ["confluence_username", "confluence_password", "confluence_token"]) assert.equal(card.input(field), null, field);
  assert.equal(card.input("confluence_oidc_token_url").props.placeholder, "https://");
  assert.equal(card.input("confluence_oidc_client_id").props.placeholder, "");
  assert.equal(card.input("confluence_oidc_client_secret").props.type, "password");
  assert.match(text(card.root()), /Token endpoint of your identity provider \(OpenID Connect\)\./);
  assert.deepEqual(card.input("confluence_oidc_client_auth").findAllByType("option").map((option) => option.props.value), ["", "client_secret_post", "client_secret_basic"]);
  await card.save();
  assert.equal(card.saves.length, 0, "an incomplete method is not saved");
  card.type("confluence_oidc_token_url", TOKEN_URL);
  card.type("confluence_oidc_client_id", "client-a");
  card.type("confluence_oidc_client_secret", "s3cret");
  card.type("confluence_oidc_client_auth", "client_secret_basic");
  await card.save();
  assert.deepEqual(card.saves[0], {
    is_active: true, confluence_url: "https://wiki.example", confluence_auth_mode: "oidc_client_credentials",
    confluence_oidc_client_id: "client-a", confluence_oidc_client_secret: "s3cret", confluence_oidc_token_url: TOKEN_URL,
    confluence_oidc_client_auth: "client_secret_basic", confluence_allowed_spaces: [], tool_policy: POLICY, policy_active: true,
  });
});

test("rendered ServiceNow: a row without a saved method saves only after one is chosen; a method shows only its fields", async () => {
  const card = mountCard(servicenow({ publicFields: { servicenow_username: "svc" }, secrets: { servicenow_password: true } }));
  assert.equal(card.root().findAll((node) => node.type === "input" && node.props.type === "radio"
    && node.props.name?.endsWith("servicenow_auth_mode") && node.props.checked).length, 0, "no method is preselected");
  for (const field of ["servicenow_username", "servicenow_password", "servicenow_token", "servicenow_client_id"]) assert.equal(card.input(field), null, field);
  assert.match(text(card.root()), /ScopeAssignment groups.*Allowed tables/s, "the table allowlist is in the Scope group");
  assert.deepEqual(card.root().findAll((node) => node.type === "fieldset").map((node) => node.props["data-group"]),
    ["connection", "authentication", "scope"], "one Scope group: the allowed tables are not a nested group");
  assert.doesNotMatch(text(card.root()), /servicenow client id|servicenow token url/, "no raw sign-in field in the generic panel");
  await card.save();
  assert.equal(card.saves.length, 0, "not saved without a method");
  assert.match(text(card.root()), /Choose how ServiceNow signs in\./);

  card.choose("servicenow_auth_mode", "bearer_token");
  assert.ok(card.input("servicenow_token"));
  assert.equal(card.input("servicenow_username"), null);
  card.choose("servicenow_auth_mode", "oidc_client_credentials");
  for (const field of ["servicenow_token_url", "servicenow_client_id", "servicenow_client_secret", "servicenow_oauth_scope",
    "servicenow_oidc_audience", "servicenow_oidc_client_auth"]) assert.ok(card.input(field), field);
  assert.equal(card.input("servicenow_token"), null);
  const before = card.saves.length;
  await card.save();
  assert.equal(card.saves.length, before, "an incomplete method is not saved");
  assert.match(text(card.root()), /Not saved: fix the highlighted fields\./);
  card.type("servicenow_token_url", TOKEN_URL);
  card.type("servicenow_client_id", "client-a");
  card.type("servicenow_client_secret", "s3cret");
  await card.save();
  const body = card.saves.at(-1);
  assert.deepEqual([body.servicenow_auth_mode, body.servicenow_token_url, body.servicenow_client_id, body.servicenow_client_secret],
    ["oidc_client_credentials", TOKEN_URL, "client-a", "s3cret"]);
  assert.equal("servicenow_username" in body || "servicenow_password" in body || "servicenow_token" in body, false);
});

test("rendered ServiceNow: a typed secret is cleared when the method changes; the test shows the coded hint", async () => {
  const card = mountCard(servicenow({ configured: true, publicFields: { servicenow_auth_mode: "bearer_token" }, secrets: { servicenow_token: true } }),
    { ok: false, summary: "The token request failed.", auth_code: "oidc_invalid_client" });
  card.choose("servicenow_auth_mode", "basic");
  card.type("servicenow_password", "pw");
  card.choose("servicenow_auth_mode", "bearer_token");
  card.choose("servicenow_auth_mode", "basic");
  assert.equal(card.input("servicenow_password").props.value, "", "the password typed for another method is gone");
  assert.equal(text(card.root().find((node) => node.props["data-testid"] === "connector-test-hint")), testCodeHint("oidc_invalid_client"));
});

test("rendered Workspace own Jira connection: OpenID Connect is offered and tested with only its fields", async () => {
  const load = makeLoader({});
  const { WorkspaceConnectorConnection } = load("admin/components/projectsTab/WorkspaceConnectorConnection.tsx");
  const calls = [];
  const readJson = async (url, init = {}) => {
    calls.push({ url, method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null });
    if (url.endsWith("/connection/test")) return { ok: false, summary: "The target system refused the token.", auth_code: "connector_unauthorized" };
    return { connector_name: "jira", source: "global", fields: {}, secret_status: {}, global: { configured: true, active: true, fields: {}, secret_status: {} }, health: null };
  };
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(WorkspaceConnectorConnection, {
      projectId: "ws-1", connectorName: "jira", product: "jira", label: "Jira", readJson, onReadyChange: () => {},
    }));
  });
  try {
    const find = (predicate) => view.root.findAll(predicate)[0];
    const choose = (name, value) => act(() => find((node) => node.type === "input" && node.props.name === name && node.props.value === value).props.onChange());
    const type = (field, value) => act(() => find((node) => node.props.id === `connector-field-jira-${field}`).props.onChange({ target: { value } }));
    choose("jira-connection", "own");
    choose("connector-field-jira-jira_auth_mode", "own");
    choose("connector-field-jira-__jira_auth_location", "oidc_client_credentials");
    type("jira_url", "https://jira.example");
    type("jira_oidc_token_url", TOKEN_URL);
    type("jira_oidc_client_id", "client-a");
    type("jira_oidc_client_secret", "s3cret");
    type("jira_oidc_scope", "read");
    await act(async () => { find((node) => node.type === "button" && text(node).trim() === "Test connection").props.onClick(); });
    const testCall = calls.filter((call) => call.method === "POST").at(-1);
    assert.deepEqual(testCall.body, {
      source: "workspace", jira_url: "https://jira.example", jira_auth_mode: "oidc_client_credentials", jira_oidc_client_id: "client-a",
      jira_oidc_client_secret: "s3cret", jira_oidc_token_url: TOKEN_URL, jira_oidc_scope: "read",
    });
    assert.equal(text(find((node) => node.props["data-testid"] === "workspace-connection-message")),
      `The target system refused the token. ${testCodeHint("connector_unauthorized")}`);
  } finally { act(() => view.unmount()); }
});
