// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/connectorConnectionStates.test.mjs
//
// A preset without a connection test is neutral ("No connection test
// available", a muted "No test" badge), never red "Connection failing". useGlobal (and save): the shown connection
// always comes from the server; an unreadable PUT answer is followed by a fresh read, and success is claimed only
// when the server reports the expected mode. Page-tree pre-check: space keys compare case-insensitively like the
// server. An incomplete own connection shows the server's `state_summary`; a Knowledge run
// with reason `own_connection_incomplete` says what to do.
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
  configuredConnectorStatus,
  connectionTestAvailable,
} from "../../src/admin/components/connectorsTab/configuredConnectorStatus.ts";
import { ownConnectionReady, parseConnection } from "../../src/admin/components/projectsTab/workspaceConnectionModel.ts";
import { settledMessage } from "../../src/admin/components/projectsTab/workspaceConnectionMessages.ts";
import { pageTreesProblem } from "../../src/admin/components/workspaceKnowledge/confluencePageTree.ts";
import { initialForm, validate } from "../../src/admin/components/workspaceKnowledge/connectorFormModel.ts";
import { reasonText } from "../../src/admin/components/workspaceKnowledge/connectorReasons.ts";
import { runReasonNotice } from "../../src/admin/components/workspaceKnowledge/runReasonNotice.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
const json = (value) => JSON.parse(JSON.stringify(value));

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
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Intl, encodeURIComponent,
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

// ---- U1 refinement ------------------------------------------------------------------------------

const NOT_IMPLEMENTED = "Connection test is not implemented for grafana.";
const grafana = (overrides = {}) => ({ tool_name: "grafana", label: "Grafana", tools: [1], configured: true, is_active: true, ...overrides });

test("A preset without a connection test is neutral; the explicit field wins; the fixed text is matched exactly", () => {
  const error = { status: "error", error: NOT_IMPLEMENTED };
  assert.equal(connectionTestAvailable(grafana(), error), false);
  assert.equal(connectionTestAvailable(grafana({ connection_test_available: true }), error), true, "an explicit field wins");
  assert.equal(connectionTestAvailable(grafana({ connection_test_available: false }), { status: "ok" }), false);
  assert.equal(connectionTestAvailable(grafana({ tool_name: "jira" }), error), true, "another tool's text is not this tool's");
  assert.equal(connectionTestAvailable(grafana(), { status: "error", error: `HTTP 401. ${NOT_IMPLEMENTED}` }), true, "never a substring");
  assert.equal(connectionTestAvailable(grafana(), null), true);
  assert.deepEqual(configuredConnectorStatus(grafana(), error), { text: "No connection test available", tone: "neutral", errorInStatus: true });
  assert.equal(configuredConnectorStatus(grafana({ is_active: false }), error).text, "Configured (inactive)");
  assert.equal(configuredConnectorStatus(grafana({ tool_name: "jira" }), { status: "error", error: "HTTP 401" }).text, "Connection failing: HTTP 401");
});

