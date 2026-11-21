// Builds the coding session summary for a work item.
import type {
  CodingAgentChatSession,
  CodingReviewSummary,
  CodingSessionSummary,
} from "./codingTypes";
import type { WorkChangePlan } from "../work/workChangePlanTypes";
import type { WorkChangeUnit } from "../work/workPullRequestTypes";
import type { WorkItem } from "../work/workItemTypes";
import type { WorkStateEvent } from "../work/workSyncWorkflowTypes";
import { codingApprovalEvidence, codingValidationEvidence, recordCount } from "./codingEvidenceModel";
import { unavailableReview } from "./codingReviewSummary";
import {
  codingBlockerCount,
  codingRecordedEvidenceCount,
  deriveCodingState,
  hasCodingIntent,
  labelForState,
  nextActionForSession,
  phaseForState,
  sessionOutcome,
  toneForState,
} from "./codingSessionState";
import {
  extractNamedValues,
  latestAgentSessions,
  latestByVersion,
  latestStateEvent,
  listLength,
  recordValue,
  uniqueStrings,
} from "./codingSessionValues";

export function buildCodingSessionSummary({
  item,
  changePlans = [],
  changeUnits = [],
  stateEvents = [],
  agentSessions = [],
  pullRequestUrls = [],
  review = unavailableReview("not_loaded"),
}: {
  item: WorkItem;
  changePlans?: WorkChangePlan[];
  changeUnits?: WorkChangeUnit[];
  stateEvents?: WorkStateEvent[];
  agentSessions?: CodingAgentChatSession[];
  // The item's pull requests from Work → Pull requests (work_pull_requests, D12: the one PR source).
  pullRequestUrls?: string[];
  // The backend reviewer verdict, already bound to the latest plan (codingReviewSummary.ts).
  review?: CodingReviewSummary;
}): CodingSessionSummary {
  const latestPlan = latestByVersion(changePlans);
  const sourceFields = recordValue(item.source_fields);
  const repositories = uniqueStrings([
    ...extractNamedValues(sourceFields?.affected_repositories),
    ...extractNamedValues(latestPlan?.affected_repositories, ["repository_name", "repository", "name"]),
    ...changeUnits.map((unit) => unit.repository_name),
  ]);
  const branches = uniqueStrings([
    ...extractNamedValues(sourceFields?.planned_branches),
    ...extractNamedValues(latestPlan?.proposed_branches, ["branch_name", "branch", "name"]),
    ...changeUnits.map((unit) => unit.branch_name),
  ]);
  // Recorded pull requests only (work_pull_requests); a plan's `expected_prs` is intent, never an open PR.
  const pullRequests = uniqueStrings(pullRequestUrls);
  // Planned files are listed entries; an object's keys are not files.
  const plannedFileCount = listLength(sourceFields?.planned_files) + listLength(latestPlan?.planned_files);
  // Planned checks and required approvals stay separate from recorded results and approvals.
  const validation = codingValidationEvidence(sourceFields, latestPlan);
  const approvals = codingApprovalEvidence(sourceFields, latestPlan);
  const latestState = latestStateEvent(stateEvents);
  const sortedAgentSessions = latestAgentSessions(agentSessions);
  const latestAgentSession = sortedAgentSessions[0] || null;
  const state = deriveCodingState({ item, latestPlan, pullRequests, sourceFields, latestState, review });
  const phase = phaseForState(state, latestPlan);
  const recordedEvidenceCount = codingRecordedEvidenceCount({ sourceFields, pullRequests, validation, approvals, stateEvents });
  // A current negative work review is one blocker; a missing or incomplete review is not.
  const blockerCount = codingBlockerCount({ item, latestPlan, sourceFields, stateEvents }) + (review.status === "block" ? 1 : 0);
  const isCodingRelevant = hasCodingIntent({
    item,
    sourceFields,
    latestPlan,
    repositories,
    branches,
    pullRequests,
    // Planning still makes an item relevant to Coding; it is just not shown as evidence.
    signalCount: recordedEvidenceCount + plannedFileCount + validation.planned + approvals.required,
    agentSessions: sortedAgentSessions,
  });

  return {
    id: item.id,
    sourceKey: item.source_key,
    title: item.title,
    state,
    tone: toneForState(state),
    statusLabel: labelForState(state),
    workItem: item,
    phase,
    // An ended session has no next step: its card and detail say what happened.
    nextAction: state === "completed" || state === "cancelled"
      ? sessionOutcome({ state, latestPlan, changeUnits, agentSessions: sortedAgentSessions, pullRequests })
      : state === "changes_requested" && review.status === "block"
        ? `Address the work review decision on plan v${review.planVersion}`
        : nextActionForSession({ phase, latestPlan, repositories, branches, pullRequests, blockerCount }),
    blockerCount,
    recordedEvidenceCount,
    isCodingRelevant,
    repositories,
    branches,
    pullRequests,
    plannedFileCount,
    validation,
    approvals,
    auditCount: recordCount(sourceFields?.audit_timeline) + stateEvents.length,
    agentSessions: sortedAgentSessions,
    latestAgentSession,
    latestPlanStatus: latestPlan?.status || null,
    review,
    updatedAt:
      latestAgentSession?.started_at ||
      latestState?.created_at ||
      item.updated_at ||
      item.last_source_updated_at ||
      item.synced_at ||
      null,
  };
}
