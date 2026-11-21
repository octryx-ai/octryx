// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/connectorStatusConsistency.test.mjs
//
// Connector status consistency (live check 440–450), frontend U1–U4. U1: a configured card says "Connected" only
// with a successful health check; a failing one shows the problem. U2: the limit badge counts limits this Workspace
// has saved. U3: the switch-to-global radio does not flip before the confirmation; card messages use the inline
// message class (sized to content), never the full-panel error state; the connectors table pins its actions.
// Naive health timestamps are UTC (the test runs in CEST, where a naive value read as local is two hours off).
process.env.TZ = "Europe/Zurich";

import assert from "node:assert/strict";

import { formatDateTime } from "../../src/admin/utils/dateTime.ts";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { configuredConnectorStatus, connectorCardShown } from "../../src/admin/components/connectorsTab/configuredConnectorStatus.ts";
import {
  workspaceLimitText,
  savedProjectLimitCount,
} from "../../src/admin/components/projectsTab/ProjectConnectorSettingsHelpers.ts";
import { healthText } from "../../src/admin/components/projectsTab/workspaceConnectionMessages.ts";
import { formatRelativeTime } from "../../src/admin/utils/formatters.ts";
import { serverTimeOf } from "../../src/admin/utils/serverTime.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const HTTP_401 = "Confluence returned HTTP 401. Check the credentials.";

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
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Intl, encodeURIComponent,
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

// ---- U1 -----------------------------------------------------------------------------------------

test("'Connected' needs a successful check; a failing check shows its problem; none yet says so", () => {
  const active = { configured: true, is_active: true };
  assert.deepEqual(configuredConnectorStatus(active, { status: "ok" }), { text: "Connected", tone: "ok", errorInStatus: false });
  assert.deepEqual(configuredConnectorStatus(active, { status: "error", error: ` ${HTTP_401} ` }),
    { text: `Connection failing: ${HTTP_401}`, tone: "error", errorInStatus: true });
  assert.deepEqual(configuredConnectorStatus(active, { status: "ERROR", error: "" }), { text: "Connection failing", tone: "error", errorInStatus: false });
  assert.equal(configuredConnectorStatus(active, null).text, "Configured · connection not checked yet");
  assert.equal(configuredConnectorStatus(active, { status: "unknown" }).tone, "neutral");
  assert.equal(configuredConnectorStatus({ configured: true, is_active: false }, { status: "error", error: HTTP_401 }).text, "Configured (inactive)");
  assert.equal(configuredConnectorStatus({ configured: false }, { status: "ok" }).text, "Not configured");
});

test("rendered U1: the card shows the failure instead of 'Connected', does not repeat it, and has no latency figure", () => {
  const { ConfiguredConnectorHeader } = load("admin/components/connectorsTab/ConfiguredConnectorHeader.tsx");
  const formatters = load("admin/utils/formatters.ts");
  const ctx = {
    CONNECTOR_ICONS: {}, formatRelativeTime: formatters.formatRelativeTime,
    connectorHealthStatusClass: formatters.connectorHealthStatusClass, formatConnectorHealthStatus: formatters.formatConnectorHealthStatus,
    handleDeleteConnector: () => {}, handleExpandConnector: () => {},
  };
  const connector = { tool_name: "confluence", label: "Confluence", tools: [1, 2], configured: true, is_active: true };
  const render = (health) => {
    let view;
    act(() => { view = TestRenderer.create(createElement(ConfiguredConnectorHeader, { connector, health, iconColor: "#000", isOpen: false, ctx })); });
    const status = view.root.find((node) => node.props["data-testid"] === "connector-status");
    const result = { status: text(status), className: status.props.className, all: text(view.root) };
    act(() => view.unmount());
    return result;
  };
  const failing = render({ status: "error", error: HTTP_401, last_checked: new Date(Date.now() - 5 * 60000).toISOString(), response_time_ms: 69 });
  assert.equal(failing.status, `Connection failing: ${HTTP_401}`);
  assert.equal(failing.className, "connector-card__status connector-card__status--error");
  assert.doesNotMatch(failing.all, /Connected/);
  assert.equal(failing.all.split(HTTP_401).length - 1, 1, "the error is shown once");
  // The check time in words; timing only in the check history.
  assert.match(failing.all, /Checked 5 min ago/);
  assert.doesNotMatch(failing.all, /69|ms\b/);
  const healthy = render({ status: "ok", error: "", last_checked: null, response_time_ms: 40 });
  assert.equal(healthy.status, "Connected");
  assert.equal(healthy.className, "connector-card__status connector-card__status--ok");
});

// ---- U2 -----------------------------------------------------------------------------------------

