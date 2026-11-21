// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/atlassianAuthModes.test.mjs
//
// Atlassian sign-in modes (frozen contract): `confluence_auth_mode` / `jira_auth_mode` is
// cloud_api_token | basic | bearer_pat. Each mode sends only its own principal and secret (Bearer never
// a principal, never another mode's secret); a saved row without a mode names no method and is kept unchanged
// until the admin picks one; an Atlassian Cloud URL suggests Cloud; a Confluence Cloud URL must end with /wiki.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { atlassianAuthSaveFields } from "../../src/admin/components/connectorsTab/atlassianAuthModel.ts";
import { atlassianAuthView } from "../../src/admin/components/connectorsTab/atlassianAuthView.ts";
import { authModeFields, authOwnedFields, storedAuthMode } from "../../src/admin/components/connectorsTab/atlassianAuthModes.ts";
import { buildConnectorSaveBody } from "../../src/admin/hooks/connectorSaveBody.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.requestAnimationFrame = (callback) => callback();

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const POLICY = { tool_instructions: "", extra_tools: [], disabled_tools: [] };

const CONFLUENCE_FIELDS = [
  "confluence_url", "confluence_auth_mode", "confluence_username", "confluence_password", "confluence_token",
  "confluence_allowed_spaces", "confluence_allowed_pages",
];

function confluence({ publicFields = {}, secrets = {}, configured = true } = {}) {
  return {
    tool_name: "confluence", label: "Confluence", description: "Confluence Cloud or Server/Data Center",
    fields: CONFLUENCE_FIELDS, secret_fields: ["confluence_password", "confluence_token"], supports_test: true,
    builtin_tools: [], tools: [], tool_policy: POLICY, is_active: true, policy_active: true, configured,
    public_fields: { confluence_url: "https://wiki.acme.test", confluence_allowed_spaces: ["ENG"], ...publicFields },
    secret_status: { confluence_password: false, confluence_token: false, ...secrets }, db_id: null, policy_id: null,
  };
}

function jira({ publicFields = {}, secrets = {} } = {}) {
  return {
    tool_name: "jira", fields: ["jira_url", "jira_auth_mode", "jira_email", "jira_token", "jira_username", "jira_password"],
    secret_fields: ["jira_token", "jira_password"], configured: true,
    public_fields: { jira_url: "https://jira.acme.test", ...publicFields },
    secret_status: { jira_token: false, jira_password: false, ...secrets },
  };
}

function openedDraft(connector) {
  const draft = {};
  for (const [key, value] of Object.entries(connector.public_fields)) {
    draft[key] = typeof value === "string" ? value : JSON.stringify(value, null, 2);
  }
  return draft;
}

// ---- contract ---------------------------------------------------------------------------------

test("each mode names exactly the contract's principal and secret", () => {
  const pairs = (product) => ["cloud_api_token", "basic", "bearer_pat"].map((mode) => {
    const { principal, secret } = authModeFields(product, mode);
    return [mode, principal, secret];
  });
  assert.deepEqual(pairs("confluence"), [
    ["cloud_api_token", "confluence_username", "confluence_token"],
    ["basic", "confluence_username", "confluence_password"],
    ["bearer_pat", null, "confluence_token"],
  ]);
  assert.deepEqual(pairs("jira"), [
    ["cloud_api_token", "jira_email", "jira_token"],
    ["basic", "jira_username", "jira_password"],
    ["bearer_pat", null, "jira_token"],
  ]);
  // Added the OpenID Connect client-credentials fields to the guided sign-in.
  assert.deepEqual(authOwnedFields("confluence").sort(), [
    "confluence_auth_mode", "confluence_oidc_audience", "confluence_oidc_client_auth", "confluence_oidc_client_id",
    "confluence_oidc_client_secret", "confluence_oidc_scope", "confluence_oidc_token_url", "confluence_password",
    "confluence_token", "confluence_url", "confluence_username",
  ]);
});

test("the saved method is read from the field only; none and unknown are distinct", () => {
  assert.equal(storedAuthMode("jira", jira({ publicFields: { jira_auth_mode: "bearer_pat" } })), "bearer_pat");
  assert.equal(storedAuthMode("jira", jira({ publicFields: { jira_email: "a@b.c" } })), "none", "credentials without a mode name no method");
  assert.equal(storedAuthMode("jira", jira({ secrets: { jira_password: true } })), "none");
  assert.equal(storedAuthMode("jira", jira()), "none");
  for (const raw of ["oauth", "BASIC", " basic", 7, true]) {
    assert.equal(storedAuthMode("jira", jira({ publicFields: { jira_auth_mode: raw } })), "unknown", String(raw));
  }
});

