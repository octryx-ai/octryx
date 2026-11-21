// The automation eligibility of a Work Item in words. Pure: no React.
//
// The backend (services/secure_work/automation_eligibility.py) reports a mode, reason codes and the policy source as
// codes (`human_only`, `missing_acceptance_criteria`, `excluded_label:no-octryx`, `sync_config`). The detail shows them
// as plain language; a code this list does not know is shown in words, never dropped.

const MODES: Record<string, string> = {
  human_only: "Humans only",
  needs_review: "Suggest only",
  direct: "Agent may start",
  blocked: "Blocked",
};

const REASONS: Record<string, string> = {
  missing_description: "No description",
  missing_acceptance_criteria: "No acceptance criteria",
  missing_repository_evidence: "No repository named",
  "work_state:done": "Already done",
  "sync_state:removed_from_source_filter": "Removed from the Jira filter",
  "sync_state:failed": "Sync failed",
};

const POLICY_SOURCES: Record<string, string> = {
  sync_config: "Intake settings",
  default: "Default rules",
};

const words = (code: string) => {
  const text = code.replace(/[_:]+/g, " ").trim();
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
};

const has = (table: Record<string, string>, key: string) => Object.prototype.hasOwnProperty.call(table, key);

export function automationModeText(mode: string | null | undefined): string {
  const key = String(mode || "").trim();
  return has(MODES, key) ? MODES[key] : words(key);
}

export function automationReasonText(reason: string): string {
  const key = String(reason || "").trim();
  if (has(REASONS, key)) return REASONS[key];
  const excluded = key.match(/^excluded_label:(.+)$/);
  if (excluded) return `Excluded by the label "${excluded[1]}"`;
  return words(key);
}

export function automationReasonsText(reasons: string[] | null | undefined): string[] {
  return (reasons || []).map(automationReasonText).filter(Boolean);
}

export function automationPolicySourceText(source: string | null | undefined): string {
  const key = String(source || "").trim();
  return has(POLICY_SOURCES, key) ? POLICY_SOURCES[key] : words(key);
}
