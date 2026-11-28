import type { ChatMessage, SelectedSession } from "../chatThreadTypes";
import type { SessionPullRequest, ThreadCodeIntelligenceStats, ThreadUsageStats } from "../chatUsageTypes";
import { MenuIcon } from "./ChatShellIcons";
import { WorkspaceHeaderActions } from "./header/WorkspaceHeaderActions";
import { isCompactChatLayout } from "./responsive/chatLayoutBreakpoints";
import { useChatLayoutMode } from "./responsive/useChatLayoutMode";
import { buildRoutingSummary } from "./routingExplainability";
import { headerWorkspaceLabel, shortRuntimeLabel } from "./chatOnboarding";
import { useRunThreadTitle } from "./workflowRun/useRunThreadTitle";
import { useExecutionTarget } from "./devices/executionTarget";
import { readableModelName } from "./devices/modelNames";
import { thinkingLevelLabel } from "./composer/thinkingSwitch";
import { AuditMark } from "./composer/AuditMark";
import { roleHeaderText } from "./roles/myRoleModel";
import { useMyRole } from "./roles/useMyRole";
import { ThreadEngineBadge } from "./engines/ThreadEngineBadge";
import { useThreadTranscript } from "./transcripts/useThreadTranscript";
import { lastModelUsed, modelDisplayName, modelShortLabel, modelsUsed, runDetailsFacts, runStatusText } from "./header/runDetailsFacts";
import { useSessionPool } from "./header/useSessionPool";

type WorkspaceHeaderProps = {
  selectedSession: SelectedSession | null;
  // The thread's loaded messages: Run details names the model(s) its answers came from.
  messages?: ChatMessage[];
  selectedSessionProjectLabel: string;
  selectedSessionRuntimePillLabel: string;
  runtimePillLabel: string;
  activeWorkflowChipLabel: string;
  threadStatusLabel: string;
  statusLabel: string;
  modeLabel: string;
  thinkingLabel: string;
  agentName: string;
  sending: boolean;
  selectedSessionIsRunning: boolean;
  selectedSessionIsArchived?: boolean;
  taskErrorSummary: string;
  taskErrorOpen: boolean;
  setTaskErrorOpen: (value: boolean | ((value: boolean) => boolean)) => void;
  onContinue: () => void;
  chatTheme: "dark" | "light";
  setChatTheme: (
    value: "dark" | "light" | ((value: "dark" | "light") => "dark" | "light"),
  ) => void;
  statsOpen: boolean;
  setStatsOpen: (value: boolean | ((value: boolean) => boolean)) => void;
  stats: ThreadUsageStats | null;
  codeIntelligence: ThreadCodeIntelligenceStats | null;
  pullRequests: SessionPullRequest[];
  traceEventCount: number;
  onOpenTrace: () => void;
  onOpenSidebar: () => void;
  workspaceOpen: boolean;
  onToggleWorkspace: () => void;
};

type Session = SelectedSession | null;

function openSessionExport(selectedSession: Session, file: string) {
  if (!selectedSession) {
    return;
  }
  window.open(`/chat/api/sessions/${selectedSession.id}/${file}`, "_blank", "noopener,noreferrer");
}

function resumeLabelOf(selectedSession: Session) {
  const resumeState = String(selectedSession?.resumeState || "").trim().toLowerCase();
  return resumeState === "approval_approved"
    ? "Resuming after approval"
    : resumeState === "approval_rejected"
      ? "Resuming after rejection"
      : "";
}

function attentionChipsOf(selectedSession: Session) {
  return [
    ...(selectedSession?.taskStatus
      ? [{ key: "action", label: selectedSession.taskStatus, className: "workspace__signal-chip workspace__signal-chip--warning" }]
      : []),
    ...(selectedSession?.pendingApprovalCount
      ? [{
          key: "approvals",
          label: `${selectedSession.pendingApprovalCount} pending approvals`,
          className: "workspace__signal-chip workspace__signal-chip--pending",
        }]
      : []),
  ];
}

type RunStateInput = Pick<WorkspaceHeaderProps, "selectedSessionProjectLabel" | "activeWorkflowChipLabel" |
  "threadStatusLabel" | "statusLabel" | "thinkingLabel"> & { selectedSession: Session; messages: ChatMessage[]; runtimeValue: string };

