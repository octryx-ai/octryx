import type { ReactNode } from "react";

import { STATE_LABELS, hasOpenConflicts, shortCommit, stateBadge } from "./skillCatalogModel";
import type { FileDiff } from "./skillDiffModel";
import type { MergeReport, Resolution, SkillDetail, SkillVersion } from "./skillCatalogTypes";
import { SkillConflictCard } from "./SkillConflictCard";
import { SkillDiff } from "./SkillDiff";
import { SkillUpdateFiles } from "./SkillUpdateFiles";
import { SkillUpdateStart } from "./SkillUpdateStart";
import { mergeKpis } from "./skillUpdateModel";
import { skillUpdateActions, useSkillUpdateState } from "./useSkillUpdateReview";

type Kpis = ReturnType<typeof mergeKpis>;

function UpdateHeader({ back, kpis, draft, published, editable, busy, blocked, onDiscard, onSubmit, onOpenReview }: {
  back: ReactNode;
  kpis: Kpis;
  draft: SkillVersion;
  published: SkillVersion | null;
  editable: boolean;
  busy: boolean;
  blocked: boolean;
  onDiscard: () => void;
  onSubmit: () => void;
  onOpenReview: () => void;
}) {
  return (
    <div className="skills__detail-head">
      <div>
        {back}
        <div className="policies__row" style={{ marginTop: ".35rem" }}>
          <span className="skills__detail-name">Update from upstream</span>
          <span className="skills__mono">{kpis.commits}</span>
          <span className={stateBadge(draft.state)}>{STATE_LABELS[draft.state]}</span>
          <span className="skills__hint">draft v{draft.version}{published ? ` · base: published v${published.version}` : ""}</span>
        </div>
      </div>
      <div className="policies__row">
        {editable ? (
          <>
            <button type="button" className="admin-panel__action-btn" disabled={busy} data-testid="skill-update-discard"
              onClick={onDiscard}>Discard draft</button>
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="skill-update-submit"
              disabled={busy || blocked} title={blocked ? "Resolve every conflict first" : undefined}
              onClick={onSubmit}>Submit for review ▸</button>
          </>
        ) : (
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="skill-update-open-review"
            onClick={onOpenReview}>Review ▸</button>
        )}
      </div>
    </div>
  );
}

function UpdateKpis({ kpis, report, draft, newFindings }: {
  kpis: Kpis;
  report: MergeReport;
  draft: SkillVersion;
  newFindings: SkillDetail["new_findings"];
}) {
  return (
    <div className="policies__kpis" style={{ marginBottom: ".9rem" }}>
      <div className="policies__kpi">
        <div className="policies__kpi-label">Upstream changes</div>
        <div className="policies__kpi-value">{kpis.filesChanged} file{kpis.filesChanged === 1 ? "" : "s"}</div>
        <div className="policies__kpi-meta">{kpis.commits} · {kpis.upstreamHunks} upstream hunk{kpis.upstreamHunks === 1 ? "" : "s"} in merged files{report.path_moved ? " · folder moved" : ""}</div>
      </div>
      <div className="policies__kpi">
        <div className="policies__kpi-label">Your local customizations</div>
        <div className="policies__kpi-value">{kpis.mergedLocal + kpis.conflicts}</div>
        <div className="policies__kpi-meta">{kpis.mergedLocal} merged automatically · {kpis.conflicts} conflict{kpis.conflicts === 1 ? "" : "s"} ({kpis.open} open, {kpis.resolved} resolved)</div>
      </div>
      <div className="policies__kpi">
        <div className="policies__kpi-label">Security review</div>
        <div className="policies__kpi-value" style={newFindings.length ? undefined : { color: "var(--status-active-ink)" }}>
          {newFindings.length ? `${newFindings.length} new finding${newFindings.length === 1 ? "" : "s"}` : "no new risks"}</div>
        <div className="policies__kpi-meta">{draft.security_report.summary.high} high · {draft.security_report.summary.medium} medium · {draft.security_report.summary.info} info</div>
      </div>
    </div>
  );
}

