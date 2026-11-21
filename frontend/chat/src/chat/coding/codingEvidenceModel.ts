import type {
  CodingApprovalEvidence,
  CodingSessionSummary,
  CodingValidationEvidence,
  WorkCodingObservability,
} from "./codingTypes";
import type { WorkChangePlan } from "../work/workChangePlanTypes";

// Planned versus recorded Coding evidence. A plan states intent: its checks, branches and
// required approvals are not results. Recorded facts come from explicit source records with a known
// shape (`validation_results`, `approvals`, run lists). A missing or malformed field stays unknown
// (`null`), an explicit empty list is a recorded zero, and object keys are never counted as records.
// Agent tool calls that the backend classifies as "validation" by tool name are shown separately as
// tool calls: a successful call (for example a generic `run_cli_command`) is not a passed test.

type UnknownRecord = Record<string, unknown>;

const PASS_STATUSES = new Set(["passed", "pass", "success", "succeeded", "ok"]);
const FAIL_STATUSES = new Set(["failed", "failure", "error", "errored", "timed_out", "timeout"]);
const GRANTED_DECISIONS = new Set(["approved", "approve", "granted", "accepted"]);
const REJECTED_DECISIONS = new Set(["rejected", "reject", "declined", "denied", "changes_requested", "needs_work"]);

function plainObject(value: unknown): UnknownRecord | null {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as UnknownRecord) : null;
}

// A record is a plain object with at least one non-empty scalar value; `{}` and bare values are not.
export function isRecordEntry(value: unknown): value is UnknownRecord {
  const fields = plainObject(value);
  if (!fields) return false;
  return Object.values(fields).some(
    (entry) => (typeof entry === "string" && entry.trim() !== "") || typeof entry === "number" || typeof entry === "boolean",
  );
}

// A list is a measurement: an empty list is zero. Anything else (absent, a string, an object) is not
// a list of records and stays unknown. Entries that are not readable records are counted as
// unrecognized, never dropped silently: they keep any outcome open.
export function readRecordList(value: unknown): { records: UnknownRecord[]; unrecognized: number } | null {
  if (!Array.isArray(value)) return null;
  const records = value.filter(isRecordEntry);
  return { records, unrecognized: value.length - records.length };
}

export function recordList(value: unknown): UnknownRecord[] | null {
  return readRecordList(value)?.records ?? null;
}

// For counts that only add up recorded records: unknown contributes nothing.
export function recordCount(value: unknown): number {
  return recordList(value)?.length ?? 0;
}

function field(entry: UnknownRecord, keys: string[]): string {
  for (const key of keys) {
    const raw = entry[key];
    if (typeof raw === "string" && raw.trim()) return raw.trim().toLowerCase();
  }
  return "";
}

const resultStatus = (entry: UnknownRecord) => field(entry, ["status", "result", "outcome", "conclusion"]);
const approvalDecision = (entry: UnknownRecord) => field(entry, ["status", "state", "decision", "result"]);

export function plannedCheckCount(plan: Pick<WorkChangePlan, "validation_plan"> | null | undefined): number {
  return Array.isArray(plan?.validation_plan) ? plan.validation_plan.length : 0;
}

export function codingValidationEvidence(
  sourceFields: UnknownRecord | null | undefined,
  plan: Pick<WorkChangePlan, "validation_plan"> | null | undefined,
  observability?: WorkCodingObservability | null,
): CodingValidationEvidence {
  const list = readRecordList(sourceFields?.validation_results);
  const results = list?.records ?? null;
  const statuses = (results || []).map(resultStatus);
  const toolCalls = observability?.summary?.validation_event_count;
  const validationTools = (observability?.tools?.by_name || []).filter((bucket) => bucket.kind === "validation");
  return {
    planned: plannedCheckCount(plan),
    results: {
      recorded: results ? results.length : null,
      passed: results ? statuses.filter((status) => PASS_STATUSES.has(status)).length : null,
      failed: results ? statuses.filter((status) => FAIL_STATUSES.has(status)).length : null,
      unrecognized: list ? list.unrecognized : null,
    },
    toolCalls: typeof toolCalls === "number"
      ? { recorded: toolCalls, failed: validationTools.reduce((sum, bucket) => sum + (bucket.failed || 0), 0) }
      : { recorded: null, failed: null },
  };
}