function useHeaderRunState({ selectedSession, messages, runtimeValue, ...labels }: RunStateInput) {
  // A thread that runs on a device answered with the device's model; the server's selection
  // ("Automatic · Gemma 4") does not apply to it and is not shown as "Selected model".
  // A workflow run on a device (its runtime_target, mirrored into the composer's target) or a device chat: the header
  // names the model that executes there ("Claude Haiku 5.5"), never the Workspace's default runtime.
  const executionTarget = useExecutionTarget(selectedSession?.id);
  const deviceModel = executionTarget.kind === "device" ? (executionTarget.model || "").trim() : "";
  const runsOnDevice = (selectedSession?.runtimeTargetId || "").startsWith("device:") || executionTarget.kind === "device";
  // Full session transcripts: shown only when one is stored and readable.
  const transcript = useThreadTranscript(selectedSession, runsOnDevice, messages);
  // "Your role: Developer" while the thread's Workspace applies role-based tools (roles contract §3.3); desktop only.
  const roleText = roleHeaderText(useMyRole(selectedSession?.projectId));
  const routingSummary = buildRoutingSummary({
    selectedSession,
    workspaceLabel: labels.selectedSessionProjectLabel,
    runtimeLabel: runtimeValue,
  });
  // Governing state (models, status, thinking, route, workflow) lives in one "Run details" disclosure; only things
  // that need attention stay visible (judge). The model the answers came from is named apart from
  // the model selected now: the selection only applies to the next message.
  const used = selectedSession ? modelsUsed(messages) : [];
  const lastUsed = selectedSession ? lastModelUsed(messages) : "";
  const facts = runDetailsFacts({
    used,
    selection: runsOnDevice ? "" : runtimeValue,
    hasSession: Boolean(selectedSession),
    status: runStatusText(labels.threadStatusLabel, labels.statusLabel),
    thinking: thinkingLevelLabel(labels.thinkingLabel),
    route: routingSummary.label,
    routeDetail: routingSummary.detail,
    workflow: labels.activeWorkflowChipLabel,
  });
  // The model in words ("Claude Haiku 5.5"), its raw id in the tooltip.
  // On a device without a chosen model nothing is named: the device's default is not known here.
  const headerModel = deviceModel
    ? readableModelName(deviceModel)
    : lastUsed
      ? modelDisplayName(modelShortLabel(lastUsed))
      : runsOnDevice ? "" : shortRuntimeLabel(runtimeValue);
  const headerModelTitle = deviceModel ? `Runs with ${deviceModel} on the device` : lastUsed ? `Model used: ${lastUsed}` : runtimeValue;
  return { runsOnDevice, transcript, roleText, facts, headerModel, headerModelTitle };
}

type RunState = ReturnType<typeof useHeaderRunState>;

function HeaderContextLine({ workspaceLabel, run, selectedSession, messages, compactLayout }: {
  workspaceLabel: string; run: RunState; selectedSession: Session; messages: ChatMessage[]; compactLayout: boolean;
}) {
  const { runsOnDevice, roleText, facts, headerModel, headerModelTitle } = run;
  // One quiet line under the title: where, which model, audited, and the Run details disclosure as a text
  // control at its end (no floating chip).
  return (
    <div className="workspace__context-line">
      <span title={headerWorkspaceLabel(workspaceLabel)}>{headerWorkspaceLabel(workspaceLabel)}</span>
      {headerModel ? <span className="workspace__context-model" title={headerModelTitle}>{headerModel}</span> : null}
      {/* The coding engine of the thread's device job (Claude Code or Codex), next to the model. */}
      <ThreadEngineBadge selectedSession={selectedSession} runsOnDevice={runsOnDevice} messages={messages} />
      {roleText && !compactLayout ? <span data-testid="workspace-role">{roleText}</span> : null}
      <AuditMark />
      {/* The body anchors to the sticky header (the details element stays unpositioned); on compact layouts
          it is a sheet below the header. */}
      <details className="workspace__run-details" data-testid="run-details">
        <summary>Run details</summary>
        <dl className="workspace__run-details-body" tabIndex={compactLayout ? 0 : undefined}>
          {facts.map((fact) => (
            <div key={fact.key} className="workspace__run-fact" data-fact={fact.key}>
              <dt>{fact.label}</dt>
              <dd title={fact.title}>{fact.value}</dd>
            </div>
          ))}
        </dl>
      </details>
    </div>
  );
}