function UpdateBody({ skillId, draft, report, published, diff, editable, busy, resolve }: {
  skillId: string;
  draft: SkillVersion;
  report: MergeReport;
  published: SkillVersion | null;
  diff: FileDiff[] | null;
  editable: boolean;
  busy: boolean;
  resolve: (conflictId: string, resolution: Resolution) => Promise<boolean>;
}) {
  return (
    <div className="skills__detail">
      <div className="admin-panel__stack" style={{ minWidth: 0 }}>
        {report.path_moved ? (
          <div className="policies__note" data-testid="skill-update-moved">
            <b>Upstream folder moved.</b> The tracked path <span className="skills__mono">{report.path_moved.from}</span> no longer
            exists at {shortCommit(report.theirs_commit)}; the draft follows <span className="skills__mono">{report.path_moved.to}</span>.
            Publishing v{draft.version} moves the tracked path.
          </div>
        ) : null}
        {report.conflicts.map((conflict) => (
          <SkillConflictCard key={conflict.id} conflict={conflict} report={report} resolution={report.resolutions?.[conflict.id]}
            editable={editable} busy={busy} onResolve={(resolution) => resolve(conflict.id, resolution)} />
        ))}
        {!report.conflicts.length ? (
          <div className="skills__merged"><div className="policies__row"><span className="work-badge work-badge--active">Merged</span>
            <span className="skills__hint">every upstream change merged without a conflict</span></div></div>
        ) : null}
        {diff === null ? <p className="skills__hint" role="status">Loading the changes…</p> : diff.map((file) => (
          <div key={file.path} className="admin-panel__card">
            <div className="admin-panel__section-header">
              {published ? `Changes against published v${published.version}` : "Contents"} · {file.path} (+{file.added} / −{file.removed})
            </div>
            <SkillDiff file={file} />
          </div>
        ))}
      </div>
      <SkillUpdateFiles skillId={skillId} draft={draft} report={report} publishedVersion={published?.version ?? null} />
    </div>
  );
}

// The full-page update review (mock `openUpdate`/`renderUpdate`): an upstream update draft with the merge
// KPIs, the moved-folder note, every conflict as a 3-way card with its resolution (saved at once with If-Match),
// the changes against the published version and previews of the merged files. Submitting stays disabled while a
// conflict is open; it freezes the draft and opens the four-eyes review.
export function SkillUpdateReview({ skillId, onBack, onOpenReview, onChanged }: {
  skillId: string;
  onBack: () => void;
  onOpenReview: (skillId: string) => void;
  onChanged: () => void | Promise<void>;
}) {
  const state = useSkillUpdateState(skillId);
  const { detail, diff, busy, problem, message, pathMissing, draft, report } = state;
  const { createDraft, resolve, submit, discard } = skillUpdateActions(state, skillId, { onBack, onOpenReview, onChanged });

  if (!detail) {
    return problem ? <p className="workspace-classification__message" role="alert">{problem}</p>
      : <p className="admin-panel__hint" role="status">Loading the update…</p>;
  }

  const back = <button type="button" className="skills__plain" data-testid="skill-update-back" onClick={onBack}>← {detail.name}</button>;
  if (!draft || !report) {
    return (
      <SkillUpdateStart detail={detail} back={back} busy={busy} pathMissing={pathMissing} problem={problem} message={message}
        onCreate={(path) => void createDraft(path)} />
    );
  }

  const kpis = mergeKpis(report, shortCommit);
  const editable = draft.state === "draft";
  const blocked = hasOpenConflicts(report);
  const published = detail.published;
  const newFindings = detail.new_findings ?? [];

  return (
    <div data-testid="skill-update-review">
      <UpdateHeader back={back} kpis={kpis} draft={draft} published={published} editable={editable} busy={busy}
        blocked={blocked} onDiscard={() => void discard()} onSubmit={() => void submit()}
        onOpenReview={() => onOpenReview(skillId)} />
      {problem ? <p className="workspace-classification__message" role="alert" data-testid="skill-update-problem">{problem}</p> : null}

      <UpdateKpis kpis={kpis} report={report} draft={draft} newFindings={newFindings} />

      <UpdateBody skillId={skillId} draft={draft} report={report} published={published} diff={diff} editable={editable}
        busy={busy} resolve={resolve} />
    </div>
  );
}
