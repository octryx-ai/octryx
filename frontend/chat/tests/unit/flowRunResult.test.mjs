import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { flowRunHeading, flowRunResultView } from "../../src/admin/components/flowBuilder/flowRunResult.ts";

// Payload shapes follow the backend contract: serialize_flow_run / serialize_flow_node_run
// (services/flow_trace.py), merged_output_json { final, nodes } (dag_executor.py), acceptance
// (runtime_acceptance.py), failure (runtime_failure_taxonomy.py), lease (recovery.py),
// approval pause output (dag_executor._create_approval_pause). Times are naive UTC ISO.
const REQUEST = "Sales acceptance: saved revision 3 returns this request.";
const RUN_ID = "f2f18495-6b3d-4d44-8784-bc93a7123607";

function run(overrides = {}) {
  return {
    id: RUN_ID, status: "completed", pattern_type: "sequential", session_id: null, parent_session_id: null,
    project_id: null, flow_definition_version_id: "d5e2b65a-0000-4000-8000-000000000003", flow_node_id: null,
    current_step_index: 2, total_steps: 2, child_session_ids: [],
    merged_output_json: { final: { result: { request: REQUEST } }, nodes: { input: { request: REQUEST }, output: { result: { request: REQUEST } } } },
    progress: { current_node_id: "output", phase: "completed", checkpointed_at: "2026-10-03T08:21:31.689000" },
    runtime_lease: {
      owner: "flow-runner", status: "terminal", last_heartbeat_at: "2026-10-03T08:21:31.689000",
      lease_expires_at: "2026-10-03T08:23:31.689000", lease_seconds: 120, is_stale: false,
    },
    plan: {},
    acceptance: {
      schema_version: "1.0", kind: "runtime_acceptance_state", state: "completed", technical_status: "completed",
      accepted: true, review_required: false, required_action: "none", reason: "Flow run completed.",
      validation_status: null, warning_count: 0, failure_category: null, updated_at: "2026-10-03T08:21:31.689414",
    },
    failure: {},
    last_error: null,
    created_at: "2026-10-03T08:21:31.274000",
    completed_at: "2026-10-03T08:21:31.689397",
    ...overrides,
  };
}

function nodeRun(node_id, node_type, status, extra = {}) {
  return {
    id: `nr-${node_id}`, flow_run_id: RUN_ID, node_id, node_type, status, attempt: 1, input: {}, output: {},
    error: null, evidence_summary: {}, artifact_refs: [], trace_refs: {}, decision_trace: {}, token_usage: {},
    cost_estimate: {}, started_at: null, completed_at: null, duration_ms: 3, ...extra,
  };
}

const COMPLETED = { run: run(), node_runs: [nodeRun("input", "trigger", "completed"), nodeRun("output", "output", "completed")] };
const FAILED = {
  run: run({
    status: "failed", completed_at: "2026-10-03T08:22:05.000000", merged_output_json: {},
    acceptance: { ...run().acceptance, state: "failed", technical_status: "failed", accepted: false, review_required: true, required_action: "fix_tool_configuration", reason: "Tool execution failed. error_type=ToolResultFailedError" },
    failure: {
      schema_version: "1.0", kind: "runtime_failure", category: "tool_error", severity: "error", retryable: false,
      required_action: "fix_tool_configuration", summary: "Tool execution failed. error_type=ToolResultFailedError",
      source: "flow_node", error_class_source: "tool_result", detail: { node_id: "lookup", node_type: "tool_step" },
      created_at: "2026-10-03T08:22:05.000000",
    },
    last_error: "jira_search returned an error",
  }),
  node_runs: [nodeRun("input", "trigger", "completed"), nodeRun("lookup", "tool_step", "failed", { error: "jira connector is not globally configured." })],
};
const PAUSED = {
  run: run({
    status: "paused", completed_at: null, merged_output_json: {},
    runtime_lease: { ...run().runtime_lease, status: "active" },
    acceptance: { ...run().acceptance, state: "needs_review", technical_status: "paused", accepted: false, review_required: true, required_action: "human_review", reason: "Run is waiting for human review." },
  }),
  node_runs: [
    nodeRun("input", "trigger", "completed"),
    nodeRun("approve", "approval", "paused", {
      output: {
        reason: "Approval node paused the flow.", approval_id: "ap-1",
        approval: { id: "ap-1", action: "flow_approval", status: "pending", title: "Approve the offer", prompt: "Check the discount before sending.", approval_mode: "approve_reject", required_role: "sales_lead" },
      },
    }),
  ],
};
const CANCELLED = {
  run: run({
    status: "cancelled", merged_output_json: {},
    acceptance: { ...run().acceptance, state: "rejected", technical_status: "cancelled", accepted: false, review_required: true, required_action: "review_rejection", reason: "Run was rejected or cancelled by review action." },
  }),
  node_runs: [nodeRun("input", "trigger", "completed")],
};

