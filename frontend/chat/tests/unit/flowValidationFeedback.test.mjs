// An explicit Validate in the workflow editor shows its result at once; background
// validation stays quiet; stale answers never apply; no run, publish, save or activation happens.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { registerHooks } from "node:module";
import { test } from "node:test";
import {
  validationIssueNodeId,
  validationStatusText,
} from "../../src/admin/components/flowBuilder/flowValidationFeedback.ts";
import { flowBuilderTabSource } from "./flowBuilderTabSource.mjs";

const INACTIVE = {
  valid: false,
  errors: [{ code: "agent_inactive", message: "agent-step-d27d80f8: the selected agent is inactive; activate it on its agent page." }],
  warnings: [],
};
const VALID = { valid: true, errors: [], warnings: [] };

test("the status text says exactly what the explicit validation found", () => {
  assert.equal(validationStatusText("idle", INACTIVE), null);
  assert.equal(validationStatusText("validating", VALID), "Validating the current draft…");
  assert.equal(
    validationStatusText("done", INACTIVE),
    "Validation found 1 blocking error. Select one to open its step.",
  );
  assert.match(validationStatusText("done", { ...INACTIVE, errors: [...INACTIVE.errors, INACTIVE.errors[0]] }), /2 blocking errors/);
  assert.equal(validationStatusText("done", VALID), "Validation passed.");
  assert.equal(validationStatusText("done", { ...VALID, warnings: [{ code: "w", message: "m" }] }), "Validation passed with 1 warning.");
  assert.match(validationStatusText("failed", VALID), /did not finish/);
  assert.match(validationStatusText("done", { valid: false, errors: [], warnings: [] }), /did not return a result/);
});

test("a validation issue opens the step it names, only when that step exists", () => {
  const ids = ["trigger", "agent-step-d27d80f8", "output"];
  assert.equal(validationIssueNodeId(INACTIVE.errors[0].message, ids), "agent-step-d27d80f8");
  assert.equal(validationIssueNodeId("edge trigger->output has no mapping", ids), "trigger");
  assert.equal(validationIssueNodeId("output.input_schema is missing request", ids), "output");
  assert.equal(validationIssueNodeId("agent-step-deleted: the selected agent is inactive", ids), null);
  assert.equal(validationIssueNodeId("The flow has no trigger", ids), null);
});

async function loadReact() {
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
  const { useFlowValidationFeedback } = await import("../../src/admin/components/flowBuilder/flowValidationFeedback.ts");
  const { flowNextAction } = await import("../../src/admin/components/flowBuilder/flowNextAction.ts");
  loader.deregister();
  const { createElement } = await import("react");
  const { default: renderer } = await import("react-test-renderer");
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  return { FlowRunPanel, useFlowValidationFeedback, flowNextAction, createElement, renderer };
}

const text = (node) => node.children.map((child) => (typeof child === "string" ? child : text(child))).join("");

test("explicit validation reveals pending and result; background validation and stale answers do not", async () => {
  const { useFlowValidationFeedback, createElement, renderer } = await loadReact();
  let api;
  function Probe({ target }) {
    api = useFlowValidationFeedback(target);
    return null;
  }
  const revision3 = { flowId: "f1", versionId: "v3", definitionJson: '{"nodes":[]}' };
  let view;
  renderer.act(() => { view = renderer.create(createElement(Probe, { target: revision3 })); });

  // Background (a run refreshing its report): nothing opens, nothing is announced.
  let background;
  renderer.act(() => { background = api.begin(false); });
  assert.deepEqual([api.state, api.revealKey], ["idle", 0]);
  renderer.act(() => api.settle(background, "done"));
  assert.deepEqual([api.state, api.revealKey], ["idle", 0]);

  // Explicit: pending at once, then the result, each revealing Readiness.
  let explicit;
  renderer.act(() => { explicit = api.begin(true); });
  assert.deepEqual([api.state, api.revealKey], ["validating", 1]);
  assert.equal(api.isCurrent(explicit), true);
  renderer.act(() => api.settle(explicit, "done"));
  assert.deepEqual([api.state, api.revealKey], ["done", 2]);

  // A newer request makes the older answer stale.
  let older;
  let newer;
  renderer.act(() => { older = api.begin(true); newer = api.begin(true); });
  assert.equal(api.isCurrent(older), false);
  assert.equal(api.isCurrent(newer), true);

  // Editing the definition while validating: the answer is stale and the pending state clears.
  renderer.act(() => view.update(createElement(Probe, { target: { ...revision3, definitionJson: '{"nodes":[1]}' } })));
  assert.equal(api.isCurrent(newer), false);
  renderer.act(() => api.settle(newer, "stale"));
  assert.equal(api.state, "idle");

  // A result belongs to its revision: another flow or revision shows none.
  let done;
  renderer.act(() => { done = api.begin(true); });
  renderer.act(() => api.settle(done, "failed"));
  assert.equal(api.state, "failed");
  renderer.act(() => view.update(createElement(Probe, { target: { ...revision3, versionId: "v4" } })));
  assert.equal(api.state, "idle");
  renderer.act(() => view.unmount());
});

