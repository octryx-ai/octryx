import type { WorkChangePlan } from "../work/workChangePlanTypes";
import { PLAN_STATUS } from "../work/planStatus";

// Plan status versus delivery lifecycle. A Work Plan's status describes the plan, not the
// Work Item's execution: it never makes a session "review ready", "blocked", "cancelled" or
// "completed". Those come only from the source item, its committed state events and recorded
// execution evidence (runs, PRs). A plan that is not approved keeps the session in planning, and
// the next action names the actual step on that exact plan in Work.

// The next step for a plan that is not approved yet, or null when the plan status is unknown and
// the generic planning guidance applies. Answering requires recorded questions: without them a
// clarification request is resolved with a new plan version (as the Work plan view offers).
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
