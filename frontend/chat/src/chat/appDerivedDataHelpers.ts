import type { ApprovalSummary } from "../chatDecisionTypes";
import type { ChatMessage, ThreadGroup } from "../chatThreadTypes";
import type { SelectedWorkspace, WorkspaceChangeEntry, WorkspaceFileEntry } from "../chatWorkspaceTypes";
import { flattenThreadSearchFields } from "./appHelpers";
import { parseChatTimestamp } from "./chatTimestamp";
import { isWorkflowProposalApproval } from "./composer/automaticWorkflow";
import { normalizeTranscriptMessages } from "./chatTimelineHelpers";


function timestampOf(value: string | null | undefined, fallback = 0): number {
  return value ? (parseChatTimestamp(value)?.getTime() ?? fallback) : fallback;
}

export function filterThreadGroups(groups: ThreadGroup[], threadSearchQuery: string) {
  const query = threadSearchQuery.trim().toLowerCase();
  if (!query) {
    return groups;
  }
  return groups
    .map((group) => {
      const sessions = (group.sessions ?? []).filter((thread) => {
        const haystack = flattenThreadSearchFields(thread)
          .join(" ")
          .toLowerCase();
        return haystack.includes(query);
      });
      return { ...group, sessions };
    })
    .filter((group) => group.sessions.length > 0);
}

function pendingAssistantMessage(
  streamActivityMessage: string | null,
  runtimeLabel: string | null | undefined,
): ChatMessage {
  return {
    id: "pending-assistant-message",
    role: "assistant",
    content: streamActivityMessage || "Working through the configured systems…",
    model: runtimeLabel ?? "Automatic fallback chain",
    createdAt: new Date().toISOString(),
    toolEvents: [],
  } satisfies ChatMessage;
}

export function buildDisplayMessages(
  messages: ChatMessage[],
  runtimeLabel: string | null | undefined,
  pendingPrompt: string | null,
  selectedSessionIsRunning: boolean,
  streamActivityMessage: string | null,
): ChatMessage[] {
  const baseMessages = normalizeTranscriptMessages(messages);
  if (!pendingPrompt) {
    if (!selectedSessionIsRunning) {
      return baseMessages;
    }
    return [...baseMessages, pendingAssistantMessage(streamActivityMessage, runtimeLabel)];
  }
  return [
    ...baseMessages,
    {
      id: "pending-user-message",
      role: "user",
      content: pendingPrompt,
      createdAt: new Date().toISOString(),
      toolEvents: [],
    } satisfies ChatMessage,
    pendingAssistantMessage(streamActivityMessage, runtimeLabel),
  ];
}

export function buildDisplayTimeline(displayMessages: ChatMessage[], selectedApprovals: ApprovalSummary[]) {
  const messageItems = displayMessages.map((message, index) => ({
    kind: "message" as const,
    id: `message-${message.id}`,
    createdAt: message.createdAt,
    order: index,
    message,
  }));
  // A held workflow proposal's approval is answered inline on its proposal
  // card, so it is not listed a second time.
  const pendingApprovalItems = selectedApprovals
    .filter((approval) => approval.status === "pending" && !isWorkflowProposalApproval(approval))
    .sort((left, right) => timestampOf(left.createdAt) - timestampOf(right.createdAt))
    .map((approval, index) => ({
      kind: "approval" as const,
      id: `approval-${approval.id}`,
      createdAt: approval.createdAt,
      order: displayMessages.length + index,
      approval,
    }));
  return [...messageItems, ...pendingApprovalItems];
}

export function timelineFollowKeyOf(displayTimeline: ReturnType<typeof buildDisplayTimeline>): string {
  const lastItem = displayTimeline.at(-1);
  if (!lastItem) {
    return "empty";
  }
  if (lastItem.kind === "message") {
    return `${lastItem.id}:${lastItem.message.content.length}:${lastItem.message.toolEvents.length}`;
  }
  return `${lastItem.id}:${lastItem.approval.status}`;
}

