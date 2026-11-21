// If / else step: plain presentation of the existing router contract, nothing rewritten.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as model from "../../src/admin/components/flowBuilder/flowConditionalBranches.ts";
import { branchCondition, branchConnections, edgeBranch } from "../../src/admin/components/flowBuilder/flowBranchConnections.ts";
import { ruleBranch, withRuleBranch } from "../../src/admin/components/flowBuilder/flowRouterRule.ts";
import * as branchModule from "../../src/admin/components/flowBuilder/flowBranchConnections.ts";
import * as ruleModule from "../../src/admin/components/flowBuilder/flowRouterRule.ts";
import * as canvasMapping from "../../src/admin/components/flowBuilder/flowCanvasMapping.ts";
import { buildPaletteGroups, defaultOpenGroups, filterPaletteGroups } from "../../src/admin/components/flowBuilder/flowPaletteModel.ts";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function load(name) {
  const exports = {};
  const base = `../../src/admin/components/flowBuilder/${name}`;
  const url = [".tsx", ".ts"].map((ext) => new URL(base + ext, import.meta.url)).find((candidate) => fs.existsSync(candidate));
  const source = fs.readFileSync(url, "utf8");
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
    exports,
    require: (path) => {
      if (path.endsWith(".css")) return {};
      if (path.endsWith("/flowConditionalBranches")) return model;
      if (path.endsWith("/flowBranchConnections")) return branchModule;
      if (path.endsWith("/flowRouterRule")) return ruleModule;
      if (path.endsWith("/flowCanvasMapping")) return canvasMapping;
      if (path.startsWith("./")) return load(path.slice(2));
      return require(path);
    },
  });
  return exports;
}
const text = (node) => (typeof node === "string" ? node : node.children.map(text).join(""));

test("rule conditions are read in the form they are stored", () => {
  assert.deepEqual(model.readRuleCondition({ when: { field: "total", operator: "gt", value: 0 } }), {
    form: "operator", field: "total", operator: "gt", value: 0, hasValue: true, check: { state: "ok" },
  });
  // A comparison key without `operator` is not a comparison: kept raw and refused.
  const keyed = model.readRuleCondition({ when: { field: "tier", equals: "gold" } });
  assert.deepEqual([keyed.form, keyed.check], ["custom", { state: "invalid", reason: "no comparison" }]);
  assert.equal(model.readRuleCondition({ when: {} }).form, "always");
  assert.equal(model.readRuleCondition({ when: null }).form, "always");
  assert.equal(model.readRuleCondition({}).form, "always");
  assert.equal(model.readRuleCondition({ when: { all: [1] } }).form, "custom");
  // false, 0, "", [] and text are not "always": kept raw and refused.
  for (const when of [false, 0, "", [], "amount > 10", 5]) {
    const condition = model.readRuleCondition({ when });
    assert.equal(condition.form, "custom", JSON.stringify(when));
    assert.equal(condition.raw, when);
    assert.equal(condition.check.state, "invalid");
  }
  // Case and spaces of a supported operator are accepted, and the saved spelling is kept.
  const spelled = model.readRuleCondition({ when: { field: "n", operator: " GT ", value: 1 } });
  assert.deepEqual([spelled.operator, spelled.check.state], [" GT ", "ok"]);
});

test("edits write the field, operator and value back into the rule; other keys are kept", () => {
  const typed = { route: "big", when: { field: "total", operator: "gt", value: 10 }, note: "kept" };
  assert.deepEqual(model.withCondition(typed, { operator: "gte" }).when, { field: "total", operator: "gte", value: 10 });
  const next = model.withCondition(typed, { value: 20 });
  assert.deepEqual(next, { route: "big", when: { field: "total", operator: "gt", value: 20 }, note: "kept" });
  assert.deepEqual(withRuleBranch({ target: "x", when: {} }, "y"), { target: "y", when: {} });
  assert.deepEqual(withRuleBranch({ when: {} }, "y"), { when: {}, route: "y" });
});

