import type { ToolArtifact, ToolEvent, TurnTrace } from "../chatThreadTypes";
import type { WorkflowOption } from "../chatOptionTypes";
import type { WorkflowProposalView } from "../chatDecisionTypes";
import type { MessageFeedbackPayload } from "./messageFeedbackModel";
import type { PerformanceSections } from "./messageBubblePanels";
import type {
  TurnExecutionSummaryLoad,
  WorkflowDecisionChoice,
} from "./run/turnExecutionSummary.types";
import type { ChatMessage } from "../chatThreadTypes";

export type MessageBubbleContentProps = {
  message: ChatMessage;
  isUser: boolean;
  isThinking: boolean;
  timestamp: string;
  participantTitle: string;
  participantSupportLabel: string;
  toolOnlyAssistant: boolean;
  hasTurnTrace: boolean;
  thinkingOpen: boolean;
  thinkingLoading: boolean;
  toggleThinking: () => Promise<void>;
  performanceOpen: boolean;
  performanceLoading: boolean;
  togglePerformance: () => Promise<void>;
  traceLoading: boolean;
  openTrace: () => Promise<void>;
  thinkingText: string;
  thinkingUnavailable: boolean;
  performance: PerformanceSections;
  performanceUnavailable: boolean;
  displayContent: string;
  theme: "dark" | "light";
  turnDiff?: Record<string, unknown> | null;
  setTraceOpen: () => void;
  referencedArtifacts?: ToolArtifact[];
  onPreviewArtifact?: (artifact: ToolArtifact) => void;
  feedbackDisabled: boolean;
  onSubmitFeedback: (messageId: string, payload: MessageFeedbackPayload) => Promise<void>;
  triggerRetryFromToolEvent: (event: ToolEvent) => Promise<void>;
  actionsDisabled: boolean;
  retrying: boolean;
  copied: boolean;
  copyMessage: () => Promise<void>;
  startEditMessage: () => void;
  reused: boolean;
  reuseMessage: () => void;
  retryPrompt?: string | null;
  triggerRetryFromHere: () => Promise<void>;
  triggerRetryPrompt: () => Promise<void>;
  speaking: boolean;
  toggleSpeak: () => void;
  effectiveTurnTrace: TurnTrace | null;
  /** Loads any trace of this thread by id: the trace view opens the turn's single model calls with it. */
  loadTurnTrace?: (traceId: string) => Promise<TurnTrace | null>;
  traceOpen: boolean;
  setTraceClosed: () => void;
  executionSummary: TurnExecutionSummaryLoad;
  retryExecutionSummary: () => void;
  onWorkflowDecision?: (choice: WorkflowDecisionChoice) => Promise<void>;
  // The thread's current workflow proposal (session state).
  workflowProposal?: WorkflowProposalView | null;
  // The composer's workflow catalog ("Other workflow…" on a pending proposal).
  workflowOptions?: readonly WorkflowOption[];
  /** A later message of the same turn; it shows no applied workflow note. */
  repeatsTurnContext?: boolean;
  /** A tool step followed by the turn's answer; it shows no "Sources · none cited" chip. */
  intermediateToolStep?: boolean;
};
