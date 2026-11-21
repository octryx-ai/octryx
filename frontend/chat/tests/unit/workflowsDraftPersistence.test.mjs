import assert from "node:assert/strict";
import { test } from "node:test";
import { flowAuthoringState, latestFlowVersion } from "../../src/admin/components/flowBuilder/flowAuthoringState.ts";

const oldDefinition = { nodes: [{ id: "a", type: "trigger", label: "Original" }], edges: [] };
const editedDefinition = { nodes: [{ id: "a", type: "trigger", label: "Edited" }], edges: [] };
const published = { id: "v1", version: 1, status: "published", definition: oldDefinition };
const draft = { id: "v2", version: 2, status: "draft", definition: editedDefinition };
const flow = { name: "Example", description: "", status: "published", current_version_id: "v1", versions: [published, draft] };

test("authoring selects latest snapshot, never the first array item or published pointer", () => {
  assert.equal(latestFlowVersion(flow).id, "v2");
  assert.equal(latestFlowVersion({ ...flow, versions: [draft, published] }).id, "v2");
  const state = flowAuthoringState(flow, null, "Example", "", editedDefinition);
  assert.equal(state.version.id, "v2");
  assert.equal(state.runnable, true);
  assert.equal(state.publishable, true);
  assert.equal(state.testsAvailable, false);
});

test("changed content or metadata blocks execution, publication and test cases until saved", () => {
  for (const [name, desc, doc] of [["Renamed", "", editedDefinition], ["Example", "changed", editedDefinition], ["Example", "", oldDefinition]]) {
    const state = flowAuthoringState(flow, "v2", name, desc, doc);
    assert.equal(state.dirty, true);
    assert.equal(state.runnable, false);
    assert.equal(state.publishable, false);
    assert.equal(state.testsAvailable, false);
  }
});

test("historical selected version has explicit identity and cannot masquerade as latest", () => {
  const state = flowAuthoringState(flow, "v1", "Example", "", oldDefinition);
  assert.equal(state.version.id, "v1");
  assert.equal(state.runnable, true);
  assert.equal(state.publishable, false);
  assert.equal(state.testsAvailable, true);
});

test("new or archived workflows cannot execute", () => {
  assert.equal(flowAuthoringState(null, null, "Example", "", editedDefinition).runnable, false);
  assert.equal(flowAuthoringState({ ...flow, status: "archived" }, "v2", "Example", "", editedDefinition).runnable, false);
});

test("unknown explicit version never falls back to another executable revision", () => {
  assert.equal(flowAuthoringState(flow, "missing", "Example", "", editedDefinition).runnable, false);
});

test("rendered header blocks stale execution and provides Save draft for existing workflows", async () => {
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
  const { FlowBuilderEditorActions } = await import("../../src/admin/components/flowBuilder/FlowBuilderHeaderActions.tsx");
  loader.deregister();
  const { createElement } = await import("react");
  const { default: renderer } = await import("react-test-renderer");
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  let view;
  const state = flowAuthoringState(flow, "v2", "Changed", "", editedDefinition);
  renderer.act(() => { view = renderer.create(createElement(FlowBuilderEditorActions, {
    hasFlow: true, busy: false, runBusy: false, dirty: state.dirty,
    runnable: state.runnable, publishReady: state.publishable,
  })); });
  const buttons = view.root.findAllByType("button");
  // The header "Run…" only opens Run & results; it stays disabled for a stale draft.
  assert.equal(buttons.find((button) => button.children.join("") === "Run…").props.disabled, true);
  assert.equal(buttons.find((button) => button.children.join("") === "Publish").props.disabled, true);
  assert.equal(buttons.find((button) => button.children.join("") === "Save draft").props.disabled, false);
  renderer.act(() => view.unmount());
});