test("completed run: the terminal result is readable, the lease is a diagnostic, not the outcome", () => {
  const view = flowRunResultView(COMPLETED);
  assert.equal(view.outcome, "Completed");
  assert.equal(view.duration, "under 1 s");
  assert.deepEqual(view.notices, []);
  assert.deepEqual(view.result, { kind: "fields", heading: "Final output", fields: [{ label: "Request", value: REQUEST, multiline: false }] });
  assert.deepEqual(view.raw, COMPLETED.run.merged_output_json, "raw result keeps final and nodes");
  const lease = view.diagnostics.find((row) => row.label === "Lease").value;
  assert.match(lease, /^Terminal · not stale · flow-runner/);
  assert.equal(view.diagnostics.some((row) => /T08:21:31/.test(row.value)), false, "times are human readable");
  assert.equal(view.diagnostics.find((row) => row.label === "Run").value, RUN_ID);
  assert.deepEqual(view.rawFacts.runtime_lease, COMPLETED.run.runtime_lease);
  assert.equal(flowRunHeading(COMPLETED, 3), "Completed in under 1 s");
});

test("failed run: the error is prominent, nothing is presented as a result", () => {
  const view = flowRunResultView(FAILED);
  assert.equal(view.outcome, "Failed");
  assert.equal(view.notices[0].tone, "error");
  assert.equal(view.notices[0].title, "Tool execution failed.");
  assert.match(view.notices[0].detail, /Step lookup: jira connector is not globally configured\./);
  assert.match(view.notices[0].detail, /Next: Fix tool configuration/);
  assert.deepEqual(view.result, { kind: "none" });
  assert.match(view.diagnostics.find((row) => row.label === "Failure").value, /error_type=ToolResultFailedError/);
});

test("approval required and review needed are prominent notices", () => {
  const paused = flowRunResultView(PAUSED);
  assert.equal(paused.outcome, "Waiting for review");
  assert.deepEqual(paused.notices[0], {
    tone: "attention", title: "Approval required at step approve: Approve the offer",
    detail: "Check the discount before sending. Requires role: sales_lead.",
  });
  const cancelled = flowRunResultView(CANCELLED);
  assert.equal(cancelled.outcome, "Cancelled");
  assert.deepEqual(cancelled.notices[0], { tone: "attention", title: "Review needed", detail: "Run was rejected or cancelled by review action." });
});

async function loadComponents() {
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
  const { FlowTracePanel } = await import("../../src/admin/components/flowBuilder/FlowTracePanel.tsx");
  const { FlowRunPanel } = await import("../../src/admin/components/flowBuilder/FlowRunPanel.tsx");
  loader.deregister();
  const { createElement } = await import("react");
  const { default: renderer } = await import("react-test-renderer");
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  return { FlowTracePanel, FlowRunPanel, createElement, renderer };
}

const text = (node) => node.children.map((child) => (typeof child === "string" ? child : text(child))).join("");