export function codingApprovalEvidence(
  sourceFields: UnknownRecord | null | undefined,
  plan: Pick<WorkChangePlan, "required_approvals"> | null | undefined,
): CodingApprovalEvidence {
  const list = readRecordList(sourceFields?.approvals);
  const approvals = list?.records ?? null;
  const decisions = (approvals || []).map(approvalDecision);
  const requirements = Array.isArray(plan?.required_approvals) ? plan.required_approvals : [];
  const granted = approvals ? decisions.filter((decision) => GRANTED_DECISIONS.has(decision)).length : null;
  const rejected = approvals ? decisions.filter((decision) => REJECTED_DECISIONS.has(decision)).length : null;
  const undecided = approvals ? approvals.length - (granted ?? 0) - (rejected ?? 0) : 0;
  return {
    required: requirements.length,
    recorded: approvals ? approvals.length : null,
    granted,
    rejected,
    unrecognized: list ? list.unrecognized : null,
    requirementsMet: list !== null && list.unrecognized === 0 && rejected === 0 && undecided === 0
      && requirementsMatched(requirements, list.records.filter((_, index) => GRANTED_DECISIONS.has(decisions[index]))),
  };
}

// The plan's required approvals carry a `type` (work_plan, code_review, security, …). A requirement
// is matched only by its own granted record of the same type; one record never satisfies two
// requirements, and a requirement without a type cannot be matched.
function requirementsMatched(requirements: unknown[], grantedRecords: UnknownRecord[]): boolean {
  const needed = requirements
    .map(plainObject)
    .filter((requirement) => requirement && requirement.required !== false)
    .map((requirement) => field(requirement as UnknownRecord, ["type", "role"]));
  if (needed.length === 0 || needed.some((type) => !type)) return false;
  const available = grantedRecords.map((entry) => field(entry, ["type", "role", "approval_type"]));
  return needed.every((type) => {
    const index = available.indexOf(type);
    if (index < 0) return false;
    available.splice(index, 1);
    return true;
  });
}

export type ValidationOutcome = "not_recorded" | "none_recorded" | "failed" | "passed" | "inconclusive";

// The outcome of the explicit source results only; tool calls never decide it.
export function validationOutcome(evidence: CodingValidationEvidence): ValidationOutcome {
  const { recorded, passed, failed, unrecognized } = evidence.results;
  if (recorded === null) return "not_recorded";
  if ((failed ?? 0) > 0) return "failed";
  // An unreadable entry may be a failure: it keeps the outcome open instead of improving it.
  if ((unrecognized ?? 0) > 0) return "inconclusive";
  if (recorded === 0) return "none_recorded";
  if (passed !== null && passed === recorded) return "passed";
  return "inconclusive";
}

export function validationAllPassed(evidence: CodingValidationEvidence): boolean {
  return validationOutcome(evidence) === "passed";
}

const plural = (count: number, word: string) => `${count} ${word}${count === 1 ? "" : "s"}`;

// One line about the recorded validation results (plus planned checks as intent).
export function validationLabel(evidence: CodingValidationEvidence): string {
  const unreadableCount = evidence.results.unrecognized ?? 0;
  const unreadable = unreadableCount ? ` · ${unreadableCount} unreadable ${unreadableCount === 1 ? "entry" : "entries"}` : "";
  const planned = `${unreadable}${evidence.planned > 0 ? ` · ${plural(evidence.planned, "check")} planned` : ""}`;
  const recorded = evidence.results.recorded ?? 0;
  switch (validationOutcome(evidence)) {
    case "not_recorded":
      return `No validation results recorded${planned}`;
    case "none_recorded":
      return `0 validation results recorded${planned}`;
    case "failed":
      return `${evidence.results.failed} failed of ${plural(recorded, "recorded result")}${planned}`;
    case "passed":
      return `${plural(recorded, "recorded result")}, all passed${planned}`;
    default: {
      const passed = evidence.results.passed ?? 0;
      const failed = evidence.results.failed ?? 0;
      const open = Math.max(recorded - passed - failed, 0);
      return `${plural(recorded, "recorded result")} (${passed} passed, ${failed} failed, ${open} without an outcome)${planned}`;
    }
  }
}

