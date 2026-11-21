import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  AGENTS_GROUP,
  buildPaletteGroups,
  defaultOpenGroups,
  filterPaletteGroups,
  flowAgentOptions,
  paletteEntryAccessibleName,
} from "../../src/admin/components/flowBuilder/flowPaletteModel.ts";

const PROJECTS = new Map([["ws-sales", "Sales"], ["ws-ops", "Operations"]]);

function catalogItem(id, category, display_name, extra = {}) {
  return {
    id, category, display_name, node_type: extra.node_type ?? "tool_step", binding_type: extra.binding_type ?? "tool",
    binding_ref: id, icon_hint: "", description: "", token_cost_risk: "low", availability_status: "available",
    disabled_reason: null, default_config: {}, ...extra,
  };
}

const CATALOG = [
  catalogItem("generic:trigger", "Input / Output", "Input", { node_type: "trigger", binding_type: "generic" }),
  catalogItem("generic:output", "Input / Output", "Output", { node_type: "output", binding_type: "generic" }),
  catalogItem("generic:agent_step", "AI", "Agent Step", { node_type: "agent_step", binding_type: "generic" }),
  catalogItem("tool:jira_search", "Tools / Jira", "Jira Search", {
    availability_status: "disabled", disabled_reason: "jira connector is not globally configured.",
  }),
  catalogItem("tool:knowledge_search", "Knowledge", "Knowledge Search", { node_type: "retrieval" }),
];

// Agent panel payload shape (camelCase, as /admin/chat/api/panel/agents returns it).
const AGENT_ROWS = [
  { id: "a-onboarding", name: "Onboarding Agent", isActive: false, projectId: "", steps: [] },
  { id: "a-global", name: "Research Agent", isActive: true, projectId: "", steps: [{}, {}] },
  { id: "a-sales", name: "Sales Agent", isActive: true, projectId: "ws-sales", steps: [] },
  { id: "a-ops", name: "Ops Agent", isActive: true, projectId: "ws-ops", steps: [] },
];

test("agents keep the agent's active flag and workspace scope (no new authorization)", () => {
  const inSales = Object.fromEntries(flowAgentOptions(AGENT_ROWS, "ws-sales", PROJECTS).map((a) => [a.id, a.disabledReason]));
  assert.equal(inSales["a-onboarding"], "Inactive — activate it on its agent page");
  assert.equal(inSales["a-global"], null);
  assert.equal(inSales["a-sales"], null);
  assert.equal(inSales["a-ops"], "Belongs to Operations; this workflow is in Sales");
  const inGlobal = Object.fromEntries(flowAgentOptions(AGENT_ROWS, null, PROJECTS).map((a) => [a.id, a.disabledReason]));
  assert.equal(inGlobal["a-sales"], "Belongs to Sales; this workflow is Global");
  assert.equal(inGlobal["a-global"], null);
});

test("groups: agents follow AI, only the start/end and AI groups open by default", () => {
  const groups = buildPaletteGroups(CATALOG, [], flowAgentOptions(AGENT_ROWS, null, PROJECTS));
  assert.deepEqual(groups.map((group) => group.label), ["Input / Output", "AI", AGENTS_GROUP, "Tools / Jira", "Knowledge"]);
  assert.deepEqual([...defaultOpenGroups(groups)], ["Input / Output", "AI", AGENTS_GROUP]);
  const jira = groups.find((group) => group.label === "Tools / Jira").entries[0];
  assert.equal(jira.disabledReason, "jira connector is not globally configured.");
  assert.equal(paletteEntryAccessibleName(jira), "Jira Search — unavailable: jira connector is not globally configured.");
  const onboarding = groups.find((group) => group.label === AGENTS_GROUP).entries.find((entry) => entry.label === "Onboarding Agent");
  assert.equal(paletteEntryAccessibleName(onboarding), "agent step: Onboarding Agent — unavailable: Inactive — activate it on its agent page");
});