test("rendered U1: the card says 'No connection test available' with a muted 'No test' badge and no red failure", () => {
  const { ConfiguredConnectorHeader } = load("admin/components/connectorsTab/ConfiguredConnectorHeader.tsx");
  const formatters = load("admin/utils/formatters.ts");
  const ctx = {
    CONNECTOR_ICONS: {}, formatRelativeTime: formatters.formatRelativeTime,
    connectorHealthStatusClass: formatters.connectorHealthStatusClass, formatConnectorHealthStatus: formatters.formatConnectorHealthStatus,
    handleDeleteConnector: () => {}, handleExpandConnector: () => {},
  };
  const render = (connector, health) => {
    let view;
    act(() => { view = TestRenderer.create(createElement(ConfiguredConnectorHeader, { connector, health, iconColor: "#000", isOpen: false, ctx })); });
    const status = byTestId(view, "connector-status")[0];
    const badge = byTestId(view, "connector-health-badge")[0];
    const result = { status: text(status), statusClass: status.props.className, badge: text(badge), badgeClass: badge.props.className, all: text(view.root) };
    act(() => view.unmount());
    return result;
  };
  const untestable = render(grafana(), { status: "error", error: NOT_IMPLEMENTED, last_checked: null, response_time_ms: 1 });
  assert.equal(untestable.status, "No connection test available");
  assert.equal(untestable.statusClass, "connector-card__status");
  assert.deepEqual([untestable.badge, untestable.badgeClass], ["No test", "connector-card__meta-badge connector-card__meta-badge--muted"]);
  assert.doesNotMatch(untestable.all, /Unhealthy|Connection failing|not implemented/);
  const failing = render(grafana({ tool_name: "jira", label: "Jira" }), { status: "error", error: "HTTP 401", last_checked: null, response_time_ms: 1 });
  assert.deepEqual([failing.badge, failing.badgeClass], ["Unhealthy", "connector-card__meta-badge connector-card__meta-badge--error"]);
});

// ---- useGlobal / save consistency ---------------------------------------------------------------

const OWN = {
  connector_name: "confluence", source: "workspace",
  fields: { confluence_url: "https://your-site.atlassian.net/wiki", confluence_auth_mode: "cloud_api_token", confluence_username: "bot@acme.test" },
  secret_status: { confluence_token: true }, global: { configured: true, active: true, fields: {}, secret_status: {} }, health: null,
  state: "own", state_summary: null,
};
const GLOBAL = { ...OWN, source: "global", fields: {}, secret_status: {}, state: "global" };

async function mountConnection({ initial, putAnswer, afterPut }) {
  const { WorkspaceConnectorConnection } = load("admin/components/projectsTab/WorkspaceConnectorConnection.tsx");
  const calls = [];
  let put = false;
  const readJson = async (url, init = {}) => {
    calls.push({ url, method: init.method || "GET" });
    if (init.method === "PUT") { put = true; return putAnswer; }
    return put ? afterPut : initial;
  };
  const ready = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(WorkspaceConnectorConnection, {
      projectId: "ws-1", connectorName: "confluence", product: "confluence", label: "Confluence", readJson, onReadyChange: (value) => ready.push(value),
    }));
  });
  const radio = (value) => view.root.find((node) => node.type === "input" && node.props.type === "radio" && node.props.value === value && node.props.name === "confluence-connection");
  const click = async (label) => { await act(async () => { view.root.find((node) => node.type === "button" && text(node).trim() === label).props.onClick(); }); };
  const message = () => { const [node] = byTestId(view, "workspace-connection-message"); return node ? { text: text(node), className: node.props.className } : null; };
  return { view, calls, radio, click, message, ready };
}

