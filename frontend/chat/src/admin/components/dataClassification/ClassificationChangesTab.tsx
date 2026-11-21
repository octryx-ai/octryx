import type { VersionRow, VersionsView } from "./classificationVersionsModel";
import { STATE_BADGE } from "./classificationVersionsModel";

const by = (row: VersionRow) => [row.author, row.approvedBy ? `approved by ${row.approvedBy}` : null].filter(Boolean).join(" · ") || "–";

// Drafts, reviews and published versions; an older version can be restored as a draft.
export function ClassificationChangesTab({ view, busy, onRollback }: {
  view: VersionsView;
  busy: boolean;
  onRollback: (version: number) => void;
}) {
  const rows = [...(view.draft ? [view.draft] : []), ...view.versions];
  return (
    <div className="sk-page">
      {view.draft?.added.length || view.draft?.removed.length ? (
        <p className="sk-hint" data-testid="classification-policy-diff">
          Generated policies: <b>{view.draft.added.length}</b> added, <b>{view.draft.removed.length}</b> removed ·{" "}
          <b>{view.draft.affectedWorkspaces}</b> {view.draft.affectedWorkspaces === 1 ? "Workspace" : "Workspaces"} at a changed level.
        </p>
      ) : null}
      <table className="admin-panel__table sk-cards" data-testid="classification-changes">
        <thead><tr><th>Version</th><th>State</th><th>Changes</th><th>By</th><th /></tr></thead>
        <tbody>
          {rows.length === 0 ? (
            <tr><td colSpan={5} className="admin-panel__cell--muted">No versions yet: the policy is the platform default.</td></tr>
          ) : rows.map((row) => {
            const state = STATE_BADGE[row.state] ?? { badge: "work-badge--neutral", label: row.state };
            return (
              <tr key={row.version}>
                <td data-label="Version">{row.version}</td>
                <td data-label="State"><span className={`work-badge ${state.badge}`}>{state.label}</span></td>
                <td data-label="Changes">
                  {row.changes.length ? row.changes.map((line) => <div key={`${line.level}-${line.rule}`}>{line.text}</div>)
                    : <span className="admin-panel__cell--muted">{row.note ?? "–"}</span>}
                  {row.review?.status === "rejected" && row.review.comment ? <div className="sk-sub">Rejected: {row.review.comment}</div> : null}
                </td>
                <td data-label="By">{by(row)}</td>
                <td>
                  {row.state === "retired" ? (
                    <button type="button" className="admin-panel__action-btn" disabled={busy || Boolean(view.draft)}
                      onClick={() => onRollback(row.version)}>Restore as draft</button>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <p className="sk-hint">
        {view.selfApproval ? "Approval rule: single admin — the author may publish their own change." : "Publishing needs a second admin (Approval rule: Four-eyes)."}{" "}
        Saved policy test cases run on submit and on publish.
      </p>
    </div>
  );
}