test("value types are explicit: text is never guessed into a number or a list", () => {
  assert.equal(model.valueTypeOf("5", "equals"), "text");
  assert.equal(model.valueTypeOf(5, "equals"), "number");
  assert.equal(model.valueTypeOf(false, "equals"), "boolean");
  assert.equal(model.valueTypeOf(["a, b"], "in"), "text_list");
  assert.equal(model.valueTypeOf([1, 2], "in"), "number_list");
  assert.equal(model.valueTypeOf([1, "a"], "in"), "keep");
  assert.equal(model.valueTypeOf({ a: 1 }, "equals"), "keep");
  assert.equal(model.valueTypeOf(undefined, "gte"), "number");
  assert.deepEqual(model.parseTypedValue("5", "text"), { value: "5" });
  assert.deepEqual(model.parseTypedValue(" 5 ", "number"), { value: 5 });
  assert.equal(model.parseTypedValue("5a", "number"), null);
  assert.deepEqual(model.parseTypedValue("a, b\nc\n", "text_list"), { value: ["a, b", "c"] });
  assert.deepEqual(model.parseTypedValue("1\n2.5", "number_list"), { value: [1, 2.5] });
  assert.equal(model.parseTypedValue("1\nx", "number_list"), null);
});

test("operators read as plain words; aliases and unsupported spellings stay visible", () => {
  assert.equal(model.operatorLabel("gte"), "is at least");
  assert.equal(model.operatorLabel("in"), "is one of");
  assert.equal(model.operatorLabel("eq"), "is equal to (saved as eq)");
  assert.equal(model.operatorLabel("GT"), "is greater than (saved as GT)");
  assert.equal(model.operatorLabel(" Eq "), "is equal to (saved as  Eq )");
  assert.deepEqual(model.operatorValueTypes(" GT "), ["number"]);
  assert.match(model.operatorLabel("between"), /not supported: the workflow stops at this step until you choose another comparison/);
  assert.deepEqual(model.ruleWarnings(model.readRuleCondition({ when: {} })), [
    "This rule has no condition, so it always matches and the rules below it never run.",
  ]);
  assert.equal(
    model.ruleWarnings(model.readRuleCondition({ when: { field: "", operator: "equals", value: "" } }))[0],
    "This rule cannot be checked (no value to check), so the workflow stops at this step with an error until it is fixed.",
  );
  assert.deepEqual(model.ruleWarnings(model.readRuleCondition({ when: { field: "n", operator: "GT", value: 1 } })), []);
  for (const warning of model.ruleWarnings(model.readRuleCondition({ when: { field: "n", operator: "between", value: 1 } }))) {
    assert.doesNotMatch(warning, /never matches/);
  }
});

test("branches and connections follow the runtime's forms and fallback", () => {
  assert.equal(ruleBranch({ route: "", target: "x" }), "x");
  assert.equal(ruleBranch({}), "default");
  assert.deepEqual(edgeBranch("found"), { kind: "branch", name: "found" });
  assert.deepEqual(edgeBranch("route:found"), { kind: "branch", name: "found" });
  assert.deepEqual(edgeBranch({ route: "found", extra: 1 }), { kind: "branch", name: "found" });
  assert.deepEqual(edgeBranch({}), { kind: "fallback" });
  assert.deepEqual(edgeBranch(undefined), { kind: "fallback" });
  assert.equal(edgeBranch({ field: "score", operator: "gt", value: 1 }).kind, "custom");
  assert.equal(edgeBranch({ field: "route", equals: "found" }).kind, "custom", "a comparison key without operator is no branch");
  assert.deepEqual(edgeBranch({ field: "route", operator: "equals", value: "missing" }), { kind: "branch", name: "missing" });
  assert.equal(edgeBranch({ field: "route", operator: "contains", value: "f" }).kind, "custom");
  assert.equal(branchCondition({ kind: "branch", name: "found" }), "route:found");

  const rules = [{ route: "large", when: { field: "amount", operator: "gt", value: 100 } }];
  const edges = [
    { source_node_id: "check", target_node_id: "approve", condition: "route:large" },
    { source_node_id: "check", target_node_id: "auto", condition: { route: "default" } },
    { source_node_id: "check", target_node_id: "audit", condition: { field: "x", operator: "exists", value: true } },
    { source_node_id: "check", target_node_id: "ghost", condition: "route:missing" },
    { source_node_id: "other", target_node_id: "elsewhere" },
  ];
  const names = { approve: "Manual approval", auto: "Auto approve" };
  const summary = branchConnections("check", rules, "default", edges, (id) => names[id] ?? id);
  assert.deepEqual(summary.branches, [
    { name: "large", label: "Rule 1", targets: ["Manual approval"], reachable: true },
    { name: "default", label: "Otherwise", targets: ["Auto approve"], reachable: true },
  ]);
  assert.deepEqual(summary.customTargets, ["audit"]);
  assert.deepEqual(summary.orphanTargets, [{ names: ["route:missing", "missing"], target: "ghost" }]);
  assert.deepEqual(summary.fallbackTargets, []);
  assert.deepEqual(summary.coverage, { state: "complete" });
  assert.deepEqual(edgeBranch(5), { kind: "never", text: "5" });
  assert.deepEqual(edgeBranch(["x"]), { kind: "never", text: '["x"]' });
});

