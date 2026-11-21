// Guided step form render contract (judge follow-up): every control has
// a programmatic label, saved tools outside the catalog survive a pick, and the
// JSON configuration stays behind an advanced disclosure unless it is in use.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as selection from "../../src/admin/components/agentsTab/stepToolSelection.ts";
import * as model from "../../src/admin/components/agentsTab/agentWorkspaceModel.ts";
const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function loadTsx(file) {
  const exports = {};
  const source = fs.readFileSync(new URL(`../../src/admin/components/agentsTab/${file}`, import.meta.url), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  vm.runInNewContext(output, { exports, require: resolve });
  return exports;
}

function resolve(name) {
  if (name.endsWith(".css")) return {};
  if (name.endsWith("/stepToolSelection")) return selection;
  if (name.endsWith("/agentWorkspaceModel")) return model;
  if (name.endsWith("/AgentStepToolsField")) return loadTsx("AgentStepToolsField.tsx");
  if (name.endsWith("/AgentStepToolUseField")) return loadTsx("AgentStepToolUseField.tsx");
  // The form opens in the design system's side panel.
  if (name.endsWith("/layout/SidePanel")) return require("../../src/layout/SidePanel.ts");
  return require(name);
}

const { AgentStepFormPanel } = loadTsx("AgentStepFormPanel.tsx");

function render(overrides = {}) {
  const writes = { tools: [], config: [] };
  const ctx = {
    agentBuilderMeta: { step_type_options: ["analysis", "tooling"], tool_options: ["knowledge_search", "get_confluence_page"] },
    agentStepFormFor: "agent-1",
    agentStepFormName: "Research",
    agentStepFormType: "analysis",
    agentStepFormInstructions: "",
    agentStepFormSuccessCriteria: "",
    agentStepFormAllowedTools: "knowledge_search, retired_tool",
    agentStepFormConfig: "{\n  \n}",
    agentStepFormEnabled: true,
    editingAgentStep: { id: "s1", name: "Research" },
    setAgentStepFormAllowedTools: (value) => writes.tools.push(value),
    setAgentStepFormConfig: (value) => writes.config.push(value),
    ...overrides,
  };
  let view;
  act(() => { view = TestRenderer.create(createElement(AgentStepFormPanel, { agentId: "agent-1", ctx })); });
  return { view, writes };
}

const hasLabel = (view, control) => {
  if (control.props.id && view.root.findAll((node) => node.type === "label" && node.props.htmlFor === control.props.id).length) return true;
  for (let node = control.parent; node; node = node.parent) if (node.type === "label") return true;
  return false;
};

test("every input, select and textarea of the step form has an associated label", () => {
  const { view } = render();
  const controls = view.root.findAll((node) => ["input", "select", "textarea"].includes(node.type));
  assert.ok(controls.length >= 8);
  for (const control of controls) assert.ok(hasLabel(view, control), `unlabelled ${control.type} ${control.props.type || ""}`);
  assert.equal(new Set(controls.map((c) => c.props.id).filter(Boolean)).size, controls.filter((c) => c.props.id).length);
  act(() => view.unmount());
});

test("a saved tool outside the catalog is marked and survives picking another tool", () => {
  const { view, writes } = render();
  const text = JSON.stringify(view.toJSON());
  assert.ok(text.includes("Not in the current catalog"));
  const options = view.root.findAll((n) => n.type === "span" && n.props.className === "agent-step-tools__option-name");
  assert.deepEqual(options.map((o) => o.props.children), ["knowledge_search", "get_confluence_page"]);
  const pick = options[1].parent.findByType("input");
  act(() => pick.props.onChange({ target: { checked: true } }));
  assert.deepEqual(writes.tools, ["knowledge_search, retired_tool, get_confluence_page"]);
  act(() => view.unmount());
});

test("the JSON configuration is collapsed when empty and open when the step already has one", () => {
  const empty = render();
  assert.equal(empty.view.root.findByType("details").props.open, false);
  act(() => empty.view.unmount());
  const used = render({ agentStepFormConfig: '{"tdd_cycle_phases":["write_tests"]}' });
  assert.equal(used.view.root.findByType("details").props.open, true);
  act(() => used.view.unmount());
});

test("changing tool use writes only tool_use and keeps the other configuration keys", () => {
  const { view, writes } = render({ agentStepFormConfig: '{"custom":1}' });
  const select = view.root.findAll((n) => n.type === "select").find((s) => s.props.value === "required");
  act(() => select.props.onChange({ target: { value: "optional" } }));
  assert.deepEqual(JSON.parse(writes.config[0]), { custom: 1, tool_use: "optional" });
  act(() => view.unmount());
});
