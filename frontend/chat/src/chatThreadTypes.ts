// Chat threads, messages, tool events, turn traces and the selected session.
import type {
  WorkflowProposalView,
} from "./chatDecisionTypes";

export type ThreadSummary = {
  id: string;
  threadNumber?: number;
  title: string;
  preview: string;
  messageCount: number;
  projectName: string;
  runtimeLabel: string;
  startedAt: string | null;
  /** When a turn was last recorded (sidebar order and time sections). */
  lastActivityAt?: string | null;
  /** The thread runs on one of the owner's devices. */
  executionTarget?: {
    kind: "device";
    deviceName: string;
    /** The newest job's engine, the profile (seat / governed) and the model, for the phone's run line. */
    engine?: string | null;
    profile?: string | null;
    model?: string | null;
  } | null;
  isSelected: boolean;
  status: string;
  runStatus?: string | null;
  runCompletionReason?: string | null;
  stopReason?: string | null;
  /** The newest turn trace recorded an explicit runtime stop (thread list projection). */
  latestTurnStopped?: boolean;
  /** The closed stop reason of that turn, when the server sends one (the thread list sends none). */
  latestTurnStopReason?: string | null;
  parentSessionId?: string;
  isSubThread?: boolean;
  subThreadCount?: number;
  subThreads?: ThreadSummary[];
  isPinned?: boolean;
};

export type ThreadGroup = {
  projectId?: string;
  projectName: string;
  sessions: ThreadSummary[];
  totalThreadCount?: number;
  loadedThreadCount?: number;
  nextOffset?: number;
  hasMore?: boolean;
  pageSize?: number;
};

export type ToolEvent = {
  id: string;
  messageId?: string | null;
  toolName: string;
  parameters: Record<string, unknown>;
  result:
    | Record<string, unknown>
    | unknown[]
    | string
    | number
    | boolean
    | null;
  executionEvent?: Record<string, unknown> | null;
  executionEvents?: Array<Record<string, unknown>>;
  artifacts?: ToolArtifact[];
  status: string;
  durationMs?: number | null;
  createdAt: string | null;
};

export type ToolArtifact = {
  name: string;
  path: string;
  mediaType: string;
  sizeBytes?: number | null;
  url: string;
};

export type DraftAttachment = {
  id: string;
  name: string;
  path: string;
  relativePath: string;
  mediaType: string;
  sizeBytes: number;
  url: string;
};

// The viewer's own feedback on one answer, as kept in the Workspace's Memory lobe.
export type MessageFeedback = {
  rating: "good" | "bad";
  liked?: string | null;
  disliked?: string | null;
  aspects?: Record<string, "liked" | "disliked">;
  createdAt?: string | null;
  updatedAt?: string | null;
};

export type DecisionTimelineEvent = {
  index?: number;
  phase: string;
  title: string;
  status: string;
  detail?: string;
  metadata?: Record<string, unknown>;
};

export type TurnTrace = {
  id: string;
  provider: string;
  model: string;
  inputMessages: Array<Record<string, unknown>>;
  contextSnapshot: Record<string, unknown>;
  toolTrace: Array<Record<string, unknown>>;
  rawOutput: Record<string, unknown>;
  usage: Record<string, unknown>;
  createdAt: string | null;
  /** An answer's trace: every model call of its turn, oldest first (content loads per call from the trace route). */
  calls?: TurnTraceCall[];
  /** A device turn whose model calls did not pass through the platform: its prompt stayed on the device. */
  promptOnDevice?: boolean;
};

export type TurnTraceCall = {
  id: string;
  provider: string;
  model: string;
  createdAt: string | null;
  tokens: { input: number; output: number; cacheRead: number; cacheCreation: number };
  durationMs: number | null;
  stopReason: string;
};

export type ChatMessage = {
  id: string;
  role: "user" | "assistant" | string;
  content: string;
  model?: string | null;
  runtimeLabel?: string | null;
  providerName?: string | null;
  createdAt: string | null;
  toolEvents: ToolEvent[];
  turnTrace?: TurnTrace | null;
  turnTraceId?: string | null;
  feedback?: MessageFeedback | null;
  /** "workflow": the platform sent this message to continue a workflow run; it is not the person's.
   * "device": a device job wrote this answer. */
  origin?: string | null;
  /** The person who wrote a user message; it stays theirs when the chat is handed over. */
  authorId?: string | null;
  authorName?: string | null;
};

export type SelectedSession = {
  id: string;
  threadNumber?: number;
  title: string;
  /** Where the title came from: "prompt" (the first prompt), "run" or "user". */
  titleSource?: string | null;
  status: string;
  runStatus?: string | null;
  runCompletionReason?: string | null;
  projectId?: string | null;
  projectName: string;
  runtimeTargetId: string;
  runtimeLabel: string;
  agentId?: string | null;
  agentName?: string | null;
  agentType?: string | null;
  agentSelectionSource?: string | null;
  workflowKey?: string;
  workflowProposal?: WorkflowProposalView | null;
  // Hide a tool approval's "Always for this Workspace" unless the viewer is a Workspace admin or owner.
  canGrantStandingConfirmation?: boolean;
  // The write plan confirmed for the current request; null when none is active.
  writePlan?: Record<string, unknown> | null;
  routingIntent?: string | null;
  routingReason?: string | null;
  resumeState?: string | null;
  stopReason?: string | null;
  startedAt: string | null;
  taskRunId?: string | null;
  taskStatus?: string | null;
  taskError?: string | null;
  approvalCount?: number;
  pendingApprovalCount?: number;
  streamToken?: string | null;
  isPinned?: boolean;
};

export type SerializedThreadContext = {
  id: string;
  version: number;
  context: Record<string, unknown>;
  derivedFromMessageId: string;
  updatedAt: string | null;
};