test("an unconnected branch fails the run unless a fallback exists; custom predicates stay undecided", () => {
  const rules = [{ route: "large", when: { field: "amount", operator: "gt", value: 100 } }];
  const toLarge = { source_node_id: "r", target_node_id: "big", condition: "route:large" };
  assert.deepEqual(branchConnections("r", rules, "default", [toLarge]).coverage, { state: "missing", branches: ["default"] });
  const fallback = { source_node_id: "r", target_node_id: "rest" };
  assert.deepEqual(branchConnections("r", rules, "default", [toLarge, fallback]).coverage, { state: "complete" });
  // A custom predicate may pick the Otherwise target at run time: no static "unmatched" claim.
  const custom = { source_node_id: "r", target_node_id: "audit", condition: { field: "score", operator: "gt", value: 1 } };
  assert.deepEqual(branchConnections("r", rules, "default", [toLarge, custom]).coverage, { state: "runtime", branches: ["default"] });
  // No connections: the workflow simply ends at the step.
  assert.deepEqual(branchConnections("r", rules, "default", []).coverage, { state: "no_connections" });
  // After a rule without a condition nothing else is picked, so later branches need no connection.
  const always = [{ route: "large", when: {} }, { route: "small", when: { field: "x", operator: "equals", value: 1 } }];
  const summary = branchConnections("r", always, "default", [toLarge]);
  assert.deepEqual(summary.branches.map((branch) => [branch.name, branch.reachable]), [["large", true], ["small", false], ["default", false]]);
  assert.deepEqual(summary.coverage, { state: "complete" });
});

test("the palette shows the router as If / else and finds it by plain and technical words", () => {
  const router = {
    id: "generic:router", category: "Logic", display_name: "Router / Conditional", node_type: "router", binding_type: "generic",
    binding_ref: "router", icon_hint: "", description: "Selects an outgoing path.", token_cost_risk: "low",
    availability_status: "available", disabled_reason: null, default_config: {},
  };
  const groups = buildPaletteGroups([router], [], []);
  const entry = groups[0].entries[0];
  assert.equal(entry.label, "If / else");
  assert.match(entry.meta, /^Router \/ Conditional · /);
  assert.equal(entry.catalogItem.id, "generic:router", "the catalog binding is unchanged");
  for (const query of ["if else", "If / else", "condition", "router", "gateway", "branch"]) {
    assert.equal(filterPaletteGroups(groups, query)[0]?.entries[0]?.label, "If / else", query);
  }
  assert.deepEqual([...defaultOpenGroups(groups)], ["Logic"]);
});

test("the inspector configures one rule plus Otherwise without operator codes and keeps typed values", () => {
  const { FlowRouterInspector } = load("FlowRouterInspector");
  const patches = [];
  const node = { id: "check", type: "router", config: { routes: [{ route: "large", when: { field: "amount", operator: "gt", value: 100 } }], default_route: "default" } };
  const nodes = [node, { id: "approve", label: "Manual approval" }];
  const edges = [{ source_node_id: "check", target_node_id: "approve", condition: "route:large" }];
  let view;
  act(() => {
    view = TestRenderer.create(createElement(FlowRouterInspector, { node, nodes, edges, onUpdate: (patch) => patches.push(patch) }));
  });
  const all = text(view.root);
  assert.match(all, /If \/ else/);
  assert.match(all, /first rule that matches picks its branch/);
  assert.match(all, /Rule 1 · branch large: continues to Manual approval/);
  assert.match(all, /Otherwise · branch default: no connection of its own/);
  assert.match(all, /If the workflow picks it, the run stops at this step with an error and nothing after it runs/);
  assert.doesNotMatch(all, /first connection/);
  const options = view.root.findAllByType("option").map((option) => text(option));
  assert.ok(options.includes("is greater than"));
  assert.equal(options.includes("gt"), false, "no operator codes as labels");
  // The value is a number and stays one; typing a new number writes a number.
  const input = view.root.findAllByType("input").find((item) => item.props.value === "100");
  act(() => input.props.onChange({ target: { value: "250" } }));
  assert.deepEqual(patches.at(-1).config.routes[0], { route: "large", when: { field: "amount", operator: "gt", value: 250 } });
  act(() => input.props.onChange({ target: { value: "25x" } }));
  assert.equal(patches.length, 1, "an invalid number is not written");
  assert.match(text(view.root), /Enter a number/);
  // Otherwise branch name is written to default_route.
  const otherwise = view.root.findAllByType("input").find((item) => item.props.placeholder === "default");
  act(() => otherwise.props.onChange({ target: { value: "small" } }));
  assert.equal(patches.at(-1).config.default_route, "small");
  assert.deepEqual(patches.at(-1).config.routes, node.config.routes);
  act(() => view.unmount());
});

