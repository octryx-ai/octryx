// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminMcpServersPage.test.mjs
//
// Admin › Connections › MCP servers: no overview cards, one full-width table with source, scope,
// transport, state, tools and where a server is allowed; a row opens the server in the side panel, whose footer ends
// with Connect (primary) or Disconnect; Source and Remove live in the "⋯" menu.
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
  mcpAllowedLabel,
  mcpScopeLabel,
  mcpServerState,
  mcpSourceLabel,
  mcpToolsText,
} from "../../src/admin/components/mcpServerPresenters.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

const SERVERS = [
  { id: "s-1", name: "context7", owner_scope: "platform", transport: "streamable-http", url: "https://mcp.example.test",
    description: "Library docs", auto_start: true, is_active: true, connected: true, tool_count: 2, catalog_slug: "context7",
    vendor: "Upstash", source_url: "https://example.test/context7" },
  { id: "s-2", name: "wiki", owner_scope: "workspace", transport: "sse", url: null, description: "", auto_start: false,
    is_active: true, connected: false, tool_count: 0, catalog_slug: null },
];

function loader() {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, URL, URLSearchParams, Error, encodeURIComponent, Promise, Map,
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

const render = (element) => {
  let view;
  act(() => {
    view = TestRenderer.create(element);
  });
  return view;
};

test("the table's words: state, source, scope, tools and where a server is allowed", () => {
  assert.deepEqual(mcpServerState(SERVERS[0]), { label: "Connected", tone: "neutral" });
  assert.equal(mcpServerState(SERVERS[1]).label, "Not connected");
  assert.equal(mcpServerState({ ...SERVERS[0], is_active: false }).label, "Inactive");
  assert.equal(mcpSourceLabel(SERVERS[0]), "Catalog");
  assert.equal(mcpSourceLabel(SERVERS[1]), "Custom");
  assert.equal(mcpScopeLabel(SERVERS[0]), "Platform");
  assert.equal(mcpScopeLabel(SERVERS[1]), "Workspace");
  assert.equal(mcpToolsText(SERVERS[0]), "2");
  assert.equal(mcpToolsText(SERVERS[1]), "—");
  assert.equal(mcpAllowedLabel(undefined), null);
  assert.deepEqual(mcpAllowedLabel({ allowedWorkspaces: 0 }), { label: "Not allowed", tone: "attention" });
  assert.equal(mcpAllowedLabel({ allowedWorkspaces: 1 }).label, "1 Workspace");
  assert.equal(mcpAllowedLabel({ allowedWorkspaces: 3 }).label, "3 Workspaces");
});

test("the server list is a table; a row opens the server", () => {
  const load = loader();
  const { AdminMcpServerList } = load("admin/components/AdminMcpServerList.tsx");
  const opened = [];
  const status = new Map([["s-1", { allowedWorkspaces: 2 }], ["s-2", { allowedWorkspaces: 0 }]]);
  const view = render(createElement(AdminMcpServerList, {
    servers: SERVERS, getMcpIconColor: () => "#000", renderMcpIcon: () => null, allowStatus: status,
    selectedName: null, onOpen: (server) => opened.push(server.name), rowMenu: () => null,
    empty: { text: "No MCP servers in this Workspace yet." },
  }));
  const table = view.root.find((node) => node.props["data-testid"] === "mcp-server-table");
  const headers = table.findAllByType("th").map(text);
  assert.deepEqual(headers.slice(0, 7), ["Name", "Source", "Scope", "Transport", "State", "Tools", "Allowed in"]);
  const rows = table.findAll((node) => node.type === "tr" && node.props["data-row-key"]);
  assert.equal(rows.length, 2);
  assert.match(text(rows[0]), /context7.*Catalog.*Platform.*streamable-http.*Connected.*2.*2 Workspaces/);
  assert.match(text(rows[1]), /wiki.*Custom.*Workspace.*sse.*Not connected.*—.*Not allowed/);
  act(() => rows[1].props.onClick());
  assert.deepEqual(opened, ["wiki"]);
});

test("an empty Workspace shows one line", () => {
  const { AdminMcpServerList } = loader()("admin/components/AdminMcpServerList.tsx");
  const view = render(createElement(AdminMcpServerList, {
    servers: [], getMcpIconColor: () => "#000", renderMcpIcon: () => null, selectedName: null, onOpen: () => {},
    rowMenu: () => null, empty: { text: "No MCP servers in this Workspace yet.", testId: "mcp-empty" },
  }));
  assert.equal(text(view.root.find((node) => node.props["data-testid"] === "mcp-empty")), "No MCP servers in this Workspace yet.");
});

test("the side panel shows the details and ends with Connect or Disconnect", () => {
  const load = loader();
  const { AdminMcpServerPanel } = load("admin/components/AdminMcpServerPanel.tsx");
  const calls = [];
  const props = {
    onClose: () => calls.push("close"), onEdit: (server) => calls.push(`edit ${server.name}`),
    onConnect: (name) => calls.push(`connect ${name}`), onDisconnect: (name) => calls.push(`disconnect ${name}`),
    onAllow: (server) => calls.push(`allow ${server.name}`), menu: createElement("span", { "data-testid": "menu" }),
  };
  const footerButtons = (view) => view.root.findByType("footer").findAllByType("button");

  const connected = render(createElement(AdminMcpServerPanel, { ...props, server: SERVERS[0], status: { allowedWorkspaces: 1, connected: true } }));
  const facts = text(connected.root.find((node) => node.props["data-testid"] === "mcp-server-facts"));
  for (const fact of ["https://mcp.example.test", "Upstash", "context7", "Auto-start", "2 exposed"]) assert.ok(facts.includes(fact), fact);
  assert.ok(text(connected.root).includes("Library docs"));
  assert.ok(connected.root.findAll((node) => node.props["data-testid"] === "menu").length === 1);
  assert.deepEqual(footerButtons(connected).map(text), ["Edit", "Disconnect"]);
  act(() => connected.root.find((node) => node.props["data-testid"] === "mcp-allow-open").props.onClick());

  const idle = render(createElement(AdminMcpServerPanel, { ...props, server: SERVERS[1] }));
  const buttons = footerButtons(idle);
  assert.deepEqual(buttons.map(text), ["Edit", "Connect"]);
  assert.match(buttons[1].props.className, /--primary/);
  act(() => buttons[1].props.onClick());
  assert.ok(!text(idle.root.find((node) => node.props["data-testid"] === "mcp-server-facts")).includes("Vendor"));
  assert.deepEqual(calls, ["allow context7", "connect wiki"]);
});

test("the overview cards are gone", () => {
  assert.equal(fs.existsSync(path.join(SRC, "admin/components/AdminMcpOverview.tsx")), false);
  const tab = fs.readFileSync(path.join(SRC, "admin/components/AdminMcpTab.tsx"), "utf8");
  assert.ok(!tab.includes("admin-overview-grid") && !tab.includes("AdminMcpOverview"));
  assert.ok(!tab.includes("admin-panel__section-header"));
});
