import type { CodingApprovalEvidence, CodingSessionSummary, CodingValidationEvidence } from "./codingTypes";
import { latestByVersion } from "./codingSessionValues";
import { approvalLabel, plannedCheckCount, validationLabel } from "./codingEvidenceModel";
import { EvidenceList, KeyValue } from "./codingDetailParts";

// The Plan step's evidence: the latest plan's facts, planned and recorded side by side.
export function CodingPlanEvidence({
  latestPlan,
  session,
  validation,
  approvals,
}: {
  latestPlan: ReturnType<typeof latestByVersion>;
  session: CodingSessionSummary;
  validation: CodingValidationEvidence;
  approvals: CodingApprovalEvidence;
}) {
  if (!latestPlan) {
    return (
      <div className="work-empty">
        <div className="work-empty__eyebrow">No plan</div>
        <h2>No Change Plan is attached to this Coding Session.</h2>
        <p>Open the Work Item to generate or approve a governed Change Plan first.</p>
      </div>
    );
  }
  return (
    <div className="coding-detail__stack">
      <div className="coding-detail__grid">
        <KeyValue label="Plan" value={`${latestPlan.title} (v${latestPlan.version})`} />
        <KeyValue label="Status" value={latestPlan.status} />
        <KeyValue label="Repositories" value={session.repositories.join(", ") || "Not planned"} />
        <KeyValue label="Planned checks" value={String(plannedCheckCount(latestPlan))} />
        <KeyValue label="Recorded validation" value={validationLabel(validation)} />
        <KeyValue label="Approvals" value={approvalLabel(approvals)} />
      </div>
      <EvidenceList title="Understood request" values={[latestPlan.understood_request]} />
      <EvidenceList
        title="Repository scope"
        values={latestPlan.affected_repositories}
        emptyText="No repository scope captured."
      />
      <EvidenceList
        title="Proposed branches"
        values={latestPlan.proposed_branches}
        emptyText="No branch plan captured."
      />
      <EvidenceList
        title="Planned files"
        values={latestPlan.planned_files}
        emptyText="No planned files captured."
      />
      <EvidenceList
        title="Validation plan"
        values={latestPlan.validation_plan}
        emptyText="No validation commands captured."
      />
      <EvidenceList title="Assumptions" values={latestPlan.assumptions} />
      <EvidenceList title="Open questions" values={latestPlan.open_questions} emptyText="No open questions." />
      <EvidenceList title="Security risks" values={latestPlan.security_risks} emptyText="No security risks captured." />
      <EvidenceList
        title="Required approvals"
        values={latestPlan.required_approvals}
        emptyText="This plan lists no required approvals."
      />
      <EvidenceList title="Rollback" values={[latestPlan.rollback_plan || "Not captured"]} />
    </div>
  );
}