test("rendered completed run: result first, raw JSON and diagnostics collapsed, input collapsed for rerun", async () => {
  const { FlowTracePanel, FlowRunPanel, createElement, renderer } = await loadComponents();
  const noop = () => {};
  const trace = createElement(FlowTracePanel, {
    trace: COMPLETED, selectedNodeRunId: null, running: false, onRefresh: noop, onRecoverInterrupted: noop,
    onResume: noop, onCancel: noop, onSelectNodeRun: noop,
  });
  let view;
  renderer.act(() => {
    view = renderer.create(createElement(FlowRunPanel, {
      heading: "Completed in under 1 s", runKey: RUN_ID, running: false, testCaseCount: 0,
      nextAction: { kind: "run", title: "Run this revision", detail: "Runs saved revision 3 (draft) exactly as stored.", canRun: true },
      report: { valid: true, errors: [], warnings: [] },
      input: createElement("p", null, "input fields"), result: trace,
      readiness: null, quality: null, testCases: null, onRun: noop, onClose: noop,
    }));
  });
  const sections = view.root.findAllByType("section").map((node) => node.props["aria-label"]);
  assert.deepEqual(sections, ["Run and results", "Result", "Run result"], "result comes before the input");
  const resultPanel = view.root.findByProps({ "aria-label": "Run result" });
  const outcome = resultPanel.findByProps({ className: "flow-run-result__outcome flow-run-result__outcome--ok" });
  // Steps are counted by status, not as "executed" rows.
  assert.match(text(outcome), /^Completedin under 1 s2 completed$/);
  assert.equal(text(resultPanel.findByProps({ className: "flow-run-result__fields" })), `Request${REQUEST}`);
  const details = view.root.findAllByType("details");
  const bySummary = (label) => details.find((node) => text(node.findAllByType("summary")[0]).startsWith(label));
  for (const label of ["Advanced: raw result", "Diagnostics", "Step details", "Edit input and run again"]) {
    assert.ok(bySummary(label), `${label} exists`);
    assert.notEqual(bySummary(label).props.open, true, `${label} is collapsed`);
  }
  assert.ok(text(bySummary("Advanced: raw result")).includes('"nodes"'));
  assert.equal(text(bySummary("Edit input and run again")).includes("input fields"), true);
  const runAgain = view.root.findAllByType("button").find((button) => text(button) === "Run again");
  assert.equal(runAgain.props.disabled, false);
  const outside = text(resultPanel).replace(text(bySummary("Diagnostics")), "").replace(text(bySummary("Advanced: raw result")), "");
  assert.equal(/lease/i.test(outside), false, "the lease never appears outside diagnostics");
  assert.equal(outside.includes(RUN_ID), false, "ids stay in diagnostics");
  renderer.act(() => view.unmount());
});

test("rendered failed and paused runs keep the error and the approval above the result", async () => {
  const { FlowTracePanel, createElement, renderer } = await loadComponents();
  const noop = () => {};
  for (const [payload, role, title] of [[FAILED, "alert", "Tool execution failed."], [PAUSED, "status", "Approval required at step approve: Approve the offer"]]) {
    let view;
    renderer.act(() => {
      view = renderer.create(createElement(FlowTracePanel, {
        trace: payload, selectedNodeRunId: null, running: false, onRefresh: noop, onRecoverInterrupted: noop,
        onResume: noop, onCancel: noop, onSelectNodeRun: noop,
      }));
    });
    const notice = view.root.findAllByProps({ role }).find((node) => node.props.className?.startsWith("flow-run-result__notice"));
    assert.equal(text(notice.findByType("strong")), title);
    const order = view.root.findByProps({ "aria-label": "Run result" }).children.map((child) => child.type?.name ?? child.props?.className);
    assert.ok(order.indexOf("RunNotices") >= 0 && order.indexOf("RunNotices") < order.indexOf("RunResultContent"), "notices sit above the result");
    if (payload === PAUSED) {
      assert.equal(view.root.findAllByType("button").some((button) => text(button) === "Approve & resume"), true);
    }
    renderer.act(() => view.unmount());
  }
});

// An agent step's output carries the child turn's closed state (flow_agent_step.py).
const AGENT = {
  run: run({ merged_output_json: { final: { result: { request: "SUM=51" } }, nodes: {} } }),
  node_runs: [
    nodeRun("input", "trigger", "completed"),
    nodeRun("agent", "agent_step", "completed", {
      output: {
        result: "SUM=51", session_id: "child-1",
        agent: { definition_id: "facb7336", name: "Text verification", mode: "draft", source: "live_draft_row" },
        turn: { state: "finished_unverified", provider: "bedrock", model: "sonnet" },
      },
    }),
    nodeRun("output", "output", "completed"),
  ],
};

