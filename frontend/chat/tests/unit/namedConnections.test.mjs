// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/namedConnections.test.mjs
//
// Named connections: Workspace → Connectors → Confluence/Jira/ServiceNow lists several accounts, each
// bound to its spaces/projects/tables, beside the "Default" (the Workspace connection). Add/edit/test/delete per
// connection; secrets are write-only (only "Credential stored" is shown, never a value); a name or scope clash is
// shown before any request; delete asks first; a server without the API shows nothing.
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
import { boundElsewhere, nameProblem, namedAsConnector, namedDraft, parseScopes, scopesProblem } from "../../src/admin/components/namedConnections/namedConnectionsForm.ts";
import { namedConnectionsUrl, namedConnector, parseNamedConnections } from "../../src/admin/components/namedConnections/namedConnectionsParse.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

const TEAM = {
  id: "c-1", name: "client-a", connector_name: "confluence", scope: "workspace", bound_scopes: ["TEAM"],
  fields: { confluence_url: "https://wiki.example.test/wiki", confluence_auth_mode: "bearer_pat" },
  secret_status: { confluence_token: true, confluence_password: false },
};
const LIST = { connector_name: "confluence", descriptor: DESCRIPTORS.confluence, default: { name: "default", configured: true, active: true, fields: {} },
  connections: [TEAM] };

test("the list is read strictly; drafts and connector views never carry a secret", () => {
  assert.equal(parseNamedConnections(null), null);
  assert.equal(parseNamedConnections({ connections: "x" }), null);
  const parsed = parseNamedConnections({ ...LIST, connections: [TEAM, { id: 3 }, { ...TEAM, id: "c-2", secret_status: { confluence_token: "yes" } }] });
  assert.equal(parsed.connections.length, 2, "an entry without id and name is dropped");
  assert.deepEqual(parsed.connections[1].secretStatus, { confluence_token: false }, "only true counts as stored");
  assert.equal(parsed.defaultActive, true);
  assert.deepEqual(namedDraft(parsed.connections[0]), TEAM.fields);
  assert.deepEqual(namedDraft(parsed.connections[0] && { ...parsed.connections[0], publicFields: { confluence_token: 7 } }), {});
  assert.equal(namedAsConnector("confluence", null).tool_name, "confluence-named", "own input ids beside the Workspace form");
  assert.equal(namedConnectionsUrl("ws 1", "jira", "c/1", "/test"),
    "/admin/chat/api/panel/projects/ws%201/connectors/jira/named-connections/c%2F1/test");
  assert.equal(namedConnector("pagerduty", D), null, "a connector without a server descriptor has no named connections");
  assert.equal(namedConnector("servicenow", D).connector, "servicenow");
  assert.equal(namedConnector("confluence", null), null, "nothing before the registry is known");
  assert.equal(parseNamedConnections({ ...LIST, descriptor: undefined }), null, "a list without its descriptor is not read");
});

test("scopes are canonical; names and clashes are explained before saving", () => {
  assert.deepEqual(parseScopes(D.confluence, "team, DOC17 team"), ["TEAM", "DOC17"]);
  assert.deepEqual(parseScopes(D.servicenow, "Incident"), ["incident"]);
  assert.equal(scopesProblem(D.confluence, " , "), "Enter at least one space this connection serves.");
  assert.match(scopesProblem(D.jira, "OPS, 1X"), /"1X" is not a valid project key/);
  assert.equal(scopesProblem(D.confluence, "~jdoe"), null);
  const connections = parseNamedConnections(LIST).connections;
  assert.deepEqual(boundElsewhere(D.confluence, connections, null, "team, ENG"), ["TEAM (client-a)"]);
  assert.deepEqual(boundElsewhere(D.confluence, connections, "c-1", "team"), [], "its own binding is no clash");
  assert.match(nameProblem("Default", connections, null), /"default" is the connector's own connection/);
  assert.match(nameProblem("CLIENT-A", connections, null), /already has this name/);
  assert.equal(nameProblem("client-a", connections, "c-1"), null);
  assert.match(nameProblem("-x", connections, null), /letters, digits/);
});

function load(relative) {
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
      window: { setTimeout: () => 0 },
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

const failure = (message, status) => Object.assign(new Error(message), status === undefined ? {} : { status });

function server(initial = LIST, { supported = true, testResult = { ok: true, summary: "Connected." } } = {}) {
  const calls = [];
  let stored = structuredClone(initial);
  const readJson = async (url, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ url, method: init.method || "GET", body });
    if (!supported) throw failure("Not Found", 404);
    if (url.endsWith("/test")) return testResult;
    if (init.method === "POST") {
      const created = { id: "c-new", name: body.name, bound_scopes: body.bound_scopes,
        fields: { confluence_url: body.confluence_url, confluence_auth_mode: body.confluence_auth_mode },
        secret_status: { confluence_token: Boolean(body.confluence_token) } };
      stored = { ...stored, connections: [...stored.connections, created] };
      return created;
    }
    if (init.method === "DELETE") {
      stored = { ...stored, connections: stored.connections.filter((item) => !url.endsWith(`/${item.id}`)) };
      return { status: "deleted" };
    }
    return stored;
  };
  return { readJson, calls };
}

