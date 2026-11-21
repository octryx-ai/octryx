// Defensive normalization of the raw `turn_execution_summary.v1` payload.
// Only allow-listed fields are copied; everything else in the response is
// dropped so no unexpected server field can reach the DOM.

import { parseTurnWorkflowChecks } from "./turnWorkflowChecks";
import {
  TURN_EXECUTION_STATES,
  TURN_EXECUTION_SUMMARY_VERSION,
  TURN_NEXT_ACTION_KINDS,
  WORKFLOW_PROPOSAL_STATUSES,
  type ClosedValue,
  type TurnApprovalSummary,
  type TurnArtifactSummary,
  type TurnCapabilityUse,
  type TurnDecisionOption,
  type TurnDecisionRequest,
  type TurnExecutionProfile,
  type TurnExecutionSummary,
  type TurnRunCapability,
  type TurnWorkflowProposal,
} from "./turnExecutionSummary.types";
import { parseTurnAnswerEvidence } from "./turnAnswerEvidence";
import { parseTurnContentObligations } from "./turnContentObligations";
import { parseTurnReplyContract } from "./turnReplyContract";
import { parseTurnRunIdentity } from "./turnRunIdentityParse";

const MAX_TEXT_LENGTH = 280;
const MAX_LIST_ITEMS = 50;

type RawRecord = Record<string, unknown>;

function asRecord(value: unknown): RawRecord | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as RawRecord)
    : null;
}

function boundedText(value: unknown, maxLength = MAX_TEXT_LENGTH) {
  if (typeof value !== "string") {
    return null;
  }
  const text = value.replace(/\s+/g, " ").trim();
  if (!text) {
    return null;
  }
  return text.length > maxLength
    ? `${text.slice(0, maxLength - 1).trimEnd()}…`
    : text;
}

function finiteNumber(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function closedValue<T extends string>(
  allowed: readonly T[],
  value: unknown,
): ClosedValue<T> {
  if (
    typeof value === "string" &&
    (allowed as readonly string[]).includes(value)
  ) {
    return value as T;
  }
  return {
    unrecognized: true,
    raw: boundedText(typeof value === "string" ? value : "", 64) ?? "",
  };
}

function boundedList<T>(value: unknown, map: (item: RawRecord) => T | null) {
  if (!Array.isArray(value)) {
    return [];
  }
  const items: T[] = [];
  for (const entry of value.slice(0, MAX_LIST_ITEMS)) {
    const record = asRecord(entry);
    const mapped = record ? map(record) : null;
    if (mapped) {
      items.push(mapped);
    }
  }
  return items;
}

function parseGate(value: unknown) {
  const record = asRecord(value);
  if (!record) {
    return null;
  }
  return {
    outcome: boundedText(record.outcome, 32),
    status: boundedText(record.status, 64),
    decisionSource: boundedText(record.decision_source, 120),
  };
}

function parseRunCapability(value: unknown): TurnRunCapability | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }
  return {
    capabilityClass: boundedText(record.class, 32),
    source: boundedText(record.source, 64),
    enforced: record.enforced === true,
    escalated: record.escalated === true,
    agentTypeIgnored: record.agent_type_ignored === true,
  };
}

function parseProfile(value: unknown): TurnExecutionProfile | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }
  return {
    version: boundedText(record.version, 64),
    profileId: boundedText(record.profile_id, 120),
    status: boundedText(record.status, 64),
    decisionSource: boundedText(record.decision_source, 120),
    workflowKey: boundedText(record.workflow_key, 120),
    executionStrategy: boundedText(record.execution_strategy, 120),
    runCapability: parseRunCapability(record.capability),
    gate: parseGate(record.gate),
  };
}

function parseCapability(record: RawRecord): TurnCapabilityUse | null {
  const name = boundedText(record.name, 120);
  return name
    ? {
        name,
        calls: finiteNumber(record.calls),
        succeeded: finiteNumber(record.succeeded),
        failed: finiteNumber(record.failed),
      }
    : null;
}

function parseApproval(record: RawRecord): TurnApprovalSummary {
  return {
    id: boundedText(record.approval_id, 120),
    toolName: boundedText(record.tool_name, 120),
    status: boundedText(record.status, 64),
    createdAt: boundedText(record.created_at, 64),
    resolvedAt: boundedText(record.resolved_at, 64),
  };
}

// The approval's display name: the tool it paused at.
export function turnApprovalLabel(approval: TurnApprovalSummary) {
  return approval.toolName || "Approval";
}