test("the panel opens Readiness with the result when revealed, and keeps run gating unchanged", async () => {
  const { FlowRunPanel, flowNextAction, createElement, renderer } = await loadReact();
  const blocked = flowNextAction({
    hasFlow: true, flowArchived: false, version: { id: "v3", version: 3, status: "draft" }, dirty: false,
    report: INACTIVE, nodeCount: 3, running: false,
  });
  const noop = () => {};
  const props = (overrides) => ({
    heading: "Revision 3 · test run", nextAction: blocked, running: false, report: INACTIVE, testCaseCount: 0,
    input: null, result: null, quality: null, testCases: null, onRun: noop, onClose: noop,
    readiness: createElement("p", null, "agent_inactive agent-step-d27d80f8"), ...overrides,
  });
  const readiness = (view) => view.root.findAllByType("details").find((node) => text(node.findByType("summary")).startsWith("Readiness"));

  let quiet;
  renderer.act(() => { quiet = renderer.create(createElement(FlowRunPanel, props({}))); });
  assert.equal(readiness(quiet).props.open, false, "Readiness stays collapsed without an explicit validation");
  assert.equal(quiet.root.findAll((node) => node.props.className?.startsWith?.("flow-run-panel__validation")).length, 0);
  renderer.act(() => quiet.unmount());

  let view;
  renderer.act(() => { view = renderer.create(createElement(FlowRunPanel, props({ revealReadinessKey: 1, validationState: "validating" }))); });
  assert.equal(readiness(view).props.open, true);
  assert.equal(text(readiness(view).findByType("summary")), "Readiness · validating…");
  renderer.act(() => view.update(createElement(FlowRunPanel, props({ revealReadinessKey: 2, validationState: "done" }))));
  const details = readiness(view);
  assert.equal(details.props.open, true);
  assert.equal(text(details.findByType("summary")), "Readiness · 1 error");
  const status = details.findByProps({ role: "status" });
  assert.equal(text(status), "Validation found 1 blocking error. Select one to open its step.");
  assert.equal(status.props["aria-live"], "polite");
  assert.match(text(details), /agent_inactive agent-step-d27d80f8/, "the exact reason is visible in the opened section");
  const runButton = view.root.findAllByType("button").find((button) => text(button) === "Run this revision");
  assert.equal(runButton.props.disabled, true, "validation feedback never unblocks the run gate");

  // The user can still collapse it; a later explicit validation reopens it.
  renderer.act(() => details.props.onToggle({ currentTarget: { open: false } }));
  assert.equal(readiness(view).props.open, false);
  renderer.act(() => view.update(createElement(FlowRunPanel, props({ revealReadinessKey: 3, validationState: "done" }))));
  assert.equal(readiness(view).props.open, true);
  renderer.act(() => view.unmount());
});

test("only the header's Validate reveals; validation never runs, publishes, saves or activates", () => {
  const tab = flowBuilderTabSource();
  const header = tab.slice(tab.indexOf("<FlowBuilderEditorActions"), tab.indexOf("/>", tab.indexOf("<FlowBuilderEditorActions")));
  assert.match(header, /onValidate=\{\(\) => void validateCurrentFlow\(\{ reveal: true \}\)\}/);
  const run = tab.slice(tab.indexOf("async function runSelectedFlow"), tab.indexOf("async function refreshRunTrace"));
  assert.match(run, /await validateCurrentFlow\(\);/, "a run's refresh stays a background validation");
  const validate = tab.slice(tab.indexOf("async function validateCurrentFlow"), tab.indexOf("async function createFlowDraft"));
  assert.match(validate, /"\/api\/v1\/flows\/validate"/);
  for (const forbidden of [/runSelectedFlow/, /setPublishGateOpen/, /createFlowDraft\(/, /\/publish/, /\/activate/, /method: "PUT"/]) {
    assert.doesNotMatch(validate, forbidden);
  }
  // A stale answer is checked before it may replace the report or reveal anything.
  const current = validate.indexOf("validation.isCurrent(request)");
  assert.ok(current > 0 && current < validate.indexOf("setValidationReport(report)"));
  assert.match(tab, /revealReadinessKey=\{validation\.revealKey\} validationState=\{validation\.state\}/);
});