// Validation-type agent tool calls, labelled as calls: they are not test results.
export function validationToolCallLabel(evidence: CodingValidationEvidence): string | null {
  const { recorded, failed } = evidence.toolCalls;
  if (recorded === null) return null;
  const failures = failed ? `, ${failed} failed` : "";
  return `${recorded} recorded tool call${recorded === 1 ? "" : "s"} related to validation${failures}`;
}

export function validationStatusWord(evidence: CodingValidationEvidence): string {
  const outcome = validationOutcome(evidence);
  if (outcome === "not_recorded") return evidence.planned > 0 ? "planned only" : "not recorded";
  if (outcome === "none_recorded") return "none recorded";
  if (outcome === "failed") return "failed";
  if (outcome === "passed") return "passed";
  return "no outcome";
}

export function validationTone(evidence: CodingValidationEvidence): "active" | "danger" | "attention" | "neutral" {
  const outcome = validationOutcome(evidence);
  if (outcome === "failed") return "danger";
  if (outcome === "passed") return "active";
  if (outcome === "inconclusive") return "attention";
  return "neutral";
}

export function approvalLabel(evidence: CodingApprovalEvidence): string {
  const required = `${evidence.required} required`;
  if (evidence.recorded === null) return `${required} · no approval records`;
  const granted = evidence.granted ?? 0;
  const rejected = evidence.rejected ?? 0;
  const open = Math.max(evidence.recorded - granted - rejected, 0);
  const unreadable = evidence.unrecognized ? `, ${evidence.unrecognized} unreadable` : "";
  return `${required} · ${granted} granted, ${rejected} rejected, ${open} without a decision${unreadable}`;
}

// `note` describes an unchecked stage that has related activity, for the accessible label.
export type CodingProcessStage = { key: string; label: string; complete: boolean; note?: string };

// The Coding step indicator. A stage is checked only by matching recorded evidence: a plan record
// for Plan, planned scope for Scope, a prepared workspace for Branch, a linked PR for Change, all
// recorded source results passed for Validate, a granted approval record for Review, and the source
// state `completed` for Done. Review is checked only when every required approval type has its own
// granted record and nothing is rejected, undecided or unreadable; other approval records are shown
// as activity, not as a completed review. The derived phase (which maps Jira Done and cancelled to "completed")
// and planned branches, files or checks never check a stage.
export function codingProcessStages(
  session: Pick<CodingSessionSummary, "state" | "latestPlanStatus" | "repositories" | "pullRequests" | "approvals">,
  recorded: { validation: CodingValidationEvidence; preparedWorkspaces: number },
): CodingProcessStage[] {
  return [
    { key: "ready_to_plan", label: "Plan", complete: Boolean(session.latestPlanStatus) },
    { key: "planning", label: "Scope", complete: session.repositories.length > 0 },
    { key: "ready_to_implement", label: "Branch", complete: recorded.preparedWorkspaces > 0 },
    { key: "implementing", label: "Change", complete: session.pullRequests.length > 0 },
    { key: "validating", label: "Validate", complete: validationAllPassed(recorded.validation) },
    {
      key: "reviewing",
      label: "Review",
      complete: session.approvals.requirementsMet,
      note: !session.approvals.requirementsMet && (session.approvals.recorded ?? 0) + (session.approvals.unrecognized ?? 0) > 0
        ? "approval records present, not verified"
        : undefined,
    },
    { key: "completed", label: "Done", complete: session.state === "completed" },
  ];
}
