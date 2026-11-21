// The transcript, composer and controls of the workspace's primary section, rendered from its props.
import { WorkspacePrimaryContent } from "./WorkspacePrimaryContent";

type WorkspacePrimaryContentProps = any;

// The props handed to the content, in order; each is passed under its own name except setSelectedAgentId, which
// carries the section's handleAgentSelection.
const FORWARDED_PROPS = [
  "error", "selectedSession", "chatState", "selectedSessionIsRunning", "handleContinue", "showResumeNotice",
  "handleLoadOlderMessages", "loadingOlderMessages", "displayTimeline", "timelineFollowKey", "runtimePillLabel",
  "projectPillLabel", "allowGlobalProjectSelection", "agentName", "currentUserName", "currentUserEmail",
  "referencedArtifactsByMessageId", "sending", "handleSubmitMessageFeedback", "handleReuseMessage",
  "handleEditMessage", "handleRetryFromMessage", "handleRetryFromToolEvent", "handleRetryPrompt",
  "handleWorkflowDecision", "setPreviewArtifact", "loadTurnTrace", "assistantRetryPromptByMessageId",
  "composerDisabled", "approvalRetryPromptById", "handleApprovalDecision", "handleRetryFromApproval",
  "handleRetryFromChangePreview", "chatTheme", "taskErrorSummary", "editingMessage", "handleCancelEditMessage",
  "generateTaskResult", "setGenerateTaskResult", "composerDragActive", "setComposerDragActive", "fileInputRef",
  "uploadDraftFiles", "slashCommand", "SLASH_COMMANDS", "handleSend", "handleStop", "setComposerValue",
  "setSlashCommand", "atMention", "routingOverridesEnabled", "setRoutingOverridesEnabled",
  "setSelectedAgentId", "setSelectedAgentGroupId", "agentGroups", "selectedAgentGroupId", "handleAgentGroupChange",
  "agentGroupPillLabel", "selectedAgentId", "agentPillLabel", "filteredAgentOptions", "handleSelectAtAgent",
  "draftAttachments", "uploadingAttachments", "removeDraftAttachment", "textareaRef", "composerValue",
  "handleComposerChange", "handleComposerKeyDown", "selectedRuntimeTargetId", "setSelectedRuntimeTargetId",
  "selectedProjectId", "setSelectedProjectId",
  "selectedThinkingLevel", "setSelectedThinkingLevel", "THINKING_OPTIONS", "thinkingPillLabel",
  "workflowOptions", "selectedWorkflowKey", "setSelectedWorkflowKey", "workflowPillLabel",
  "selectedWorkflowCapability", "sttAvailable", "sttListening", "startSTT", "showCanvas", "openCanvas", "ttsEnabled",
] as const;

export function renderWorkspacePrimaryContent(props: WorkspacePrimaryContentProps) {
  const forwarded = Object.fromEntries(
    FORWARDED_PROPS.map((name) => [name, name === "setSelectedAgentId" ? props.handleAgentSelection : props[name]]),
  );
  return <WorkspacePrimaryContent {...forwarded} />;
}
