// Self-contained mirror of the backend `turn_execution_summary.v1` contract
// (backend/app/services/session/turn_execution_summary.py). The tables are
// copied verbatim so the e2e test does not need a live backend turn;
// tests/unit/turnExecutionSummaryContract.test.mjs fails if they drift from
// the backend source.

export const SUMMARY_VERSION = "turn_execution_summary.v1";

export const BACKEND_SUMMARY_STATES = [
  "finished_unverified",
  "denied",
  "needs_approval",
  "needs_configuration",
  "needs_clarification",
  "needs_confirmation",
  "started",
  "blocked_unknown",
  "waiting_approval",
  "stopped",
  "failed",
  "cancelled",
  "unknown",
];

// reason code -> [source, fixed server text]
export const BACKEND_REASONS = {
  runtime_finished: ["runtime", "The agent turn finished; no verification contract checked its result."],
  runtime_failed: ["runtime", "The agent turn failed before it finished."],
  runtime_cancelled: ["runtime", "The agent turn was cancelled."],
  runtime_stopped_step_tool_required: [
    "runtime",
    "The agent stopped: a step that must use one of its tools answered without one after a reminder.",
  ],
  runtime_stopped_step_stalled: [
    "runtime",
    "The agent stopped: its final step kept answering without its required tools until its attempt limit.",
  ],
  runtime_stopped_answer_evidence_uncited: [
    "runtime",
    "The answer was withheld: after a reminder it still did not cite the sources this turn found.",
  ],
  runtime_stopped_answer_evidence_invented_url: [
    "runtime",
    "The answer was withheld: after a reminder it still cited a link none of this turn's sources contain.",
  ],
  runtime_stopped_agent_reply_not_json: [
    "runtime",
    "The agent stopped: its final reply is not the single JSON object its reply format requires.",
  ],
  runtime_stopped_agent_reply_schema_mismatch: [
    "runtime",
    "The agent stopped: its final reply does not match the fields its reply format declares.",
  ],
  runtime_stopped_agent_reply_contract_invalid: [
    "runtime",
    "The agent stopped: its reply format is not valid, so its final reply could not be checked.",
  ],
  runtime_outcome_unknown: ["runtime", "The runtime outcome of this turn is not recorded."],
  intermediate_trace: ["runtime", "This step is part of a longer turn; the turn's last message shows its outcome."],
  approval_pending: ["approval", "A tool action in this turn is waiting for an approval decision."],
  approval_state_unknown: ["approval", "An approval requested in this turn could not be resolved."],
  clarification_requested: ["runtime", "The agent paused this turn to ask for clarification."],
  workflow_decision_requested: ["workflow", "The workflow paused this turn until you record a decision."],
  gate_denied: ["execution_gate", "Execution policy denied this request; it was not executed."],
  gate_needs_approval: ["execution_gate", "This request requires an approval before it can run."],
  gate_needs_configuration: ["execution_gate", "This request requires configuration before it can run."],
  gate_needs_clarification: ["execution_gate", "This request needs clarification before it can run."],
  gate_needs_confirmation: ["execution_gate", "A suggested workflow waits for your confirmation; nothing ran."],
  workflow_run_started: ["workflow", "The workflow run started for its Work item; it continues in its own chat."],
  gate_needs_start_confirmation: ["execution_gate", "A workflow run waits for your start; nothing ran yet."],
  gate_blocked_unknown: ["execution_gate", "The request was blocked because its execution state is unclear."],
  model_alias_not_admitted: [
    "model_admission",
    "This project is not granted the model alias for this request; no model was called.",
  ],
  model_data_policy_denied: [
    "model_admission",
    "The Workspace data policy does not permit this request on this model alias; no model was called.",
  ],
  missing_snapshot: ["trace", "No execution decision was recorded for this turn."],
  malformed_snapshot: ["trace", "The recorded execution decision for this turn is not readable."],
  inconsistent_snapshot: ["trace", "The recorded execution decision for this turn is inconsistent."],
};

// reason code -> [next action kind, fixed server label]
export const BACKEND_NEXT_ACTIONS = {
  runtime_finished: ["none", null],
  runtime_failed: ["retry", "Send the request again."],
  runtime_cancelled: ["retry", "Send the request again."],
  runtime_stopped_step_tool_required: [
    "complete_configuration",
    "Rephrase the request so the step can use its tools, or ask an administrator to set its tool use to optional.",
  ],
  runtime_stopped_step_stalled: ["complete_configuration", "Ask an administrator to review the agent's final step and its tools."],
  runtime_stopped_answer_evidence_uncited: ["retry", "Open the sources this turn found, or send the request again."],
  runtime_stopped_answer_evidence_invented_url: ["retry", "Open the sources this turn found, or send the request again."],
  runtime_stopped_agent_reply_not_json: [
    "retry",
    "Send the request again, or ask an administrator to review the agent's reply format.",
  ],
  runtime_stopped_agent_reply_schema_mismatch: [
    "retry",
    "Send the request again, or ask an administrator to review the agent's reply format.",
  ],
  runtime_stopped_agent_reply_contract_invalid: ["complete_configuration", "Ask an administrator to fix the agent's reply format."],
  runtime_outcome_unknown: ["none", null],
  intermediate_trace: ["none", null],
  approval_pending: ["resolve_approval", "Approve or reject the pending action."],
  approval_state_unknown: [
    "contact_administrator",
    "Ask an administrator to check the approval requested in this turn.",
  ],
  clarification_requested: ["provide_clarification", "Answer the agent's question to continue."],
  workflow_decision_requested: ["provide_clarification", "Choose one of the offered decisions to continue."],
  gate_denied: ["contact_administrator", "Ask an administrator to review the execution policy."],
  gate_needs_approval: [
    "contact_administrator",
    "Ask an administrator to authorize this kind of request; no approval request was created.",
  ],
  gate_needs_configuration: ["complete_configuration", "Complete the missing configuration, then retry."],
  gate_needs_clarification: ["provide_clarification", "Restate the request with the missing details."],
  // The label is prompt catalog data (workflow.proposal.gate_needs_confirmation), rendered by the server.
  gate_needs_confirmation: ["confirm_workflow_proposal", null],
  workflow_run_started: ["none", null],
  gate_needs_start_confirmation: ["confirm_workflow_proposal", "Start the run, choose another workflow, or don't start."],
  gate_blocked_unknown: ["contact_administrator", "Ask an administrator to review this session."],
  model_alias_not_admitted: [
    "complete_configuration",
    "Ask an administrator to grant the model alias to this project, then retry.",
  ],
  model_data_policy_denied: ["contact_administrator", "Ask an administrator to review the model's data policy."],
  missing_snapshot: ["none", null],
  malformed_snapshot: ["none", null],
  inconsistent_snapshot: ["none", null],
};

