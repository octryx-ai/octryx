// Workflow checks section of `turn_execution_summary.v1`: typed parse and pure presentation.
//
// Backend `services/workflow_checks/results.py` owns the closed record of a turn whose selected
// workflow declares checks: `passed` (no blocking check failed), `reminded` (an intermediate reply
// that got the one repair reminder) and `not_verified` (a blocking check still failed after the
// reminder; the answer was delivered, marked as not verified). An unknown value renders nothing.

export const TURN_WORKFLOW_CHECK_STATES = ["passed", "reminded", "not_verified"] as const;

export type TurnWorkflowCheckState = (typeof TURN_WORKFLOW_CHECK_STATES)[number];

export type TurnWorkflowCheck = { type: string; outcome: string; blocking: boolean; description: string };

export type TurnWorkflowChecks = {
  workflowKey: string;
  state: TurnWorkflowCheckState;
  checks: TurnWorkflowCheck[];
};

export function parseTurnWorkflowChecks(value: unknown): TurnWorkflowChecks | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  if (!TURN_WORKFLOW_CHECK_STATES.includes(record.state as TurnWorkflowCheckState)) return null;
  const results = Array.isArray(record.results) ? record.results : [];
  return {
    workflowKey: typeof record.workflow_key === "string" ? record.workflow_key : "",
    state: record.state as TurnWorkflowCheckState,
    checks: results.slice(0, 20).flatMap((item) => {
      if (!item || typeof item !== "object") return [];
      const check = item as Record<string, unknown>;
      return [{
        type: String(check.type ?? ""),
        outcome: String(check.outcome ?? ""),
        blocking: check.blocking === true,
        description: String(check.description ?? ""),
      }];
    }),
  };
}

export function presentWorkflowChecks(
  checks: TurnWorkflowChecks | null,
): { tone: "success" | "attention"; label: string; description: string } | null {
  if (!checks || checks.state === "reminded") return null;
  const failed = checks.checks.filter((check) => check.blocking && check.outcome === "failed");
  if (checks.state === "passed") {
    return { tone: "success", label: "passed", description: `Every blocking check of ${checks.workflowKey} passed.` };
  }
  return {
    tone: "attention",
    label: "not verified",
    description: `Failed after one repair: ${failed.map((check) => check.description || check.type).join("; ")}`,
  };
}