test("a saved value no type can show is kept and only replaced on request", () => {
  const { FlowRouterInspector } = load("FlowRouterInspector");
  const patches = [];
  const node = { id: "r", type: "router", config: { routes: [{ route: "x", when: { field: "f", operator: "equals", value: { nested: 1 } } }] } };
  let view;
  act(() => {
    view = TestRenderer.create(createElement(FlowRouterInspector, { node, onUpdate: (patch) => patches.push(patch) }));
  });
  assert.match(text(view.root), /\{"nested":1\}/);
  assert.match(text(view.root), /kept exactly as saved/);
  assert.equal(patches.length, 0);
  act(() => view.unmount());
});

test("a connection out of If / else picks its branch; other condition forms stay until changed", () => {
  const { FlowEdgeMappingEditor } = load("FlowEdgeMappingEditor");
  const router = { id: "check", type: "router", config: { routes: [{ route: "large", when: {} }], default_route: "default" } };
  const updates = [];
  const render = (data) => {
    let view;
    act(() => {
      view = TestRenderer.create(
        createElement(FlowEdgeMappingEditor, {
          edge: { id: "e1", source: "check", target: "approve", data },
          nodes: [router, { id: "approve" }],
          onUpdate: (id, next) => updates.push(next),
          onDelete() {},
        }),
      );
    });
    return view;
  };
  const object = { field: "score", operator: "gt", value: 1 };
  const custom = render({ condition: JSON.stringify(object), conditionSource: object });
  const select = custom.root.findByType("select");
  assert.equal(select.props.value, "__custom__");
  assert.ok(custom.root.findAllByType("input").some((input) => input.props.value === JSON.stringify(object)), "custom text stays editable");
  act(() => select.props.onChange({ target: { value: "large" } }));
  assert.equal(updates.at(-1).condition, "route:large");
  act(() => custom.unmount());

  const legacyString = render({ condition: "large", conditionSource: "large" });
  assert.equal(legacyString.root.findByType("select").props.value, "large", "bare branch names are recognised, not rewritten");
  act(() => legacyString.root.findByType("select").props.onChange({ target: { value: "__fallback__" } }));
  assert.equal(updates.at(-1).condition, "");
  act(() => legacyString.unmount());
});

// --- Value editor identity (judge): the shown value always belongs to the authored rule ---

function inspector(initial) {
  const { FlowRouterInspector } = load("FlowRouterInspector");
  const patches = [];
  let props = { onUpdate: (patch) => patches.push(patch), edges: [], nodes: [], ...initial };
  let view;
  act(() => {
    view = TestRenderer.create(createElement(FlowRouterInspector, props));
  });
  return {
    patches,
    values: () => view.root.findAllByProps({ "data-testid": "router-rule-value" }).filter((item) => typeof item.type === "string").map((item) => item.props.value),
    value: (index = 0) => view.root.findAllByProps({ "data-testid": "router-rule-value" }).filter((item) => typeof item.type === "string")[index],
    kept: () => view.root.findAllByProps({ "data-testid": "router-rule-value-kept" }).filter((item) => typeof item.type === "string"),
    button: (label, index = 0) => view.root.findAllByType("button").filter((item) => text(item) === label)[index],
    rerender(next) {
      props = { ...props, ...next };
      act(() => view.update(createElement(FlowRouterInspector, props)));
    },
    // Applies the last patch the way the editor does (new node config from onUpdate).
    applyLast() {
      const patch = patches.at(-1);
      this.rerender({ node: { ...props.node, ...patch } });
    },
    unmount: () => act(() => view.unmount()),
  };
}

