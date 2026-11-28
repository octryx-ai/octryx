import type { PanelTaskRunRow } from "./taskTypes";

// Only an exact match on an error run is explained; lookalikes stay unclassified and show the original text.

export type KnownRunError = {
  summary: string;
  guidance: string;
};

// A paused Action cannot run, so its guidance says to resume it first instead of running it again.
type RunErrorText = {
  summary: string;
  cause: string;
  next: string;
  nextWhenPaused: string;
};

const RESUME = "Resume the action before running it.";

const KNOWN_RUN_ERRORS: Record<string, RunErrorText> = {
  agent_definition_inactive: {
    summary: "The selected agent was turned off",
    cause:
      "The agent this action uses was inactive when this run was attempted, so the run was refused.",
    next: "Check which agent the action uses and activate it on the agent's page, or edit the action to choose an active agent.",
    nextWhenPaused: `Check which agent the action uses and activate it on the agent's page, or edit the action to choose an active agent. ${RESUME}`,
  },
  agent_definition_not_published: {
    summary: "The selected agent had no published revision",
    cause:
      "Agents run only from a published revision here, and the selected agent had none that could run.",
    next: "Review the agent and publish a revision on its page, then run the action again.",
    nextWhenPaused:
      "Review the agent and publish a revision on its page, then resume the action before running it again.",
  },
  agent_definition_execution_mode_not_configured: {
    summary: "Agent execution is not configured",
    cause:
      "The platform's agent execution mode was not configured correctly, so the agent could not run.",
    next: "Ask a workspace administrator to configure the agent execution mode.",
    nextWhenPaused: `Ask a workspace administrator to configure the agent execution mode. ${RESUME}`,
  },
  agent_reply_not_json: {
    summary: "The reply was not the required JSON",
    cause:
      "The agent stopped: its final reply is not the single JSON object its reply format requires, so the run was not accepted.",
    next: "Run the action again, or ask an administrator to review the agent's reply format.",
    nextWhenPaused:
      "Resume the action first, then run it again; if it repeats, ask an administrator to review the agent's reply format.",
  },
  agent_reply_schema_mismatch: {
    summary: "The reply did not match the declared fields",
    cause:
      "The agent stopped: its final reply does not match the fields its reply format declares, so the run was not accepted.",
    next: "Run the action again, or ask an administrator to review the agent's reply format.",
    nextWhenPaused:
      "Resume the action first, then run it again; if it repeats, ask an administrator to review the agent's reply format.",
  },
  agent_reply_contract_invalid: {
    summary: "The agent's reply format is not valid",
    cause:
      "The agent's reply format is not valid, so its final reply could not be checked and the run was not accepted.",
    next: "Ask an administrator to fix the agent's reply format (edit the agent, Output format).",
    nextWhenPaused: `Ask an administrator to fix the agent's reply format (edit the agent, Output format). ${RESUME}`,
  },
  agent_reply_contract_unchecked: {
    summary: "The reply could not be checked",
    cause:
      "The agent has a checked reply format, but this run did not end with one final reply that could be checked, so it was not accepted.",
    next: "Open the run's chat to see how the turn ended, then run the action again; if it repeats, ask an administrator to review the agent.",
    nextWhenPaused:
      "Open the run's chat to see how the turn ended, then resume the action before running it again; if it repeats, ask an administrator to review the agent.",
  },
  agent_reply_contract_path_unsupported: {
    summary: "A step's agent needs a checked reply",
    cause:
      "A step of this action uses an agent with a checked reply format, which a step run cannot check, so the step was refused.",
    next: "Run that agent directly as the action's agent, or set its output format to Free text.",
    nextWhenPaused: `Make that agent the action's own agent, or set its output format to Free text. ${RESUME}`,
  },
};

const RUNTIME_STOP_REASONS = new Set([
  "step_tool_required",
  "step_stalled",
  "answer_evidence_uncited",
  "answer_evidence_invented_url",
]);

const STOPPED_BY_CHECK: RunErrorText = {
  summary: "Stopped by a safety or quality check",
  cause:
    "The agent's turn was stopped by a safety or quality check, so the run was not accepted.",
  next: "Open the run's chat to see why, then run the action again; if it repeats, ask an administrator to review the agent.",
  nextWhenPaused:
    "Open the run's chat to see why, then resume the action before running it again; if it repeats, ask an administrator to review the agent.",
};

const STOP_CODE = /^[a-z][a-z0-9_]{0,63}$/;

function outputRecordsStop(output: unknown, error: string): boolean {
  if (!output || typeof output !== "object" || Array.isArray(output))
    return false;
  const outcome = (output as { turn_outcome?: unknown }).turn_outcome;
  if (!outcome || typeof outcome !== "object" || Array.isArray(outcome))
    return false;
  const { state, reason } = outcome as { state?: unknown; reason?: unknown };
  return state === "stopped" && reason === error && STOP_CODE.test(error);
}

function explain(text: RunErrorText, paused: boolean): KnownRunError {
  return {
    summary: text.summary,
    guidance: `${text.cause} ${paused ? text.nextWhenPaused : text.next}`,
  };
}

export function knownRunError(
  // `output` is read only if the server sends it (the run list does not today).
  run: Pick<PanelTaskRunRow, "status" | "error"> & { output?: unknown },
  { paused = false }: { paused?: boolean } = {},
): KnownRunError | null {
  if (run.status !== "error" || typeof run.error !== "string") return null;
  if (Object.prototype.hasOwnProperty.call(KNOWN_RUN_ERRORS, run.error)) {
    return explain(KNOWN_RUN_ERRORS[run.error], paused);
  }
  if (
    RUNTIME_STOP_REASONS.has(run.error) ||
    outputRecordsStop(run.output, run.error)
  ) {
    return explain(STOPPED_BY_CHECK, paused);
  }
  return null;
}
