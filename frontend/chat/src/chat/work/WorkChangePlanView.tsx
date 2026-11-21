// The selected Change Plan: status row, version delta, its plan blocks, open questions and the reviewer decision.

import type { WorkChangePlan } from "./workChangePlanTypes";
import { Badge } from "./WorkAreaViews";
import { WorkPlanClarificationAnswers, type ClarificationAnswerResult } from "./WorkPlanClarificationAnswers";
import type { ClarificationAnswer } from "./workPlanClarificationModel";
import { CompactObjects, PlanBlock, StringList, VersionDelta } from "./WorkChangePlanBlocks";
import { planAuthorLabel, planTypeLabel, planUsageLabel } from "./workChangePlanLabels";

export function WorkChangePlanView({ selected, newest, previous, busyAction, canDecide, decisionText, setDecisionText,
  answerPlan, decide }: {
  selected: WorkChangePlan;
  newest: WorkChangePlan | null;
  previous: WorkChangePlan | null;
  busyAction: string | null;
  canDecide: boolean;
  decisionText: string;
  setDecisionText: (text: string) => void;
  answerPlan: (
    plan: WorkChangePlan,
    payload: { expected_latest_version: number; answers: ClarificationAnswer[] },
  ) => Promise<ClarificationAnswerResult>;
  decide: (action: "approve" | "reject" | "request_clarification") => Promise<void>;
}) {
  return (
    <>
      <div className="work-change-plan__status-row">
        <Badge value={selected.status} />
        <span>{planTypeLabel(selected)}</span>
        <span>{planAuthorLabel(selected)}</span>
        <span>{planUsageLabel(selected)}</span>
        <span>Jira sync: {selected.jira_sync_preview?.will_mutate_jira ? "will sync" : "preview only"}</span>
        {selected.supersedes_plan_id ? <span>Supersedes previous plan</span> : null}
      </div>

      {previous ? <VersionDelta current={selected} previous={previous} /> : null}

      <PlanBlock title="Understood request">
        <p>{selected.understood_request}</p>
      </PlanBlock>

      <PlanBlock title="Open questions">
        <WorkPlanClarificationAnswers plan={selected} newest={newest} busy={Boolean(busyAction)} onAnswer={answerPlan} />
      </PlanBlock>

      <PlanBlock title="Assumptions">
        <StringList values={selected.assumptions} emptyText="No assumptions captured." />
      </PlanBlock>

      <PlanBlock title="Repository and branch plan">
        <CompactObjects
          values={[
            ...selected.affected_repositories.map((entry) => ({ kind: "repository", ...entry })),
            ...selected.proposed_branches.map((entry) => ({ kind: "branch", ...entry })),
          ]}
          emptyText="No repository impact captured."
        />
      </PlanBlock>

      <PlanBlock title="Validation and risks">
        <CompactObjects
          values={[
            ...selected.validation_plan.map((entry) => ({ kind: "validation", ...entry })),
            ...selected.security_risks.map((entry) => ({ kind: "risk", ...entry })),
          ]}
          emptyText="No validation or risk items captured."
        />
      </PlanBlock>

      <PlanBlock title="Review and approval contract">
        <CompactObjects
          values={[
            ...selected.required_approvals.map((entry) => ({ kind: "approval", ...entry })),
            ...selected.reviewer_recommendations.slice(0, 3).map((entry) => ({
              kind: "recommended reviewer",
              display_name: entry.display_name,
              score: entry.score,
              available: entry.available,
            })),
          ]}
          emptyText="No reviewer or approval data captured."
        />
      </PlanBlock>

      <PlanBlock title="Rollback">
        <p>{selected.rollback_plan || "No rollback considerations captured."}</p>
      </PlanBlock>

      {selected.jira_sync_preview?.comment_body ? (
        <PlanBlock title="Jira approval comment">
          <pre>{selected.jira_sync_preview.comment_body}</pre>
        </PlanBlock>
      ) : null}

      {canDecide ? (
        <div className="work-change-plan__decision">
          <textarea
            value={decisionText}
            disabled={Boolean(busyAction)}
            onChange={(event) => setDecisionText(event.target.value)}
            placeholder={`Decision note for version ${selected.version}, rejection reason, or clarification request...`}
          />
          <div>
            <button
              type="button"
              className="work-area__button is-active"
              disabled={Boolean(busyAction)}
              onClick={() => void decide("approve")}
            >
              Approve v{selected.version}
            </button>
            <button
              type="button"
              className="work-area__button"
              disabled={Boolean(busyAction)}
              onClick={() => void decide("request_clarification")}
            >
              Clarify
            </button>
            <button
              type="button"
              className="work-area__button"
              disabled={Boolean(busyAction)}
              onClick={() => void decide("reject")}
            >
              Reject
            </button>
          </div>
        </div>
      ) : null}
    </>
  );
}