function HeaderSignalLine({ attentionChips, running, resumeLabel }: {
  attentionChips: ReturnType<typeof attentionChipsOf>; running: boolean; resumeLabel: string;
}) {
  return (
    <div className="workspace__signal-line">
      <div className="workspace__signal-row" role="group" aria-label="Turn context">
        {attentionChips.map((chip) => (
          <span key={chip.key} className={chip.className}>{chip.label}</span>
        ))}
        {running ? (
          <span className="workspace__thinking-chip">
            {resumeLabel || "Running"}
          </span>
        ) : null}
      </div>
    </div>
  );
}

function HeaderActions({ props, layoutMode, run }: {
  props: WorkspaceHeaderProps; layoutMode: ReturnType<typeof useChatLayoutMode>; run: RunState;
}) {
  const { selectedSession } = props;
  const pool = useSessionPool(selectedSession?.id ?? null);
  return (
    <WorkspaceHeaderActions
      layoutMode={layoutMode}
      hasSelectedSession={Boolean(selectedSession)}
      taskError={selectedSession?.taskError || ""}
      taskErrorSummary={props.taskErrorSummary}
      taskErrorOpen={props.taskErrorOpen}
      setTaskErrorOpen={props.setTaskErrorOpen}
      selectedSessionIsArchived={props.selectedSessionIsArchived}
      selectedSessionIsRunning={props.selectedSessionIsRunning}
      onContinue={props.onContinue}
      workspaceOpen={props.workspaceOpen}
      onToggleWorkspace={props.onToggleWorkspace}
      onExportEvidencePdf={() => openSessionExport(selectedSession, "export.pdf")}
      onExportAnalysisJson={() => openSessionExport(selectedSession, "export.analysis.json")}
      poolItem={pool}
      chatTheme={props.chatTheme}
      setChatTheme={props.setChatTheme}
      statsOpen={props.statsOpen}
      setStatsOpen={props.setStatsOpen}
      stats={props.stats}
      codeIntelligence={props.codeIntelligence}
      pullRequests={props.pullRequests}
      traceEventCount={props.traceEventCount}
      onOpenTrace={props.onOpenTrace}
      onOpenTranscript={run.transcript.available ? run.transcript.open : null}
    />
  );
}

export function WorkspaceHeader(props: WorkspaceHeaderProps) {
  const { selectedSession, messages = [], selectedSessionProjectLabel, sending, selectedSessionIsRunning } = props;
  const layoutMode = useChatLayoutMode();
  // A run's chat is titled by its Work item and current state; the stored title stays on hover.
  const runTitle = useRunThreadTitle(selectedSession?.id);
  const compactLayout = isCompactChatLayout(layoutMode);
  const runtimeValue = selectedSession
    ? props.selectedSessionRuntimePillLabel
    : props.runtimePillLabel;
  const run = useHeaderRunState({ ...props, selectedSession, messages, runtimeValue });
  const attentionChips = attentionChipsOf(selectedSession);

  return (
    <header
      className={`workspace__header ${compactLayout ? "workspace__header--compact" : ""}`}
    >
      <div className="workspace__header-main">
        <button
          type="button"
          className="icon-button icon-button--mobile"
          onClick={props.onOpenSidebar}
          aria-label="Open chats"
          title="Open chats"
        >
          <MenuIcon />
        </button>
        <div className="workspace__header-copy">
          {/* Compact layouts cut long titles to one line; the full title stays on hover and for
              assistive technology. */}
          <div className="workspace__title" title={selectedSession?.title || undefined} data-testid="workspace-title">
            {runTitle || selectedSession?.title || "New chat"}
          </div>
          <HeaderContextLine workspaceLabel={selectedSessionProjectLabel} run={run} selectedSession={selectedSession}
            messages={messages} compactLayout={compactLayout} />
          {attentionChips.length || sending || selectedSessionIsRunning ? (
            <HeaderSignalLine attentionChips={attentionChips} running={sending || selectedSessionIsRunning}
              resumeLabel={resumeLabelOf(selectedSession)} />
          ) : null}
        </div>
      </div>
      <HeaderActions props={props} layoutMode={layoutMode} run={run} />
      {run.transcript.viewer}
    </header>
  );
}
