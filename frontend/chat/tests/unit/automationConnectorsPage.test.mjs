// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/automationConnectorsPage.test.mjs
//
// Remove lives in the connector drawer, lists what uses the connector and stays disabled while
// anything does; once nothing does, the typed name confirms. Pause calls only the pause endpoint.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement, Fragment } from "react";
import TestRenderer from "react-test-renderer";

import { makeLoader, text } from "./automationTestLoader.mjs";

const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

async function mount(usage) {
  const { useConnectorLifecycle } = makeLoader()("admin/components/connectorsTab/ConnectorDangerZone.tsx");
  // The connector drawer renders the hook's toggle, its menu items as buttons and its dialog.
  function ConnectorDangerZone({ connector, ctx }) {
    const { toggle, menuItems, dialog } = useConnectorLifecycle(connector, ctx);
    return createElement(Fragment, null, toggle, ...menuItems.map((item) =>
      createElement("button", { key: item.label, type: "button", disabled: item.disabled, onClick: item.onSelect }, item.label)), dialog);
  }
  const calls = [];
  const ctx = {
    readJson: async (url) => { calls.push(["GET", url]); return usage; },
    handleDeleteConnector: async (tool, typed) => { calls.push(["DELETE", tool, typed]); },
    handleSetConnectorActive: async (tool, active) => { calls.push(["ACTIVE", tool, active]); },
  };
  const connector = { tool_name: "jira", label: "Jira", is_active: true, configured: true };
  let view;
  await act(async () => { view = TestRenderer.create(createElement(ConnectorDangerZone, { connector, ctx })); });
  const button = (label) => view.root.find((node) => node.type === "button" && text(node).startsWith(label));
  return { view, calls, button };
}

test("Remove is blocked while a Workspace uses the connector and names it", async () => {
  const { view, calls, button } = await mount({ workspaces: ["Payments"], named_connections: [], knowledge_sources: 0, references: 1 });
  await act(async () => { button("Remove…").props.onClick(); });
  assert.match(text(view.root), /Reassign or remove these first/);
  assert.match(text(view.root), /Workspaces: Payments/);
  assert.equal(button("Remove connector").props.disabled, true);
  assert.deepEqual(calls, [["GET", "/admin/chat/api/panel/connectors/jira/usage"]]);
});

test("an unused connector is removed after typing its name; Pause only flips is_active", async () => {
  const { view, calls, button } = await mount({ workspaces: [], named_connections: [], knowledge_sources: 0, references: 0 });
  await act(async () => { button("Pause").props.onClick(); });
  await act(async () => { button("Remove…").props.onClick(); });
  assert.equal(button("Remove connector").props.disabled, true, "disabled until the name is typed");
  const input = view.root.find((node) => node.type === "input");
  await act(async () => { input.props.onChange({ target: { value: "jira" } }); });
  await act(async () => { button("Remove connector").props.onClick(); });
  assert.deepEqual(calls.filter(([kind]) => kind !== "GET"), [["ACTIVE", "jira", false], ["DELETE", "jira", "jira"]]);
});