test("the message after a save or switch is success only when the server reports the expected mode", () => {
  assert.deepEqual(settledMessage(parseConnection(GLOBAL), "global", "done"), { ok: true, text: "done" });
  assert.match(settledMessage(null, "global", "done").text, /answer could not be read/);
  assert.equal(settledMessage(null, "global", "done").ok, false);
  assert.match(settledMessage(parseConnection(OWN), "global", "done").text, /still reports this Workspace's own connection/);
  assert.match(settledMessage(parseConnection(GLOBAL), "own", "done").text, /own connection was not stored/);
});

test("rendered useGlobal: an unreadable PUT answer is re-read; the shown state and message follow the server", async () => {
  // The re-read says global: success, and the radio flips.
  let ui = await mountConnection({ initial: OWN, putAnswer: null, afterPut: GLOBAL });
  act(() => ui.radio("global").props.onChange());
  await ui.click("Use global connection");
  assert.deepEqual(ui.calls.map((call) => call.method), ["GET", "PUT", "GET"], "re-read after the unreadable answer");
  assert.equal(ui.radio("global").props.checked, true);
  assert.deepEqual(ui.message(), { text: "This Workspace now uses the global Confluence connection.", className: "admin-panel__success" });
  act(() => ui.view.unmount());

  // Nothing readable at all: no success claimed, the stored own connection stays shown.
  ui = await mountConnection({ initial: OWN, putAnswer: "<html>", afterPut: "<html>" });
  act(() => ui.radio("global").props.onChange());
  await ui.click("Use global connection");
  assert.equal(ui.radio("own").props.checked, true);
  assert.match(ui.message().text, /^The change was sent, but the server's answer could not be read/);
  assert.equal(ui.message().className, "workspace-connection__message");
  act(() => ui.view.unmount());

  // The server still reports the own connection.
  ui = await mountConnection({ initial: OWN, putAnswer: OWN, afterPut: OWN });
  act(() => ui.radio("global").props.onChange());
  await ui.click("Use global connection");
  assert.match(ui.message().text, /still reports this Workspace's own connection/);
  assert.equal(ui.calls.filter((call) => call.method === "GET").length, 1, "a readable answer needs no re-read");
  act(() => ui.view.unmount());
});

test("rendered save: an unreadable answer is re-read before success is claimed", async () => {
  const ui = await mountConnection({ initial: OWN, putAnswer: undefined, afterPut: OWN });
  await ui.click("Save connection");
  assert.deepEqual(ui.calls.map((call) => call.method), ["GET", "PUT", "GET"]);
  assert.deepEqual(ui.message(), { text: "Saved this Workspace's own Confluence connection.", className: "admin-panel__success" });
  act(() => ui.view.unmount());
});

// ---- Page-tree pre-check ------------------------------------------------------------------------

test("page trees: a tree in a whole space is refused whatever the case, as the server does", () => {
  const tree = { space_key: "DEMO", root_page_id: "100002" };
  assert.match(pageTreesProblem([tree], ["demo"]), /already synced whole/);
  assert.match(pageTreesProblem([{ ...tree, space_key: "demo" }], ["DEMO"]), /already synced whole/);
  assert.equal(pageTreesProblem([tree], ["ENG"]), null);
  const form = { ...initialForm(null), key: "team-wiki", scopeMode: "trees", pageTrees: [tree], keys: "demo" };
  assert.match(validate(form).problem, /already synced whole/);
});

// ---- L-1: incomplete own connection -------------------------------------------------------------

const SUMMARY = "Own connection incomplete: set its URL, auth mode and credential, or use the global connection.";
const DISABLED = "Own connection disabled for this Workspace: enable the connector in its access settings.";

test("L-1: the server's own_incomplete state and summary are read; an incomplete own connection is not runtime-ready", () => {
  const incomplete = parseConnection({ ...OWN, state: "own_incomplete", state_summary: SUMMARY });
  assert.deepEqual(json({ incomplete: incomplete.incomplete, summary: incomplete.stateSummary }), { incomplete: true, summary: SUMMARY });
  assert.equal(ownConnectionReady("confluence", incomplete), false, "URL and mode alone are not enough when the server says incomplete");
  assert.equal(ownConnectionReady("confluence", parseConnection(OWN)), true);
  assert.equal(parseConnection({ ...OWN, state: "own", state_summary: SUMMARY }).stateSummary, null, "only for own_incomplete");
  assert.equal(parseConnection({ ...OWN, state: undefined }).incomplete, false, "an older server");
  // A disabled own entry reads own_disabled with its own fixed summary, handled like own_incomplete.
  const disabled = parseConnection({ ...OWN, state: "own_disabled", state_summary: DISABLED });
  assert.deepEqual(json({ incomplete: disabled.incomplete, summary: disabled.stateSummary }), { incomplete: true, summary: DISABLED });
  assert.equal(ownConnectionReady("confluence", disabled), false);
  assert.equal(parseConnection({ ...OWN, state: "own_paused", state_summary: DISABLED }).stateSummary, null, "only the known states");
});

test("rendered L-1: the incomplete own connection shows the server's summary and is not ready", async () => {
  const ui = await mountConnection({ initial: { ...OWN, state: "own_incomplete", state_summary: SUMMARY }, putAnswer: null, afterPut: null });
  const [note] = byTestId(ui.view, "workspace-connection-incomplete");
  assert.equal(text(note), SUMMARY);
  assert.equal(note.props.role, "note");
  assert.equal(ui.ready.at(-1), false);
  act(() => ui.view.unmount());
  const off = await mountConnection({ initial: { ...OWN, state: "own_disabled", state_summary: DISABLED }, putAnswer: null, afterPut: null });
  assert.equal(text(byTestId(off.view, "workspace-connection-incomplete")[0]), DISABLED);
  assert.equal(off.ready.at(-1), false);
  act(() => off.view.unmount());
  const complete = await mountConnection({ initial: OWN, putAnswer: null, afterPut: null });
  assert.equal(byTestId(complete.view, "workspace-connection-incomplete").length, 0);
  act(() => complete.view.unmount());
});

test("L-1: a run refused with own_connection_incomplete says what to do, in the reason text and as a notice", () => {
  assert.match(reasonText("own_connection_incomplete"), /^this Workspace's own connection is incomplete: set its URL, auth mode and credential/);
  const notice = runReasonNotice("own_connection_incomplete", []);
  assert.equal(notice.code, "own_connection_incomplete");
  assert.equal(notice.title, "This Workspace's own connection is incomplete");
  assert.match(notice.text, /Complete it under Workspace settings → Connectors, or switch the Workspace to the global connection\./);
  assert.match(reasonText("connection_not_configured"), /^no active connection/, "the generic reason is unchanged");
});

test("rendered L-1: the last run report shows the notice", () => {
  const { KnowledgeConnectorRun } = load("admin/components/workspaceKnowledge/KnowledgeConnectorRun.tsx");
  const run = { id: "r1", state: "needs_configuration", reason: "own_connection_incomplete", report: {}, started_at: "2026-10-05T10:00:00Z", finished_at: "2026-10-05T10:00:01Z", outcomes: [] };
  let view;
  act(() => { view = TestRenderer.create(createElement(KnowledgeConnectorRun, { connectorKey: "demo", kind: "confluence", run })); });
  assert.match(text(view.root), /This Workspace's own connection is incomplete/);
  act(() => view.unmount());
});

test("a source on a connection the Workspace was not released reads as a release to ask for, with where", async () => {
  const { connectorRequest } = await import("../../src/admin/components/workspaceKnowledge/connectorsApi.ts");
  const original = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({
    detail: { code: "source_connection_not_granted", field: "connection_id", message: "not granted" },
  }), { status: 403, headers: { "Content-Type": "application/json" } });
  try {
    await assert.rejects(connectorRequest("/x", { method: "PUT", body: "{}" }), (error) => {
      assert.equal(error.reason, "source_connection_not_granted");
      assert.equal(error.field, "connection_id");
      assert.match(error.message, /not released to this Workspace. A platform admin must release/);
      return true;
    });
    // A platform admin gets the connection's id and name: the words name it and a link opens it.
    globalThis.fetch = async () => new Response(JSON.stringify({
      detail: { code: "source_connection_not_granted", field: "connection_id", connection_id: "c-1", connection_name: "Jira (prod)" },
    }), { status: 403, headers: { "Content-Type": "application/json" } });
    const { notGrantedView } = await import("../../src/admin/components/workspaceKnowledge/connectorReasons.ts");
    const error = await connectorRequest("/x", { method: "PUT", body: "{}" }).catch((failure) => failure);
    assert.deepEqual(notGrantedView(error), {
      text: "The connection “Jira (prod)” is not released to this Workspace. Release it in Admin › Connections: tick this Workspace under Workspaces.",
      href: "/chat?area=admin&tab=adminConnections&connection=c-1",
    });
    assert.equal(notGrantedView(new Error("other")), null);
  } finally {
    globalThis.fetch = original;
  }
});