const routerNode = (id, rules) => ({ id, type: "router", config: { routes: rules, default_route: "default" } });
const gt = (route, value) => ({ route, when: { field: "amount", operator: "gt", value } });

test("switching to another If / else step with the same comparison shows that step's value", () => {
  const ui = inspector({ node: routerNode("a", [gt("big", 100)]) });
  assert.deepEqual(ui.values(), ["100"]);
  act(() => ui.value().props.onChange({ target: { value: "10x" } }));
  ui.rerender({ node: routerNode("b", [gt("big", 5)]) });
  assert.deepEqual(ui.values(), ["5"], "neither the old value nor the unfinished entry stays");
  ui.unmount();
});

test("reordering and removing same-comparison rules keeps each value with its rule", () => {
  const ui = inspector({ node: routerNode("r", [gt("first", 1), gt("second", 2)]) });
  assert.deepEqual(ui.values(), ["1", "2"]);
  act(() => ui.button("Move down", 0).props.onClick());
  ui.applyLast();
  assert.equal(JSON.stringify(ui.patches.at(-1).config.routes.map((rule) => rule.route)), '["second","first"]');
  assert.deepEqual(ui.values(), ["2", "1"]);
  act(() => ui.button("Remove", 0).props.onClick());
  ui.applyLast();
  assert.deepEqual(ui.values(), ["1"]);
  assert.equal(JSON.stringify(ui.patches.at(-1).config.routes), JSON.stringify([gt("first", 1)]));
  ui.unmount();
});

test("typing keeps the entry; an outside change such as undo shows the stored value again", () => {
  const ui = inspector({ node: routerNode("r", [gt("big", 100)]) });
  const input = () => ui.value();
  const before = input();
  act(() => input().props.onChange({ target: { value: "2.50" } }));
  ui.applyLast();
  assert.equal(input(), before, "the same input element stays mounted while typing (focus is kept)");
  assert.equal(ui.patches.at(-1).config.routes[0].when.value, 2.5);
  assert.equal(input().props.value, "2.50", "the typed text stays while the stored value is the one typed");
  act(() => input().props.onChange({ target: { value: "2.5x" } }));
  ui.rerender({});
  assert.equal(input().props.value, "2.5x", "an unfinished entry survives unrelated renders");
  // Undo restores the earlier stored value from outside the editor.
  ui.rerender({ node: routerNode("r", [gt("big", 100)]) });
  assert.equal(input().props.value, "100");
  // Redo / another outside change to a different type re-derives the type too.
  ui.rerender({ node: routerNode("r", [{ route: "big", when: { field: "amount", operator: "equals", value: "gold" } }]) });
  assert.equal(input().props.value, "gold");
  assert.equal(ui.patches.length, 1, "synchronising never writes");
  ui.unmount();
});

test("an unknown saved value stays kept across node switches and is never written back", () => {
  const kept = routerNode("k", [{ route: "x", when: { field: "f", operator: "equals", value: { nested: 1 } } }]);
  const ui = inspector({ node: kept });
  const shown = () => ui.values();
  const keptText = () => ui.kept().map((item) => text(item));
  assert.deepEqual(shown(), []);
  assert.deepEqual(keptText(), ['{"nested":1}']);
  ui.rerender({ node: routerNode("n", [{ route: "x", when: { field: "f", operator: "equals", value: 7 } }]) });
  assert.deepEqual(shown(), ["7"]);
  ui.rerender({ node: kept });
  assert.deepEqual(shown(), [], "the kept value is shown read-only again, not as an editable 7");
  assert.deepEqual(keptText(), ['{"nested":1}']);
  assert.equal(ui.patches.length, 0);
  ui.unmount();
});

// --- Parity in the inspector (shared reading with the graph labels) ---

