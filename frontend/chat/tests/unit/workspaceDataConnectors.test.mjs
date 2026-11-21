// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workspaceDataConnectors.test.mjs
//
//
// Workspace › Data › Connectors: the connections available in this Workspace are a read-only
// list from the central connections API with the Workspace filter, linked to Admin › Connections; the old connector
// cards are gone. What only a Workspace sets (use the connector here, its limits, its own and named connections)
// is one compact table whose row opens a side panel with Cancel / Save access in the footer. No project wording,
// no raw limit keys.
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
  inheritedSummary,
  labelForLimitField,
} from "../../src/admin/components/projectsTab/ProjectConnectorSettingsHelpers.ts";
import { platformConnectorState } from "../../src/admin/components/projectsTab/workspaceConnectorTableState.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id && typeof node.type === "string");

// One module cache per mount, so the page and the test share the same AdminNavigationContext.
function loader(extra = {}) {
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
  return (relative) => loadFile(path.join(SRC, relative));
}

const ACCESS = {
  connector_name: "aws", label: "AWS", description: "", limit_fields: ["aws_allowed_services"],
  global_configured: true, global_active: true, project_enabled: true, project_limits: {},
  inherited_limits: {}, effective_limits: { aws_allowed_services: ["ec2", "s3"] }, inherits_global_limits: true,
};
const CONNECTIONS = { connections: [
  { id: "c1", type: "jira", name: "Jira (Standard)", state: "ok", available_in: "all", uses: { knowledge: false, tickets: true, agent_tools: "read" }, last_tested_at: null },
  { id: "c2", type: "confluence", name: "Confluence-DOC17", state: "failing", state_reason: "HTTP 401", available_in: "selected", uses: { knowledge: true, agent_tools: "off" } },
] };

async function mount() {
  const fetched = [];
  const fetch = async (url) => {
    fetched.push(url);
    const body = url.startsWith("/api/v1/admin/connections") ? CONNECTIONS : { types: [] };
    return { status: 200, json: async () => body };
  };
  const calls = [];
  const readJson = async (url, init = {}) => {
    calls.push({ url, method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null });
    return { project_id: "ws-1", connectors: [ACCESS] };
  };
  const opened = [];
  const load = loader({ fetch });
  const { ProjectConnectorSettingsSection } = load("admin/components/projectsTab/ProjectConnectorSettingsSection.tsx");
  const { AdminNavigationContext } = load("admin/adminNavigation.ts");
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(AdminNavigationContext.Provider, { value: { openAdminTab: (tab) => opened.push(tab) } },
      createElement(ProjectConnectorSettingsSection, { ctx: { configuringProjectQuality: { id: "ws-1" }, readJson } })));
  });
  return { view, fetched, calls, opened };
}

test("the connections of this Workspace come from the connections API with its filter, read-only, linked to Admin", async () => {
  const { view, fetched, opened } = await mount();
  assert.ok(fetched.includes("/api/v1/admin/connections?workspace_id=ws-1"), fetched.join(", "));
  const table = byTestId(view, "workspace-connections-table")[0];
  assert.match(text(table), /Jira \(Standard\).*Working.*Tickets · Tools: read/s);
  assert.match(text(table), /Confluence-DOC17.*Failing/s);
  assert.equal(view.root.findAll((node) => node.type === "button" && /Save|Edit|Delete|Add connection/.test(text(node))).length, 0,
    "nothing on the list changes a connection");
  await act(async () => { byTestId(view, "workspace-connections-manage")[0].props.onClick(); });
  assert.deepEqual(opened, ["adminConnections"]);
  act(() => view.unmount());
});

test("no connector cards; a connector's Workspace access opens in a side panel with Save access in the footer", async () => {
  const { view, calls } = await mount();
  assert.equal(view.root.findAll((node) => typeof node.props.className === "string" && /\bconnector-card\b(?!__icon)/.test(node.props.className)).length, 0);
  const all = text(view.root);
  assert.doesNotMatch(all, /project/i, "Workspace wording, never project");
  assert.doesNotMatch(all, /Enable platform connectors for this workspace/, "no explanatory sentence on the page");
  assert.match(text(byTestId(view, "workspace-connector-table")[0]), /AWS.*On.*No Workspace limits.*Ready/s);
  assert.equal(byTestId(view, "workspace-connector-panel").length, 0);
  const row = view.root.find((node) => node.type === "tr" && node.props["data-row-key"] === "aws");
  await act(async () => { row.props.onClick(); });
  const panel = byTestId(view, "workspace-connector-panel")[0];
  assert.match(text(panel), /Use AWS in this Workspace/);
  assert.match(text(panel), /Allowed AWS services/);
  const footer = panel.find((node) => node.type === "footer");
  assert.deepEqual(footer.findAll((node) => node.type === "button").map(text), ["Cancel", "Save access"]);
  await act(async () => { byTestId(view, "workspace-connector-enabled")[0].props.onChange({ target: { checked: false } }); });
  await act(async () => { footer.find((node) => node.type === "button" && text(node) === "Save access").props.onClick(); });
  const put = calls.find((call) => call.method === "PUT");
  assert.equal(put.url, "/admin/chat/api/panel/projects/ws-1/connectors/aws");
  assert.deepEqual(put.body, { is_active: false, limits: {} });
  act(() => view.unmount());
});

test("Cancel drops the unsaved change of the open connector", async () => {
  const { view, calls } = await mount();
  await act(async () => { view.root.find((node) => node.type === "tr" && node.props["data-row-key"] === "aws").props.onClick(); });
  await act(async () => { byTestId(view, "workspace-connector-enabled")[0].props.onChange({ target: { checked: false } }); });
  await act(async () => { view.root.find((node) => node.type === "button" && text(node) === "Cancel").props.onClick(); });
  assert.equal(byTestId(view, "workspace-connector-panel").length, 0);
  await act(async () => { view.root.find((node) => node.type === "tr" && node.props["data-row-key"] === "aws").props.onClick(); });
  assert.equal(byTestId(view, "workspace-connector-enabled")[0].props.checked, true);
  assert.equal(calls.filter((call) => call.method === "PUT").length, 0);
  act(() => view.unmount());
});

test("limit fields and the limits in effect read as words, not keys or JSON", () => {
  assert.equal(labelForLimitField("aws_allowed_services"), "Allowed AWS services");
  assert.equal(labelForLimitField("github_allowed_repositories"), "Allowed GitHub repositories");
  assert.equal(labelForLimitField("k8s_allowed_namespaces"), "Allowed Kubernetes namespaces");
  assert.equal(inheritedSummary(ACCESS), "Allowed AWS services: ec2, s3");
  assert.equal(inheritedSummary({ ...ACCESS, effective_limits: {} }), "No platform limit is set.");
  assert.deepEqual(platformConnectorState({ global_configured: true, global_active: true }), { label: "Ready", tone: "neutral" });
  assert.deepEqual(platformConnectorState({ global_configured: true, global_active: false }), { label: "Off", tone: "attention" });
  assert.deepEqual(platformConnectorState({ global_configured: false, global_active: false }), { label: "Not set up", tone: "neutral" });
});

test("Workspace overview: plain sections without card frames; a wrapped link value starts at the left", () => {
  const source = fs.readFileSync(path.join(SRC, "admin/components/projectsTab/ProjectSettingsOverview.tsx"), "utf8");
  assert.doesNotMatch(source, /admin-panel__card|admin-panel__section-header/);
  const css = fs.readFileSync(path.join(SRC, "admin/components/projectsTab/workspaceList.css"), "utf8");
  assert.match(css, /\.workspace-overview \.sk-link \{\s*text-align: start;/);
});
