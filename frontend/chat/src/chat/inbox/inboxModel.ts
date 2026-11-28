import { resolveAdminAreaForTab } from "../../admin/config/adminPanelAreas";
import type { AdminTab } from "../../admin/types/adminPanelTypes.governance";

export type InboxLink = { href?: string; tab?: AdminTab; label: string };
export type InboxItem = {
  kind:
    | "tool_approval"
    | "governance_review"
    | "device_approval"
    | "clarification"
    | "workflow_run_paused"
    | "workflow_run_confirmation"
    | "workflow_run_spec_approval"
    | "workflow_run_review_own_pr"
    | "workflow_run_approval"
    | "workflow_run_acceptance"
    | "workflow_run_audience_receipt"
    | "workflow_run_role_decision"
    | "workflow_handoff";
  id: string;
  title: string;
  subtitle: string;
  created_at: string | null;
  expires_at?: string | null;
  link: InboxLink;
  proof_action?: { challenge_id: string };
  decision_action?: { run_id: string };
  handoff_action?: { handoff_id: string };
};
export type InboxPayload = { waiting: InboxItem[]; requested_by_me: InboxItem[]; count: number };

export const INBOX_KIND_LABELS: Record<InboxItem["kind"], string> = {
  tool_approval: "! decide",
  governance_review: "! review",
  device_approval: "! device",
  clarification: "? answer",
  workflow_run_paused: "! run paused",
  workflow_run_confirmation: "! confirm",
  workflow_run_spec_approval: "! approve spec",
  workflow_run_review_own_pr: "! review PR",
  workflow_run_approval: "! approve",
  workflow_run_acceptance: "! functional acceptance",
  workflow_run_audience_receipt: "! audience check",
  workflow_run_role_decision: "! decide",
  workflow_handoff: "! handoff",
};

export function readInbox(payload: unknown): InboxPayload | null {
  if (!payload || typeof payload !== "object") return null;
  const value = payload as Partial<InboxPayload>;
  if (!Array.isArray(value.waiting) || !Array.isArray(value.requested_by_me)) return null;
  return { waiting: value.waiting, requested_by_me: value.requested_by_me, count: Number(value.count ?? value.waiting.length) };
}

export function inboxHref(link: InboxLink): string {
  if (link.href) return link.href;
  if (link.tab) return `/chat?area=${resolveAdminAreaForTab(link.tab)}&tab=${encodeURIComponent(link.tab)}`;
  return "/chat";
}
