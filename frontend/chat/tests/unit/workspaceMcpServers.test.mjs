// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workspaceMcpServers.test.mjs
//
// MCP servers next to the named connections: Workspace → Connectors lists the MCP servers the Workspace
// can use (platform and its own), read-only, with scope, transport and status, never the server URL; the button
// opens Automation → MCP, where they are managed. A failed listing shows nothing.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { mcpServerStatus, parseMcpServerRows } from "../../src/admin/components/namedConnections/mcpServerListingModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

const SERVERS = [
  { id: "s-2", name: "wiki-search", owner_scope: "workspace", workspace_id: "ws-1", transport: "streamable-http",
    url: "https://mcp.example.test/sse?token=fake-never-shown", is_active: true, connected: true, tool_count: 3 },
  { id: "s-1", name: "atlassian", owner_scope: "platform", workspace_id: null, transport: "sse",
    url: "https://atlassian.example.test", is_active: true, connected: false, tool_count: 0 },
  { id: "s-3", name: "old", owner_scope: "platform", transport: "stdio", is_active: false, connected: false },
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
      module, exports: module.exports, console, URL, URLSearchParams, Error, encodeURIComponent, Promise,
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

async function mount(readJson) {
  const load = loader();
  const { WorkspaceMcpServers } = load("admin/components/namedConnections/WorkspaceMcpServers.tsx");
  const { AdminNavigationContext } = load("admin/adminNavigation.ts");
  const opened = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(AdminNavigationContext.Provider,
      { value: { openAdminTab: (tab) => opened.push(tab) } },
      createElement(WorkspaceMcpServers, { projectId: "ws-1", readJson })));
  });
  return { view, opened, all: () => (view.toJSON() ? text(view.root) : "") };
}

test("rows: scope, transport and status, sorted by name, never the URL", () => {
  const rows = parseMcpServerRows(SERVERS, "ws-1");
  assert.deepEqual(rows.map((row) => [row.name, row.scope, row.transport, row.status]), [
    ["atlassian", "Platform", "sse", "Not connected"],
    ["old", "Platform", "stdio", "Inactive"],
    ["wiki-search", "This Workspace", "streamable-http", "Connected · 3 tools"],
  ]);
  assert.ok(!JSON.stringify(rows).includes("token"));
  assert.equal(parseMcpServerRows(SERVERS, "ws-2")[2].scope, "Another Workspace");
  assert.deepEqual(parseMcpServerRows({ error: "x" }, "ws-1"), []);
  assert.deepEqual(parseMcpServerRows([{ transport: "sse" }, null], "ws-1"), []);
  assert.equal(mcpServerStatus({ connected: true, tool_count: 1 }), "Connected · 1 tool");
});

test("the Workspace listing reads the registry and the allow state, and links to Runtime → MCP servers", async () => {
  const urls = [];
  const ui = await mount(async (url) => {
    urls.push(url);
    return url.startsWith("/api/v1/admin/workspaces/") ? { servers: [] } : SERVERS;
  });
  assert.deepEqual(urls.sort(), ["/admin/chat/api/panel/mcp/servers?workspace_id=ws-1",
    "/api/v1/admin/workspaces/ws-1/mcp-servers"]);
  const all = ui.all();
  assert.match(all, /MCP servers \(3\)/);
  assert.match(all, /wiki-search · This Workspace · streamable-http · Connected · 3 tools/);
  assert.ok(!all.includes("fake-never-shown") && !all.includes("https://"));
  assert.equal(ui.view.root.findAll((node) => node.type === "input" || node.type === "form").length, 0);
  const manage = ui.view.root.findAll((node) => node.type === "button")[0];
  assert.equal(text(manage), "Manage MCP servers");
  await act(async () => manage.props.onClick());
  assert.deepEqual(ui.opened, ["mcp"]);
});

test("runtime WP S6: a server is allowed in this Workspace with one toggle", async () => {
  const calls = [];
  const ui = await mount(async (url, init) => {
    calls.push([url, init?.method ?? "GET", init?.body ?? ""]);
    if (url === "/api/v1/admin/workspaces/ws-1/mcp-servers") return { servers: [{ server_id: "s-1", allowed: false }] };
    if (url.startsWith("/api/v1/admin/workspaces/")) return { allowed: true };
    return SERVERS;
  });
  const toggles = ui.view.root.findAll((node) => node.type === "input" && node.props["data-testid"] === "workspace-mcp-allow");
  assert.equal(toggles.length, 1);
  await act(async () => toggles[0].props.onChange({ target: { checked: true } }));
  assert.deepEqual(calls.at(-1), ["/api/v1/admin/workspaces/ws-1/mcp-servers/s-1", "PUT", JSON.stringify({ allowed: true })]);
  assert.match(ui.all(), /Allowed in this Workspace/);
});

test("a failed listing shows nothing", async () => {
  const ui = await mount(async () => {
    throw Object.assign(new Error("Not Found"), { status: 404 });
  });
  assert.equal(ui.view.toJSON(), null);
});
