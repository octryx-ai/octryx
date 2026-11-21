import assert from "node:assert/strict";
import { test } from "node:test";
import { buildNewFlowPayload, BASIC_WORKFLOW_STARTER, GLOBAL_WORKFLOW_SCOPE } from "../../src/admin/components/flowBuilder/flowDraftCreation.ts";
import { FLOW_BUILDER_TEMPLATES } from "../../src/admin/components/flowBuilder/flowBuilderTemplates.ts";

test("creation requires name and explicit workspace scope", () => {
  assert.throws(() => buildNewFlowPayload("", "ws", BASIC_WORKFLOW_STARTER, "unique"), /Name/);
  assert.throws(() => buildNewFlowPayload("Review", "", BASIC_WORKFLOW_STARTER, "unique"), /workspace/);
  assert.throws(() => buildNewFlowPayload("Review", "ws", "unknown", "unique"), /supported/);
  assert.equal(buildNewFlowPayload("Review", GLOBAL_WORKFLOW_SCOPE, BASIC_WORKFLOW_STARTER, "unique").project_id, null);
});
test("basic starter is connected and has no agent or tool execution", () => {
  const payload = buildNewFlowPayload(" Review request ", "ws", BASIC_WORKFLOW_STARTER, "unique");
  assert.equal(payload.name, "Review request");
  assert.equal(payload.project_id, "ws");
  assert.deepEqual(payload.definition.nodes.map((node) => node.type), ["trigger", "output"]);
  assert.equal(payload.definition.edges[0].source_node_id, payload.definition.nodes[0].id);
  assert.equal(payload.definition.edges[0].target_node_id, payload.definition.nodes[1].id);
});
test("template copies are independent and duplicate names generate distinct keys", () => {
  const template = FLOW_BUILDER_TEMPLATES[0];
  const first = buildNewFlowPayload("Review", "ws", template.key, "one");
  const second = buildNewFlowPayload("Review", "ws", template.key, "two");
  assert.notEqual(first.key, second.key);
  first.definition.nodes[0].label = "Changed";
  assert.notEqual(second.definition.nodes[0].label, "Changed");
  assert.notEqual(template.definition.nodes[0].label, "Changed");
});

const { registerHooks } = await import("node:module");
const { readFileSync } = await import("node:fs");
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
const { FlowDraftCreateDrawer } = await import("../../src/admin/components/flowBuilder/FlowDraftCreateDrawer.tsx");
loader.deregister();
const { createElement } = await import("react");
const { default: renderer } = await import("react-test-renderer");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.window = { addEventListener() {}, removeEventListener() {} };
function mount(props = {}) {
  let view;
  renderer.act(() => { view = renderer.create(createElement(FlowDraftCreateDrawer, {
    projects: [{ id: "ws", name: "Support" }], onClose() {}, onCreated() {}, ...props,
  })); });
  return view;
}
function enterDetails(view, scope = "ws") {
  renderer.act(() => {
    view.root.findByType("input").props.onChange({ target: { value: "Request review" } });
    view.root.findAllByType("select")[0].props.onChange({ target: { value: scope } });
  });
}
test("drawer requires choices and submits only draft creation", async () => {
  const requests = [];
  let created;
  const view = mount({ readJson: async (path, options) => { requests.push([path, options]); return { id: "new", project_id: "ws" }; }, onCreated: (flow) => { created = flow; } });
  const submit = () => view.root.findAllByType("button").find((button) => button.props.type === "submit");
  assert.equal(submit().props.disabled, true);
  enterDetails(view);
  assert.equal(submit().props.disabled, false);
  await renderer.act(async () => { view.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
  assert.equal(requests.length, 1);
  assert.equal(requests[0][0], "/api/v1/flows");
  assert.equal(requests[0][1].method, "POST");
  assert.equal(JSON.parse(requests[0][1].body).project_id, "ws");
  assert.deepEqual(created, { id: "new", project_id: "ws" });
  renderer.act(() => view.unmount());
});
test("failed creation keeps input and displays error", async () => {
  const view = mount({ readJson: async () => { throw new Error("Creation unavailable"); }, onCreated() { assert.fail("Must not open failed draft"); } });
  enterDetails(view);
  await renderer.act(async () => { view.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
  assert.equal(view.root.findByProps({ role: "alert" }).children.join(""), "Creation unavailable");
  assert.equal(view.root.findByType("input").props.value, "Request review");
  renderer.act(() => view.unmount());
});
test("invalid scope and cancellation create nothing", async () => {
  let closed = false;
  const view = mount({ readJson: async () => { assert.fail("No request expected"); }, onClose() { closed = true; } });
  enterDetails(view, "removed-workspace");
  await renderer.act(async () => { view.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
  assert.match(view.root.findByProps({ role: "alert" }).children.join(""), /available workspace/);
  renderer.act(() => { view.root.findAllByType("button").find((button) => button.children.join("") === "Cancel").props.onClick(); });
  assert.equal(closed, true);
  renderer.act(() => view.unmount());
});
