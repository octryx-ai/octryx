import type { PolicyVersion } from "./policyEngineVersions";
import { relativeTime } from "./policyCatalogModel";

// The draft bar: only while a draft or a version in review exists — the change count against
// the published version, the saved test cases' result, who saved it, and the next lifecycle step, which opens the
// lifecycle drawer (changes, checks, note, review, history).
export function PolicyDraftBar({ working, publishedVersion, changeCount, authorName, selfApproval = false, onLifecycle }: {
  working: PolicyVersion;
  publishedVersion: number | null;
  changeCount: number;
  authorName: string;
  /** The approval rule lets the author publish in one step (no second admin). */
  selfApproval?: boolean;
  onLifecycle: () => void;
}) {
  const review = working.state === "in_review";
  const report = working.testReport;
  const tests = report ? (report.total ? `${report.passed}/${report.total} test cases pass` : "no saved test cases") : "test cases not run";
  const against = publishedVersion !== null ? `against published v${publishedVersion}` : "· nothing published yet";
  const saved = [authorName ? `by ${authorName}` : "", relativeTime(working.updatedAt)].filter(Boolean).join(", ");
  return (
    <div className="policies__draft-bar" data-testid="policy-draft-bar">
      <div className="policies__row">
        <span className={`work-badge ${review ? "work-badge--running" : "work-badge--attention"}`}>{review ? "In review" : "Draft"} v{working.version}</span>
        <span>
          <strong>{changeCount} change{changeCount === 1 ? "" : "s"}</strong> {against} ·{" "}
          <span className={report && !report.ok ? "policies__fail" : ""}>{tests}</span>
          {review ? (selfApproval ? " · ready to publish" : " · waiting for another platform admin") : saved ? ` · last saved ${saved}` : ""}
        </span>
      </div>
      <div className="policies__row">
        <button type="button" className="admin-panel__action-btn" data-testid="draft-review" onClick={onLifecycle}>Review changes</button>
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="draft-next" onClick={onLifecycle}>
          {review ? "Review & publish" : selfApproval ? "Publish" : "Submit for review"}
        </button>
      </div>
    </div>
  );
}