export const BACKEND_STATE_BY_REASON = {
  runtime_finished: "finished_unverified",
  runtime_failed: "failed",
  runtime_cancelled: "cancelled",
  runtime_stopped_step_tool_required: "stopped",
  runtime_stopped_step_stalled: "stopped",
  runtime_stopped_answer_evidence_uncited: "stopped",
  runtime_stopped_answer_evidence_invented_url: "stopped",
  runtime_stopped_agent_reply_not_json: "stopped",
  runtime_stopped_agent_reply_schema_mismatch: "stopped",
  runtime_stopped_agent_reply_contract_invalid: "stopped",
  runtime_outcome_unknown: "unknown",
  intermediate_trace: "unknown",
  approval_pending: "waiting_approval",
  approval_state_unknown: "unknown",
  clarification_requested: "needs_clarification",
  workflow_decision_requested: "needs_clarification",
  gate_denied: "denied",
  gate_needs_approval: "needs_approval",
  gate_needs_configuration: "needs_configuration",
  gate_needs_clarification: "needs_clarification",
  gate_needs_confirmation: "needs_confirmation",
  workflow_run_started: "started",
  gate_needs_start_confirmation: "needs_confirmation",
  gate_blocked_unknown: "blocked_unknown",
  model_alias_not_admitted: "needs_configuration",
  model_data_policy_denied: "denied",
  missing_snapshot: "unknown",
  malformed_snapshot: "unknown",
  inconsistent_snapshot: "unknown",
};

// Profile decision sources used by the e2e fixtures; each one is produced by
// the backend profile producer (asserted by the contract unit test).
export const PROFILE_DECISION_SOURCES = {
  directChat: "direct_chat_safe",
};

export const GATE_SOURCE_PROFILE = "execution_profile";

// Mirrors `_profile_section`: the gate is always nested and its outcome is
// derived from `allowed`; the gate source is a closed `execution_gate` value.
export function profileSection({
  profileId,
  status,
  decisionSource,
  workflowKey = null,
  executionStrategy = null,
  gateSource = GATE_SOURCE_PROFILE,
  // Mirrors the backend's closed projection of the run capability; the
  // default is what a profile without a capability section projects to.
  capability = {
    class: "unknown",
    source: null,
    enforced: false,
    escalated: false,
    agent_type_ignored: false,
  },
  // The turn's tool surface source and governed set key (W22b); the default is
  // what a turn without a recorded surface projects to.
  toolSurface = { source: "unknown", set: null },
}) {
  const allowed = status === "allowed";
  return {
    version: "execution_profile.v1",
    profile_id: profileId,
    status,
    decision_source: decisionSource,
    workflow_key: workflowKey,
    execution_strategy: executionStrategy,
    capability,
    tool_surface: toolSurface,
    gate: {
      outcome: allowed ? "allowed" : "blocked",
      status,
      decision_source: gateSource,
    },
  };
}

// Mirrors `build_turn_execution_summary` for one reason code.
export function buildSummaryFixture({
  traceId,
  sessionId,
  reasonCode,
  profile = null,
  agent = { id: null, name: null },
  model = { provider: null, model: null },
  capabilities = [],
  approvals = [],
  artifacts = [],
  usage = { tokens_in: null, tokens_out: null },
  decisionRequest = null,
  workflowProposal = null,
  runIdentity = { kind: "compat_turn", product_run_id: null, run_state: null, attempt: null },
}) {
  const state = BACKEND_STATE_BY_REASON[reasonCode];
  if (!state) {
    throw new Error(`Unknown backend reason code: ${reasonCode}`);
  }
  const [source, text] = BACKEND_REASONS[reasonCode];
  const [kind, label] = BACKEND_NEXT_ACTIONS[reasonCode];
  const gateBlocked = profile !== null && profile.gate.outcome === "blocked";
  return {
    version: SUMMARY_VERSION,
    trace_id: traceId,
    session_id: sessionId,
    message_id: null,
    run_identity: runIdentity,
    state,
    state_reason: { code: reasonCode, source, text },
    next_action: { kind, label },
    execution_profile: profile,
    agent: profile === null ? { id: null, name: null } : agent,
    // A gate-blocked turn never reached a model.
    model: gateBlocked ? { provider: null, model: null } : model,
    capabilities_used: capabilities,
    approvals,
    artifacts,
    usage,
    decision_request: decisionRequest,
    workflow_proposal: workflowProposal,
  };
}
