import type { WorkChangePlan } from "../work/workChangePlanTypes";
import { PLAN_STATUS } from "../work/planStatus";

// A plan's status describes the plan, never the item's execution: it never makes a session review ready, blocked or completed.

export function planNextAction(plan: WorkChangePlan | null): string | null {
  if (!plan) return null;
  const version = plan.version;
  switch (plan.status) {
    case PLAN_STATUS.draft:
      return `Review draft Work Plan v${version}`;
    case PLAN_STATUS.readyForReview:
      return `Review Work Plan v${version}`;
    case PLAN_STATUS.needsClarification:
      return Array.isArray(plan.open_questions) && plan.open_questions.length > 0
        ? `Answer the open questions on Work Plan v${version}`
        : `Create a new Work Plan version for the clarification on v${version}`;
    case PLAN_STATUS.rejected:
      return `Create a new Work Plan version (v${version} was rejected)`;
    case PLAN_STATUS.superseded:
      return "Create a new Work Plan version";
    default:
      return null;
  }
}