test("a run whose agent turn finished unverified never reads as a verified success", () => {
  const view = flowRunResultView(AGENT);
  assert.equal(view.outcome, "Execution finished · result not verified");
  assert.equal(view.tone, "attention");
  assert.equal(view.notices[0].title, "Agent result not verified");
  assert.match(view.notices[0].detail, /^Text verification: the agent's turn finished/);
  assert.doesNotMatch(`${view.notices[0].title} ${view.notices[0].detail}`, /\bagent-step|\bagent\b:/);
  assert.match(flowRunHeading(AGENT, 3), /^Execution finished in .+ · result not verified$/);
  assert.ok(view.diagnostics.some((row) => row.label === "Flow execution acceptance"));
  assert.ok(!view.diagnostics.some((row) => row.label === "Acceptance"));
  // A run without agent turns keeps its plain outcome.
  assert.equal(flowRunResultView(COMPLETED).outcome, "Completed");
});

// Judge (screenshot 39): an agent deactivated after the editor validated. The backend records the
// closed failure facts (runtime_failure_taxonomy classify_runtime_failure + FlowAgentReferenceError).
const INACTIVE = {
  run: run({
    status: "failed", merged_output_json: {}, last_error: "Node agent-step-d27d80f8 failed: agent_inactive error_type=FlowAgentReferenceError",
    acceptance: { ...run().acceptance, state: "failed", accepted: false, review_required: true, required_action: "fix_workflow_configuration" },
    failure: {
      schema_version: "1.0", kind: "runtime_failure", category: "input_contract_error", severity: "error", retryable: false,
      required_action: "fix_workflow_configuration", summary: "Workflow configuration or input contract is invalid. error_type=FlowAgentReferenceError",
      source: "node_execution", error_class_source: "explicit",
      detail: { code: "agent_inactive", node_id: "agent-step-d27d80f8", node_type: "agent_step", error_type: "FlowAgentReferenceError" },
    },
  }),
  node_runs: [nodeRun("input", "trigger", "completed"), nodeRun("agent-step-d27d80f8", "agent_step", "failed", { error: "agent_inactive error_type=FlowAgentReferenceError" })],
};

test("a typed agent guard failure reads as a plain message; codes and ids stay in Diagnostics", async () => {
  const { needsValidationRefresh } = await import("../../src/admin/components/flowBuilder/flowFailureMessages.ts");
  const view = flowRunResultView(INACTIVE);
  assert.equal(view.notices[0].title, "The selected agent is inactive.");
  assert.equal(view.notices[0].detail, "Activate it on its agent page or select another agent.");
  const primary = `${view.notices[0].title} ${view.notices[0].detail}`;
  assert.doesNotMatch(primary, /agent_inactive|error_type|FlowAgentReferenceError|agent-step-d27d80f8/);
  const code = view.diagnostics.find((row) => row.label === "Failure code");
  assert.match(code.value, /agent_inactive/);
  assert.match(code.value, /step agent-step-d27d80f8/);
  assert.match(code.value, /FlowAgentReferenceError/);
  // Configuration refusals refresh the editor's validation; transient failures do not.
  assert.equal(needsValidationRefresh(INACTIVE), true);
  const transient = { ...INACTIVE, run: { ...INACTIVE.run, failure: { ...INACTIVE.run.failure, category: "runtime_exception", detail: { code: "agent_turn_failed" } } } };
  assert.equal(needsValidationRefresh(transient), false);
  assert.equal(flowRunResultView(transient).notices[0].title, "The agent's turn failed.");
  // An unknown code keeps the generic, honest failure summary.
  const unknown = { ...INACTIVE, run: { ...INACTIVE.run, failure: { ...INACTIVE.run.failure, detail: { code: "something_new" } } } };
  assert.match(flowRunResultView(unknown).notices[0].title, /^Workflow configuration or input contract is invalid\.$/);
});

// An If / else step chose a branch without a connection and without a fallback connection.
// Shape from backend/tests/test_flow_router_branches.py (input_contract_error, fix_workflow_configuration).
const ROUTER_UNMATCHED = {
  run: run({
    status: "failed", merged_output_json: {}, last_error: "Node router failed: router_branch_unmatched error_type=RouterBranchUnmatchedError",
    acceptance: { ...run().acceptance, state: "failed", accepted: false, review_required: true, required_action: "fix_workflow_configuration" },
    failure: {
      schema_version: "1.0", kind: "runtime_failure", category: "input_contract_error", severity: "error", retryable: false,
      required_action: "fix_workflow_configuration", summary: "Workflow configuration or input contract is invalid. error_type=RouterBranchUnmatchedError",
      source: "node_execution", error_class_source: "explicit",
      detail: { code: "router_branch_unmatched", node_id: "router", node_type: "router", error_type: "RouterBranchUnmatchedError" },
    },
  }),
  node_runs: [nodeRun("input", "trigger", "completed"), nodeRun("router", "router", "failed", { error: "router_branch_unmatched error_type=RouterBranchUnmatchedError" })],
};

test("an unmatched If / else branch reads as a plain instruction; the code stays in Diagnostics", async () => {
  const { needsValidationRefresh } = await import("../../src/admin/components/flowBuilder/flowFailureMessages.ts");
  const view = flowRunResultView(ROUTER_UNMATCHED);
  assert.equal(view.notices[0].tone, "error");
  assert.equal(view.notices[0].title, "The If / else step picked a branch that has no matching connection, so no later step ran.");
  assert.equal(view.notices[0].detail, "Connect that branch to the next step, or add a connection without a branch as the fallback for all other cases.");
  assert.doesNotMatch(`${view.notices[0].title} ${view.notices[0].detail}`, /router_branch_unmatched|error_type|RouterBranchUnmatchedError/);
  // The typed code wins over the generic configuration summary; the facts stay available.
  assert.equal(view.notices.filter((notice) => /input contract is invalid/.test(notice.title)).length, 0);
  const code = view.diagnostics.find((row) => row.label === "Failure code");
  assert.match(code.value, /router_branch_unmatched/);
  assert.match(code.value, /step router/);
  assert.match(code.value, /RouterBranchUnmatchedError/);
  assert.equal(needsValidationRefresh(ROUTER_UNMATCHED), true);
  // Other mappings are unchanged.
  assert.equal(flowRunResultView(INACTIVE).notices[0].title, "The selected agent is inactive.");
});

// A rule or custom connection condition that cannot be checked.
function routerRefusal(code) {
  return {
    ...ROUTER_UNMATCHED,
    run: {
      ...ROUTER_UNMATCHED.run,
      last_error: `Node router failed: ${code} error_type=RouterRuleInvalidError`,
      failure: { ...ROUTER_UNMATCHED.run.failure, summary: "Workflow configuration or input contract is invalid. error_type=RouterRuleInvalidError", detail: { code, node_id: "router", node_type: "router", error_type: "RouterRuleInvalidError" } },
    },
  };
}

test("If / else rules and connection conditions that cannot be checked read as plain instructions", async () => {
  const { needsValidationRefresh } = await import("../../src/admin/components/flowBuilder/flowFailureMessages.ts");
  const rule = flowRunResultView(routerRefusal("router_rule_invalid"));
  assert.equal(rule.notices[0].title, "An If / else rule in this workflow cannot be checked (unknown comparison, missing field or a value of the wrong kind), so no branch ran.");
  assert.equal(rule.notices[0].detail, "Fix the rule in the If / else step and run again.");
  const connection = flowRunResultView(routerRefusal("router_condition_invalid"));
  assert.equal(connection.notices[0].title, "A connection out of an If / else step uses a condition that cannot be checked, so no branch ran.");
  assert.equal(connection.notices[0].detail, "Fix the connection's condition and run again.");
  for (const view of [rule, connection]) {
    assert.doesNotMatch(`${view.notices[0].title} ${view.notices[0].detail}`, /router_|error_type|RouterRuleInvalidError/);
    assert.match(view.diagnostics.find((row) => row.label === "Failure code").value, /RouterRuleInvalidError/);
  }
  assert.equal(needsValidationRefresh(routerRefusal("router_rule_invalid")), true);
  // And the other mappings are unchanged.
  assert.match(flowRunResultView(ROUTER_UNMATCHED).notices[0].title, /^The If \/ else step picked a branch that has no matching connection/);
});