test("a method sends only its own fields: Bearer never a principal, never another method's secret", () => {
  for (const product of ["confluence", "jira"]) {
    const connector = product === "confluence" ? confluence({ configured: false }) : jira();
    const url = product === "confluence" ? "https://wiki.acme.test" : "https://jira.acme.test";
    const typedEverything = {
      [`${product}_url`]: url, confluence_username: "svc", jira_email: "a@b.c", jira_username: "svc",
      confluence_password: "pw", confluence_token: "tok", jira_password: "pw", jira_token: "tok",
    };
    const body = (mode) => atlassianAuthSaveFields(product, connector, { ...typedEverything, [`${product}_auth_mode`]: mode });
    const secretOf = (mode) => authModeFields(product, mode).secret;
    assert.deepEqual(Object.keys(body("bearer_pat")).sort(), [`${product}_auth_mode`, `${product}_url`, secretOf("bearer_pat")].sort());
    for (const mode of ["cloud_api_token", "basic"]) {
      const { principal, secret } = authModeFields(product, mode);
      assert.deepEqual(Object.keys(body(mode)).sort(), [`${product}_auth_mode`, `${product}_url`, principal, secret].sort(), `${product} ${mode}`);
    }
  }
});

test("a connector without a saved mode needs an explicit method; the chosen method may keep its stored secret", () => {
  const unset = confluence({ publicFields: { confluence_username: "svc" }, secrets: { confluence_password: true } });
  const view = atlassianAuthView("confluence", unset, openedDraft(unset));
  assert.equal(view.stored, "none");
  assert.deepEqual(view.errors, { confluence_auth_mode: { message: "Choose how Confluence signs in.", live: false } });
  const basic = { ...openedDraft(unset), confluence_auth_mode: "basic" };
  assert.deepEqual(atlassianAuthView("confluence", unset, basic).errors, {}, "the stored password is kept");
  assert.deepEqual(atlassianAuthSaveFields("confluence", unset, basic), {
    confluence_url: "https://wiki.acme.test", confluence_auth_mode: "basic", confluence_username: "svc",
  });
  const pat = { ...openedDraft(unset), confluence_auth_mode: "bearer_pat" };
  assert.match(atlassianAuthView("confluence", unset, pat).errors.confluence_token.message, /Enter the personal access token/);
});

test("Cloud is suggested for an atlassian.net URL; a Confluence Cloud URL must end with /wiki", () => {
  const fresh = confluence({ configured: false, publicFields: { confluence_url: "" } });
  const view = (draft) => atlassianAuthView("confluence", fresh, draft);
  assert.equal(view({ confluence_url: "https://acme.atlassian.net/wiki", __confluence_auth_location: "own" }).cloudSuggested, true);
  assert.equal(view({ confluence_url: "https://acme.atlassian.net/wiki" }).cloudSuggested, true, "also before any choice");
  assert.equal(view({ confluence_url: "https://acme.atlassian.net/wiki", confluence_auth_mode: "cloud_api_token" }).cloudSuggested, false);
  assert.equal(view({ confluence_url: "https://wiki.acme.test", __confluence_auth_location: "own" }).cloudSuggested, false);
  assert.equal(view({ confluence_url: "https://evil.test/acme.atlassian.net" }).cloudSuggested, false, "the host decides, not the path");

  const cloud = (url) => view({ confluence_url: url, confluence_auth_mode: "cloud_api_token", confluence_username: "a@b.c", confluence_token: "t" }).errors.confluence_url;
  assert.match(cloud("https://acme.atlassian.net").message, /ends with \/wiki/);
  assert.equal(cloud("https://acme.atlassian.net").live, true);
  assert.equal(cloud("https://acme.atlassian.net/wiki"), undefined);
  assert.equal(cloud("https://acme.atlassian.net/wiki/"), undefined);
  assert.equal(cloud("https://wiki.acme.test"), undefined, "an own domain is not checked");
  const jiraCloud = atlassianAuthView("jira", jira(), { jira_url: "https://acme.atlassian.net", jira_auth_mode: "cloud_api_token", jira_email: "a@b.c", jira_token: "t" });
  assert.deepEqual(jiraCloud.errors, {}, "Jira Cloud has no /wiki");
});

test("an unknown saved method or an own instance without a method blocks the save", () => {
  const unknown = confluence({ publicFields: { confluence_auth_mode: "oauth" } });
  const view = atlassianAuthView("confluence", unknown, openedDraft(unknown));
  assert.equal(view.errors.confluence_auth_mode.live, true);
  assert.equal("confluence_auth_mode" in atlassianAuthSaveFields("confluence", unknown, openedDraft(unknown)), false, "never echoed back");
  const own = atlassianAuthView("confluence", confluence({ configured: false }), { confluence_url: "https://wiki.acme.test", __confluence_auth_location: "own" });
  assert.match(own.errors.confluence_auth_mode.message, /Choose how your own instance signs in/);
});

// ---- rendered Confluence card --------------------------------------------------------------------

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
      module, exports: module.exports, URL, URLSearchParams, console, requestAnimationFrame: globalThis.requestAnimationFrame,
      document: { getElementById: () => null }, require: (name) => resolve(name, path.dirname(file)),
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

