// Parts of the chat composer: the agent chip, the input enhancements and the footer controls.
import { ComposerInputEnhancements } from "./ComposerInputEnhancements";
import { ComposerFooterControls } from "./ComposerFooterControls";
import type { buildGroupedAgentOptions } from "./composerShellHelpers";
import type { ComposerShellProps } from "./composerShellTypes";
import type { ComposerAgentIdentity } from "./chatAgentGuidance";
import type { ChatLayoutMode } from "./responsive/chatLayoutBreakpoints";

const AGENT_ROLE_TITLES = {
  selected: "Sent with your next message",
  bound: "This chat's agent for the next message",
  latest_turn: "Agent of the latest turn in this chat",
} as const;

export function ComposerAgentChip({ shownAgent, onClear }: { shownAgent: ComposerAgentIdentity; onClear: () => void }) {
  return (
    <div className="composer-selected-agents" aria-live="polite">
      <span
        className="composer-agent-chip"
        title={AGENT_ROLE_TITLES[shownAgent.role]}
      >
        <span className="composer-agent-chip__mark">@</span>
        {shownAgent.role === "latest_turn" ? (
          <span className="composer-agent-chip__qualifier">
            Latest turn
          </span>
        ) : null}
        <span className="composer-agent-chip__label">
          {shownAgent.label}
        </span>
        {shownAgent.availability === "inactive" ? (
          <span className="composer-agent-chip__qualifier">
            inactive
          </span>
        ) : null}
        {shownAgent.clearable ? (
          <button
            type="button"
            className="composer-agent-chip__remove"
            onClick={onClear}
            aria-label="Clear selected agent"
          >
            x
          </button>
        ) : null}
      </span>
      {shownAgent.latestTurnNote ? (
        <span className="composer-agent-chip__note">
          {shownAgent.latestTurnNote}
        </span>
      ) : null}
    </div>
  );
}

export function ComposerEnhancements({ props, groupedAgentOptions }: {
  props: ComposerShellProps;
  groupedAgentOptions: ReturnType<typeof buildGroupedAgentOptions>;
}) {
  return (
    <ComposerInputEnhancements
      fileInputRef={props.fileInputRef}
      uploadDraftFiles={props.uploadDraftFiles}
      slashCommand={props.slashCommand}
      slashCommands={props.slashCommands}
      setComposerValue={props.setComposerValue}
      setSlashCommand={props.setSlashCommand}
      handleSend={props.handleSend}
      atMention={props.atMention}
      groupedAgentOptions={groupedAgentOptions}
      handleSelectAtAgent={props.handleSelectAtAgent}
      draftAttachments={props.draftAttachments}
      uploadingAttachments={props.uploadingAttachments}
      removeDraftAttachment={props.removeDraftAttachment}
    />
  );
}

export function ComposerFooter({ props, layoutMode }: { props: ComposerShellProps; layoutMode: ChatLayoutMode }) {
  return (
    <ComposerFooterControls
      layoutMode={layoutMode}
      composerDisabled={props.composerDisabled}
      uploadingAttachments={props.uploadingAttachments}
      fileInputRef={props.fileInputRef}
      runtimePillLabel={props.runtimePillLabel}
      selectedRuntimeTargetId={props.selectedRuntimeTargetId}
      setSelectedRuntimeTargetId={props.setSelectedRuntimeTargetId}
      runtimeOptions={props.runtimeOptions}
      projectPillLabel={props.projectPillLabel}
      selectedProjectId={props.selectedProjectId}
      selectedThinkingLevel={props.selectedThinkingLevel}
      setSelectedThinkingLevel={props.setSelectedThinkingLevel}
      workflowOptions={props.workflowOptions}
      selectedWorkflowKey={props.selectedWorkflowKey}
      setSelectedWorkflowKey={props.setSelectedWorkflowKey}
      workflowPillLabel={props.workflowPillLabel}
      selectedWorkflowCapability={props.selectedWorkflowCapability}
      sttAvailable={props.sttAvailable}
      sttListening={props.sttListening}
      startSTT={props.startSTT}
      selectedSession={props.selectedSession}
      showCanvas={props.showCanvas}
      openCanvas={props.openCanvas}
      ttsEnabled={props.ttsEnabled}
      selectedSessionIsRunning={props.selectedSessionIsRunning}
      selectedSessionIsArchived={props.selectedSessionIsArchived}
      sending={props.sending}
      composerValue={props.composerValue}
      draftAttachments={props.draftAttachments}
      textareaRef={props.textareaRef}
      handleComposerChange={props.handleComposerChange}
      handleStop={props.handleStop}
      handleSend={props.handleSend}
    />
  );
}
