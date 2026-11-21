// Cedar policy engine model: policy set versions, their test reports and issues, the diff summary and refusals.
import { isRecord, num, optNum, str, strs } from "./policyEngineValues";

export type TestResult = { id: string; name: string; expected: string; actual: string; passed: boolean; determining: string[] };
export type TestReport = { passed: number; failed: number; total: number; results: TestResult[]; ok: boolean };

export function readTestReport(raw: unknown): TestReport | null {
  if (!isRecord(raw)) return null;
  const results = (Array.isArray(raw.results) ? raw.results : []).filter(isRecord).map((item) => ({
    id: str(item.id),
    name: str(item.name),
    expected: str(item.expected),
    actual: str(item.actual),
    passed: item.passed === true,
    determining: strs(item.determining),
  }));
  const failed = results.filter((item) => !item.passed).length;
  return { passed: results.length - failed, failed, total: results.length, results, ok: failed === 0 };
}

export type PolicyVersion = {
  version: number;
  state: string;
  digest: string;
  policyIds: string[];
  note: string;
  baseVersion: number | null;
  createdBy: string;
  createdAt: string;
  updatedAt: string;
  submittedBy: string;
  approvalId: string | null;
  publishedAt: string;
  policies: string | null;
  testReport: TestReport | null;
};

export function readVersion(raw: unknown): PolicyVersion | null {
  if (!isRecord(raw) || optNum(raw.version) === null) return null;
  return {
    version: num(raw.version),
    state: str(raw.state),
    digest: str(raw.digest),
    policyIds: strs(raw.policy_ids),
    note: str(raw.note),
    baseVersion: optNum(raw.base_version),
    createdBy: str(raw.created_by),
    createdAt: str(raw.created_at),
    updatedAt: str(raw.updated_at) || str(raw.created_at),
    submittedBy: str(raw.submitted_by),
    approvalId: str(raw.approval_id) || str(raw.governance_approval_id) || null,
    publishedAt: str(raw.published_at),
    policies: typeof raw.policies === "string" ? raw.policies : null,
    testReport: readTestReport(raw.test_report),
  };
}

export function readVersions(raw: unknown): PolicyVersion[] {
  const items = isRecord(raw) && Array.isArray(raw.items) ? raw.items : [];
  return items.map(readVersion).filter((item): item is PolicyVersion => item !== null);
}

export const publishedVersion = (versions: PolicyVersion[]) => versions.find((item) => item.state === "published") ?? null;
export const openDraft = (versions: PolicyVersion[]) => versions.find((item) => item.state === "draft") ?? null;
export const inReview = (versions: PolicyVersion[]) => versions.find((item) => item.state === "in_review") ?? null;

export type PolicyIssue = { policyId: string; code: string; message: string; line: number | null };

export function readIssues(raw: unknown): PolicyIssue[] {
  const list = isRecord(raw) && Array.isArray(raw.issues) ? raw.issues : [];
  return list.filter(isRecord).map((item) => ({
    policyId: str(item.policy_id),
    code: str(item.code),
    message: str(item.message),
    line: optNum(item.line),
  }));
}

/** Changed lines between the published text and the draft, for the summary next to the diff view. */
export function diffSummary(base: string, draft: string): { added: number; removed: number } {
  const count = (lines: string[]) => lines.reduce((map, line) => map.set(line, (map.get(line) ?? 0) + 1), new Map<string, number>());
  const before = count(base.split("\n"));
  const after = count(draft.split("\n"));
  let added = 0;
  let removed = 0;
  for (const [line, times] of after) added += Math.max(0, times - (before.get(line) ?? 0));
  for (const [line, times] of before) removed += Math.max(0, times - (after.get(line) ?? 0));
  return { added, removed };
}

const REFUSALS: Record<string, string> = {
  policy_set_invalid: "The policies do not validate; fix the marked lines.",
  policy_set_too_large: "The policy text is too long (200,000 characters at most).",
  policy_set_templates_not_allowed: "Templates (?principal / ?resource) are not supported.",
  policy_set_version_not_draft: "Only a draft can be changed.",
  policy_set_version_not_in_review: "Submit the draft for review first.",
  policy_set_approval_required: "Publishing needs the review approval.",
  policy_set_approval_not_approved: "The review is not approved yet: another platform admin has to approve it.",
  policy_set_approval_mismatched: "The approval belongs to other content; submit again.",
  policy_set_self_approval: "Four-eyes: the author or submitter cannot approve their own policy set (Settings → Governance → Approval rule).",
  policy_set_approver_not_platform_admin: "The approver must be a platform admin.",
  policy_set_tests_failed: "Saved test cases fail with this version; publishing is blocked.",
  policy_set_retire_requires_review: "The published version is retired only through review: publish an empty draft.",
  policy_engine_mode_invalid: "Unknown mode.",
  policy_engine_enforce_not_ready: "Enforcement is not ready yet.",
  approval_already_resolved: "The review was already decided.",
  policy_set_draft_conflict: "Someone else changed the draft meanwhile. The page reloaded it: check the change and save again.",
  policy_set_draft_exists: "A draft already exists: edit the policy in that draft.",
  policy_set_version_not_editable: "The draft is in review and frozen: withdraw it or wait for the review.",
  policy_set_if_match_required: "The page lost track of the draft version; reload and save again.",
  policy_id_exists: "A policy with this @id already exists; choose another name or @id.",
  policy_not_found: "That policy is no longer in the draft.",
  policy_builder_model_invalid: "The builder input is incomplete; fix the marked steps.",
  policy_cedar_statement_invalid: "Write exactly one Cedar policy with an @id.",
  policy_edit_body_invalid: "The request was incomplete.",
};

export function refusalText(error: unknown): string {
  const value = isRecord(error) ? error : {};
  const code = str(value.code);
  if (code && REFUSALS[code]) return REFUSALS[code];
  if (num(value.status) === 403) return "Platform admin role required.";
  const message = error instanceof Error ? error.message : str(value.message);
  return message ? `Refused: ${message}.` : "The request failed.";
}
