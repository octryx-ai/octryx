import assert from "node:assert/strict";
import { test } from "node:test";
import { connectorWorkspaceState } from "../../src/admin/components/projectsTab/workspaceConnectorTableState.ts";

// Fresh-install test: Workspace › Connector access read "GitHub · Off · Not set up" beside a working
// "GitHub (demo)" connection. A named connection available here serves the Workspace; the row says so.
const github = { connector_name: "github", project_enabled: false, global_configured: false, global_active: false };

test("a working named connection serves the Workspace: 'Via <name>', no platform connector needed", () => {
  const state = connectorWorkspaceState(github, [{ type: "github", name: "GitHub (demo)", state: "ok" }]);
  assert.equal(state.workspace.label, "Via GitHub (demo)");
  assert.equal(state.workspace.tone, "neutral");
  assert.equal(state.platform.label, "Not needed");
});

test("a failing one still serves it, marked; without any connection the old On/Off and platform state stay", () => {
  const failing = connectorWorkspaceState(github, [{ type: "github", name: "GitHub (team)", state: "failing" }]);
  assert.deepEqual([failing.workspace.label, failing.workspace.tone], ["Via GitHub (team)", "attention"]);
  const none = connectorWorkspaceState(github, [{ type: "jira", name: "Jira", state: "ok" }]);
  assert.deepEqual([none.workspace.label, none.platform.label], ["Off", "Not set up"]);
  const global = connectorWorkspaceState({ ...github, global_configured: true, global_active: true },
    [{ type: "github", name: "GitHub (demo)", state: "ok" }]);
  assert.equal(global.platform.label, "Ready", "a platform connector that exists keeps its own state");
});
