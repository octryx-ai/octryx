import { RunPayload } from "./RunPayload";
import { SpecStudioLink } from "../specStudio/SpecStudioLink";
import { allowedByDefaultCountText } from "./allowedByDefaultModel";
import { DecisionCard } from "./DecisionCard";
import { CARD_ACTION_KEYS, decisionCard, isStopLike } from "./decisionCardModel";
import { PublishProveStatus } from "./PublishProveStatus";
import { PipelineAudit } from "./PipelineAudit";
import { RunActionControls } from "./RunActionControls";
import { runtimeTargetReason } from "./runtimeTargetModel";
import { runActionsInOrder, runCounterTexts, runDetailTexts, runNextAction, runSteps } from "./runCardModel";
import { runEventsPath, runHistory, type RunDecision, type RunEvent } from "./runHistoryModel";
import { approvalDetailHref } from "../approval/approvalDetailModel";
import { RunHistory } from "./RunHistory";
import { RunTokens } from "./RunTokens";
import { RemedyWorkspaceContext } from "../devices/RemedyAction";
import { ParallelWorkBoard } from "./ParallelWorkBoard";
import { useRunResource } from "./useRunResource";
import { TranscriptLink } from "../transcripts/TranscriptButton";
import { LINK_ACCOUNT_HREF } from "../profile/linkedAccountsModel";
import { documentationView, followUpFailure, INSTALL_LAUNCHER_HREF, reviewerNoticeView, runGateText, runPositionText, runStopText, runUsageText } from "./workflowRunModel";
import { payloadView } from "./workflowRunPayloadView";
import { type RunAction, type RunActionValue, type WorkflowRun } from "./workflowRunTypes";

type RunDetailsProps = {
  run: WorkflowRun;
  id: string;
  objectName: string;
  inputs: Record<string, number | string>;
  setInput: (key: string, value: number | string) => void;
  valueOf: (action: RunAction) => RunActionValue;
  busy: boolean;
  onChoose: (action: RunAction, value?: RunActionValue) => void;
};
type RunStepItem = ReturnType<typeof runSteps>[number];

function RunSteps({ steps }: { steps: RunStepItem[] }) {
  return (
    <ol className="workflow-run-steps" aria-label="Phases" data-testid="workflow-run-steps">
      {steps.map((step) => (
        <li
          key={step.id}
          className={`workflow-run-steps__step workflow-run-steps__step--${step.state}`}
          aria-current={step.state === "active" || step.state === "problem" ? "step" : undefined}
        >
          <span className="workflow-run-steps__dot" aria-hidden="true" />
          {step.title}
        </li>
      ))}
    </ol>
  );
}

function RunFacts({ run, position, runtimeReason, usage, allowedByDefault, waitingApproval }: {
  run: WorkflowRun;
  position: string;
  runtimeReason: string | null;
  usage: string | null;
  allowedByDefault: string | null;
  waitingApproval: string;
}) {
  return (
    <div className="run-bar__facts">
      {position ? <span>{position}</span> : null}
      {runCounterTexts(run).map((text) => (
        <span key={text}>{text}</span>
      ))}
      {run.branch ? <span className="run-bar__branch" title={run.branch}>Branch {run.branch}</span> : null}
      {runtimeReason ? <span data-testid="workflow-run-runtime-reason">{runtimeReason}</span> : null}
      {usage ? <span data-testid="workflow-run-usage">{usage}</span> : null}
      {allowedByDefault ? <span data-testid="workflow-run-allowed-by-default">{allowedByDefault}</span> : null}
      <TranscriptLink projectId={run.project_id} filter={{ workflowRunId: run.id }} testId="workflow-run-transcript" />
      {waitingApproval ? (
        <a className="ds-link-button run-bar__approval" href={approvalDetailHref(waitingApproval)} data-testid="workflow-run-waiting-approval">
          Waiting approval ›
        </a>
      ) : null}
    </div>
  );
}

// The notices that follow the question: a failed follow-up, the reviewer, the documentation and the failure.
function RunNotices({ run }: { run: WorkflowRun }) {
  const reviewerNotice = reviewerNoticeView(run);
  const followUp = followUpFailure(run);
  const documentation = documentationView(run);
  return (
    <>
    {followUp ? (
      <p className="run-bar__text" role="alert" data-testid="workflow-run-follow-up-failed">
        {followUp.text}
        {followUp.needsDevice ? (
          <>
            {" "}
            <a href={INSTALL_LAUNCHER_HREF} data-testid="workflow-run-install-launcher">Pair Claude Code with the launcher</a>
          </>
        ) : null}
      </p>
    ) : null}
    {reviewerNotice ? (
      <p className="run-bar__text" role="note" data-testid="workflow-run-reviewer-notice">
        {reviewerNotice.text}
        {reviewerNotice.url ? (
          <>
            {" "}
            <a href={reviewerNotice.url} target="_blank" rel="noreferrer">Open the pull request</a>
          </>
        ) : null}
        {reviewerNotice.linkAccount ? (
          <>
            {" "}
            <a href={LINK_ACCOUNT_HREF} data-testid="workflow-run-link-account">Link your account</a>
          </>
        ) : null}
      </p>
    ) : null}
    {documentation ? (
      <p className="run-bar__text" data-testid="workflow-run-documentation">
        {documentation.url ? (
          <a href={documentation.url} target="_blank" rel="noreferrer">{documentation.title}</a>
        ) : documentation.title}
        {documentation.version ? ` · version ${documentation.version}` : ""}
        {documentation.inKnowledge ? " · in Knowledge" : ""}
      </p>
    ) : null}
    {run.failure ? (
      <div className="workflow-run-banner__payload">
        <div className="run-bar__title">This did not work yet</div>
        {run.failure.findings ? <pre className="workflow-run-banner__text">{run.failure.findings}</pre> : null}
        {run.failure.follow_up_issue ? <p className="run-bar__text">Follow-up issue {run.failure.follow_up_issue}</p> : null}
      </div>
    ) : null}
    </>
  );
}

