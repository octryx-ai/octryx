// "Test in chat" on the canonical agent page (judge J-E-005).
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as model from "../../src/admin/components/agentsTab/agentWorkspaceModel.ts";
const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function load() {
  const exports = {};
  const location = { href: "http://x/chat?area=workflows&tab=agents" };
  const source = fs.readFileSync(new URL("../../src/admin/components/agentsTab/AgentTestAction.tsx", import.meta.url), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  vm.runInNewContext(output, {
    exports, window: { location },
    require: (name) => (name.endsWith("agentWorkspaceModel") ? model : require(name)),
  });
  return { Action: exports.AgentTestAction, location };
}

const workspaces = [{ id: "w1", name: "Petclinic", is_active: true }, { id: "w2", name: "Fixture", is_active: false }];
const testButton = (view) => view.root.findAllByType("button").find((b) => b.props.children === "Test in chat");

test("an inactive agent or an agent in an inactive workspace cannot be tested", () => {
  const { Action } = load();
  let view;
  act(() => { view = TestRenderer.create(createElement(Action, { agent: { id: "a" , projectId: "w1" }, active: false, workspaces })); });
  assert.equal(testButton(view).props.disabled, true);
  act(() => view.update(createElement(Action, { agent: { id: "a", projectId: "w2" }, active: true, workspaces })));
  assert.equal(testButton(view).props.disabled, true);
  act(() => view.unmount());
});

test("an agent with a workspace opens a chat with that agent and workspace", () => {
  const { Action, location } = load();
  let view;
  act(() => { view = TestRenderer.create(createElement(Action, { agent: { id: "a", projectId: "w1" }, active: true, workspaces })); });
  act(() => testButton(view).props.onClick());
  assert.equal(location.href, "/chat?new=true&agent_id=a&project_id=w1&workspace_id=w1");
  act(() => view.unmount());
});

test("a global agent needs an explicit active test workspace; nothing is preselected", () => {
  const { Action, location } = load();
  let view;
  act(() => { view = TestRenderer.create(createElement(Action, { agent: { id: "g", projectId: "" }, active: true, workspaces })); });
  assert.equal(testButton(view).props.disabled, true);
  const select = view.root.findByType("select");
  assert.deepEqual(select.findAllByType("option").map((o) => o.props.value), ["", "w1"]);
  act(() => select.props.onChange({ target: { value: "w1" } }));
  act(() => testButton(view).props.onClick());
  assert.equal(location.href, "/chat?new=true&agent_id=g&project_id=w1&workspace_id=w1");
  act(() => view.unmount());
});
