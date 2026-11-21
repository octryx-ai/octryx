// The update review and the review drawer model: pure helpers for the 3-way conflict view, the merge KPIs,
// resolutions, upstream-update refusals and the four-eyes lifecycle state. Unit-tested in
// tests/unit/skillUpdateModel.test.mjs.
import type { Conflict, Finding, MergeReport, Resolution, Review, SkillVersion } from "./skillCatalogTypes";
import type { FileDiff } from "./skillDiffModel";

export type MarkedLine = { text: string; mark: "" | "loc" | "add" };

/** A merge line without its trailing newline (the merge keeps `\n` on every line). */
export function lineText(line: string): string {
  return line.replace(/\r?\n$/, "");
}

/** Lines of `side` that are not in `base` (longest common subsequence), marked with `mark`. */
export function markChanged(base: string[], side: string[], mark: "loc" | "add"): MarkedLine[] {
  const a = base.map(lineText);
  const b = side.map(lineText);
  const table: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0));
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      table[i][j] = a[i] === b[j] ? table[i + 1][j + 1] + 1 : Math.max(table[i + 1][j], table[i][j + 1]);
    }
  }
  const common = new Set<number>();
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      common.add(j);
      i += 1;
      j += 1;
    } else if (table[i + 1][j] >= table[i][j + 1]) i += 1;
    else j += 1;
  }
  return b.map((text, index) => ({ text, mark: common.has(index) ? "" : mark }));
}

export const FILE_STATUS_LABELS: Record<string, { label: string; tone: string }> = {
  unchanged: { label: "unchanged", tone: "neutral" },
  same_change: { label: "same change on both sides", tone: "neutral" },
  added_upstream: { label: "added upstream", tone: "running" },
  removed_upstream: { label: "removed upstream", tone: "attention" },
  took_upstream: { label: "changed upstream only", tone: "running" },
  kept_local: { label: "local change kept", tone: "active" },
  merged: { label: "merged", tone: "active" },
  conflict: { label: "conflict", tone: "attention" },
};

export function fileStatus(status: string): { label: string; tone: string } {
  return FILE_STATUS_LABELS[status] ?? { label: status.replace(/_/g, " "), tone: "neutral" };
}

export type MergeKpis = {
  commits: string;
  filesChanged: number;
  mergedLocal: number;
  upstreamHunks: number;
  conflicts: number;
  open: number;
  resolved: number;
};

export function mergeKpis(report: MergeReport, shortCommit: (commit: string | null) => string): MergeKpis {
  const changed = report.files.filter((file) => file.status !== "unchanged" && file.status !== "same_change");
  const open = report.conflicts.filter((conflict) => !report.resolutions?.[conflict.id]).length;
  return {
    commits: `${shortCommit(report.base_commit)} → ${shortCommit(report.theirs_commit)}`,
    filesChanged: changed.length,
    mergedLocal: report.files.reduce((sum, file) => sum + (file.local_hunks ?? 0) + (file.status === "kept_local" ? 1 : 0), 0),
    upstreamHunks: report.files.reduce((sum, file) => sum + (file.upstream_hunks ?? 0), 0),
    conflicts: report.conflicts.length,
    open,
    resolved: report.conflicts.length - open,
  };
}

/** The `resolutions` body of `PUT …/versions/{v}`: every saved resolution plus the new one. */
export function withResolution(report: MergeReport, conflictId: string, resolution: Resolution): Record<string, Resolution> {
  return { ...(report.resolutions ?? {}), [conflictId]: resolution };
}

export function resolutionIssue(resolution: Resolution, conflict: Conflict): string | null {
  if (resolution.choice === "manual" && !(resolution.text ?? "").trim()) return "Write the merged text first.";
  if (resolution.choice === "relocate" && !conflict.relocation) return "This conflict cannot be applied in another file.";
  return null;
}

export function resolutionLabel(resolution: Resolution | undefined, conflict: Conflict): string {
  if (!resolution) return "Open";
  if (resolution.choice === "relocate") return `Your change applied in ${conflict.relocation?.path ?? "the new place"}`;
  if (resolution.choice === "upstream") return "Upstream taken";
  if (resolution.choice === "mine") return "Your lines kept";
  return "Edited by hand";
}

