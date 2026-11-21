// Pure state -> tone/label mapping for the turn execution summary.
// No state claims success: a finished turn is "finished, unverified" and stays
// neutral.

import type {
  ClosedValue,
  TurnExecutionState,
  TurnExecutionSummaryLoad,
  TurnNextAction,
  TurnNextActionKind,
  TurnRunCapability,
} from "./turnExecutionSummary.types";

export type TurnExecutionTone =
  | "neutral"
  | "attention"
  | "blocked"
  | "error";

export type TurnExecutionStatePresentation = {
  tone: TurnExecutionTone;
  label: string;
  description: string;
};

const STATE_PRESENTATION: Record<
  TurnExecutionState,
  TurnExecutionStatePresentation
> = {
  finished_unverified: {
    tone: "neutral",
    label: "Finished, unverified",
    description: "The turn finished without an automated verification step.",
  },
  denied: {
    tone: "blocked",
    label: "Denied",
    description: "Policy denied this turn. Nothing was executed.",
  },
  needs_approval: {
    tone: "attention",
    label: "Needs approval",
    description: "Execution requires an approval before it can start.",
  },
  needs_configuration: {
    tone: "attention",
    label: "Needs configuration",
    description: "Execution is blocked until required configuration exists.",
  },
  needs_clarification: {
    tone: "attention",
    label: "Needs clarification",
    description: "Execution is blocked until the request is clarified.",
  },
  needs_confirmation: {
    tone: "attention",
    label: "Needs confirmation",
    description: "A suggested workflow waits for your confirmation.",
  },
  // Not an exception: the run continues in its own chat, so the line stays calm.
  started: {
    tone: "neutral",
    label: "Workflow run started",
    description: "The workflow run started for its Work item; it continues in its own chat.",
  },
  blocked_unknown: {
    tone: "blocked",
    label: "Blocked",
    description: "Execution was blocked for an unrecognized reason.",
  },
  waiting_approval: {
    tone: "attention",
    label: "Waiting for approval",
    description: "An approval request is pending.",
  },
  stopped: {
    tone: "attention",
    label: "Stopped",
    description: "A runtime rule of the agent ended this turn before it finished; the reason says which.",
  },
  failed: {
    tone: "error",
    label: "Failed",
    description: "The turn failed during execution.",
  },
  cancelled: {
    tone: "neutral",
    label: "Cancelled",
    description: "The turn was cancelled.",
  },
  unknown: {
    tone: "neutral",
    label: "Status unknown",
    description: "No execution record exists for this turn.",
  },
};

const UNRECOGNIZED_STATE: TurnExecutionStatePresentation = {
  tone: "neutral",
  label: "Unrecognized status",
  description: "The server reported a status this client does not recognize.",
};

export function isUnrecognized<T extends string>(
  value: ClosedValue<T>,
): value is Exclude<ClosedValue<T>, T> {
  return typeof value === "object" && value !== null && value.unrecognized;
}

export function presentTurnExecutionState(
  state: ClosedValue<TurnExecutionState> | unknown,
): TurnExecutionStatePresentation {
  if (
    typeof state === "string" &&
    Object.prototype.hasOwnProperty.call(STATE_PRESENTATION, state)
  ) {
    return STATE_PRESENTATION[state as TurnExecutionState];
  }
  return UNRECOGNIZED_STATE;
}

const NEXT_ACTION_LABELS: Record<TurnNextActionKind, string | null> = {
  none: null,
  contact_administrator: "Contact an administrator",
  resolve_approval: "Resolve the pending approval",
  complete_configuration: "Complete the required configuration",
  provide_clarification: "Clarify the request",
  confirm_workflow_proposal: "Allow the suggested workflow, choose another one, or deny it",
  retry: "Retry the turn",
};

// The server-provided label wins; the local label is only a fallback for a
// recognized kind. `none` yields no action; an unrecognized kind without a
// label yields a neutral hint instead of a guessed action.
export function presentNextAction(action: TurnNextAction | null | undefined) {
  if (!action) {
    return null;
  }
  const kind = action.kind;
  if (kind === "none") {
    return null;
  }
  if (action.label) {
    return action.label;
  }
  if (
    typeof kind === "string" &&
    Object.prototype.hasOwnProperty.call(NEXT_ACTION_LABELS, kind)
  ) {
    return NEXT_ACTION_LABELS[kind];
  }
  return "Unrecognized next action";
}

const RUN_CAPABILITY_LABELS: Record<string, string> = {
  read_only: "Read-only",
  change: "Change",
  deliver: "Deliver",
};

// The run capability comes from the selected workflow; an escalation raised by
// the user's own decision and an ignored request mode are stated explicitly.
export function presentRunCapability(
  capability: TurnRunCapability | null | undefined,
) {
  if (!capability?.capabilityClass) {
    return null;
  }
  const label =
    RUN_CAPABILITY_LABELS[capability.capabilityClass] ??
    "Unrecognized capability";
  const notes = [
    capability.enforced ? null : "not enforced",
    capability.escalated ? "raised by your decision" : null,
    capability.agentTypeIgnored ? "requested mode ignored" : null,
  ].filter(Boolean);
  return notes.length ? `${label} (${notes.join(", ")})` : label;
}

// An intermediate trace is one step of a longer turn; the turn's last message
// carries the outcome, so only that final trace gets a status card.
export function shouldShowTurnExecutionCard(load: TurnExecutionSummaryLoad) {
  if (load.status === "idle") {
    return false;
  }
  return !(
    load.status === "ready" &&
    load.summary.stateReason.code === "intermediate_trace"
  );
}
