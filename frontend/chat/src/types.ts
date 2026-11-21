import type { ChatAgentGuidance } from "./chat/chatAgentGuidance";
import type { ApprovalSummary } from "./chatDecisionTypes";
import type {
  RuntimeOption,
  ProjectOption,
  AgentModeOption,
  AgentGroupOption,
  ChatAgentOption,
  ChatLaunchSurface,
} from "./chatOptionTypes";
import type {
  ThreadSummary,
  ThreadGroup,
  ToolEvent,
  ChatMessage,
  SelectedSession,
  SerializedThreadContext,
} from "./chatThreadTypes";
import type { ThreadUsageStats } from "./chatUsageTypes";
import type { SelectedWorkspace } from "./chatWorkspaceTypes";

export type ChatState = {
  currentUser: {
    id: string;
    username: string;
    email?: string;
    displayName?: string;
    roles: string[];
  };
  branding?: {
    app_name: string;
    logo_url: string;
    logo_svg: string;
    // Platform feature switch (server config only); off renders the built-in defaults.
    enabled?: boolean;
  };
  launchSurface?: ChatLaunchSurface;
  activeThreadGroups: ThreadGroup[];
  archivedThreadCount: number;
  archivedThreads: ThreadSummary[];
  selectedSession: SelectedSession | null;
  // The address asked for a chat this person cannot open (missing, or not theirs); no other chat is opened instead.
  requestedSessionNotFound?: boolean;
  selectedSessionIsArchived: boolean;
  selectedSessionIsRunning: boolean;
  selectedMessages: ChatMessage[];
  selectedMessagesHasMore?: boolean;
  selectedProject: ProjectOption | null;
  selectedProjectId: string;
  runtimeOptions: RuntimeOption[];
  selectedRuntimeTargetId: string;
  selectedRuntimeLabel: string;
  selectedThinkingLevel: string;
  selectedAgentId: string;
  selectedAgentName: string;
  selectedAgentType: string;
  selectedAgentSelectionSource?: string;
  agentModes: AgentModeOption[];
  projects: ProjectOption[];
  traceEvents: ToolEvent[];
  traceEventCount: number;
  selectedThreadStats: ThreadUsageStats | null;
  selectedThreadContext?: SerializedThreadContext | null;
  selectedApprovals: ApprovalSummary[];
  selectedWorkspace?: SelectedWorkspace | null;
  newThread: boolean;
  settingsUrl: string;
  toolsUrl: string;
  controlPlaneUrl: string;
  dashboardUrl: string;
  agentOptions: ChatAgentOption[];
  agentGroups?: AgentGroupOption[];
  chatAgentGuidance?: ChatAgentGuidance | null;
};
