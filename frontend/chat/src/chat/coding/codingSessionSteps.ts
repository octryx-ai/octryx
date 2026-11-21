import type { CodingSessionDetailData, CodingSessionSummary, CodingSessionTab, CodingValidationEvidence } from "./codingTypes";
import type { WorkChangePlan } from "../work/workChangePlanTypes";
import { PLAN_STATUS, planStatusLabel } from "../work/planStatus";
import { validationLabel, validationOutcome } from "./codingEvidenceModel";
import { reviewSummaryLabel } from "./codingReviewSummary";
import { WORK_ACTION_STATES } from "./codingWorkActionModel";

// The Coding session as steps: one list read from top to bottom instead of nine tabs. Every
// step state is mapped from recorded evidence the session already carries: a plan record, change units and a
// prepared workspace, recorded validation results, linked pull requests, approval records and the source state. A
// plan's intent never completes a step. Pure functions only, so the unit tests read them directly.

export type CodingStepKey = "plan" | "changes" | "tests" | "pullRequest" | "review" | "done";
export type CodingSectionKey = CodingStepKey | "rules" | "details";
// "stopped": a step that was under way when the session ended (completed or cancelled); it will not go on.
export type CodingStepState = "done" | "active" | "problem" | "pending" | "stopped";
export type CodingStep = { key: CodingStepKey; title: string; state: CodingStepState; summary: string; at: string | null };

export const STEP_STATE_LABEL: Record<CodingStepState, string> = {
  done: "Done",
  active: "In progress",
  problem: "Needs attention",
  pending: "Not started",
  stopped: "Not finished",
};

// A session that ended: its steps say what happened, never what is still to do.
const ENDED_STATES = new Set(["completed", "cancelled"]);

type StepInput = {
  session: CodingSessionSummary;
  detail: CodingSessionDetailData | null;
  latestPlan: WorkChangePlan | null;
  validation: CodingValidationEvidence;
  preparedWorkspaces: number;
};

const RUNNING_STATES = new Set(["approved", "implementing", "testing"]);
const REVIEW_STATES = new Set(["review_ready", "pr_open", "changes_requested"]);

function planStep({ session, latestPlan }: StepInput): CodingStep {
  const at = latestPlan?.approved_at || latestPlan?.updated_at || latestPlan?.created_at || null;
  if (!latestPlan) {
    const planning = session.phase === "ready_to_plan" || session.phase === "planning";
    return { key: "plan", title: "Plan", state: planning ? "active" : "pending", summary: "No plan yet.", at: null };
  }
  const files = latestPlan.planned_files.length;
  const status = latestPlan.status;
  const summary = `Plan v${latestPlan.version} · ${planStatusLabel(status)}${files ? ` · ${files} file${files === 1 ? "" : "s"} planned` : ""}`;
  if (status === PLAN_STATUS.approved) return { key: "plan", title: "Plan", state: "done", summary, at };
  if (status === PLAN_STATUS.rejected || status === PLAN_STATUS.needsClarification || session.state === "needs_replan") {
    return { key: "plan", title: "Plan", state: "problem", summary, at };
  }
  return { key: "plan", title: "Plan", state: "active", summary, at };
}

function changesStep({ session, detail, preparedWorkspaces }: StepInput): CodingStep {
  const units = detail?.changeUnits || [];
  const repositories = [...new Set(units.map((unit) => unit.repository_name).filter(Boolean))];
  const agent = session.latestAgentSession;
  const parts = [
    units.length ? `${units.length} change unit${units.length === 1 ? "" : "s"} in ${repositories.join(", ") || "no repository"}` : "",
    preparedWorkspaces ? "workspace prepared" : "",
    agent ? `agent ${agent.run_status || agent.status || "started"}` : "",
  ].filter(Boolean);
  const summary = parts.length ? `${parts.join(" · ")}.` : "No change yet.";
  const at = agent?.started_at || null;
  // Done only with something to show for it: recorded change units, or a linked pull request that holds
  // them; never "Done · No change yet."
  const prs = session.pullRequests.length;
  if (prs > 0) {
    const delivered = parts.length ? summary : `Changes are in the linked pull request${prs === 1 ? "" : "s"}.`;
    return { key: "changes", title: "Changes", state: "done", summary: delivered, at };
  }
  if (session.state === "blocked" && session.phase === "implementing") return { key: "changes", title: "Changes", state: "problem", summary, at };
  const active = session.phase === "implementing" || session.phase === "ready_to_implement" || preparedWorkspaces > 0 || Boolean(agent);
  return { key: "changes", title: "Changes", state: active ? "active" : "pending", summary, at };
}

function testsStep({ session, validation }: StepInput): CodingStep {
  const summary = `${validationLabel(validation)}.`;
  const outcome = validationOutcome(validation);
  if (outcome === "passed") return { key: "tests", title: "Tests", state: "done", summary, at: null };
  if (outcome === "failed") return { key: "tests", title: "Tests", state: "problem", summary, at: null };
  const active = session.phase === "validating" || outcome === "inconclusive" || session.state === "testing";
  return { key: "tests", title: "Tests", state: active ? "active" : "pending", summary, at: null };
}

function pullRequestStep({ session }: StepInput): CodingStep {
  const count = session.pullRequests.length;
  if (!count) return { key: "pullRequest", title: "Pull request", state: "pending", summary: "No pull request yet.", at: null };
  const labels = session.pullRequests.map(pullRequestLabel).join(", ");
  return { key: "pullRequest", title: "Pull request", state: "done", summary: `${labels} opened.`, at: null };
}

