// Workflow proposals and approval views a person decides on in a chat.

// The current turn's workflow proposal, from the thread's own session
// metadata. `reason` is the proposal model's short explanation; the closed
// turn execution summary never carries it.
export type WorkflowProposalView = {
  proposalId: string | null;
  status: "needs_confirmation" | "none" | "disabled" | string;
  reasonCode: string | null;
  workflowKey: string | null;
  workflowTitle: string | null;
  confidence: string | null;
  reason: string | null;
  changeCapable: boolean | null;
  decision: "apply" | "skip" | null;
  // A phased workflow starts as a workflow run for a Work item after one start card (`run/workflowStartModel.ts`
  // reads `start` and `started`; their wire shapes are snake_case from `phased_start.py`).
  phased?: boolean;
  start?: unknown;
  started?: unknown;
};

// The scope a tool approval's "Always for this Workspace" would grant.
export type StandingRuleView = {
  toolName: string;
  argumentClass: string | null;
};

export type ApprovalSummary = {
  id: string;
  taskRunId?: string | null;
  sessionId?: string | null;
  requestedBy: string;
  approvedBy?: string | null;
  // The decider's display name, when the payload carries one.
  approvedByName?: string | null;
  action: string;
  status: string;
  reason?: string | null;
  createdAt: string | null;
  resolvedAt?: string | null;
  // The approval in words, served for every approval: what runs where, why the person is asked, and the
  // preview's detail lines readable. The preview below keeps its machine fields.
  title?: string | null;
  subtitle?: string | null;
  details?: string[] | null;
  changePreview?: {
    id: string;
    taskRunId?: string | null;
    sessionId?: string | null;
    approvalId?: string | null;
    toolName?: string | null;
    requestFingerprint?: string | null;
    preview?: Record<string, unknown> | null;
    acknowledgedBy?: string | null;
    acknowledgedAt?: string | null;
    createdAt?: string | null;
    updatedAt?: string | null;
  } | null;
  // Null when "Always for this Workspace" is not offered for this approval.
  standingRule?: StandingRuleView | null;
};
