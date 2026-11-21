// Classification policy versions: draft, review, test report, version list and refusal texts.
import { readEffects } from "./classificationEffectsModel";
import { readCatalog, type CatalogLevel } from "./classificationLevelCatalog";
import type { LevelRules } from "./classificationMatrixRows";
import { isRecord, list, text } from "./classificationValueReaders";

export type ChangeLine = { level: string | null; rule: string; text: string };
export type TestReport = { total: number; failed: number; ok: boolean };
export type Review = { status: string; comment: string; canApprove: boolean };
export type VersionRow = {
  version: number;
  state: string;
  note: string | null;
  defaultLevel: string | null;
  changes: ChangeLine[];
  author: string | null;
  approvedBy: string | null;
  publishedAt: string | null;
  testReport: TestReport | null;
  review: Review | null;
};
export type DraftView = VersionRow & {
  levels: LevelRules[];
  levelCatalog: CatalogLevel[] | null;
  added: string[];
  removed: string[];
  affectedWorkspaces: number;
};
export type VersionsView = {
  effects: ReturnType<typeof readEffects>;
  publishedVersion: number | null;
  draft: DraftView | null;
  versions: VersionRow[];
  approvalRule: string;
  selfApproval: boolean;
};


function readReport(value: unknown): TestReport | null {
  if (!isRecord(value)) return null;
  return { total: Number(value.total) || 0, failed: Number(value.failed) || 0, ok: value.ok === true };
}

function readVersion(value: unknown): VersionRow | null {
  if (!isRecord(value) || typeof value.version !== "number") return null;
  const review = isRecord(value.review) ? value.review : null;
  return {
    version: value.version,
    state: text(value.state),
    note: text(value.note) || null,
    defaultLevel: text(value.default_level) || null,
    changes: list(value.changes).filter(isRecord).map((line) => ({
      level: text(line.level) || null, rule: text(line.rule), text: text(line.text),
    })),
    author: text(value.author) || null,
    approvedBy: text(value.approved_by) || null,
    publishedAt: text(value.published_at) || null,
    testReport: readReport(value.test_report),
    review: review ? { status: text(review.status), comment: text(review.comment), canApprove: review.can_approve === true } : null,
  };
}

export function readVersions(payload: unknown): VersionsView | null {
  if (!isRecord(payload)) return null;
  const draftRecord = isRecord(payload.draft) ? payload.draft : null;
  const draftBase = draftRecord ? readVersion(draftRecord) : null;
  const diff = draftRecord && isRecord(draftRecord.policy_diff) ? draftRecord.policy_diff : {};
  return {
    effects: readEffects(payload),
    publishedVersion: typeof payload.published_version === "number" ? payload.published_version : null,
    draft: draftRecord && draftBase ? {
      ...draftBase,
      levels: list(draftRecord.levels).filter(isRecord).map((item) => ({ level: text(item.level), rules: isRecord(item.rules) ? { ...item.rules } : {} })),
      levelCatalog: readCatalog(draftRecord.level_catalog),
      added: list(diff.added).map(text),
      removed: list(diff.removed).map(text),
      affectedWorkspaces: Number(draftRecord.affected_workspaces) || 0,
    } : null,
    versions: list(payload.versions).map(readVersion).filter((row): row is VersionRow => row !== null),
    approvalRule: text(payload.approval_rule) || "four_eyes",
    selfApproval: payload.self_approval === true,
  };
}

/** The draft bar sentence. */
export function draftBarText(view: VersionsView | null): string {
  const against = view?.publishedVersion ? `published version ${view.publishedVersion}` : "the live policy";
  const draft = view?.draft;
  if (!draft) return `No changes against ${against}`;
  if (draft.state === "in_review") {
    return draft.review?.canApprove ? "Submitted for review · you can approve it" : "Submitted for review · waiting for a second admin";
  }
  const count = draft.changes.length;
  const parts = [`${count} ${count === 1 ? "change" : "changes"} against ${against}`];
  if (draft.testReport) parts.push(`${draft.testReport.total - draft.testReport.failed}/${draft.testReport.total} test cases pass`);
  parts.push(view?.selfApproval ? "you may publish it yourself (Approval rule: single admin)" : "needs a second admin");
  return parts.join(" · ");
}

export const STATE_BADGE: Record<string, { badge: string; label: string }> = {
  draft: { badge: "work-badge--attention", label: "Draft" },
  in_review: { badge: "work-badge--running", label: "In review" },
  published: { badge: "work-badge--active", label: "Published" },
  retired: { badge: "work-badge--neutral", label: "Retired" },
};

const VERSION_CODE_TEXT: Record<string, string> = {
  classification_draft_in_review: "the draft is in review; withdraw it before changing it",
  classification_draft_missing: "there is no open draft",
  classification_draft_unchanged: "the draft has no changes against the published version",
  classification_draft_tests_failed: "a saved policy test case fails with this draft",
  classification_self_approval_not_allowed: "under four-eyes another admin has to approve",
  classification_review_already_decided: "the review was already decided",
  classification_version_not_in_review: "the version is not in review",
  classification_default_level_unknown: "the level for new Workspaces is not a known level",
};

export function versionErrorText(error: unknown): string {
  const record = isRecord(error) ? error : null;
  if (record?.status === 403 && record.code !== "classification_self_approval_not_allowed") {
    return "Only platform admins can change the classification policy.";
  }
  const code = typeof record?.code === "string" ? record.code : "";
  const message = typeof record?.message === "string" ? record.message : "";
  return `Not done: ${VERSION_CODE_TEXT[code] ?? (message || "the request was refused")}.`;
}
