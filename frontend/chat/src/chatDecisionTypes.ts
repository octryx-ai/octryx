// `reason` lives only in the session metadata; the closed turn execution summary never carries it.
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
  // The wire shapes of `start` and `started` are snake_case from `phased_start.py`.
  phased?: boolean;
  start?: unknown;
  started?: unknown;
};

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
  approvedByName?: string | null;
  action: string;
  status: string;
  reason?: string | null;
  createdAt: string | null;
  resolvedAt?: string | null;
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