function reviewStep({ session }: StepInput): CodingStep {
  const approvals = session.approvals;
  if (approvals.requirementsMet) {
    return { key: "review", title: "Review", state: "done", summary: "Every required approval is recorded.", at: null };
  }
  const summary = `${reviewSummaryLabel(session.review)}.`;
  if ((approvals.rejected ?? 0) > 0 || session.state === "changes_requested" || session.review.status === "block") {
    return { key: "review", title: "Review", state: "problem", summary, at: null };
  }
  const active = session.phase === "reviewing" || REVIEW_STATES.has(session.state);
  return { key: "review", title: "Review", state: active ? "active" : "pending", summary, at: null };
}

function doneStep({ session }: StepInput, nothingHappened = false): CodingStep {
  const at = session.updatedAt || null;
  if (session.state === "completed") {
    return { key: "done", title: "Done", state: "done", summary: nothingHappened ? "Completed. No change was made in this session." : "Completed.", at };
  }
  if (session.state === "cancelled") {
    return { key: "done", title: "Done", state: "problem", summary: nothingHappened ? "Cancelled before any change was made." : "Cancelled.", at };
  }
  return { key: "done", title: "Done", state: "pending", summary: "Closes after the merge.", at: null };
}

/**
 * The session's steps in reading order: Plan → Changes → Tests → Pull request → Review → Done. A session that ended
 * lists only the steps that happened, a step still under way is
 * "Not finished", and Done says when nothing was changed at all; it never shows "Not started" steps.
 */
export function codingSessionSteps(input: StepInput): CodingStep[] {
  const steps = [planStep(input), changesStep(input), testsStep(input), pullRequestStep(input), reviewStep(input)];
  if (!ENDED_STATES.has(input.session.state)) return [...steps, doneStep(input)];
  const happened = steps
    .filter((step) => step.state !== "pending")
    .map((step): CodingStep => (step.state === "pending" ? { ...step, state: "done" } : step.state === "active" ? { ...step, state: "stopped" } : step));
  return [...happened, doneStep(input, happened.length === 0)];
}

/** Whether a session ended (completed or cancelled): it shows its outcome, not a next action. */
export function sessionEnded(session: Pick<CodingSessionSummary, "state">): boolean {
  return ENDED_STATES.has(session.state);
}

/** The step the session stands at: the first one needing attention or in progress, else the first not started. */
export function currentStepKey(steps: CodingStep[]): CodingStepKey {
  return (
    steps.find((step) => step.state === "problem")?.key ??
    steps.find((step) => step.state === "active")?.key ??
    steps.find((step) => step.state === "pending")?.key ??
    "done"
  );
}

// Each tab id opens the step or section that holds its content.
const TAB_SECTION: Partial<Record<CodingSessionTab, CodingSectionKey>> = {
  plan: "plan",
  changes: "changes",
  tests: "tests",
  pullRequest: "pullRequest",
  reviews: "review",
  policy: "rules",
  process: "details",
  details: "details",
};

/** Which step or section a tab opens; "overview" opens the step the session stands at. */
export function sectionForTab(tab: CodingSessionTab, steps: CodingStep[]): CodingSectionKey {
  return TAB_SECTION[tab] ?? currentStepKey(steps);
}

export const SECTION_TAB: Record<CodingSectionKey, CodingSessionTab> = {
  plan: "plan",
  changes: "changes",
  tests: "tests",
  pullRequest: "pullRequest",
  review: "reviews",
  done: "overview",
  rules: "policy",
  details: "details",
};

export type CodingNextAction =
  | { kind: "start" }
  | { kind: "link"; label: string; href: string; external?: boolean }
  | { kind: "section"; label: string; section: CodingSectionKey }
  | null;

/**
 * The one primary action of the header. A session that needs a person in Work has none here: the Work action panel
 * right below names the exact place. Otherwise: start the agent once a plan is approved, follow the running
 * agent in its chat, open the pull request or the review while it waits for one.
 */
export function codingNextAction(session: CodingSessionSummary, canStartAgent: boolean): CodingNextAction {
  if (WORK_ACTION_STATES.has(session.state) || session.state === "completed" || session.state === "cancelled") return null;
  const agent = session.latestAgentSession;
  if (REVIEW_STATES.has(session.state)) {
    const pr = session.pullRequests[0];
    if (session.state === "pr_open" && pr && /^https?:\/\//i.test(pr)) {
      return { kind: "link", label: "Open pull request", href: pr, external: true };
    }
    return { kind: "section", label: "Open review", section: "review" };
  }
  if (agent && RUNNING_STATES.has(session.state)) return { kind: "link", label: "Open task chat", href: agent.chat_url };
  if (canStartAgent && !agent) return { kind: "start" };
  return null;
}

/** Why Start agent waits, shown beside the disabled button (a disabled action says why). */
export function startBlockedReason(session: CodingSessionSummary, latestPlan: WorkChangePlan | null): string {
  if (session.state === "completed") return "The session is complete.";
  if (WORK_ACTION_STATES.has(session.state)) return "Resolve the work action below first.";
  if (latestPlan?.status !== PLAN_STATUS.approved) return "Needs an approved plan.";
  return "";
}

export function pullRequestLabel(url: string): string {
  const match = url.match(/pull-requests?\/([^/?#]+)/i) || url.match(/\/pull\/([^/?#]+)/i);
  return match ? `PR ${match[1]}` : url;
}
