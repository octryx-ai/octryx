// The run result counted every trace row as an executed step. The live four-node validation
// run (amount > 10 → above_limit, Otherwise → within_limit) showed 3 completed + 1 skipped as
// "4 steps executed". Rows are node attempts (dag_executor: skipped branches get a `skipped` row,
// a retried node gets a new row with attempt + 1 after its interrupted row became `cancelled`).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { registerHooks } from "node:module";
import { transpileModule, ModuleKind, JsxEmit } from "typescript";
import { createElement } from "react";
import renderer from "react-test-renderer";
import { flowRunStepCounts } from "../../src/admin/components/flowBuilder/flowRunStepCounts.ts";
import { flowRunResultView } from "../../src/admin/components/flowBuilder/flowRunResult.ts";

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
const { FlowTracePanel } = await import("../../src/admin/components/flowBuilder/FlowTracePanel.tsx");
const { RunOutcome } = await import("../../src/admin/components/flowBuilder/FlowRunResultParts.tsx");
loader.deregister();
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const text = (node) => node.children.map((child) => (typeof child === "string" ? child : text(child))).join("");

const RUN_ID = "4c1f7a52-1116-4000-8000-000000000001";
const nodeRun = (id, node_id, node_type, status, attempt = 1) => ({
  id, flow_run_id: RUN_ID, node_id, node_type, status, attempt, input: {}, output: {}, error: null, evidence_summary: {},
  artifact_refs: [], trace_refs: {}, decision_trace: {}, token_usage: {}, cost_estimate: {}, started_at: null, completed_at: null, duration_ms: 2,
});
const run = (overrides = {}) => ({
  id: RUN_ID, status: "completed", pattern_type: "dag", session_id: null, flow_definition_version_id: "v-1116",
  current_step_index: 4, total_steps: 4, merged_output_json: { final: { result: "above" } }, progress: {}, runtime_lease: {},
  plan: {}, acceptance: {}, failure: {}, last_error: null, created_at: "2026-10-04T08:00:00.000000", completed_at: "2026-10-04T08:00:00.400000",
  ...overrides,
});
// The live validation run's shape: the If / else picked above_limit, within_limit was skipped.
const LIVE = {
  run: run(),
  node_runs: [
    nodeRun("r1", "input", "trigger", "completed"),
    nodeRun("r2", "check", "router", "completed"),
    nodeRun("r3", "above_limit", "output", "completed"),
    nodeRun("r4", "within_limit", "output", "skipped"),
  ],
};

test("3 completed + 1 skipped reads as such, not as 4 executed steps", () => {
  const counts = flowRunStepCounts(LIVE.node_runs);
  assert.equal(counts.summary, "3 completed · 1 skipped");
  assert.deepEqual([counts.steps, counts.attempts, counts.attemptsNote], [4, 4, ""]);
  const steps = flowRunResultView(LIVE).diagnostics.find((row) => row.label === "Steps");
  assert.equal(steps.value, "3 completed · 1 skipped · 4 planned");
  assert.doesNotMatch(steps.value, /executed/);
});

test("a retried step counts once by its latest attempt; earlier attempts are attempts, not steps", () => {
  const rows = [
    nodeRun("a1", "input", "trigger", "completed"),
    nodeRun("a2", "lookup", "tool_step", "cancelled", 1), // interrupted, then recovered
    nodeRun("a3", "lookup", "tool_step", "completed", 2),
    nodeRun("a4", "output", "output", "completed"),
  ];
  const counts = flowRunStepCounts(rows);
  assert.equal(counts.summary, "3 completed");
  assert.equal(counts.attemptsNote, "4 attempts for 3 steps");
  // Latest attempt wins even if rows arrive out of order.
  assert.equal(flowRunStepCounts([rows[2], rows[1]]).summary, "1 completed");
});

