// Plain-language messages for the closed node-failure codes the backend records on a flow run
// (`run.failure.detail.code`, services/runtime_failure_taxonomy.py + flow_orchestration/
// flow_agent_reference.py / flow_agent_step.py / agent_node_guard.py / router_branches.py /
// conditional_rules.py). Only typed codes are mapped;
// error text is never parsed. The raw code, error type and node id stay in Diagnostics.
import type { FlowRunTracePayload } from "./flowRunTypes";
import { asRecord } from "./flowTraceFormat";

export type FailureMessage = { title: string; action: string };

const MESSAGES: Record<string, FailureMessage> = {
  agent_inactive: {
    title: "The selected agent is inactive.",
    action: "Activate it on its agent page or select another agent.",
  },
  agent_not_accessible: {
    title: "The selected agent does not exist or is not available to you.",
    action: "Select another agent.",
  },
  agent_out_of_scope: {
    title: "The selected agent belongs to a different workspace than this workflow.",
    action: "Select an agent of this workflow's workspace or a Global agent.",
  },
  agent_needs_publication: {
    title: "The selected agent has no published revision, which this platform requires to run it.",
    action: "Publish the agent on its agent page or select another agent.",
  },
  agent_execution_not_configured: {
    title: "Agent execution is not configured on this platform.",
    action: "Ask an administrator to configure the agent execution mode.",
  },
  agent_step_needs_agent: {
    title: "This agent step has no agent selected.",
    action: "Select an agent for the step, or give it instructions.",
  },
  agent_step_input_too_large: {
    title: "The input for this agent step is too large to send to the agent.",
    action: "Shorten the input or split the work into smaller steps.",
  },
  supervisor_execution_unsupported: {
    title: "Supervisor steps cannot run in workflows yet.",
    action: "Replace the supervisor step with agent steps.",
  },
  agent_turn_denied: { title: "The agent's turn was denied by policy.", action: "Ask an administrator to review the policy." },
  agent_turn_needs_configuration: { title: "The agent needs configuration before it can run.", action: "Complete the agent's configuration." },
  agent_turn_needs_clarification: { title: "The agent asked for clarification instead of answering.", action: "Make the step's instructions or input more specific." },
  agent_turn_needs_approval: { title: "The agent requested an approval, which a workflow step cannot wait for.", action: "Review the agent's session, then change the step." },
  agent_turn_stopped: { title: "The agent stopped before finishing.", action: "Open the agent's session to see why." },
  agent_turn_failed: { title: "The agent's turn failed.", action: "Try again; if it keeps failing, open the agent's session." },
  agent_turn_cancelled: { title: "The agent's turn was cancelled.", action: "Run again." },
  agent_turn_outcome_unknown: { title: "The agent's turn ended without a recorded outcome.", action: "Open the agent's session to check it." },
  flow_run_timeout_exceeded: { title: "The workflow ran longer than its time limit.", action: "Raise the run time limit or simplify the step." },
  // An If / else step picked a branch no connection runs and there is no fallback connection.
  router_branch_unmatched: {
    title: "The If / else step picked a branch that has no matching connection, so no later step ran.",
    action: "Connect that branch to the next step, or add a connection without a branch as the fallback for all other cases.",
  },
  // A rule or a custom connection condition of an If / else step cannot be checked.
  router_rule_invalid: {
    title: "An If / else rule in this workflow cannot be checked (unknown comparison, missing field or a value of the wrong kind), so no branch ran.",
    action: "Fix the rule in the If / else step and run again.",
  },
  router_condition_invalid: {
    title: "A connection out of an If / else step uses a condition that cannot be checked, so no branch ran.",
    action: "Fix the connection's condition and run again.",
  },
};

export function failureCode(trace: FlowRunTracePayload): string | null {
  const code = asRecord(asRecord(trace.run.failure).detail).code;
  return typeof code === "string" && code ? code : null;
}

export function failureMessage(trace: FlowRunTracePayload): FailureMessage | null {
  const code = failureCode(trace);
  return code ? MESSAGES[code] ?? null : null;
}

// A run refused for its configuration (category `input_contract_error`) means the editor's last
// validation result may be stale; transient failures (provider, runtime, timeouts) are not.
export function needsValidationRefresh(trace: FlowRunTracePayload): boolean {
  const failure = asRecord(trace.run.failure);
  return trace.run.status === "failed" && failure.category === "input_contract_error";
}