function parseArtifact(record: RawRecord): TurnArtifactSummary {
  return {
    id: boundedText(record.artifact_id, 120),
    toolName: boundedText(record.tool_name, 120),
    sizeBytes: finiteNumber(record.size_bytes),
    createdAt: boundedText(record.created_at, 64),
  };
}

// Decision keys and values are snake_case catalog tokens; anything else
// drops the whole request so a malformed payload never renders a button.
const DECISION_TOKEN = /^[a-z][a-z0-9_]{0,63}$/;
// The largest closed backend decision is the developer diagram type (14 options).
const MAX_DECISION_OPTIONS = 16;

function decisionToken(value: unknown) {
  return typeof value === "string" && DECISION_TOKEN.test(value) ? value : null;
}

function parseDecisionOption(record: RawRecord): TurnDecisionOption | null {
  const value = decisionToken(record.value);
  const label = boundedText(record.label, 80);
  return value && label ? { value, label } : null;
}

function parseDecisionRequest(value: unknown): TurnDecisionRequest | null {
  const record = asRecord(value);
  const decisionKey = record ? decisionToken(record.decision_key) : null;
  if (!record || !decisionKey) {
    return null;
  }
  const options = boundedList(record.options, parseDecisionOption).slice(
    0,
    MAX_DECISION_OPTIONS,
  );
  if (options.length === 0) {
    return null;
  }
  const recorded = decisionToken(record.recorded_value);
  return {
    decisionKey,
    options,
    recordedValue:
      recorded && options.some((option) => option.value === recorded)
        ? recorded
        : null,
  };
}

function parseWorkflowProposal(value: unknown): TurnWorkflowProposal | null {
  const record = asRecord(value);
  if (!record) {
    return null;
  }
  return {
    status: closedValue(WORKFLOW_PROPOSAL_STATUSES, record.status),
    reasonCode: decisionToken(record.reason_code),
    proposalId: boundedText(record.proposal_id, 64),
    workflowKey: boundedText(record.workflow_key, 120),
    workflowTitle: boundedText(record.workflow_title, 120),
    confidence: boundedText(record.confidence, 16),
    changeCapable:
      typeof record.change_capable === "boolean" ? record.change_capable : null,
  };
}

function modelLabel(value: unknown) {
  const record = asRecord(value);
  if (!record) {
    return null;
  }
  const provider = boundedText(record.provider, 80);
  const model = boundedText(record.model, 120);
  if (provider && model) {
    return `${provider} / ${model}`;
  }
  return model ?? provider;
}

// Returns null when the payload is not a v1 summary; callers render that as
// "unavailable" rather than guessing a state.
export function parseTurnExecutionSummary(
  payload: unknown,
): TurnExecutionSummary | null {
  const record = asRecord(payload);
  if (!record || record.version !== TURN_EXECUTION_SUMMARY_VERSION) {
    return null;
  }
  const reason = asRecord(record.state_reason);
  const nextAction = asRecord(record.next_action);
  const agent = asRecord(record.agent);
  const usage = asRecord(record.usage);
  return {
    version: TURN_EXECUTION_SUMMARY_VERSION,
    traceId: boundedText(record.trace_id, 120),
    sessionId: boundedText(record.session_id, 120),
    messageId: boundedText(record.message_id, 120),
    runIdentity: parseTurnRunIdentity(record.run_identity),
    state: closedValue(TURN_EXECUTION_STATES, record.state),
    stateReason: {
      code: boundedText(reason?.code, 64),
      source: boundedText(reason?.source, 64),
      text: boundedText(reason?.text),
    },
    nextAction: {
      kind: closedValue(TURN_NEXT_ACTION_KINDS, nextAction?.kind),
      label: boundedText(nextAction?.label, 160),
    },
    executionProfile: parseProfile(record.execution_profile),
    agentName: boundedText(agent?.name, 120),
    modelLabel: modelLabel(record.model),
    capabilitiesUsed: boundedList(record.capabilities_used, parseCapability),
    approvals: boundedList(record.approvals, parseApproval),
    artifacts: boundedList(record.artifacts, parseArtifact),
    usage: {
      tokensIn: finiteNumber(usage?.tokens_in),
      tokensOut: finiteNumber(usage?.tokens_out),
    },
    decisionRequest: parseDecisionRequest(record.decision_request),
    workflowProposal: parseWorkflowProposal(record.workflow_proposal),
    answerEvidence: parseTurnAnswerEvidence(record.answer_evidence),
    workflowChecks: parseTurnWorkflowChecks(record.workflow_checks),
    replyContract: parseTurnReplyContract(record.reply_contract),
    contentObligations: parseTurnContentObligations(record.content_obligations),
  };
}
