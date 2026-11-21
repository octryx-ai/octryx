import { SURFACES, SURFACE_LABELS } from "./skillCatalogTypes";
import { shortCommit, shortDigest } from "./skillCatalogModel";
import type { FileDiff } from "./skillDiffModel";
import type { Review, SkillDetail, SkillVersion } from "./skillCatalogTypes";
import { SkillDiff } from "./SkillDiff";
import { changeSummary, securityLine, timelineIndex, unacknowledgedHigh } from "./skillUpdateModel";

// Draft → In review → Published, with the current step marked and what each step waits for.
export function ReviewTimeline({ version, published, review, shown, blocked, selfApproval }: {
  version: SkillVersion | null;
  published: SkillVersion | null;
  review: Review | null;
  shown: SkillVersion;
  blocked: boolean;
  selfApproval: boolean;
}) {
  const stepAt = timelineIndex(version?.state ?? (published ? "published" : null));
  const step = (index: number, title: string, text: string) => {
    const className = index === stepAt ? " policies__timeline-step--current" : index < stepAt || (stepAt === 2 && !version) ? " policies__timeline-step--done" : "";
    return <div className={`policies__timeline-step${className}`}><b>{title}</b>{text}</div>;
  };
  return (
    <div className="policies__timeline">
      {step(0, "Draft", version?.state === "draft" ? (blocked ? "conflicts open" : "submit to freeze") : "frozen")}
      {step(1, "In review", version?.state === "in_review" ? `submitted by ${review?.submitter?.name ?? review?.requested_by?.name ?? "—"}` : version ? (selfApproval ? "you approve it yourself" : "a second platform admin approves") : "done")}
      {step(2, "Published", !version ? `v${shown.version} is live` : review?.status === "approved" ? `approved by ${review.decided_by?.name ?? "—"}` : selfApproval ? "publish in one step" : "needs a second admin")}
    </div>
  );
}

// The summary of the open version: change, path, digest, security, surfaces, changed files and findings.
export function ReviewSummary({ version, detail, diff }: { version: SkillVersion; detail: SkillDetail; diff: FileDiff[] | null }) {
  return (
    <section className="work-detail__section">
      <h3>Summary</h3>
      <dl className="work-detail__kv" data-testid="skill-review-summary">
        <dt>Change</dt><dd>{changeSummary(version, shortCommit)}</dd>
        {version.upstream ? (<><dt>Path</dt><dd className="skills__mono">{version.merge_report?.path_moved ? "→ " : ""}{version.upstream.path}</dd></>) : null}
        <dt>Digest</dt><dd className="skills__mono">{shortDigest(version.digest)} ({version.state === "draft" ? "frozen on submit" : "frozen"})</dd>
        <dt>Security</dt><dd>{securityLine(version, detail.new_findings ?? [])}</dd>
        <dt>Surfaces</dt>
        <dd><span className="skills__surfaces">
          {SURFACES.filter((surface) => version[`available_${surface}`]).map((surface) => (
            <span key={surface} className="work-badge work-badge--active">{SURFACE_LABELS[surface]}</span>
          ))}
          {SURFACES.every((surface) => !version[`available_${surface}`]) ? "none" : null}
        </span></dd>
        <dt>Files changed</dt>
        <dd>{diff === null ? "…" : diff.length ? diff.map((file) => `${file.path} +${file.added}/−${file.removed}`).join(" · ") : "none"}</dd>
      </dl>
      {(detail.new_findings ?? []).length ? (
        <ul className="skills__hint">{detail.new_findings.map((finding) => <li key={finding.id}><b>{finding.severity}</b> · {finding.message}{finding.file ? ` (${finding.file})` : ""}</li>)}</ul>
      ) : null}
      {unacknowledgedHigh(version).length ? (
        <div className="policies__warn" data-testid="skill-review-unacknowledged">
          Acknowledge these high findings in Security before publishing: {unacknowledgedHigh(version).map((finding) => finding.message).join("; ")}
        </div>
      ) : null}
    </section>
  );
}

// The full diff against the published version (or the contents of a first version).
export function ReviewChanges({ published, diff }: { published: SkillVersion | null; diff: FileDiff[] | null }) {
  return (
    <section className="work-detail__section">
      <h3>{published ? `Changes against published v${published.version}` : "Contents"}</h3>
      {diff === null ? <p className="skills__hint" role="status">Loading the diff…</p>
        : diff.length ? diff.map((file) => (
          <div key={file.path} className="admin-panel__stack">
            <span className="skills__mono">{file.path} (+{file.added} / −{file.removed})</span>
            <SkillDiff file={file} maxHeight="16rem" />
          </div>
        )) : <p className="skills__hint">No file changed.</p>}
    </section>
  );
}