async function mount(srv, connector = "confluence") {
  const { NamedConnections } = load("admin/components/namedConnections/NamedConnections.tsx");
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(NamedConnections, {
      projectId: "ws-1", connector, label: "Confluence", readJson: srv.readJson,
    }));
  });
  const find = (predicate) => view.root.findAll(predicate)[0] ?? null;
  const id = (field) => `connector-field-${connector}-named-${field}`;
  return {
    view,
    all: () => (view.toJSON() ? text(view.root) : ""),
    type: (field, value) => act(() => find((node) => node.type === "input" && node.props.id === id(field)).props.onChange({ target: { value } })),
    radio: (value) => act(() => find((node) => node.type === "input" && node.props.type === "radio" && node.props.value === value).props.onChange()),
    click: async (label, index = 0) => {
      const buttons = view.root.findAll((node) => node.type === "button" && text(node).trim() === label);
      await act(async () => { buttons[index].props.onClick(); });
    },
    has: (testId) => Boolean(find((node) => node.props["data-testid"] === testId)),
    // The bound keys are tags (delivery 5): a separator commits the typed keys, × removes one.
    removeTag: (label) => act(() => find((node) => node.type === "button" && node.props["aria-label"] === label).props.onClick()),
  };
}

test("the list shows the default and each connection with its spaces, never a secret", async () => {
  const ui = await mount(server());
  assert.match(ui.all(), /Default · the Workspace connection above/);
  assert.match(ui.all(), /client-aID c-1Copy ID/);
  assert.match(ui.all(), /Personal access token · Spaces: TEAM · Credential stored · Not tested since the last change/);
  assert.doesNotMatch(ui.all(), /secret_ref|bearer_pat/, "the auth mode is shown in words, never a field name");
});

test("add: an incomplete or clashing connection sends nothing; a complete one is created", async () => {
  const srv = server();
  const ui = await mount(srv);
  await ui.click("Add connection");
  ui.type("name", "client-b");
  ui.type("scopes", "DOC17, team ");
  const tags = ui.view.root.findAll((node) => node.props.className?.startsWith?.("key-tags__tag")).map((node) => node.props["data-key"]);
  assert.deepEqual(tags, ["DOC17", "TEAM"], "one tag per key, in the binding's canonical case");
  await ui.click("Save connection");
  assert.equal(srv.calls.filter((call) => call.method !== "GET").length, 0);
  assert.match(ui.all(), /Already bound by another connection: TEAM \(client-a\)\./);

  ui.type("confluence_url", "https://wiki.example.test/wiki");
  ui.radio("own");
  ui.radio("bearer_pat");
  ui.type("confluence_token", "typed-pat");
  await ui.click("Save connection");
  assert.equal(srv.calls.filter((call) => call.method !== "GET").length, 0, "a complete sign-in with a clash sends nothing");

  ui.removeTag("Remove space TEAM");
  await ui.click("Save connection");
  const post = srv.calls.find((call) => call.method === "POST");
  assert.equal(post.url, "/admin/chat/api/panel/projects/ws-1/connectors/confluence/named-connections");
  assert.deepEqual(post.body, {
    name: "client-b", bound_scopes: ["DOC17"], confluence_url: "https://wiki.example.test/wiki",
    confluence_auth_mode: "bearer_pat", confluence_token: "typed-pat",
  });
  assert.match(ui.all(), /Saved the Confluence connection "client-b"/);
  assert.match(ui.all(), /client-bID c-new/);
  assert.match(ui.all(), /Spaces: DOC17 · Credential stored/);
  assert.doesNotMatch(ui.all(), /typed-pat/, "a typed secret is never shown back");
});