test("coverage never treats malformed rules as always and follows prefix matches", () => {
  // `when: false` is refused, not "always": later branches stay reachable and the step is blocked.
  const blocked = branchConnections("r", [{ route: "a", when: false }, { route: "b", when: { field: "x", operator: "gt", value: 1 } }], "rest", []);
  assert.deepEqual(blocked.branches.map((branch) => [branch.name, branch.reachable]), [["a", true], ["b", true], ["rest", true]]);
  assert.deepEqual(blocked.coverage, { state: "blocked", reason: "rule 1: the condition is not a comparison" });
  // A non-rule item blocks too and names no branch.
  assert.equal(branchConnections("r", ["oops"], "rest", [{ source_node_id: "r", target_node_id: "t" }]).coverage.state, "blocked");
  // A literal route:foo branch is connected by the "route:foo" condition; no orphan.
  const literal = branchConnections("r", [{ route: "route:foo", when: { field: "a", operator: "gt", value: 1 } }], "rest", [
    { source_node_id: "r", target_node_id: "big", condition: "route:foo" },
    { source_node_id: "r", target_node_id: "rest" },
  ]);
  assert.deepEqual(literal.branches[0].targets, ["big"]);
  assert.deepEqual(literal.orphanTargets, []);
  // Both names declared: the one connection serves both branches.
  const both = branchConnections("r", [{ route: "foo", when: { field: "a", operator: "gt", value: 1 } }, { route: "route:foo", when: { field: "b", operator: "lt", value: 0 } }], "rest", [
    { source_node_id: "r", target_node_id: "x", condition: "route:foo" },
  ]);
  assert.deepEqual(both.branches.map((branch) => branch.targets), [["x"], ["x"], []]);
  // A custom connection condition the server cannot check blocks the step.
  const badEdge = branchConnections("r", [], "rest", [{ source_node_id: "r", target_node_id: "x", condition: { field: "s", operator: "in", value: 1 } }]);
  assert.deepEqual(badEdge.invalidCustomTargets, ["x"]);
  assert.equal(badEdge.coverage.state, "blocked");
});

function renderInspector(node, extra = {}) {
  const { FlowRouterInspector } = load("FlowRouterInspector");
  const patches = [];
  let view;
  act(() => {
    view = TestRenderer.create(createElement(FlowRouterInspector, { node, onUpdate: (patch) => patches.push(patch), edges: [], nodes: [], ...extra }));
  });
  const warnings = () => view.root.findAllByProps({ "data-testid": "router-rule-warning" }).filter((item) => typeof item.type === "string").map(text);
  return { view, patches, warnings, all: () => text(view.root) };
}
const routerWith = (routes, extraConfig = {}) => ({ id: "r", type: "router", config: { routes, default_route: "rest", ...extraConfig } });

test("a malformed condition is shown raw and blocks the step; it is never called always", () => {
  for (const when of [false, 0, "", [], "amount > 10"]) {
    const ui = renderInspector(routerWith([{ route: "a", when }]));
    const raw = ui.view.root.findAllByProps({ "data-testid": "router-rule-raw" }).filter((item) => typeof item.type === "string");
    assert.equal(text(raw[0]), JSON.stringify(when));
    assert.match(ui.warnings()[0], /^This rule cannot be checked \(the condition is not a comparison\), so the workflow stops at this step/);
    assert.doesNotMatch(ui.all(), /always matches/);
    assert.match(ui.all(), /This step cannot run until it is fixed/);
    assert.equal(ui.patches.length, 0);
    act(() => ui.view.unmount());
  }
});

test("an accepted operator alias in another case is not flagged and keeps its spelling on value edits", () => {
  const ui = renderInspector(routerWith([{ route: "big", when: { field: "amount", operator: "GT", value: 10 } }]));
  const select = ui.view.root.findAllByType("select")[0];
  assert.equal(select.props.value, "GT");
  assert.ok(ui.view.root.findAllByType("option").some((option) => text(option) === "is greater than (saved as GT)"));
  assert.deepEqual(ui.warnings(), []);
  const value = ui.view.root.findAllByProps({ "data-testid": "router-rule-value" }).find((item) => typeof item.type === "string");
  act(() => value.props.onChange({ target: { value: "20" } }));
  assert.equal(JSON.stringify(ui.patches.at(-1).config.routes[0]), JSON.stringify({ route: "big", when: { field: "amount", operator: "GT", value: 20 } }));
  act(() => ui.view.unmount());
});

