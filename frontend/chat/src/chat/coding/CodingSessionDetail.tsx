import { useEffect, useState } from "react";

import type { CodingSessionDetailData, CodingSessionSummary, CodingSessionTab } from "./codingTypes";
import type { WorkChangePlan } from "../work/workChangePlanTypes";
import { hasFailedEvidence, latestByVersion, recordValue } from "./codingSessionValues";
import { CodingAuditPanel } from "./CodingAuditPanel";
import { CodingExecutionTrace } from "./CodingExecutionTrace";
import { CodingPipelineTracePanel } from "./CodingPipelineTracePanel";
import { RuntimeObservabilityDeepDive } from "./CodingRuntimeObservability";
import { CodingReviewWorkspace } from "./CodingReviewWorkspace";
import { CodingReviewsPanel } from "./CodingReviewsPanel";
import { CodingWorkspaceEvidence } from "./CodingWorkspaceEvidence";
import { CodingTestsEvidence } from "./CodingTestsEvidence";
import { CodingWorkActionPanel } from "./CodingWorkActionPanel";
import { codingWorkAction } from "./codingWorkActionModel";
import { codingApprovalEvidence, codingValidationEvidence } from "./codingEvidenceModel";
import { CodingSessionHeader } from "./CodingSessionHeader";
import { CodingStepSection } from "./CodingStepSection";
import { CodingPlanEvidence } from "./CodingPlanEvidence";
import { CodingExternalActivity } from "./CodingExternalActivity";
import { CodingProcessTrace, TaskChatSummary } from "./CodingProcessEvidence";
import { CodingSessionCockpit, CodingSessionFacts } from "./CodingSessionOverview";
import { ExternalLinkList } from "./codingDetailParts";
import { compactUrlLabel, workspaceRecords } from "./codingDetailValues";
import {
  codingNextAction,
  codingSessionSteps,
  SECTION_TAB,
  type CodingStep,
  sectionForTab,
  startBlockedReason,
  type CodingSectionKey,
} from "./codingSessionSteps";
import { LoadingState } from "../../layout/LoadingState";

type DetailProps = {
  session: CodingSessionSummary;
  detail: CodingSessionDetailData | null;
  loading: boolean;
  // Each tab id opens the step or section that holds its content.
  activeTab: CodingSessionTab;
  startingAgent: boolean;
  onTabChange: (tab: CodingSessionTab) => void;
  onStartAgent: () => void;
  onRestartAgent: () => void;
  // A recorded review decision invalidates the verdict; a failed or missing verdict can be re-read.
  onReviewRecorded?: () => void;
  onRetryReview?: () => void;
  // Loads the session's evidence again after it could not be read.
  onRetryDetail?: () => void;
};

// A Coding session read from top to bottom: Plan → Changes → Tests → Pull request → Review →
// Done, each step with its state, one line and its evidence when opened; the step the session stands at opens by
// itself. Rules and audit, then the counters, ids and model internals (Details) close the page.
export function CodingSessionDetail({ session, detail, loading, activeTab, startingAgent, onTabChange, onStartAgent,
  onRestartAgent, onReviewRecorded, onRetryReview, onRetryDetail }: DetailProps) {
  const latestPlan = latestByVersion(detail?.changePlans || []);
  const sourceFields = recordValue(session.workItem.source_fields);
  const requiresWorkAction = ["needs_replan", "needs_human_review", "blocked"].includes(session.state);
  const canStartAgent = latestPlan?.status === "approved" && session.state !== "completed" && !requiresWorkAction;
  // Planned checks/required approvals versus recorded results/approvals, with the runtime record.
  const validation = codingValidationEvidence(sourceFields, latestPlan, detail?.observability);
  const approvals = codingApprovalEvidence(sourceFields, latestPlan);
  // What Work needs before coding can continue, addressed to the exact plan.
  const workAction = codingWorkAction(session, detail, loading);
  const workspaces = workspaceRecords(detail);
  const preparedWorkspaces = workspaces.filter((workspace) => workspace.status === "prepared").length;
  const steps = codingSessionSteps({ session, detail, latestPlan, validation, preparedWorkspaces });
  const { open, toggle, openSection } = useOpenSections(activeTab, steps, session.id, onTabChange);
  const failed = hasFailedEvidence(session.workItem.source_fields) || session.state === "blocked";
  const evidence: EvidenceContext = { session, detail, latestPlan, sourceFields, validation, approvals, workspaces };

  return (
    <section className="coding-detail" aria-label="Coding Session detail">
      <CodingSessionHeader session={session} nextAction={codingNextAction(session, canStartAgent)} canStartAgent={canStartAgent}
        startReason={startBlockedReason(session, latestPlan)} startingAgent={startingAgent} onStartAgent={onStartAgent}
        onRestartAgent={onRestartAgent} onOpenSection={openSection} />
      <div className="coding-detail__body">
        {/* Inside the scrolling body: a long notice scrolls with the steps. */}
        <CodingWorkActionPanel action={workAction} />
        {loading ? <LoadingState label="session evidence" variant="page" rows={3} onRetry={onRetryDetail} /> : null}
        {!loading && !detail ? (
          <p className="coding-detail__unavailable" role="status">
            Session evidence not available.{" "}
            {onRetryDetail ? <button type="button" className="work-area__button" onClick={onRetryDetail}>Try again</button> : null}
          </p>
        ) : null}
        {!loading ? <CodingSessionCockpit session={session} onRetryReview={onRetryReview} /> : null}
        {!loading ? (
          <ol className="coding-steps" aria-label="Coding session steps">
            {steps.map((step) => (
              <li key={step.key}>
                <CodingStepSection sectionKey={step.key} title={step.title} state={step.state} summary={step.summary} at={step.at}
                  open={open.has(step.key)} onToggle={() => toggle(step.key)}>
                  <StepEvidence step={step} evidence={evidence} onTabChange={onTabChange} onReviewRecorded={onReviewRecorded} />
                </CodingStepSection>
              </li>
            ))}
          </ol>
        ) : null}
        {!loading ? <ClosingSections evidence={evidence} open={open} toggle={toggle} failed={failed} /> : null}
      </div>
    </section>
  );
}

