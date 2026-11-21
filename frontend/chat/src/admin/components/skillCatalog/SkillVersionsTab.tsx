import { useState } from "react";

import { SkillDiff } from "./SkillDiff";
import { loadDiff, retireVersion, rollbackVersion } from "./skillCatalogApi";
import { STATE_LABELS, refusalText, shortCommit, stateBadge } from "./skillCatalogModel";
import type { FileDiff } from "./skillDiffModel";
import type { SkillDetail, SkillVersion } from "./skillCatalogTypes";
import { formatWhen } from "./skillDetailModel";

type DiffView = { version: number; against: number | null; files: FileDiff[] };

// The tab's state and its two server steps: a diff against the published version, and an action (roll back, retire)
// that reports its result through onChanged.
function useSkillVersions(detail: SkillDetail, onChanged: (message: string) => Promise<void>) {
  const [diff, setDiff] = useState<DiffView | null>(null);
  const [confirmRetire, setConfirmRetire] = useState(false);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);

  const act = async (action: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setProblem(null);
    try {
      await action();
      setConfirmRetire(false);
      await onChanged(done);
    } catch (error) {
      setProblem(refusalText(error));
    } finally {
      setBusy(false);
    }
  };
  const showDiff = async (row: SkillVersion) => {
    setBusy(true);
    setProblem(null);
    try {
      const raw = (await loadDiff(detail.id, row.version, "published")) as { against?: number | null; files?: FileDiff[] };
      setDiff({ version: row.version, against: raw.against ?? null, files: raw.files ?? [] });
    } catch (error) {
      setProblem(refusalText(error));
    } finally {
      setBusy(false);
    }
  };
  return { diff, setDiff, confirmRetire, setConfirmRetire, busy, problem, act, showDiff };
}

type VersionsState = ReturnType<typeof useSkillVersions>;

// Detail → Versions & review (mock `versionsHtml`): the version history with author → approver, upstream commit and
// state; per row a diff against the published version, roll back (creates a new draft) for earlier versions, and
// retire on the published version behind a confirm step.
export function SkillVersionsTab({ detail, onChanged }: { detail: SkillDetail; onChanged: (message: string) => Promise<void> }) {
  const versions = useSkillVersions(detail, onChanged);
  const { diff, setDiff, confirmRetire, problem } = versions;
  const published = detail.published;

  return (
    <div data-testid="skill-versions">
      {confirmRetire && published ? (
        <p className="policies__warn" role="alert">Retiring v{published.version} stops its delivery in every Workspace; nothing is
          published for this skill until another version is published.</p>
      ) : null}
      <div className="skills__scroll">
        <table className="admin-panel__table">
          <thead><tr><th scope="col">Version</th><th scope="col">Change</th><th scope="col">Author → approver</th><th scope="col">Upstream</th><th scope="col">Dates</th><th scope="col">State</th><th scope="col"><span className="classification-policy__sr">Actions</span></th></tr></thead>
          <tbody>
            {detail.versions.map((row) => (
              <VersionRow key={row.id} row={row} actions={<VersionActions detail={detail} row={row} versions={versions} />} />
            ))}
          </tbody>
        </table>
      </div>
      {problem ? <p className="policies__warn skill-detail__gap" role="alert">{problem}</p> : null}
      {diff ? <DiffCard diff={diff} onClose={() => setDiff(null)} /> : null}
      <p className="skills__hint skill-detail__gap">Same lifecycle as platform policies: draft → in review → published → retired. Published
        versions are frozen; the approver must be a different platform admin than the author and the submitter. Rolling back
        creates a new draft from the chosen version.</p>
    </div>
  );
}

function VersionRow({ row, actions }: { row: SkillVersion; actions: JSX.Element }) {
  return (
    <tr className={row.state === "retired" ? "admin-panel__row--inactive" : undefined} data-testid={`skill-version-${row.version}`}>
      <td className="skills__mono">v{row.version}</td>
      <td>{row.note || <span className="admin-panel__cell--muted">—</span>}</td>
      <td>{row.author_name || "—"} → {row.reviewer_name ? `${row.reviewer_name}${row.approval_mode === "self" ? " (self-approved)" : ""}` : <i>{row.state === "draft" || row.state === "in_review" ? "pending" : "—"}</i>}</td>
      <td className="skills__mono">{row.upstream ? shortCommit(row.upstream.commit) : "—"}</td>
      <td className="admin-panel__cell--muted">
        <div>created {formatWhen(row.created_at)}</div>
        {row.published_at ? <div>published {formatWhen(row.published_at)}</div> : null}
        {row.retired_at ? <div>retired {formatWhen(row.retired_at)}</div> : null}
      </td>
      <td><span className={stateBadge(row.state)}>{STATE_LABELS[row.state]}</span></td>
      <td>{actions}</td>
    </tr>
  );
}

function VersionActions({ detail, row, versions }: { detail: SkillDetail; row: SkillVersion; versions: VersionsState }) {
  const { busy, confirmRetire, setConfirmRetire, act, showDiff } = versions;
  const published = detail.published;
  const isPublished = published?.version === row.version;
  const canRollback = !isPublished && (row.state === "published" || row.state === "retired");
  return (
    <div className="skill-detail__actions">
      {published && !isPublished ? (
        <button type="button" className="admin-panel__action-btn" disabled={busy} data-testid={`skill-version-diff-${row.version}`}
          onClick={() => void showDiff(row)}>Diff</button>
      ) : null}
      {canRollback ? (
        <button type="button" className="admin-panel__action-btn" disabled={busy} data-testid={`skill-version-rollback-${row.version}`}
          onClick={() => void act(() => rollbackVersion(detail.id, row.version), `A new draft was created from v${row.version}.`)}>Roll back to this version</button>
      ) : null}
      {isPublished && !confirmRetire ? (
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" disabled={busy}
          data-testid="skill-version-retire" onClick={() => setConfirmRetire(true)}>Retire</button>
      ) : null}
      {isPublished && confirmRetire ? (
        <>
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" disabled={busy} data-testid="skill-version-retire-confirm"
            onClick={() => void act(() => retireVersion(detail.id, row.version), `v${row.version} retired.`)}>Retire v{row.version}</button>
          <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => setConfirmRetire(false)}>Cancel</button>
        </>
      ) : null}
    </div>
  );
}

function DiffCard({ diff, onClose }: { diff: DiffView; onClose: () => void }) {
  return (
    <div className="admin-panel__card skill-detail__gap" data-testid="skill-version-diff">
      <div className="policies__flex-between">
        <div className="admin-panel__section-header">v{diff.version} against published{diff.against !== null ? ` v${diff.against}` : ""}</div>
        <button type="button" className="admin-panel__action-btn" onClick={onClose}>Close</button>
      </div>
      {diff.files.filter((file) => file.status !== "unchanged").map((file) => (
        <div key={file.path} className="skill-detail__gap">
          <div className="policies__row"><span className="skills__mono">{file.path}</span><span className="work-badge work-badge--neutral">{file.status}</span>
            <span className="skills__hint">+{file.added} −{file.removed}</span></div>
          <SkillDiff file={file} />
        </div>
      ))}
      {diff.files.every((file) => file.status === "unchanged") ? <p className="skills__hint">No file differs from the published version.</p> : null}
    </div>
  );
}