test("search filters every entry, including collapsed groups, by all terms", () => {
  const groups = buildPaletteGroups(CATALOG, [], flowAgentOptions(AGENT_ROWS, null, PROJECTS));
  assert.deepEqual(filterPaletteGroups(groups, "knowledge").map((g) => [g.label, g.entries.map((e) => e.label)]), [["Knowledge", ["Knowledge Search"]]]);
  assert.deepEqual(filterPaletteGroups(groups, "research agent").flatMap((g) => g.entries.map((e) => e.label)), ["Research Agent"]);
  assert.equal(filterPaletteGroups(groups, "zzz").length, 0);
  assert.equal(filterPaletteGroups(groups, "  ").length, groups.length);
});

test("rendered palette: search box, collapsed tool groups, disabled agents and tools with reasons", async () => {
  const { registerHooks } = await import("node:module");
  const { transpileModule, ModuleKind, JsxEmit } = await import("typescript");
  const loader = registerHooks({
    resolve(specifier, context, nextResolve) {
      if (specifier.startsWith(".") && !/\.[a-z]+$/.test(specifier)) {
        try { return nextResolve(`${specifier}.tsx`, context); } catch { /* Shared TS resolver follows. */ }
      }
      return nextResolve(specifier, context);
    },
    load(url, context, nextLoad) {
      if (url.endsWith(".css")) return { format: "module", source: "", shortCircuit: true };
      if (url.endsWith(".tsx")) return { format: "module", shortCircuit: true, source: transpileModule(readFileSync(new URL(url), "utf8"), {
        compilerOptions: { module: ModuleKind.ESNext, jsx: JsxEmit.ReactJSX },
      }).outputText };
      return nextLoad(url, context);
    },
  });
  const { FlowPalette } = await import("../../src/admin/components/flowBuilder/FlowPalette.tsx");
  loader.deregister();
  const { createElement } = await import("react");
  const { default: renderer } = await import("react-test-renderer");
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;

  const added = [];
  let view;
  renderer.act(() => {
    view = renderer.create(createElement(FlowPalette, {
      onAddNode: (...args) => added.push(args), nodeCatalogItems: CATALOG,
      agents: flowAgentOptions(AGENT_ROWS, "ws-sales", PROJECTS),
    }));
  });
  const search = view.root.findByProps({ "aria-label": "Search steps, tools and agents" });
  assert.equal(search.type, "input");
  const buttons = () => view.root.findAllByType("button");
  for (const button of buttons()) {
    const name = button.props["aria-label"] ?? button.children.filter((child) => typeof child !== "string").length;
    assert.ok(name, "every palette button has an accessible name or text");
  }
  const byName = (name) => buttons().find((button) => button.props["aria-label"] === name);
  assert.equal(byName("Add Agent Step").props.disabled, false);
  assert.equal(byName("Add agent step: Sales Agent").props.disabled, false);
  assert.equal(byName("agent step: Onboarding Agent — unavailable: Inactive — activate it on its agent page").props.disabled, true);
  assert.equal(byName("agent step: Ops Agent — unavailable: Belongs to Operations; this workflow is in Sales").props.disabled, true);
  // Tool groups start collapsed: the policy-gated Jira tool is not listed until searched.
  assert.equal(buttons().some((button) => /Jira Search/.test(button.props["aria-label"] ?? "")), false);
  const jiraHeader = buttons().find((button) => button.props["aria-controls"]?.includes("tools-jira"));
  assert.equal(jiraHeader.props["aria-expanded"], false);

  renderer.act(() => byName("Add agent step: Sales Agent").props.onClick());
  assert.deepEqual(added[0].slice(0, 3), ["agent_step", "a-sales", "Sales Agent"]);

  renderer.act(() => search.props.onChange({ target: { value: "jira" } }));
  const jira = byName("Jira Search — unavailable: jira connector is not globally configured.");
  assert.equal(jira.props.disabled, true);
  assert.equal(buttons().some((button) => button.props["aria-label"] === "Add agent step: Sales Agent"), false);
  renderer.act(() => view.unmount());
});