test("test runs on the stored connection; delete asks first and then removes it", async () => {
  const srv = server();
  const ui = await mount(srv);
  await ui.click("Test");
  const testCall = srv.calls.find((call) => call.url.endsWith("/test"));
  assert.deepEqual([testCall.method, testCall.url, testCall.body],
    ["POST", "/admin/chat/api/panel/projects/ws-1/connectors/confluence/named-connections/c-1/test", {}]);
  assert.match(ui.all(), /client-a: Connected\./);

  await ui.click("Delete");
  assert.ok(ui.has("named-connection-confirm-delete"));
  assert.equal(srv.calls.filter((call) => call.method === "DELETE").length, 0, "nothing deleted before confirming");
  await ui.click("Delete connection");
  assert.equal(srv.calls.filter((call) => call.method === "DELETE")[0].url,
    "/admin/chat/api/panel/projects/ws-1/connectors/confluence/named-connections/c-1");
  assert.doesNotMatch(ui.all(), /ID c-1/);
});

test("a server refusal is shown in its own words; a failed load is an error", async () => {
  const refusing = server();
  const original = refusing.readJson;
  refusing.readJson = async (url, init = {}) => {
    if (init.method === "PUT") throw failure("Already bound by another connection: TEAM (client-z).", 409);
    return original(url, init);
  };
  const ui = await mount(refusing);
  await ui.click("Edit");
  ui.type("name", "client-a2");
  await ui.click("Save connection");
  assert.match(ui.all(), /Already bound by another connection: TEAM \(client-z\)\./);

  const failed = await mount(server(LIST, { supported: false }));
  assert.match(failed.all(), /Named connections could not be loaded\. Nothing was changed\./);
});

test("ServiceNow uses the same list with tables and its own sign-in fields", async () => {
  const srv = server({ connector_name: "servicenow", descriptor: DESCRIPTORS.servicenow, default: { configured: false, active: false }, connections: [] });
  const ui = await mount(srv, "servicenow");
  assert.match(ui.all(), /Default · the Workspace connection above \(not enabled for this Workspace\)/);
  await ui.click("Add connection");
  assert.match(ui.all(), /Tables served by this connection/);
  assert.match(ui.all(), /ServiceNow URL/);
});

// A connector type the UI has never seen: everything comes from its descriptor (generic form, delivery 3).
const EXAMPLE = {
  connector_name: "examplecloud", label: "Example Cloud",
  binding: { label: "account", plural: "Accounts", pattern: "[0-9]{4}", case: "exact", example: "1234", hierarchical: false },
  fields: [
    { name: "ex_url", label: "API URL", kind: "url", required: true, options: [], placeholder: "" },
    { name: "ex_verify", label: "Verify TLS", kind: "bool", required: false, options: [], placeholder: "" },
    { name: "ex_regions", label: "Regions", kind: "list", required: false, options: [], placeholder: "" },
    { name: "ex_key", label: "API key", kind: "secret", required: true, options: [], placeholder: "" },
  ],
  url_field: "ex_url", form: "fields", testable: false, unscoped: "single",
};

