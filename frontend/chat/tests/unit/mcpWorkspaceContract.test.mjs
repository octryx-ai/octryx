// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// Every Workspace-scoped MCP registry call from the admin tab must
// name its Workspace, and the request bodies must match the backend schemas
// (MCPServerCreateRequest, MCPCatalogInstallRequest, MCPServerUpdateRequest are
// extra="forbid", so any stray field is a 422). The backend sources are read as
// text and their field sets compared, so a schema change fails here.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

import {
  MCP_CUSTOM_TRANSPORTS,
  MCP_DEFAULT_CUSTOM_TRANSPORT,
  MCP_SERVERS_CREATE_PATH,
  buildMcpCatalogInstallBody,
  buildMcpCatalogUpdateBody,
  buildMcpCustomServerBody,
  mcpCatalogInstallPath,
  mcpCatalogListPath,
  mcpEditValuesFromSettings,
  mcpServerActionPath,
  mcpServersListPath,
  mcpWorkspaceOptions,
  resolveMcpWorkspaceId,
  splitMcpCatalogValues,
} from "../../src/admin/components/mcpWorkspaceContract.ts";

const repoRoot = new URL("../../../../", import.meta.url);

function backendSchemaFields(className) {
  const source = readFileSync(
    new URL("backend/app/schemas/admin/admin_panel/_connectors.py", repoRoot),
    "utf8",
  );
  const start = source.indexOf(`class ${className}(BaseModel):`);
  assert.notEqual(start, -1, `${className} not found`);
  const rest = source.slice(start).split("\n").slice(1);
  const fields = new Set();
  for (const line of rest) {
    if (/^\S/.test(line)) break;
    const match = /^ {4}([a-z_]+):/.exec(line);
    if (match) fields.add(match[1]);
  }
  return fields;
}

const PRESET = {
  fields: [
    { name: "endpoint", type: "select", default: "observability" },
    { name: "user_agent", type: "text" },
    { name: "api_key", type: "password" },
  ],
};

describe("Workspace selection", () => {
  test("offers active projects only, named, in listed order", () => {
    const options = mcpWorkspaceOptions([
      { id: "p1", name: "Alpha", is_active: true },
      { id: "p2", name: "Retired", is_active: false },
      { id: "p3", name: "", is_active: true },
      { id: " ", name: "Blank", is_active: true },
    ]);
    assert.deepEqual(options, [
      { id: "p1", name: "Alpha" },
      { id: "p3", name: "p3" },
    ]);
  });

  // The selection comes only from the shared active workspace, never from the first project in the list; an
  // unlisted or empty one resolves to none.
  test("keeps a listed selection, otherwise selects no Workspace", () => {
    const options = [
      { id: "p1", name: "Alpha" },
      { id: "p3", name: "Gamma" },
    ];
    assert.equal(resolveMcpWorkspaceId(options, "p3"), "p3");
    assert.equal(resolveMcpWorkspaceId(options, "gone"), "");
    assert.equal(resolveMcpWorkspaceId(options, ""), "");
    assert.equal(resolveMcpWorkspaceId([], "p1"), "");
  });
});

describe("Workspace-scoped paths", () => {
  test("list and catalog carry workspace_id", () => {
    assert.equal(
      mcpServersListPath("p 1"),
      "/admin/chat/api/panel/mcp/servers?workspace_id=p+1",
    );
    assert.equal(
      mcpCatalogListPath("p1"),
      "/admin/chat/api/panel/mcp/catalog?workspace_id=p1",
    );
  });

  test("server actions carry workspace_id and encode the name", () => {
    assert.equal(
      mcpServerActionPath("a/b", "p1", "connect"),
      "/admin/chat/api/panel/mcp/servers/a%2Fb/connect?workspace_id=p1",
    );
    assert.equal(
      mcpServerActionPath("srv", "p1", "disconnect"),
      "/admin/chat/api/panel/mcp/servers/srv/disconnect?workspace_id=p1",
    );
    assert.equal(
      mcpServerActionPath("srv", "p1"),
      "/admin/chat/api/panel/mcp/servers/srv?workspace_id=p1",
    );
  });

  test("create and install use the collection paths", () => {
    assert.equal(MCP_SERVERS_CREATE_PATH, "/admin/chat/api/panel/mcp/servers");
    assert.equal(
      mcpCatalogInstallPath("aws docs"),
      "/admin/chat/api/panel/mcp/catalog/aws%20docs/install",
    );
  });

  test("a missing Workspace is an explicit error, never an unscoped call", () => {
    assert.throws(() => mcpServersListPath(""), /Select a Workspace/);
    assert.throws(() => mcpServerActionPath("srv", " "), /Select a Workspace/);
  });
});

