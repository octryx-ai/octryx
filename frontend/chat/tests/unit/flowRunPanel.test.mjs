import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { flowAuthoringState } from "../../src/admin/components/flowBuilder/flowAuthoringState.ts";
import { flowNextAction, readinessLabel } from "../../src/admin/components/flowBuilder/flowNextAction.ts";
import { RUN_WORKSPACE_REQUIRED, flowRunRequest } from "../../src/admin/components/flowBuilder/flowRunRequest.ts";
import {
  extraInputKeys,
  triggerInputFields,
  withInputFieldValue,
} from "../../src/admin/components/flowBuilder/flowRunInput.ts";
import { flowBuilderTabSource } from "./flowBuilderTabSource.mjs";

const definition = {
  schema_version: "2.0",
  nodes: [
    { id: "input", type: "trigger", label: "Concurrent B", output_schema: { request: "string" }, config: { trigger_type: "manual" }, position: { x: 80, y: 80 } },
    { id: "output", type: "output", label: "Return result", input_schema: { request: "string" }, position: { x: 380, y: 80 } },
  ],
  edges: [{ source_node_id: "input", target_node_id: "output" }],
};
const VALID = { valid: true, errors: [], warnings: [] };
const published = { id: "v2-published", version: 2, status: "published", definition };
const draft = { id: "v3-draft", version: 3, status: "draft", definition };
const flow = { id: "f1", name: "Flow", description: "", status: "published", current_version_id: "v2-published", versions: [published, draft] };

function actionFor({ edited = definition, report = VALID, running = false, versionId = "v3-draft", archived = false } = {}) {
  const authoring = flowAuthoringState(archived ? { ...flow, status: "archived" } : flow, versionId, "Flow", "", edited);
  return {
    authoring,
    action: flowNextAction({
      hasFlow: true, flowArchived: archived, version: authoring.version, dirty: authoring.dirty,
      report, nodeCount: edited.nodes.length, running,
    }),
  };
}

test("next action agrees with the validation report and the saved state", () => {
  const ready = actionFor();
  assert.equal(ready.action.kind, "run");
  assert.equal(ready.action.canRun, true);
  assert.match(ready.action.detail, /revision 3 \(draft\)/);

  const dirty = actionFor({ edited: { ...definition, nodes: [{ ...definition.nodes[0], label: "Edited" }, definition.nodes[1]] } });
  assert.equal(dirty.authoring.runnable, false);
  assert.deepEqual([dirty.action.title, dirty.action.canRun], ["Save the draft first", false]);

  const invalid = actionFor({ report: { valid: false, errors: [{ code: "a", message: "x" }, { code: "b", message: "y" }], warnings: [] } });
  assert.deepEqual([invalid.action.title, invalid.action.canRun], ["Fix 2 validation errors", false]);
  assert.equal(readinessLabel({ valid: false, errors: [{}, {}], warnings: [] }), "2 errors");

  assert.equal(actionFor({ report: { valid: false, errors: [], warnings: [] } }).action.kind, "validate");
  assert.equal(actionFor({ archived: true }).action.kind, "archived");
  assert.equal(actionFor({ running: true }).action.canRun, false);
  assert.equal(flowNextAction({ hasFlow: false, flowArchived: false, version: undefined, dirty: true, report: VALID, nodeCount: 0, running: false }).kind, "create");
  assert.equal(readinessLabel(VALID), "valid");
});