test("The limit badge counts limits saved for this Workspace, not the fields the connector offers", () => {
  const access = (project_limits) => ({ connector_name: "confluence", limit_fields: ["confluence_allowed_spaces", "confluence_allowed_pages"], project_limits });
  assert.equal(savedProjectLimitCount(access({ confluence_allowed_spaces: ["DEMO"] })), 1);
  assert.equal(savedProjectLimitCount(access({ confluence_allowed_spaces: ["DEMO"], confluence_allowed_pages: [{ id: "1" }] })), 2);
  assert.equal(savedProjectLimitCount(access({ confluence_allowed_spaces: [], confluence_allowed_pages: [] })), 0);
  assert.equal(savedProjectLimitCount(access({})), 0);
  assert.equal(savedProjectLimitCount({ connector_name: "x", project_limits: { a: ["1"] } }), 0, "no limit fields, nothing counted");
  assert.deepEqual([0, 1, 2].map(workspaceLimitText), ["No Workspace limits", "1 Workspace limit", "2 Workspace limits"]);
});

test("rendered U2: the Workspace connector table shows the saved limit count", async () => {
  const { ProjectConnectorSettingsSection } = load("admin/components/projectsTab/ProjectConnectorSettingsSection.tsx");
  const { AdminNavigationContext } = load("admin/adminNavigation.ts");
  const access = (connector_name, label, project_limits) => ({
    connector_name, label, description: "", limit_fields: ["confluence_allowed_spaces", "confluence_allowed_pages"],
    global_configured: true, global_active: true, project_enabled: true, project_limits, inherited_limits: {},
    effective_limits: {}, inherits_global_limits: false,
  });
  const listing = { project_id: "ws-1", connectors: [access("confluence", "Confluence", { confluence_allowed_spaces: ["DEMO"] }), access("other", "Other", {})] };
  const readJson = async (url) => (url.endsWith("/connection") ? GLOBAL : listing);
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(AdminNavigationContext.Provider, { value: { openAdminTab: () => {} } },
      createElement(ProjectConnectorSettingsSection, { ctx: { configuringProjectQuality: { id: "ws-1" }, readJson } })));
  });
  assert.deepEqual(view.root.findAll((node) => node.props["data-testid"] === "connector-limit-badge").map(text),
    ["1 Workspace limit", "No Workspace limits"]);
  act(() => view.unmount());
});

// ---- U3 -----------------------------------------------------------------------------------------

const OWN = {
  connector_name: "confluence", source: "workspace",
  fields: { confluence_url: "https://your-site.atlassian.net/wiki", confluence_auth_mode: "cloud_api_token", confluence_username: "bot@acme.test" },
  secret_status: { confluence_token: true }, global: { configured: true, active: true, fields: {}, secret_status: {} },
  health: { status: "ok", last_checked: "2026-10-05T09:00:00" },
};
const GLOBAL = { ...OWN, source: "global", fields: {}, secret_status: {}, health: null };

async function mountConnection(stored, { testResult = { ok: true } } = {}) {
  const { WorkspaceConnectorConnection } = load("admin/components/projectsTab/WorkspaceConnectorConnection.tsx");
  const calls = [];
  let current = stored;
  const readJson = async (url, init = {}) => {
    calls.push({ url, method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null });
    if (url.endsWith("/test")) return testResult;
    if (init.method === "PUT") current = GLOBAL;
    return current;
  };
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(WorkspaceConnectorConnection, {
      projectId: "ws-1", connectorName: "confluence", product: "confluence", label: "Confluence", readJson,
    }));
  });
  const radio = (value) => view.root.find((node) => node.type === "input" && node.props.type === "radio" && node.props.value === value && node.props.name === "confluence-connection");
  const button = (label) => view.root.find((node) => node.type === "button" && text(node).trim() === label);
  const has = (id) => view.root.findAll((node) => node.props["data-testid"] === id).length > 0;
  return { view, calls, radio, button, has };
}

test("rendered U3: choosing global over a stored own connection asks first; the radio stays on own until confirmed", async () => {
  const ui = await mountConnection(OWN);
  act(() => ui.radio("global").props.onChange());
  assert.ok(ui.has("workspace-connection-confirm-global"));
  assert.equal(ui.radio("global").props.checked, false, "not flipped before the confirmation");
  assert.equal(ui.radio("own").props.checked, true);
  assert.equal(ui.calls.filter((call) => call.method === "PUT").length, 0);
  // Both choices sit in the card's action row below the consequence.
  const confirm = ui.view.root.find((node) => node.props["data-testid"] === "workspace-connection-confirm-global");
  assert.deepEqual(confirm.findByProps({ className: "connector-card__actions" }).findAllByType("button").map(text),
    ["Use global connection", "Keep own connection"]);
  await act(async () => { ui.button("Keep own connection").props.onClick(); });
  assert.ok(!ui.has("workspace-connection-confirm-global"));
  assert.equal(ui.radio("own").props.checked, true);
  act(() => ui.radio("global").props.onChange());
  await act(async () => { ui.button("Use global connection").props.onClick(); });
  assert.deepEqual(ui.calls.filter((call) => call.method === "PUT").map((call) => call.body), [{ source: "global" }]);
  assert.equal(ui.radio("global").props.checked, true, "flips once the switch is saved");
  assert.ok(!ui.has("workspace-connection-confirm-global"));
});