describe("request bodies match the backend schemas", () => {
  test("custom create is workspace-owned and schema-exact", () => {
    const body = buildMcpCustomServerBody({
      workspaceId: "p1",
      name: " my-mcp ",
      transport: "sse",
      url: " https://example.com/mcp ",
      description: " d ",
      autoStart: false,
    });
    assert.deepEqual(body, {
      owner_scope: "workspace",
      workspace_id: "p1",
      name: "my-mcp",
      transport: "sse",
      url: "https://example.com/mcp",
      description: "d",
      auto_start: false,
    });
    const allowed = backendSchemaFields("MCPServerCreateRequest");
    for (const key of Object.keys(body)) assert.ok(allowed.has(key), key);
    assert.throws(
      () => buildMcpCustomServerBody({ ...body, workspaceId: "" }),
      /Select a Workspace/,
    );
  });

  test("custom transports are the backend's remote transports", () => {
    const source = readFileSync(
      new URL("backend/app/services/mcp_server_registry_writes.py", repoRoot),
      "utf8",
    );
    const match = /_REMOTE_TRANSPORTS = \{([^}]*)\}/.exec(source);
    assert.ok(match);
    const backend = new Set(
      [...match[1].matchAll(/"([^"]+)"/g)].map((item) => item[1]),
    );
    assert.deepEqual(new Set(MCP_CUSTOM_TRANSPORTS), backend);
    assert.ok(backend.has(MCP_DEFAULT_CUSTOM_TRANSPORT));
  });

  test("catalog install splits settings and Secret References", () => {
    const body = buildMcpCatalogInstallBody({
      preset: PRESET,
      workspaceId: "p1",
      name: " cf ",
      autoStart: true,
      values: { endpoint: "bindings", user_agent: " ", api_key: "secret:s1" },
    });
    assert.deepEqual(body, {
      owner_scope: "workspace",
      workspace_id: "p1",
      name: "cf",
      auto_start: true,
      settings: { endpoint: "bindings" },
      secret_refs: { api_key: "secret:s1" },
    });
    const allowed = backendSchemaFields("MCPCatalogInstallRequest");
    for (const key of Object.keys(body)) assert.ok(allowed.has(key), key);
  });

  test("catalog update keeps blank secrets and sends plain fields", () => {
    const body = buildMcpCatalogUpdateBody({
      preset: PRESET,
      autoStart: false,
      values: { endpoint: "observability", user_agent: "", api_key: "" },
    });
    assert.deepEqual(body, {
      auto_start: false,
      settings: { endpoint: "observability", user_agent: "" },
      secret_refs: {},
    });
    const allowed = backendSchemaFields("MCPServerUpdateRequest");
    for (const key of Object.keys(body)) assert.ok(allowed.has(key), key);
  });

  test("values outside the preset are never sent", () => {
    assert.deepEqual(
      splitMcpCatalogValues(PRESET, { unknown: "x" }, "install"),
      { settings: {}, secret_refs: {} },
    );
  });
});

describe("edit form seed", () => {
  test("uses stored settings or defaults, never a secret value", () => {
    assert.deepEqual(
      mcpEditValuesFromSettings(PRESET, {
        user_agent: "ua",
        api_key: "leak",
      }),
      { endpoint: "observability", user_agent: "ua", api_key: "" },
    );
  });
});