test("run request targets exactly the stored revision shown, never the published default", () => {
  const { authoring, action } = actionFor();
  const request = flowRunRequest(action, authoring.version?.id, { projectId: "p1", inputJson: '{"request":"hello"}' });
  assert.equal(request.ok, true);
  assert.equal(request.path, "/api/v1/flows/versions/v3-draft/run");
  assert.deepEqual(JSON.parse(request.body), { project_id: "p1", initial_input: { request: "hello" } });
  // A DAG run starts in a Workspace: without one nothing is sent.
  assert.deepEqual(flowRunRequest(action, authoring.version?.id, { projectId: null, inputJson: "{}" }),
    { ok: false, error: RUN_WORKSPACE_REQUIRED });

  const partial = flowRunRequest(action, authoring.version?.id, { projectId: "p1", inputJson: "{}", nodeId: "output" });
  assert.equal(partial.path, "/api/v1/flows/versions/v3-draft/partial-run");
  assert.equal(JSON.parse(partial.body).node_id, "output");

  const dirty = actionFor({ edited: { ...definition, edges: [] } });
  const refused = flowRunRequest(dirty.action, dirty.authoring.version?.id, { projectId: null, inputJson: "{}" });
  assert.deepEqual(refused, { ok: false, error: dirty.action.detail });
  assert.equal(flowRunRequest(action, "v3-draft", { projectId: "p1", inputJson: "[1]" }).ok, false);
});

test("guided input fields come only from a flat primitive trigger schema", () => {
  assert.deepEqual(triggerInputFields(definition), [{ name: "request", type: "string", label: "Request" }]);
  const nested = { ...definition, nodes: [{ ...definition.nodes[0], output_schema: { request: "object" } }] };
  assert.equal(triggerInputFields(nested), null);
  assert.equal(triggerInputFields({ ...definition, nodes: [definition.nodes[0], definition.nodes[0]] }), null);
  const typed = [
    { name: "count", type: "integer", label: "Count" },
    { name: "urgent", type: "boolean", label: "Urgent" },
  ];
  assert.deepEqual(JSON.parse(withInputFieldValue({ request: "x" }, typed[0], "4.7")), { request: "x", count: 4 });
  assert.deepEqual(JSON.parse(withInputFieldValue({ count: 3 }, typed[0], "")), {});
  assert.deepEqual(JSON.parse(withInputFieldValue({}, typed[1], true)), { urgent: true });
  assert.deepEqual(extraInputKeys({ request: "x", stray: 1 }, triggerInputFields(definition)), ["stray"]);
});

test("run panel is one column with a container query; new CSS uses tokens only", () => {
  const dir = new URL("../../src/admin/components/flowBuilder/", import.meta.url);
  const css = readFileSync(new URL("flowRunPanel.css", dir), "utf8");
  assert.match(css, /container-type:\s*inline-size/);
  assert.match(css, /\.flow-run-panel__fields\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\)/);
  assert.match(css, /@container flow-run-panel \(min-width: 60rem\)/);
  for (const file of ["flowRunPanel.css", "flowPalette.css", "flowRunResult.css"]) {
    assert.doesNotMatch(readFileSync(new URL(file, dir), "utf8"), /#[0-9a-f]{3,8}\b|rgba?\(/i, `${file} must use tokens`);
  }
  const tracePanel = readFileSync(new URL("FlowTracePanel.tsx", dir), "utf8");
  assert.doesNotMatch(tracePanel, />\s*Run trace\s*</);
});

