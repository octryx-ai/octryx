// The chat composer of the primary workspace, wired to the workspace state and handlers.
import { ComposerShell } from "./ComposerShell";

export function renderWorkspaceComposer(
  props: any,
  shownAgent: any,
  agentNotice: { text: string; href: string } | null,
) {
  const {
    selectedSession, chatState, selectedSessionIsRunning, runtimePillLabel, projectPillLabel, sending,
    composerDisabled, editingMessage, handleCancelEditMessage, generateTaskResult, setGenerateTaskResult,
    composerDragActive, setComposerDragActive, fileInputRef, uploadDraftFiles, slashCommand, SLASH_COMMANDS,
    handleSend, handleStop, setComposerValue, setSlashCommand, atMention, routingOverridesEnabled,
    setRoutingOverridesEnabled, setSelectedAgentId, setSelectedAgentGroupId,
    agentGroups, selectedAgentGroupId, handleAgentGroupChange, agentGroupPillLabel, selectedAgentId,
    agentPillLabel, filteredAgentOptions, handleSelectAtAgent, draftAttachments, uploadingAttachments,
    removeDraftAttachment, textareaRef, composerValue, handleComposerChange, handleComposerKeyDown,
    selectedRuntimeTargetId, setSelectedRuntimeTargetId, selectedProjectId, selectedThinkingLevel,
    setSelectedThinkingLevel, workflowOptions, selectedWorkflowKey, setSelectedWorkflowKey,
    workflowPillLabel, selectedWorkflowCapability, sttAvailable, sttListening, startSTT, showCanvas,
    openCanvas, ttsEnabled,
  } = props;
  return (
    <ComposerShell
      selectedSession={selectedSession}
      selectedSessionIsArchived={chatState?.selectedSessionIsArchived}
      selectedSessionIsRunning={selectedSessionIsRunning}
      editingMessage={editingMessage}
      onCancelEditMessage={handleCancelEditMessage}
      generateTaskResult={generateTaskResult}
      setGenerateTaskResult={setGenerateTaskResult}
      composerDragActive={composerDragActive}
      setComposerDragActive={setComposerDragActive}
      composerDisabled={composerDisabled}
      fileInputRef={fileInputRef}
      uploadDraftFiles={uploadDraftFiles}
      slashCommand={slashCommand}
      slashCommands={SLASH_COMMANDS}
      handleSend={handleSend}
      handleStop={handleStop}
      setComposerValue={setComposerValue}
      setSlashCommand={setSlashCommand}
      atMention={atMention}
      routingOverridesEnabled={routingOverridesEnabled}
      setRoutingOverridesEnabled={(enabled) => {
        setRoutingOverridesEnabled(enabled);
        if (!enabled) {
          setSelectedAgentId("");
          setSelectedAgentGroupId("");
        }
      }}
      agentGroups={agentGroups}
      selectedAgentGroupId={selectedAgentGroupId}
      setSelectedAgentGroupId={handleAgentGroupChange}
      agentGroupPillLabel={agentGroupPillLabel}
      selectedAgentId={selectedAgentId}
      selectedAgentSelectionSource={
        chatState?.selectedSession?.agentSelectionSource ??
        chatState?.selectedAgentSelectionSource ??
        ""
      }
      setSelectedAgentId={setSelectedAgentId}
      agentPillLabel={agentPillLabel}
      agentIdentity={shownAgent}
      agentNotice={agentNotice}
      chatAgentOptions={filteredAgentOptions}
      handleSelectAtAgent={handleSelectAtAgent}
      draftAttachments={draftAttachments}
      uploadingAttachments={uploadingAttachments}
      removeDraftAttachment={removeDraftAttachment}
      textareaRef={textareaRef}
      composerValue={composerValue}
      handleComposerChange={handleComposerChange}
      handleComposerKeyDown={handleComposerKeyDown}
      selectedRuntimeTargetId={selectedRuntimeTargetId}
      setSelectedRuntimeTargetId={setSelectedRuntimeTargetId}
      runtimeOptions={chatState?.runtimeOptions ?? []}
      runtimePillLabel={runtimePillLabel}
      selectedProjectId={selectedProjectId}
      projectPillLabel={projectPillLabel}
      selectedThinkingLevel={selectedThinkingLevel}
      setSelectedThinkingLevel={setSelectedThinkingLevel}
      workflowOptions={workflowOptions}
      selectedWorkflowKey={selectedWorkflowKey}
      setSelectedWorkflowKey={setSelectedWorkflowKey}
      workflowPillLabel={workflowPillLabel}
      selectedWorkflowCapability={selectedWorkflowCapability}
      sttAvailable={sttAvailable}
      sttListening={sttListening}
      startSTT={startSTT}
      showCanvas={showCanvas}
      openCanvas={() => openCanvas()}
      ttsEnabled={ttsEnabled}
      sending={sending}
    />
  );
}