type EvidenceContext = {
  session: CodingSessionSummary;
  detail: CodingSessionDetailData | null;
  latestPlan: WorkChangePlan | null;
  sourceFields: ReturnType<typeof recordValue>;
  validation: ReturnType<typeof codingValidationEvidence>;
  approvals: ReturnType<typeof codingApprovalEvidence>;
  workspaces: ReturnType<typeof workspaceRecords>;
};

// Which sections are open: the step the session stands at, plus every one the person or a tab request opened.
function useOpenSections(activeTab: CodingSessionTab, steps: CodingStep[], sessionId: string,
  onTabChange: (tab: CodingSessionTab) => void) {
  const [open, setOpen] = useState<Set<CodingSectionKey>>(() => new Set([sectionForTab(activeTab, steps)]));
  const opened = sectionForTab(activeTab, steps);
  // Another session starts with its own current step; a tab request (Open Reviews, a blocked start) adds its section.
  useEffect(() => setOpen(new Set([opened])), [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => setOpen((current) => (current.has(opened) ? current : new Set([...current, opened]))), [opened]);
  const openSection = (key: CodingSectionKey) => {
    setOpen((current) => new Set([...current, key]));
    onTabChange(SECTION_TAB[key]);
  };
  const toggle = (key: CodingSectionKey) => {
    if (open.has(key)) setOpen((current) => new Set([...current].filter((entry) => entry !== key)));
    else openSection(key);
  };
  return { open, toggle, openSection };
}

function StepEvidence({ step, evidence, onTabChange, onReviewRecorded }: {
  step: CodingStep;
  evidence: EvidenceContext;
  onTabChange: (tab: CodingSessionTab) => void;
  onReviewRecorded?: () => void;
}) {
  const { session, detail, latestPlan, sourceFields, validation, approvals, workspaces } = evidence;
  if (step.key === "plan") {
    return <CodingPlanEvidence latestPlan={latestPlan} session={session} validation={validation} approvals={approvals} />;
  }
  if (step.key === "changes") {
    return (
      <div className="coding-detail__stack">
        <CodingExecutionTrace session={session} detail={detail} latestPlan={latestPlan} />
        {session.latestAgentSession ? <TaskChatSummary session={session} /> : null}
        <CodingWorkspaceEvidence workspaces={workspaces} compact />
        <CodingReviewWorkspace session={session} detail={detail} latestPlan={latestPlan}
          onOpenReviews={() => onTabChange("reviews")} />
      </div>
    );
  }
  if (step.key === "tests") {
    return (
      <div className="coding-detail__stack">
        <CodingTestsEvidence sourceFields={sourceFields} latestPlan={latestPlan}
          observability={detail?.observability || null} validation={validation} />
        <CodingPipelineTracePanel
          traces={detail?.cicdPipelineTraces?.items || []}
          agentFailureContext={detail?.cicdPipelineTraces?.agent_failure_context || null}
        />
      </div>
    );
  }
  if (step.key === "pullRequest") {
    return <ExternalLinkList links={session.pullRequests.map((url) => ({ label: compactUrlLabel(url), href: url }))}
      emptyText="A pull request appears here once the session opens one." />;
  }
  if (step.key === "review") {
    return <CodingReviewsPanel workItemId={session.id} latestPlan={latestPlan} changeUnits={detail?.changeUnits || []}
      reviewerPayload={detail?.reviewerPayload || null} fallbackRecommendations={latestPlan?.reviewer_recommendations || []}
      onRecorded={onReviewRecorded ? () => onReviewRecorded() : undefined} />;
  }
  return step.key === "done" ? <p className="work-detail__empty">{step.summary}</p> : null;
}

function ClosingSections({ evidence, open, toggle, failed }: {
  evidence: EvidenceContext;
  open: Set<CodingSectionKey>;
  toggle: (key: CodingSectionKey) => void;
  failed: boolean;
}) {
  const { session, detail, latestPlan, sourceFields } = evidence;
  return (
    <div className="coding-steps__closing">
      <CodingStepSection sectionKey="rules" title="Rules and audit" summary="What the agent may do here, and what it did."
        open={open.has("rules")} onToggle={() => toggle("rules")}>
        <div className="coding-detail__stack">
          <RuntimeObservabilityDeepDive observability={detail?.observability || null} />
          <CodingAuditPanel session={session} report={detail?.auditReport || null} fallbackBlocked={failed} />
        </div>
      </CodingStepSection>
      <CodingStepSection sectionKey="details" title="Details" summary="Counters, ids, the pipeline trace and external activity."
        open={open.has("details")} onToggle={() => toggle("details")}>
        <div className="coding-detail__stack">
          <CodingSessionFacts session={session} sourceFields={sourceFields} detail={detail} latestPlan={latestPlan} />
          <CodingProcessTrace detail={detail} />
          <CodingExternalActivity sourceFields={sourceFields} session={session} detail={detail} />
          <p className="coding-detail__ids">Work item id: {session.id}</p>
        </div>
      </CodingStepSection>
    </div>
  );
}