function mountCard(connector) {
  const { ConfiguredConnectorCard } = loadModule("admin/components/connectorsTab/ConfiguredConnectorCard.tsx");
  let draft = openedDraft(connector);
  const saves = [];
  let view;
  const ctx = {
    CONNECTOR_COLORS: {}, connectorHealthHistory: {}, connectorTestResult: {}, connectorSaving: null, connectorTesting: null,
    expandedConnector: connector.tool_name,
    getConnectorDraft: () => draft,
    setConnectorField: (_tool, field, value) => {
      draft = { ...draft, [field]: value };
      act(() => view.update(render()));
    },
    handleSaveConnector: async (toolName, saved, confirmedBody) => {
      saves.push(confirmedBody || buildConnectorSaveBody(saved, draft, POLICY));
      return { state: "saved" };
    },
    handleTestConnector: async () => {},
  };
  const render = () => createElement(ConfiguredConnectorCard, { connector, ctx });
  act(() => { view = TestRenderer.create(render()); });
  const id = (field) => `connector-field-${connector.tool_name}-${field}`;
  const has = (field) => view.root.findAll((node) => typeof node.type === "string" && node.props?.id === id(field)).length > 0;
  const radio = (name, value) => view.root.find((node) => node.type === "input" && node.props.type === "radio"
    && node.props.name === id(name) && node.props.value === value);
  const choose = (name, value) => act(() => radio(name, value).props.onChange());
  const type = (field, value) => act(() => view.root.find((node) => node.props?.id === id(field)).props.onChange({ target: { value } }));
  const save = async () => { await act(async () => { view.root.find((node) => node.type === "button" && text(node) === "Save").props.onClick(); }); };
  return { root: () => view.root, has, radio, choose, type, save, saves };
}

test("rendered: a Confluence row without a saved mode shows no sign-in inputs and saves only after a method is chosen", async () => {
  const card = mountCard(confluence({ publicFields: { confluence_username: "svc" }, secrets: { confluence_token: true } }));
  assert.equal(card.root().findAll((node) => node.type === "input" && node.props.type === "radio" && node.props.checked).length, 0,
    "no method is preselected");
  assert.match(text(card.root()), /No sign-in method is saved yet\./);
  for (const field of ["confluence_username", "confluence_password", "confluence_token"]) assert.equal(card.has(field), false, field);
  assert.match(text(card.root()), /ScopeAllowed spacesENG×/, "the allowed spaces are tags in the Scope group (delivery 5)");
  assert.doesNotMatch(text(card.root()), /confluence auth mode|confluence username/, "no raw sign-in field in the generic panel");
  await card.save();
  assert.equal(card.saves.length, 0);
  assert.match(text(card.root()), /Choose how Confluence signs in\./);
});

test("rendered: own instance with a personal access token shows only the token and sends Bearer fields", async () => {
  const card = mountCard(confluence({ configured: false, publicFields: { confluence_url: "", confluence_allowed_spaces: [] } }));
  card.type("confluence_url", "https://wiki.acme.test");
  card.choose("confluence_auth_mode", "own");
  await card.save();
  assert.equal(card.saves.length, 0);
  assert.match(text(card.root()), /Choose how your own instance signs in\./);
  card.choose("__confluence_auth_location", "bearer_pat");
  assert.equal(card.has("confluence_username"), false, "a token needs no username");
  assert.equal(card.has("confluence_token"), true);
  card.type("confluence_token", "pat-123");
  await card.save();
  assert.equal(card.saves.length, 1);
  const body = card.saves[0];
  assert.deepEqual([body.confluence_url, body.confluence_auth_mode, body.confluence_token], ["https://wiki.acme.test", "bearer_pat", "pat-123"]);
  assert.equal("confluence_username" in body || "confluence_password" in body, false);
});

test("rendered: an atlassian.net URL suggests Cloud; Cloud asks for email and API token and /wiki", async () => {
  const card = mountCard(confluence({ configured: false, publicFields: { confluence_url: "", confluence_allowed_spaces: [] } }));
  card.type("confluence_url", "https://acme.atlassian.net");
  assert.ok(card.root().find((node) => node.props?.["data-testid"] === "confluence-cloud-suggestion"));
  card.choose("confluence_auth_mode", "cloud");
  assert.equal(card.root().findAll((node) => node.props?.["data-testid"] === "confluence-cloud-suggestion").length, 0);
  assert.match(text(card.root()), /A Confluence Cloud URL ends with \/wiki/);
  card.type("confluence_url", "https://acme.atlassian.net/wiki");
  card.type("confluence_username", "bot@acme.test");
  card.type("confluence_token", "api-token");
  await card.save();
  const body = card.saves[0];
  assert.deepEqual([body.confluence_auth_mode, body.confluence_username, body.confluence_token], ["cloud_api_token", "bot@acme.test", "api-token"]);
  assert.equal("confluence_password" in body, false);
});
