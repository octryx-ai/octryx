import { ComposerNotices } from "./ComposerNotices";
import {
  buildGroupedAgentOptions,
  getResumeComposerCopy,
} from "./composerShellHelpers";
import { useChatLayoutMode } from "./responsive/useChatLayoutMode";
import type { ChatLayoutMode } from "./responsive/chatLayoutBreakpoints";
import type { ComposerShellProps } from "./composerShellTypes";
import { deriveChatAgentPresentation } from "./chatAgentGuidance";
import { roleChatNotice } from "./roles/myRoleModel";
import { useMyRole } from "./roles/useMyRole";
import { writePlanNotice } from "./approval/writePlanView";
import { ComposerAgentChip, ComposerEnhancements, ComposerFooter } from "./composerShellParts";
import { composerDragHandlers } from "./composerDragHandlers";

// Identity is shown whether or not the selection can be edited; the host passes the derived
// identity, and without it only the explicit selection or a matching session record is shown.
function shownAgentOf(props: ComposerShellProps) {
  return props.agentIdentity !== undefined
    ? props.agentIdentity
    : deriveChatAgentPresentation({
        guidance: null,
        selectedSession: props.selectedSession,
        routingOverridesEnabled: props.routingOverridesEnabled,
        selectedAgentId: props.selectedAgentId,
        agentOptions: props.chatAgentOptions,
        selectedAgentLabel: props.agentPillLabel,
      }).identity;
}

// The long desktop placeholder wraps to three lines on a phone and clips the
// single-row textarea, so narrow viewports get the short form.
function composerPlaceholderOf(selectedSessionIsArchived: boolean | undefined, layoutMode: ChatLayoutMode) {
  return selectedSessionIsArchived
    ? "Restore this thread in Settings"
    : layoutMode === "phone"
      ? "Message Octryx…"
      : "Message Octryx… Use / for commands, @ to mention people, tools, or files.";
}

function clearAgentSelection(props: ComposerShellProps) {
  props.setSelectedAgentId("");
  props.setSelectedAgentGroupId("");
  props.setRoutingOverridesEnabled(false);
  props.textareaRef.current?.focus();
}

export function ComposerShell(props: ComposerShellProps) {
  const { selectedSession, selectedSessionIsRunning, composerDisabled, textareaRef } = props;
  const layoutMode = useChatLayoutMode();
  // The chat's Workspace: the open thread's, else the one a new chat starts in.
  const chatWorkspaceId = selectedSession?.projectId || props.selectedProjectId;
  const chatWorkspaceName =
    selectedSession?.projectId && selectedSession.projectName ? selectedSession.projectName : props.projectPillLabel;
  const roleNotice = roleChatNotice(useMyRole(chatWorkspaceId), chatWorkspaceName);
  const resumeComposerCopy = getResumeComposerCopy(
    selectedSession?.resumeState,
    selectedSessionIsRunning,
  );
  const groupedAgentOptions = buildGroupedAgentOptions(
    props.chatAgentOptions,
    props.atMention.query.toLowerCase(),
  );
  const shownAgent = shownAgentOf(props);
  const clearSelectedAgent = () => clearAgentSelection(props);
  return (
    <footer className="composer-shell">
      <div className="composer-shell__stack">
        <ComposerNotices
          editingMessage={props.editingMessage}
          onCancelEditMessage={props.onCancelEditMessage}
          resumeComposerCopy={resumeComposerCopy}
          generateTaskResult={props.generateTaskResult}
          setGenerateTaskResult={props.setGenerateTaskResult}
          agentNotice={props.agentNotice}
          roleNotice={roleNotice}
          planNotice={writePlanNotice(selectedSession?.writePlan)}
        />
        <div
          className={`composer ${props.composerDragActive ? "composer--drag-active" : ""}`}
          {...composerDragHandlers(composerDisabled, props.setComposerDragActive, props.uploadDraftFiles)}
        >
          <div className="composer__card">
            <ComposerEnhancements props={props} groupedAgentOptions={groupedAgentOptions} />
            <div className="composer__input-region">
              {shownAgent ? <ComposerAgentChip shownAgent={shownAgent} onClear={clearSelectedAgent} /> : null}
              <textarea
                ref={textareaRef}
                value={props.composerValue}
                rows={1}
                disabled={composerDisabled}
                placeholder={composerPlaceholderOf(props.selectedSessionIsArchived, layoutMode)}
                onChange={(event) => props.handleComposerChange(event.target.value)}
                onKeyDown={props.handleComposerKeyDown}
              />
            </div>
            <ComposerFooter props={props} layoutMode={layoutMode} />
          </div>
        </div>
      </div>
    </footer>
  );
}