test("every backend status is named; nothing unknown or unfinished counts as completed", () => {
  const rows = [
    nodeRun("s1", "a", "agent_step", "failed"),
    nodeRun("s2", "b", "approval", "paused"),
    nodeRun("s3", "c", "tool_step", "running"),
    nodeRun("s4", "d", "tool_step", "pending"),
    nodeRun("s5", "e", "tool_step", "cancelled"),
    nodeRun("s6", "f", "output", "skipped"),
    nodeRun("s7", "g", "tool_step", "queued"),
  ];
  assert.equal(
    flowRunStepCounts(rows).summary,
    "1 failed · 1 running · 1 waiting · 1 not started · 1 cancelled · 1 skipped · 1 with unknown status “queued”",
  );
  assert.equal(flowRunStepCounts([]).summary, "No steps recorded");
});

test("the rendered result shows status counts and keeps every raw row with its status", () => {
  const noop = () => {};
  const retried = {
    run: run({ status: "completed" }),
    node_runs: [...LIVE.node_runs.slice(0, 2), nodeRun("r3a", "above_limit", "output", "cancelled", 1), nodeRun("r3", "above_limit", "output", "completed", 2), LIVE.node_runs[3]],
  };
  for (const [trace, expected, summary] of [
    [LIVE, "3 completed · 1 skipped", "Step details (4 steps)"],
    [retried, "3 completed · 1 skipped (5 attempts for 4 steps)", "Step details (4 steps, 5 attempts)"],
  ]) {
    let view;
    renderer.act(() => {
      view = renderer.create(createElement(FlowTracePanel, {
        trace, selectedNodeRunId: null, running: false, onRefresh: noop, onRecoverInterrupted: noop, onResume: noop, onCancel: noop, onSelectNodeRun: noop,
      }));
    });
    const counts = view.root.findByProps({ "data-testid": "flow-run-step-counts" });
    assert.equal(text(counts), expected);
    assert.doesNotMatch(text(view.root.findByProps({ "aria-label": "Run result" })), /steps? executed/);
    const list = view.root.findByProps({ role: "list" });
    assert.equal(list.props["aria-label"], "Step runs, including skipped steps and retries");
    const rows = list.findAllByProps({ role: "listitem" });
    assert.equal(rows.length, trace.node_runs.length, "every raw row stays listed");
    assert.deepEqual(rows.map((row) => row.findAllByType("span").find((span) => /flow-builder__badge/.test(span.props.className ?? ""))).map((badge) => text(badge)), trace.node_runs.map((row) => row.status));
    const summaries = view.root.findAllByType("summary").map((node) => text(node).replace(/\s+/g, " ").trim());
    assert.ok(summaries.includes(summary), `${summary} in ${summaries.join(" | ")}`);
    renderer.act(() => view.unmount());
  }
});

test("RunOutcome is the one outcome presentation and shows the truthful counts", () => {
  const view = { outcome: "Completed", tone: "ok", duration: "under 1 s" };
  const render = (steps) => {
    let tree;
    renderer.act(() => { tree = renderer.create(createElement(RunOutcome, { view, steps })); });
    const value = text(tree.root.findByType("p"));
    renderer.act(() => tree.unmount());
    return value;
  };
  assert.equal(render(flowRunStepCounts(LIVE.node_runs)), "Completedin under 1 s3 completed · 1 skipped");
  assert.equal(
    render(flowRunStepCounts([nodeRun("x1", "x", "tool_step", "cancelled", 1), nodeRun("x2", "x", "tool_step", "completed", 2)])),
    "Completedin under 1 s1 completed (2 attempts for 1 step)",
  );
  // FlowTracePanel uses RunOutcome rather than its own copy of the markup, and no "executed" wording is left.
  const panel = readFileSync(new URL("../../src/admin/components/flowBuilder/FlowTracePanel.tsx", import.meta.url), "utf8");
  const parts = readFileSync(new URL("../../src/admin/components/flowBuilder/FlowRunResultParts.tsx", import.meta.url), "utf8");
  assert.match(panel, /<RunOutcome view=\{view\} steps=\{stepCounts\} \/>/);
  assert.doesNotMatch(panel, /flow-run-result__outcome/);
  assert.doesNotMatch(parts.replace(/\/\/.*$/gm, ""), /executed/);
});