test("rendered U3: without a stored own connection the radio switches directly", async () => {
  const ui = await mountConnection(GLOBAL);
  act(() => ui.radio("own").props.onChange());
  act(() => ui.radio("global").props.onChange());
  assert.equal(ui.radio("global").props.checked, true);
  assert.ok(!ui.has("workspace-connection-confirm-global"));
});

test("rendered U3: a failed test is an inline message sized to its text, not the full-panel error state", async () => {
  const ui = await mountConnection(OWN, { testResult: { ok: false, message: "Confluence returned HTTP 403." } });
  await act(async () => { ui.button("Test connection").props.onClick(); });
  const message = ui.view.root.find((node) => node.props["data-testid"] === "workspace-connection-message");
  assert.equal(text(message), "Confluence returned HTTP 403.");
  assert.equal(message.props.className, "workspace-connection__message");
  assert.equal(ui.view.root.findAll((node) => typeof node.props.className === "string" && node.props.className.split(" ").includes("admin-panel__error")).length, 0);
});

// Design-system pilot: the sources are one full-width table (layout/DataTable); each row carries its own ⋯ menu, so
// actions never leave the panel and the row opens the source's side panel.
test("rendered U3: each source row carries its own menu; the selected row is marked", () => {
  const { KnowledgeSourceList } = load("admin/components/workspaceKnowledge/sources/KnowledgeSourceList.tsx");
  const connector = {
    connector_key: "demo", kind: "confluence", scope: { spaces: ["DEMO"] }, products: [], version: null, max_items_per_run: 100,
    state: "active", cursor: { pass_number: 1, token: null, pass_started_at: null, last_completed_at: null, completed_passes: 0 },
    schedule: { enabled: false, interval_minutes: 60, next_run_at: null }, running: false, last_run: null,
  };
  const noop = () => {};
  let view;
  act(() => {
    view = TestRenderer.create(createElement(KnowledgeSourceList, { connectors: [connector], selectedKey: "demo", busy: false, runningKey: null,
      mayAuthor: true, actions: { onRun: noop, onShow: noop, onEdit: noop, onToggle: noop, onReleases: noop, onDelete: noop, onOpenUploads: noop } }));
  });
  assert.equal(view.root.findAll((node) => node.type === "table").length, 1);
  const row = view.root.find((node) => node.type === "tr" && node.props["data-row-key"] === "demo");
  assert.equal(row.props["aria-selected"], true);
  assert.ok(row.findAll((node) => node.type === "button" && node.props["aria-label"] === "More actions for demo").length);
  act(() => view.unmount());
});

// ---- U4 -----------------------------------------------------------------------------------------

test("Naive health times are UTC in the relative time and in the Workspace 'Last test'", () => {
  const fiveMinutesAgo = new Date(Date.now() - 5 * 60000).toISOString();
  const naive = fiveMinutesAgo.replace(/Z$/, "");
  assert.equal(serverTimeOf(naive), Date.parse(fiveMinutesAgo));
  assert.equal(formatRelativeTime(naive), "5 min ago", "read as local CEST this was '2 h ago'");
  assert.equal(formatRelativeTime(fiveMinutesAgo), "5 min ago");
  assert.equal(formatRelativeTime("soon"), "");
  assert.equal(formatRelativeTime(null), "");
  assert.equal(healthText({ status: "ok", checkedAt: "2026-10-05T09:00:00" }),
    `Last test: connected (${formatDateTime("2026-10-05T09:00:00Z")}).`);
  assert.match(healthText({ status: "ok", checkedAt: "2026-10-05T09:00:00" }), /11:00/, "09:00 UTC is 11:00 in CEST");
});

test("a connector only Workspaces hold accounts for gets its card, saying so, without a global entry", () => {
  const bitbucket = { tool_name: "bitbucket", configured: false, workspace_connections: 2 };
  assert.equal(connectorCardShown(bitbucket, null), true);
  assert.deepEqual(configuredConnectorStatus(bitbucket, null),
    { text: "Workspace connections only (2)", tone: "neutral", errorInStatus: false });
  assert.equal(connectorCardShown({ ...bitbucket, workspace_connections: 0 }, null), false);
  assert.equal(connectorCardShown({ ...bitbucket, workspace_connections: 0 }, "bitbucket"), true);
  assert.equal(configuredConnectorStatus({ ...bitbucket, workspace_connections: 0 }, null).text, "Not configured");
});
