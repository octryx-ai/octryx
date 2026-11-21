import { useEffect, useState } from "react";

import { readJson } from "../../utils/adminPanelHelpers";

// The platform approval rule (backend `services/governance/approval_rule.py`, Settings → Governance → "Approval rule").
// Every four-eyes surface reads it: when an author may approve their own change, it offers the single-step
// "Publish" (`self_approve: true` on the publish request) instead of "Submit for review" + a second admin.

export const APPROVAL_RULE_PATH = "/api/v1/admin/governance/approval-rule";

export type ApprovalRuleValue = "four_eyes" | "single_admin";

export type ApprovalRule = {
  rule: ApprovalRuleValue;
  label: string;
  options: { value: ApprovalRuleValue; label: string }[];
  /** True when the author may approve their own change now (the rule, or the development exception). */
  selfApprovalAllowed: boolean;
  /** `approval_rule` (the setting) or `dev_flag` (OCTRYX_FOUR_EYES_DEV_SELF_APPROVAL on a local stack). */
  selfApprovalSource: "approval_rule" | "dev_flag" | null;
};

export const FOUR_EYES_RULE: ApprovalRule = {
  rule: "four_eyes",
  label: "Four-eyes (a second admin approves)",
  options: [],
  selfApprovalAllowed: false,
  selfApprovalSource: null,
};

const isRule = (value: unknown): value is ApprovalRuleValue => value === "four_eyes" || value === "single_admin";

export function readApprovalRule(raw: unknown): ApprovalRule {
  const record = raw && typeof raw === "object" ? (raw as Record<string, unknown>) : {};
  const rule = isRule(record.rule) ? record.rule : "four_eyes";
  const options = Array.isArray(record.options)
    ? record.options.flatMap((item) => {
        const option = item && typeof item === "object" ? (item as Record<string, unknown>) : {};
        return isRule(option.value) ? [{ value: option.value, label: String(option.label ?? option.value) }] : [];
      })
    : [];
  const source = record.self_approval_source;
  return {
    rule,
    label: typeof record.label === "string" && record.label ? record.label : rule,
    options,
    selfApprovalAllowed: record.self_approval_allowed === true,
    selfApprovalSource: source === "approval_rule" || source === "dev_flag" ? source : null,
  };
}

export const loadApprovalRule = async () => readApprovalRule(await readJson<unknown>(APPROVAL_RULE_PATH));

export const saveApprovalRule = async (rule: ApprovalRuleValue) =>
  readApprovalRule(await readJson<unknown>(APPROVAL_RULE_PATH, { method: "PUT", body: JSON.stringify({ rule }) }));

/** The rule for a publish surface; four-eyes until it loaded (and when it cannot be read: fail closed). */
export function useApprovalRule(): ApprovalRule {
  const [rule, setRule] = useState<ApprovalRule>(FOUR_EYES_RULE);
  useEffect(() => {
    let alive = true;
    loadApprovalRule().then((loaded) => { if (alive) setRule(loaded); }, () => undefined);
    return () => { alive = false; };
  }, []);
  return rule;
}

/** The short mode text for badges and histories. */
export const approvalModeBadgeText = (rule: ApprovalRule) =>
  rule.selfApprovalAllowed ? "Single admin: self-approval on" : "Four-eyes approval";

/** "self-approved" for a version an author approved themselves (`approval_mode: "self"`), else null. */
export const approvalModeHistoryText = (mode: unknown) => (mode === "self" ? "self-approved" : null);
