import { DeviceJobPanel } from "./devices/DeviceJobPanel";
import { RemedyWorkspaceContext } from "./devices/RemedyAction";
import { ChatErrorBoundary } from "./ChatErrorBoundary";
import { EmptyState } from "./EmptyState";
import { chatNotFoundNotice } from "./chatNotFound";
import { TEXT_ONLY_AGENT_HINT } from "./chatOnboarding";
import { WorkflowRunBanner } from "./workflowRun/WorkflowRunBanner";
import { runRefreshKey } from "./workflowRun/workflowRunModel";
import { renderWorkspaceComposer } from "./workspaceComposer";
import { renderWorkspaceTimelineItem } from "./workspaceTimelineItem";
import { ResumeNotice } from "./ResumeNotice";
import { MessageTimeline } from "./MessageTimeline";
import { unusedLaunchAgentNotice } from "./chatOnboarding";
import { repeatedTurnMessageIds } from "./run/workflowTurnContext";
import { intermediateToolMessageIds } from "./evidence/intermediateToolMessages";
import { AGENTS_PAGE_HREF, agentPageHref } from "../admin/agentLinks";
import {
  currentChatAgentGuidance,
  deriveChatAgentPresentation,
} from "./chatAgentGuidance";

type WorkspacePrimaryContentProps = any;

// The note under the composer when the chat was launched for an agent it did not use.
function unusedLaunchNotice(agentPresentation: ReturnType<typeof deriveChatAgentPresentation>) {
  const unusedLaunch = agentPresentation.unusedLaunchAgent;
  return unusedLaunch
    ? {
        text: unusedLaunchAgentNotice(unusedLaunch),
        // Recovery goes to the canonical Agents page; a deleted or foreign agent is never linked.
        href:
          unusedLaunch.reason === "unavailable"
            ? AGENTS_PAGE_HREF
            : agentPageHref(unusedLaunch.id),
      }
    : null;
}

function FeedBanners({ error, showResumeNotice, selectedSession, chatState }: WorkspacePrimaryContentProps) {
  return (
    <>
      {error ? (
        <div className="workspace__feed-banner">
          <div className="workspace__error">{error}</div>
        </div>
      ) : null}
      {showResumeNotice ? (
        <div className="workspace__feed-banner">
          <ResumeNotice resumeState={selectedSession?.resumeState} />
        </div>
      ) : null}
      {chatNotFoundNotice(chatState) ? (
        <div className="workspace__feed-banner" role="status" data-testid="chat-not-found">
          {chatNotFoundNotice(chatState)}
        </div>
      ) : null}
    </>
  );
}

function LoadOlderMessages({ loading, onLoad }: { loading: boolean; onLoad: () => Promise<void> | void }) {
  return (
    <div className="workspace__timeline-actions">
      <button
        type="button"
        className="workspace__timeline-action"
        onClick={() => void onLoad()}
        disabled={loading}
      >
        <span>
          {loading
            ? "Loading older messages…"
            : "Load older messages"}
        </span>
      </button>
    </div>
  );
}

