import type { RunReport } from "./connectorTypes";

// A Git repository run report as per-file outcome counts and the commit the run read. The skipped total is split by
// its fixed reasons (skipped_reasons); a skipped remainder without a known reason is shown as "other skipped".

export type CountPart = { key: string; label: string; count: number };

// Always shown, also when zero: what happened to the repository's files in this run.
const OUTCOMES = ["created", "updated", "unchanged"] as const;
const SKIP_REASONS: Array<{ key: string; label: string; always: boolean }> = [
  { key: "excluded", label: "excluded", always: true },
  { key: "skipped_binary", label: "skipped binary", always: true },
  { key: "skipped_too_large", label: "skipped too large", always: true },
  { key: "skipped_unsupported_path", label: "skipped unsupported path", always: false },
  { key: "skipped_empty", label: "skipped empty", always: false },
  { key: "path_too_long", label: "skipped path too long", always: false },
];
// Only shown when non-zero.
const RARE_OUTCOMES = ["failed", "retired"] as const;

const SHORT_SHA = 12;

export function gitRunCounts(report: RunReport): CountPart[] {
  const reasons = report.skipped_reasons ?? {};
  const parts: CountPart[] = OUTCOMES.map((key) => ({ key, label: key, count: report[key] ?? 0 }));
  for (const reason of SKIP_REASONS) {
    const count = reasons[reason.key] ?? 0;
    if (reason.always || count > 0) parts.push({ key: reason.key, label: reason.label, count });
  }
  const known = SKIP_REASONS.reduce((sum, reason) => sum + (reasons[reason.key] ?? 0), 0);
  const otherSkipped = (report.skipped ?? 0) - known;
  if (otherSkipped > 0) parts.push({ key: "skipped", label: "other skipped", count: otherSkipped });
  for (const key of RARE_OUTCOMES) {
    const count = report[key] ?? 0;
    if (count > 0) parts.push({ key, label: key, count });
  }
  return parts;
}

// "3 created · 0 updated · ...": every count part in its fixed order.
export function gitRunCountsText(report: RunReport): string {
  return gitRunCounts(report).map((part) => `${part.count} ${part.label}`).join(" · ");
}

// The ref the run asked for and the commit it read (12-character sha), or null before a ref was resolved.
export function gitRunRevision(report: RunReport): { ref: string; commit: string } | null {
  const repository = report.repository;
  if (!repository?.commit) return null;
  return { ref: repository.ref ?? "", commit: repository.commit.slice(0, SHORT_SHA) };
}