test("rendered panel: next action, input, run button, result, then secondary sections", async () => {
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
  const { FlowRunPanel } = await import("../../src/admin/components/flowBuilder/FlowRunPanel.tsx");
  const { FlowRunInputSection } = await import("../../src/admin/components/flowBuilder/FlowRunInputSection.tsx");
  const { FlowTracePanel } = await import("../../src/admin/components/flowBuilder/FlowTracePanel.tsx");
  loader.deregister();
  const { createElement } = await import("react");
  const { default: renderer } = await import("react-test-renderer");
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;

  const render = (action, inputJson = '{"request":"hello"}') => {
    let view;
    const noop = () => {};
    renderer.act(() => {
      view = renderer.create(createElement(FlowRunPanel, {
        heading: "Revision 3 · test run", nextAction: action, running: false, report: VALID, testCaseCount: 0,
        input: createElement(FlowRunInputSection, { definition, inputJson, onInputChange: noop }),
        result: createElement(FlowTracePanel, {
          trace: null, selectedNodeRunId: null, running: false, onRefresh: noop, onRecoverInterrupted: noop,
          onResume: noop, onCancel: noop, onSelectNodeRun: noop,
        }),
        readiness: null, quality: null, testCases: null, onRun: noop, onClose: noop,
      }));
    });
    return view;
  };
  const text = (node) => node.children.map((child) => (typeof child === "string" ? child : text(child))).join("");

  const ready = render(actionFor().action);
  const runButton = ready.root.findAllByType("button").find((button) => text(button) === "Run this revision");
  assert.equal(runButton.props.disabled, false);
  const guided = ready.root.findAllByType("label").find((label) => text(label).startsWith("Request"));
  assert.equal(guided.findByType("textarea").props.value, "hello");
  assert.equal(guided.props.htmlFor, guided.findByType("textarea").props.id);
  assert.equal(ready.root.findByProps({ "aria-label": "Raw test input (JSON object)" }).type, "textarea");
  assert.deepEqual(ready.root.findAllByType("summary").map(text), [
    "Advanced: raw input", "Readiness · valid", "Quality", "Test cases · 0",
  ]);
  const order = ready.root.findAllByType("section").map((node) => node.props["aria-label"]);
  assert.deepEqual(order, ["Run and results", "Test input", "Result", "Run result"]);
  renderer.act(() => ready.unmount());

  // During a rerun the shown result is the previous run's and the heading says a run is in flight.
  let rerun;
  renderer.act(() => {
    rerun = renderer.create(createElement(FlowRunPanel, {
      heading: "Completed in 5.8 s", nextAction: actionFor().action, running: true, report: VALID, testCaseCount: 0,
      runKey: "previous-run", input: null, result: createElement("p", null, "old answer"),
      readiness: null, quality: null, testCases: null, onRun: () => {}, onClose: () => {},
    }));
  });
  assert.equal(text(rerun.root.findAllByType("strong")[0]), "Running this revision…");
  assert.ok(rerun.root.findAllByType("section").some((node) => node.props["aria-label"] === "Previous result (before this run)"));
  renderer.act(() => rerun.unmount());

  const blocked = render(actionFor({ edited: { ...definition, edges: [] } }).action);
  assert.equal(text(blocked.root.findByProps({ role: "status" })).startsWith("Save the draft first"), true);
  assert.equal(blocked.root.findAllByType("button").find((button) => text(button) === "Run this revision").props.disabled, true);
  renderer.act(() => blocked.unmount());
});

test("the editor header opens Run & results; only the panel's button starts a run", () => {
  const tab = flowBuilderTabSource();
  const header = tab.slice(tab.indexOf("<FlowBuilderEditorActions"), tab.indexOf("/>", tab.indexOf("<FlowBuilderEditorActions")));
  assert.match(header, /onRun=\{\(\) => setOperationsOpen\(true\)\}/);
  assert.doesNotMatch(header, /runSelectedFlow/);
  const panel = tab.slice(tab.indexOf("<FlowRunPanel"), tab.indexOf("/>", tab.indexOf("<FlowRunPanel")));
  assert.match(panel, /onRun=\{runSelectedFlow\}/);
});

test("after a configuration refusal the refreshed report replaces a stale Ready to run", () => {
  // The editor re-validates with its flow_id; the backend then returns the agent guard error.
  const stale = actionFor().action;
  assert.equal(stale.canRun, true);
  const refreshed = actionFor({
    report: { valid: false, errors: [{ code: "agent_inactive", message: "agent-step: the selected agent is inactive; activate it on its agent page." }], warnings: [] },
  }).action;
  assert.equal(refreshed.canRun, false);
  assert.equal(refreshed.title, "Fix 1 validation error");
  const tab = flowBuilderTabSource();
  const run = tab.slice(tab.indexOf("async function runSelectedFlow"), tab.indexOf("async function refreshRunTrace"));
  assert.match(run, /if \(needsValidationRefresh\(trace\)\) await validateCurrentFlow\(\);/);
  const validate = tab.slice(tab.indexOf("async function validateCurrentFlow"), tab.indexOf("async function createFlowDraft"));
  assert.match(validate, /flow_id: selectedFlow\.id/);
});