// The chat's timeline: its messages, the live device job below them and, for an empty chat, the welcome or one line.
function WorkspaceTimeline({ props, agentPresentation, repeatedTurnMessages, intermediateToolMessages }: {
  props: WorkspacePrimaryContentProps;
  agentPresentation: ReturnType<typeof deriveChatAgentPresentation>;
  repeatedTurnMessages: ReturnType<typeof repeatedTurnMessageIds>;
  intermediateToolMessages: ReturnType<typeof intermediateToolMessageIds>;
}) {
  const { selectedSession, chatState, handleLoadOlderMessages, loadingOlderMessages, displayTimeline, timelineFollowKey,
    projectPillLabel, setComposerValue, textareaRef, selectedProjectId } = props;
  const shownAgent = agentPresentation.identity;
  return (
    <ChatErrorBoundary fallbackTitle="Timeline error">
      {/* A refused tool call's "Allow in this Workspace" applies to the thread's Workspace. */}
      <RemedyWorkspaceContext.Provider value={selectedSession?.projectId ?? null}>
      <MessageTimeline
        items={displayTimeline}
        followKey={timelineFollowKey}
        footer={<DeviceJobPanel sessionId={selectedSession?.id} projectId={selectedSession?.projectId} messages={chatState?.selectedMessages} />}
        onReachStart={
          chatState?.selectedMessagesHasMore && !loadingOlderMessages
            ? () => {
                void handleLoadOlderMessages();
              }
            : undefined
        }
        emptyState={selectedSession?.id ? (
          // An existing chat without messages is not a new chat: one line, the composer below.
          <p className="workspace__empty-session" data-testid="chat-no-messages">
            No messages yet.{agentPresentation.toolSurface === "none" ? ` ${TEXT_ONLY_AGENT_HINT}` : ""}
          </p>
        ) : (
          <EmptyState
            projectName={projectPillLabel}
            projectId={selectedProjectId}
            agentName={
              shownAgent && shownAgent.availability !== "unavailable"
                ? shownAgent.label
                : ""
            }
            agentAvailability={shownAgent?.availability ?? "unknown"}
            toolSurface={agentPresentation.toolSurface}
            onUseStarter={(prompt: string) => {
              setComposerValue(prompt);
              textareaRef.current?.focus();
            }}
          />
        )}
        renderItem={(item: any) =>
          renderWorkspaceTimelineItem(item, props, repeatedTurnMessages, intermediateToolMessages)
        }
      />
      </RemedyWorkspaceContext.Provider>
    </ChatErrorBoundary>
  );
}

export function WorkspacePrimaryContent(props: WorkspacePrimaryContentProps) {
  const {
    error,
    selectedSession,
    chatState,
    selectedSessionIsRunning,
    showResumeNotice,
    handleLoadOlderMessages,
    loadingOlderMessages,
    displayTimeline,
    agentName,
    routingOverridesEnabled,
    selectedAgentId,
  } = props;
  // One derivation for the composer chip and the empty chat: guidance only applies to the
  // session it was projected for and to the agent it names.
  const agentPresentation = deriveChatAgentPresentation({
    guidance: currentChatAgentGuidance(
      chatState?.chatAgentGuidance,
      selectedSession,
    ),
    selectedSession,
    routingOverridesEnabled,
    selectedAgentId,
    agentOptions: chatState?.agentOptions ?? [],
    selectedAgentLabel: agentName,
  });
  const shownAgent = agentPresentation.identity;
  const agentNotice = unusedLaunchNotice(agentPresentation);
  // Later messages of a turn repeat its workflow context; they show no applied note.
  const repeatedTurnMessages = repeatedTurnMessageIds(displayTimeline ?? []);
  // Tool steps followed by the turn's answer show no "none cited" chip.
  const intermediateToolMessages = intermediateToolMessageIds(displayTimeline ?? []);

  return (
    <>
      <FeedBanners error={error} showResumeNotice={showResumeNotice} selectedSession={selectedSession} chatState={chatState} />
      <WorkflowRunBanner sessionId={selectedSession?.id} chatTitle={selectedSession?.title}
        chatTitleSource={selectedSession?.titleSource}
        refreshKey={runRefreshKey(chatState, Boolean(selectedSessionIsRunning))} />
      {chatState?.selectedMessagesHasMore ? (
        <LoadOlderMessages loading={loadingOlderMessages} onLoad={handleLoadOlderMessages} />
      ) : null}
      <WorkspaceTimeline props={props} agentPresentation={agentPresentation}
        repeatedTurnMessages={repeatedTurnMessages} intermediateToolMessages={intermediateToolMessages} />

      {renderWorkspaceComposer(props, shownAgent, agentNotice)}
    </>
  );
}