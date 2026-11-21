// Observability → Decisions: every non-allow outcome of every gate plus the approval lifecycle.
import type { AdminTab } from "../../types/adminPanelTypes.governance";
import type { BadgeTone } from "./obUi";

export type DecisionItem = {
  id: string;
  time: string | null;
  outcome: string;
  gate: string;
  action: string;
  what: string;
  /** Why it was asked, in words (same text as the approval card); the raw codes stay in what_code / rule_code. */
  subtitle?: string | null;
  what_code?: string | null;
  who: string;
  decided_by: string | null;
  workspace_id: string | null;
  workspace_name: string | null;
  rule: string | null;
  rule_code?: string | null;
  reason: string | null;
  mode: string;
  session_id: string | null;
  run_key: string | null;
  approval_id: string | null;
  determining_policies: string[];
  content: Record<string, unknown> | null;
  obligation: Record<string, unknown> | null;
};

export type DecisionDetail = DecisionItem & { run_exists: boolean; lifecycle: DecisionItem[] };
export type DecisionPage = { window_hours: number; page: number; page_size: number; total: number; items: DecisionItem[] };
export type DecisionsToday = { by_outcome: Record<string, number>; total: number; allowed: number };

export const DECISION_OUTCOMES = ["denied", "needs_approval", "approved", "rejected", "expired", "remedied", "reported"];

export const GATE_LABELS: Record<string, string> = {
  cedar: "Policy (Cedar)",
  tool_policy: "Tool policy",
  tool_approval: "Tool approval",
  mcp_access: "MCP access",
  execution_gate: "Execution gate",
  runtime_readiness: "Runtime readiness",
  content_routing: "Content routing",
  content_security: "Content security",
  device_job: "Device job",
  governance_review: "Governance review",
};

// Where each gate's rules are declared; Decisions never edits a rule itself.
export type EditTarget = { label: string; tab?: AdminTab; href?: string };
export const EDIT_TARGETS: Record<string, EditTarget> = {
  // Today's navigation (wiki check): Admin › <entry> › <view>, Agents › <view>.
  cedar: { label: "Admin › Rules › Policies", tab: "cedarPolicies" },
  tool_policy: { label: "Admin › Rules › Tool & approval policies", tab: "policies" },
  tool_approval: { label: "Admin › Rules › Tool & approval policies", tab: "policies" },
  mcp_access: { label: "Admin › Connections › MCP servers", tab: "mcp" },
  execution_gate: { label: "Agents › Workflows", tab: "workflowList" },
  runtime_readiness: { label: "Admin › Models › Providers", tab: "providers" },
  content_routing: { label: "Admin › Rules › Classification", tab: "classificationPolicy" },
  // The shipped platform content policies are listed in Content security.
  content_security: { label: "Admin › Rules › Content security", tab: "contentSecurity" },
  device_job: { label: "Agents › Connected clients", href: "/chat?area=agents" },
  governance_review: { label: "Admin › Rules › Approval rule", tab: "approvalRule" },
};

export function decisionOutcomeLabel(outcome: string): string {
  const words = outcome.replace(/_/g, " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function decisionTone(outcome: string): BadgeTone {
  if (outcome === "denied" || outcome === "rejected" || outcome === "error") return "danger";
  if (outcome.startsWith("needs_") || outcome === "mismatch" || outcome === "dropped") return "attention";
  if (outcome === "approved") return "active";
  if (outcome === "remedied" || outcome === "would_remedy") return "running";
  return "neutral";
}

export function gateLabel(gate: string): string {
  return GATE_LABELS[gate] ?? gate;
}

export function decisionsQuery(params: {
  windowHours: number;
  outcome: string;
  gate: string;
  workspaceId: string;
  policyId: string;
  page: number;
}): string {
  const search = new URLSearchParams({ window_hours: String(params.windowHours), page: String(params.page) });
  if (params.outcome) search.set("outcome", params.outcome);
  if (params.gate) search.set("gate", params.gate);
  if (params.workspaceId) search.set("workspace_id", params.workspaceId);
  if (params.policyId) search.set("policy_id", params.policyId);
  return `/api/v1/observability/decisions?${search.toString()}`;
}

/** `?decision=<id>` (refusal links and content notices), `?policy=<id>` (Policies → Show decisions) and `?outcome=<outcome>`. */
export function readDecisionParams(search: string): { decision: string | null; policy: string; outcome: string } {
  const params = new URLSearchParams(search);
  const decision = params.get("decision");
  const outcome = params.get("outcome") ?? "";
  return {
    decision: decision && /^[A-Za-z0-9-]{1,64}$/.test(decision) ? decision : null,
    policy: (params.get("policy") ?? "").slice(0, 200),
    outcome: /^[a-z_]{1,20}$/.test(outcome) ? outcome : "",
  };
}

/** The link a refusal carries (`decision_id`) to its record in Observability → Decisions. */
export const decisionRecordHref = (id: string) =>
  `/chat?area=operations&tab=observabilityDecisions&decision=${encodeURIComponent(id)}`;

/** Policies → "Show decisions": the timeline filtered to one policy. */
export const policyDecisionsHref = (policyId: string) =>
  `/chat?area=operations&tab=observabilityDecisions&policy=${encodeURIComponent(policyId)}`;
