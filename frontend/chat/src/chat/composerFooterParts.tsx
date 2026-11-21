// Parts of the composer footer: the routing pills, the utility actions, the send/stop button and the token insert
// into the message at the cursor.
import { SendIcon } from "./composerIcons";
import { StopIcon } from "./ChatShellIcons";
import { ComposerRoutingPills } from "./composer/ComposerRoutingPills";
import { RunOnControls } from "./devices/RunOnControls";
import { useExecutionTarget } from "./devices/executionTarget";
import { ComposerUtilityActions } from "./composer/ComposerUtilityActions";
import type { ComposerFooterControlsProps } from "./ComposerFooterControls";

function insertComposerToken(
  { composerDisabled, textareaRef, composerValue, handleComposerChange }: ComposerFooterControlsProps,
  token: string,
) {
  if (composerDisabled) {
    return;
  }

  const textarea = textareaRef.current;
  if (!textarea) {
    handleComposerChange(`${composerValue}${token}`);
    return;
  }

  const selectionStart = textarea.selectionStart ?? composerValue.length;
  const selectionEnd = textarea.selectionEnd ?? composerValue.length;
  const nextValue =
    composerValue.slice(0, selectionStart) +
    token +
    composerValue.slice(selectionEnd);
  const nextCursor = selectionStart + token.length;

  handleComposerChange(nextValue);
  window.requestAnimationFrame(() => {
    textarea.focus();
    textarea.setSelectionRange(nextCursor, nextCursor);
  });
}

function renderSubmitButton({
  selectedSessionIsRunning,
  selectedSessionIsArchived,
  sending,
  composerValue,
  draftAttachments,
  handleStop,
  handleSend,
}: ComposerFooterControlsProps) {
  return (
    <div className="composer__submit">
      <button
        type="button"
        aria-label={selectedSessionIsRunning ? "Stop run" : "Send message"}
        title={selectedSessionIsRunning ? "Stop run" : "Send message"}
        className={`send-button${selectedSessionIsRunning ? " send-button--stop" : ""}`}
        disabled={
          selectedSessionIsArchived ||
          (selectedSessionIsRunning ? false : sending) ||
          (!selectedSessionIsRunning &&
            !composerValue.trim() &&
            draftAttachments.length === 0)
        }
        onClick={() =>
          void (selectedSessionIsRunning ? handleStop() : handleSend())
        }
      >
        {sending ? (
          <span className="send-button__spinner" />
        ) : selectedSessionIsRunning ? (
          <StopIcon />
        ) : (
          <SendIcon />
        )}
      </button>
    </div>
  );
}

function renderRoutingPills(props: ComposerFooterControlsProps, deviceTarget: boolean) {
  const { selectedSession, selectedProjectId, projectPillLabel, composerDisabled } = props;
  return (
    <ComposerRoutingPills
      runOn={<RunOnControls sessionId={selectedSession?.id} projectId={selectedProjectId}
        workspaceName={projectPillLabel} composerDisabled={composerDisabled} />}
      hideServerOnly={deviceTarget}
      composerDisabled={composerDisabled}
      runtimePillLabel={props.runtimePillLabel}
      selectedRuntimeTargetId={props.selectedRuntimeTargetId}
      setSelectedRuntimeTargetId={props.setSelectedRuntimeTargetId}
      runtimeOptions={props.runtimeOptions}
      selectedThinkingLevel={props.selectedThinkingLevel}
      setSelectedThinkingLevel={props.setSelectedThinkingLevel}
      workflowOptions={props.workflowOptions}
      selectedWorkflowKey={props.selectedWorkflowKey}
      setSelectedWorkflowKey={props.setSelectedWorkflowKey}
      workflowPillLabel={props.workflowPillLabel}
      selectedWorkflowCapability={props.selectedWorkflowCapability}
    />
  );
}

export function useComposerFooterParts(props: ComposerFooterControlsProps) {
  const { selectedSession } = props;
  // With a device target the Server-only pills (runtime model, mode of work) hide.
  const deviceTarget = useExecutionTarget(selectedSession?.id).kind === "device";

  const insertToken = (token: string) => insertComposerToken(props, token);

  const routingPills = renderRoutingPills(props, deviceTarget);

  const utilityActions = (showAttach: boolean) => (
    <ComposerUtilityActions
      composerDisabled={props.composerDisabled}
      uploadingAttachments={props.uploadingAttachments}
      fileInputRef={props.fileInputRef}
      sttAvailable={props.sttAvailable}
      sttListening={props.sttListening}
      startSTT={props.startSTT}
      selectedSession={selectedSession}
      showCanvas={props.showCanvas}
      openCanvas={props.openCanvas}
      insertComposerToken={insertToken}
      showAttach={showAttach}
    />
  );

  return { routingPills, utilityActions, submitButton: renderSubmitButton(props) };
}