/** The merged files worth previewing: SKILL.md, files upstream added, and relocation targets. */
export function previewPaths(report: MergeReport, filePaths: string[]): string[] {
  const wanted = new Set<string>(["SKILL.md"]);
  for (const file of report.files) if (file.status === "added_upstream") wanted.add(file.path);
  for (const conflict of report.conflicts) if (conflict.relocation) wanted.add(conflict.relocation.path);
  const present = new Set(filePaths);
  return [...wanted].filter((path) => present.has(path)).sort((a, b) => (a === "SKILL.md" ? -1 : b === "SKILL.md" ? 1 : a.localeCompare(b)));
}

export type UpdateFailure = "path_missing" | "draft_exists" | "up_to_date" | "other";

export function updateFailure(error: unknown): UpdateFailure {
  const code = error && typeof error === "object" ? (error as { code?: unknown }).code : null;
  if (code === "skill_upstream_path_missing") return "path_missing";
  if (code === "skill_draft_exists") return "draft_exists";
  if (code === "skill_up_to_date") return "up_to_date";
  return "other";
}

/** Changed files of a `…/diff` response with their +/- counts. */
export function changedFiles(files: FileDiff[]): FileDiff[] {
  return files.filter((file) => file.status !== "unchanged");
}

// ---- review drawer ---------------------------------------------------------------------------------------------

/** 0 Draft, 1 In review, 2 Published (index of the current timeline step). */
export function timelineIndex(state: string | null | undefined): number {
  return state === "draft" ? 0 : state === "in_review" ? 1 : 2;
}

export function changeSummary(version: SkillVersion, shortCommit: (commit: string | null) => string): string {
  if (version.merge_report) return `Upstream ${shortCommit(version.merge_report.theirs_commit)} + local customizations`;
  if (version.note) return version.note;
  if (version.version === 1 && !version.base_version) return "New skill";
  return version.base_version ? `Edited from v${version.base_version}` : "—";
}

export type ReviewAction = "submit" | "approve" | "publish" | "publish_own" | null;

/** The one primary action of the drawer; approve only for a viewer the server allows to approve. Under the
 * single-admin approval rule (`selfApproval`) a draft or a pending review is published in one step (`publish_own`). */
export function reviewAction(version: SkillVersion | null, review: Review | null, selfApproval = false): ReviewAction {
  if (!version) return null;
  if (version.state === "draft") return selfApproval ? "publish_own" : "submit";
  if (version.state !== "in_review" || !review) return null;
  if (review.status === "approved") return "publish";
  if (review.status === "pending" && selfApproval) return "publish_own";
  if (review.status === "pending" && review.viewer.can_approve) return "approve";
  return null;
}

/** High findings of the version that are not acknowledged yet (publishing refuses them). */
export function unacknowledgedHigh(version: SkillVersion): Finding[] {
  const acknowledged = new Set(version.acknowledged_findings ?? []);
  return (version.security_report?.findings ?? []).filter((finding) => finding.severity === "high" && !acknowledged.has(finding.id));
}

export function securityLine(version: SkillVersion, newFindings: Finding[]): string {
  const summary = version.security_report?.summary ?? { high: 0, medium: 0, info: 0 };
  const counts = `${summary.high} high · ${summary.medium} medium · ${summary.info} info`;
  if (!newFindings.length) return `${counts} · no new findings`;
  return `${counts} · ${newFindings.length} new against the published version`;
}

export function waitingReason(review: Review): string {
  if (review.viewer.is_author && review.viewer.is_submitter) return "You authored and submitted this version.";
  if (review.viewer.is_author) return "You authored this version.";
  if (review.viewer.is_submitter) return "You submitted this version.";
  if (review.status !== "pending") return `The review is ${review.status}.`;
  return "Your account cannot approve this version.";
}

export function names(people: { name: string }[]): string {
  return people.length ? people.map((person) => person.name).join(", ") : "no other platform admin";
}