test("a new connector type is rendered from its descriptor alone: fields by kind, secrets write-only", async () => {
  const stored = { id: "x-1", name: "acct-a", scope: "workspace", bound_scopes: ["1234"],
    fields: { ex_url: "https://api.example.test", ex_verify: false, ex_regions: ["eu", "us"] },
    secret_status: { ex_key: true }, last_test: null, usage: null };
  const calls = [];
  const readJson = async (url, init = {}) => {
    calls.push({ url, method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null });
    if (init.method === "PUT" || init.method === "POST") return { ...stored, name: "acct-a" };
    return { connector_name: "examplecloud", descriptor: EXAMPLE, default: { configured: false, active: false },
      connections: [stored] };
  };
  const { NamedConnections } = load("admin/components/namedConnections/NamedConnections.tsx");
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(NamedConnections, {
      projectId: null, connector: "examplecloud", label: "Example Cloud", readJson }));
  });
  const all = () => text(view.root);
  assert.match(all(), /Accounts: 1234 · Credential stored/);
  assert.equal(view.root.findAll((node) => node.type === "button" && text(node) === "Test").length, 0,
    "no test button for a connector without a connection test");
  const button = (label) => view.root.findAll((node) => node.type === "button" && text(node).trim() === label)[0];
  await act(async () => { button("Add connection").props.onClick(); });
  await act(async () => { button("Cancel").props.onClick(); });
  await act(async () => { button("Edit").props.onClick(); });
  const input = (field) => view.root.findAll((node) => (node.type === "input" || node.type === "select")
    && node.props.id === `connector-field-examplecloud-named-${field}`)[0];
  assert.equal(input("ex_url").props.value, "https://api.example.test");
  assert.equal(input("ex_verify").props.value, "false");
  assert.equal(input("ex_regions").props.value, "eu, us");
  assert.equal(input("ex_key").props.value, "", "a stored secret is never filled in");
  assert.equal(input("ex_key").props.placeholder, "Stored · leave empty to keep");
  act(() => input("ex_url").props.onChange({ target: { value: "not a url" } }));
  await act(async () => { button("Save connection").props.onClick(); });
  assert.equal(calls.filter((call) => call.method === "PUT").length, 0, "an invalid field sends nothing");
  assert.match(all(), /API URL: an http\(s\) URL\./);
  act(() => input("ex_url").props.onChange({ target: { value: "https://api2.example.test" } }));
  await act(async () => { button("Save connection").props.onClick(); });
  const put = calls.find((call) => call.method === "PUT");
  assert.equal(put.url, "/admin/chat/api/panel/connectors/examplecloud/named-connections/x-1");
  assert.deepEqual(put.body, { name: "acct-a", bound_scopes: ["1234"], ex_url: "https://api2.example.test",
    ex_verify: "false", ex_regions: "eu, us" }, "an empty secret keeps the stored one; nothing else is invented");
});

test("Kubernetes clusters keep their case and form; the URL is the API server", () => {
  assert.deepEqual(parseScopes(D.kubernetes, "Prod, arn:aws:eks:eu-central-1:1:cluster/x"),
    ["Prod", "arn:aws:eks:eu-central-1:1:cluster/x"]);
  assert.match(scopesProblem(D.kubernetes, "prod, -bad"), /"-bad" is not a valid cluster key/);
  assert.equal(D.kubernetes.urlField, "k8s_api_url");
  assert.deepEqual(D.kubernetes.fields.filter((field) => field.kind === "secret").map((field) => field.name), ["k8s_token"]);
});

test("AWS accounts are twelve digits; keys are secrets, the platform opt-in is a yes/no field", () => {
  assert.deepEqual(parseScopes(D.aws, "222222222222 222222222222"), ["222222222222"]);
  assert.match(scopesProblem(D.aws, "12345"), /"12345" is not a valid account key/);
  assert.deepEqual(D.aws.fields.filter((field) => field.kind === "secret").map((field) => field.name),
    ["aws_access_key_id", "aws_secret_access_key", "aws_session_token"]);
  assert.equal(D.aws.fields.find((field) => field.name === "allow_platform_credentials").kind, "bool");
});

test("Git hosts bind owners, groups and repositories in lower case; nested GitLab paths are one key", () => {
  assert.deepEqual(parseScopes(D.github, "ACME, Acme/Payments"), ["acme", "acme/payments"]);
  assert.match(scopesProblem(D.github, "acme/payments/extra"), /"acme\/payments\/extra" is not a valid repository or owner key/);
  assert.equal(scopesProblem(D.gitlab, "river/sub/project"), null);
  assert.match(scopesProblem(D.bitbucket, "RIVER"), /"river" is not a valid repository key/, "Bitbucket binds repositories");
  assert.equal(D.gitlab.testable, false);
});

test("observability instances are free labels; Loki and Prometheus are a URL only", () => {
  assert.deepEqual(parseScopes(D.loki, "Prod-EU payments"), ["prod-eu", "payments"]);
  assert.deepEqual(D.prometheus.fields.map((field) => field.name), ["prometheus_url"]);
  assert.deepEqual(D.grafana.fields.filter((field) => field.kind === "secret").map((field) => field.name), ["grafana_token"]);
});

test("Azure subscriptions are GUIDs in lower case; GCP projects follow Google's project id form", () => {
  assert.deepEqual(parseScopes(D.azure, "AAAAAAAA-0000-0000-0000-00000000000A"), ["aaaaaaaa-0000-0000-0000-00000000000a"]);
  assert.match(scopesProblem(D.azure, "not-a-guid"), /is not a valid subscription key/);
  assert.equal(scopesProblem(D.gcp, "prod-4711"), null);
  assert.match(scopesProblem(D.gcp, "x"), /is not a valid project key/);
});