function addArtifactFiles(fileMap: Map<string, WorkspaceFileEntry>, messages: ChatMessage[]) {
  for (const message of messages) {
    for (const event of message.toolEvents ?? []) {
      for (const artifact of event.artifacts ?? []) {
        if (!artifact?.path || fileMap.has(artifact.path)) {
          continue;
        }
        const relativePath = artifact.path.split("/").filter(Boolean).at(-1) || artifact.name;
        fileMap.set(artifact.path, {
          path: artifact.path,
          relativePath,
          parentPath: "",
          name: artifact.name,
          kind: "file",
          depth: 0,
          mediaType: artifact.mediaType,
          sizeBytes: artifact.sizeBytes,
          url: artifact.url,
          toolName: event.toolName,
          createdAt: event.createdAt,
          modifiedAt: event.createdAt,
        });
      }
    }
  }
}

function addApprovalChanges(changeMap: Map<string, WorkspaceChangeEntry>, selectedApprovals: ApprovalSummary[]) {
  for (const approval of selectedApprovals) {
    if (!approval.changePreview?.id || changeMap.has(approval.changePreview.id)) {
      continue;
    }
    changeMap.set(approval.changePreview.id, {
      id: approval.changePreview.id,
      approvalId: approval.id,
      toolName: approval.changePreview.toolName || "",
      requestFingerprint: approval.changePreview.requestFingerprint || "",
      summary:
        String(approval.changePreview.preview?.summary || "").trim() ||
        String(approval.changePreview.preview?.path || "").trim() ||
        approval.changePreview.toolName ||
        approval.changePreview.requestFingerprint ||
        "",
      status: approval.status,
      createdAt: approval.changePreview.createdAt || approval.createdAt,
      preview: approval.changePreview.preview || {},
    });
  }
}

export function buildEffectiveWorkspace(
  messages: ChatMessage[],
  selectedApprovals: ApprovalSummary[],
  selectedWorkspace: SelectedWorkspace | null,
) {
  const baseWorkspace = selectedWorkspace ?? {
    rootLabel: "Working Files",
    rootPath: "",
    isTemporary: true,
    files: [],
    loadedDirectories: [""],
    changes: [],
  };
  const fileMap = new Map((baseWorkspace.files ?? []).map((file) => [file.path, file]));
  addArtifactFiles(fileMap, messages);
  const changeMap = new Map((baseWorkspace.changes ?? []).map((change) => [change.id, change]));
  addApprovalChanges(changeMap, selectedApprovals);
  return {
    rootLabel: baseWorkspace.rootLabel,
    rootPath: baseWorkspace.rootPath,
    isTemporary: baseWorkspace.isTemporary,
    files: Array.from(fileMap.values()),
    loadedDirectories: baseWorkspace.loadedDirectories ?? [""],
    changes: Array.from(changeMap.values()),
  };
}

export function buildAssistantRetryPrompts(messages: ChatMessage[]) {
  const mapping = new Map<string, string>();
  let lastUserPrompt = "";
  for (const message of messages) {
    if (message.role === "user") {
      lastUserPrompt = message.content || "";
      continue;
    }
    if (message.role === "assistant" && lastUserPrompt) {
      mapping.set(message.id, lastUserPrompt);
    }
  }
  return mapping;
}

export function buildApprovalRetryPrompts(messages: ChatMessage[], selectedApprovals: ApprovalSummary[]) {
  const mapping = new Map<string, string>();
  const sorted = [...messages].sort((left, right) => timestampOf(left.createdAt) - timestampOf(right.createdAt));
  for (const approval of selectedApprovals) {
    const cutoff = timestampOf(approval.createdAt, Number.POSITIVE_INFINITY);
    let prompt = "";
    for (const message of sorted) {
      if (timestampOf(message.createdAt) > cutoff) {
        break;
      }
      if (message.role === "user" && (message.content || "").trim()) {
        prompt = message.content || "";
      }
    }
    if (prompt) {
      mapping.set(approval.id, prompt);
    }
  }
  return mapping;
}