test("an unknown comparison is worded as blocking the step, not as never matching", () => {
  const ui = renderInspector(routerWith([{ route: "x", when: { field: "n", operator: "between", value: [1, 2] } }]));
  assert.ok(ui.view.root.findAllByType("option").some((option) => /^between \(not supported: the workflow stops at this step/.test(text(option))));
  assert.match(ui.warnings()[0], /cannot be checked \(unsupported comparison\), so the workflow stops at this step with an error/);
  assert.doesNotMatch(ui.all(), /never matches/);
  act(() => ui.view.unmount());
});

test("items that are not rules and non-list rules are kept as saved through other edits", () => {
  const ui = renderInspector(routerWith(["not a rule", { route: "b", when: { field: "y", operator: "gt", value: 1 } }]));
  assert.match(ui.all(), /This is not a rule, so the workflow stops at this step with an error until it is removed/);
  const branch = ui.view.root.findAllByType("input").find((input) => input.props.value === "b");
  act(() => branch.props.onChange({ target: { value: "bigger" } }));
  assert.equal(JSON.stringify(ui.patches.at(-1).config.routes), JSON.stringify(["not a rule", { route: "bigger", when: { field: "y", operator: "gt", value: 1 } }]));
  act(() => ui.view.unmount());

  const notAList = renderInspector(routerWith("oops"));
  assert.match(notAList.all(), /The saved rules of this step are not a list, so it cannot run/);
  assert.equal(notAList.view.root.findAllByType("button").some((button) => /Add/.test(text(button))), false, "no edit replaces the saved value");
  act(() => notAList.view.unmount());
});

test("the connection editor shows a literal route:foo branch as that branch, not as unknown", () => {
  const { FlowEdgeMappingEditor } = load("FlowEdgeMappingEditor");
  const router = routerWith([{ route: "route:foo", when: { field: "a", operator: "gt", value: 1 } }, "not a rule"]);
  let view;
  act(() => {
    view = TestRenderer.create(createElement(FlowEdgeMappingEditor, {
      edge: { id: "e", source: "r", target: "t", data: { condition: "route:foo", conditionSource: "route:foo" } },
      nodes: [router, { id: "t" }], onUpdate() {}, onDelete() {},
    }));
  });
  const select = view.root.findByType("select");
  assert.equal(select.props.value, "route:foo");
  assert.equal(view.root.findAllByType("option").some((option) => /no rule picks it/.test(text(option))), false);
  act(() => view.unmount());
});

test("an ambiguous route:foo connection stays 'Multiple branches' until one branch is picked explicitly", () => {
  const { FlowEdgeMappingEditor } = load("FlowEdgeMappingEditor");
  const router = routerWith([
    { route: "foo", when: { field: "a", operator: "gt", value: 1 } },
    { route: "route:foo", when: { field: "b", operator: "lt", value: 0 } },
  ]);
  const stored = { id: "e", source_node_id: "r", target_node_id: "t", condition: "route:foo" };
  const updates = [];
  const render = (data) => {
    let view;
    act(() => {
      view = TestRenderer.create(createElement(FlowEdgeMappingEditor, {
        edge: { id: "e", source: "r", target: "t", data }, nodes: [router, { id: "t" }],
        onUpdate: (id, next) => updates.push(next), onDelete() {},
      }));
    });
    return view;
  };
  const rf = canvasMapping.toRfEdge(stored);
  const view = render(rf.data);
  const select = view.root.findByType("select");
  assert.equal(select.props.value, "__multiple__");
  assert.ok(view.root.findAllByType("option").some((option) => text(option) === "Multiple branches: “route:foo” and “foo” (kept as saved)"));
  // Rendering and re-choosing the placeholder change nothing; the saved condition round-trips.
  act(() => select.props.onChange({ target: { value: "__multiple__" } }));
  assert.equal(updates.length, 0);
  assert.deepEqual(canvasMapping.toDefinitionEdge(rf), stored);

  // Picking "foo" writes a condition that runs only for "foo" ({route: "foo"}), so it is unique.
  act(() => select.props.onChange({ target: { value: "foo" } }));
  const foo = updates.at(-1);
  assert.equal(JSON.stringify(canvasMapping.storedCondition(foo)), JSON.stringify({ route: "foo" }));
  act(() => view.unmount());
  const fooView = render(foo);
  assert.equal(fooView.root.findByType("select").props.value, "foo");
  act(() => fooView.unmount());

  // Picking the literal "route:foo" writes route:route:foo, which runs only for that branch.
  const again = render(rf.data);
  act(() => again.root.findByType("select").props.onChange({ target: { value: "route:foo" } }));
  assert.equal(canvasMapping.storedCondition(updates.at(-1)), "route:route:foo");
  act(() => again.unmount());
  assert.equal(render(updates.at(-1)).root.findByType("select").props.value, "route:foo");
});