function RunDetailsList({ run }: { run: WorkflowRun }) {
  return (
    <details className="workflow-run-banner__details" data-testid="workflow-run-details">
      <summary>Details</summary>
      <ul className="workflow-run-banner__details-list">
        {runDetailTexts(run).map((text) => (
          <li key={text}>{text}</li>
        ))}
      </ul>
    </details>
  );
}

// With a decision card, its own actions live on the card and stop-like ones read as dangerous.
function otherActionsOf(run: WorkflowRun, card: ReturnType<typeof decisionCard>) {
  return card
    ? runActionsInOrder(run)
      .filter((action) => !CARD_ACTION_KEYS.includes(action.key))
      .map((action) => (isStopLike(action) ? { ...action, tone: "danger" } : action))
    : runActionsInOrder(run);
}

// Everything the run bar folds away (product inventory): the phases as steps, what the person needs to
// act (question, checks, payload), counters once used, the actions, and the provenance with the run ids.
export function RunDetails({ run, id, objectName, inputs, setInput, valueOf, busy, onChoose }: RunDetailsProps) {
  const steps = runSteps(run);
  const onStep = steps.some((step) => step.state === "active" || step.state === "problem");
  const position = onStep ? "" : runPositionText(run);
  const gate = runGateText(run);
  const runtimeReason = runtimeTargetReason(run.runtime_target);
  const usage = runUsageText(run.model_usage);
  // A product owner's decision (readiness, review) has its own card; its confirm and change live there.
  const card = decisionCard(run.waiting);
  const resource = useRunResource<{ events: RunEvent[]; decisions?: RunDecision[] }>(runEventsPath(run.id), run.updated_at);
  const events = resource?.events ?? null;
  const history = runHistory(events, run.nodes, undefined, resource?.decisions, run.project_id ?? null);
  const allowedByDefault = allowedByDefaultCountText(events);
  const waitingApproval = typeof run.waiting?.approval_id === "string" ? run.waiting.approval_id : "";
  const otherActions = otherActionsOf(run, card);
  return (
    <div className="run-bar__details" id={id} data-testid="workflow-run-bar-details">
      <div className="run-bar__title">{run.work_item ? `${run.work_item.key} ${run.work_item.title}` : run.title}</div>
      {steps.length ? <RunSteps steps={steps} /> : null}
      <ParallelWorkBoard work={run.work} nodes={run.nodes} currentNode={run.current_node} />
      <RunFacts run={run} position={position} runtimeReason={runtimeReason} usage={usage}
        allowedByDefault={allowedByDefault} waitingApproval={waitingApproval} />
      {gate && !card ? <p className="run-bar__text">{gate}</p> : null}
      {run.pause ? <p className="run-bar__text">{run.pause.detail}</p> : null}
      {run.waiting?.question && !card ? <p className="run-bar__text">{run.waiting.question}</p> : null}
      <RunNotices run={run} />
      <PipelineAudit pipeline={run.pipeline} />
      <PublishProveStatus value={run.publish_prove} />
      <SpecStudioLink runId={run.id} summary={run.spec_studio} className="ds-btn workflow-run-banner__studio" />
      {card ? (
        <DecisionCard run={run} card={card} events={events} busy={busy} onChoose={onChoose} />
      ) : (
        <RunPayload view={payloadView(run.waiting ?? null)} />
      )}
      {run.last_error ? <p className="run-bar__text">{run.last_error}</p> : null}
      {runStopText(run) ? (
        <p className="run-bar__text" data-testid="workflow-run-stop-reason">{runStopText(run)}</p>
      ) : null}
      <RunActionControls
        actions={otherActions}
        primary={card ? null : runNextAction(run)}
        inputs={inputs}
        setInput={setInput}
        valueOf={valueOf}
        busy={busy}
        onChoose={onChoose}
        objectName={objectName}
      />
      {/* A refused tool call's "Allow in this Workspace" applies to the run's Workspace. */}
      <RemedyWorkspaceContext.Provider value={run.project_id ?? null}>
        <RunHistory entries={history} openFindings={run.open_findings} />
      </RemedyWorkspaceContext.Provider>
      <RunTokens runId={run.id} refreshKey={run.updated_at} />
      <RunDetailsList run={run} />
    </div>
  );
}
