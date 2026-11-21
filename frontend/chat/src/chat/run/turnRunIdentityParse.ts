// Typed parse of `turn_execution_summary.v1.run_identity`.
//
// The server resolves the Run/Attempt only through the turn's stamp and only
// for the session owner; state and end reason are read from the database.
// This parser is defensive on top of that: an unknown kind, or a
// `product_run` without a usable run/attempt identity, becomes the neutral
// `unresolved` kind. The reserved `verifying` state is deliberately absent
// and parses as unrecognized.

import type { ClosedValue } from "./turnExecutionSummary.types";

export const TURN_RUN_IDENTITY_KINDS = [
  "product_run",
  "unscoped_turn",
  "compat_turn",
  "unresolved",
] as const;

export type TurnRunIdentityKind = (typeof TURN_RUN_IDENTITY_KINDS)[number];

// Backend `RUN_STATES` minus the reserved `verifying`, plus the summary's `unknown`.
export const TURN_RUN_STATES = [
  "requested",
  "admitted",
  "running",
  "completed",
  "finished_unverified",
  "failed",
  "cancelled",
  "denied",
  "needs_approval",
  "needs_configuration",
  "needs_clarification",
  "waiting_approval",
  "incomplete",
  "unknown",
] as const;

export type TurnRunState = (typeof TURN_RUN_STATES)[number];

// Backend `RUN_END_REASONS` plus the summary's `unknown`.
export const TURN_RUN_END_REASONS = [
  "gate_denied",
  "gate_missing_profile",
  "gate_unknown_status",
  "gate_needs_approval",
  "gate_needs_configuration",
  "gate_needs_clarification",
  "runtime_not_ready",
  "model_alias_not_admitted",
  "model_data_policy_denied",
  "preparation_failed",
  "runtime_finished",
  "provider_error",
  "runtime_error",
  "runtime_exception",
  "approval_pending",
  "clarification_requested",
  "completion_not_accepted",
  "delegated_outcome_unrecorded",
  "generator_closed",
  "task_cancelled",
  "interrupted_by_restart",
  // The turn waits on its workflow proposal's approval record.
  "awaiting_workflow_confirmation",
  "unknown",
] as const;

export type TurnRunEndReason = (typeof TURN_RUN_END_REASONS)[number];

export type TurnRunAttempt = {
  id: string;
  number: number;
  state: ClosedValue<TurnRunState>;
  endReason: ClosedValue<TurnRunEndReason> | null;
};

export type TurnRunIdentity =
  | {
      kind: "product_run";
      runId: string;
      runState: ClosedValue<TurnRunState>;
      attempt: TurnRunAttempt;
    }
  | {
      kind: Exclude<TurnRunIdentityKind, "product_run">;
      runId: null;
      runState: null;
      attempt: null;
    };

const RUN_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const MAX_ATTEMPT_NUMBER = 1_000_000;

type RawRecord = Record<string, unknown>;

function asRecord(value: unknown): RawRecord | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as RawRecord)
    : null;
}

function runId(value: unknown) {
  return typeof value === "string" && RUN_ID.test(value) ? value : null;
}

function closed<T extends string>(
  allowed: readonly T[],
  value: unknown,
): ClosedValue<T> {
  if (
    typeof value === "string" &&
    (allowed as readonly string[]).includes(value)
  ) {
    return value as T;
  }
  const raw = typeof value === "string" ? value.slice(0, 64) : "";
  return { unrecognized: true, raw };
}

function withoutRun(
  kind: Exclude<TurnRunIdentityKind, "product_run">,
): TurnRunIdentity {
  return { kind, runId: null, runState: null, attempt: null };
}

function parseAttempt(value: unknown): TurnRunAttempt | null {
  const record = asRecord(value);
  const id = runId(record?.id);
  const number = record?.number;
  if (
    !record ||
    !id ||
    typeof number !== "number" ||
    !Number.isInteger(number) ||
    number < 1 ||
    number > MAX_ATTEMPT_NUMBER
  ) {
    return null;
  }
  return {
    id,
    number,
    state: closed(TURN_RUN_STATES, record.state),
    endReason:
      record.end_reason === null || record.end_reason === undefined
        ? null
        : closed(TURN_RUN_END_REASONS, record.end_reason),
  };
}

export function parseTurnRunIdentity(value: unknown): TurnRunIdentity {
  const record = asRecord(value);
  const kind = record?.kind;
  if (kind === "product_run") {
    const id = runId(record?.product_run_id);
    const attempt = parseAttempt(record?.attempt);
    return id && attempt
      ? {
          kind,
          runId: id,
          runState: closed(TURN_RUN_STATES, record?.run_state),
          attempt,
        }
      : withoutRun("unresolved");
  }
  if (kind === "unscoped_turn" || kind === "compat_turn") {
    return withoutRun(kind);
  }
  return withoutRun("unresolved");
}
