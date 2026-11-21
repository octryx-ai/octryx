import { useState, type ReactNode } from "react";

import { STATE_LABELS, shortCommit } from "./skillCatalogModel";
import type { SkillDetail } from "./skillCatalogTypes";

// The update review before an update draft exists: offers "Create update draft" when the last check found an
// upstream update, asks for the new upstream path when the tracked folder is gone (`skill_upstream_path_missing`),
// and explains why nothing can be reviewed otherwise (an open draft that is not an upstream update, or up to date).
export function SkillUpdateStart({ detail, back, busy, pathMissing, problem, message, onCreate }: {
  detail: SkillDetail;
  back: ReactNode;
  busy: boolean;
  pathMissing: boolean;
  problem: string | null;
  message: string | null;
  onCreate: (path?: string) => void;
}) {
  const [path, setPath] = useState("");
  const status = detail.upstream_status;
  const open = detail.open;
  const candidates = status?.candidates ?? [];
  const needsPath = pathMissing || status?.error === "skill_upstream_path_missing";

  return (
    <div data-testid="skill-update-start">
      <div className="skills__detail-head">
        <div>
          {back}
          <div className="policies__row" style={{ marginTop: ".35rem" }}>
            <span className="skills__detail-name">Update from upstream</span>
            {status?.latest_commit ? <span className="skills__mono">{shortCommit(status.current_commit)} → {shortCommit(status.latest_commit)}</span> : null}
          </div>
        </div>
      </div>
      <div className="admin-panel__stack" style={{ maxWidth: "48rem" }}>
        {problem ? <p className="workspace-classification__message" role="alert" data-testid="skill-update-problem">{problem}</p> : null}
        {message ? <p className="admin-panel__hint" role="status" data-testid="skill-update-message">{message}</p> : null}
        {open ? (
          <div className="policies__warn" data-testid="skill-update-other-draft">
            v{open.version} is open ({STATE_LABELS[open.state].toLowerCase()}) and is not an upstream update. Publish or discard it
            before an update draft can be created.
          </div>
        ) : !detail.source ? (
          <p className="admin-panel__hint">This skill has no upstream source.</p>
        ) : status?.update_available || needsPath ? (
          <div className="admin-panel__card">
            <div className="admin-panel__section-header">{needsPath ? "Upstream folder moved" : "Upstream update available"}</div>
            <p className="skills__hint">
              Creating the update draft merges the upstream changes with your local customizations. Non-overlapping changes are
              merged; overlapping ones become conflicts you resolve here before submitting.
              {status?.path_moved ? ` The tracked folder moved from ${status.path_moved.from} to ${status.path_moved.to}.` : ""}
            </p>
            {needsPath ? (
              <div className="admin-panel__stack">
                <div className="policies__warn">The tracked upstream folder is gone and no single new folder matches. Enter the new path.</div>
                {candidates.length ? (
                  <div className="policies__row">
                    {candidates.map((candidate) => (
                      <button key={candidate} type="button" className="admin-panel__action-btn" onClick={() => setPath(candidate)}>{candidate}</button>
                    ))}
                  </div>
                ) : null}
                <label className="admin-panel__field"><span>Upstream path</span>
                  <input className="skills__mono" value={path} data-testid="skill-update-path" onChange={(event) => setPath(event.target.value)} /></label>
              </div>
            ) : null}
            <div className="policies__row">
              <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="skill-update-create"
                disabled={busy || (needsPath && !path.trim())}
                onClick={() => onCreate(needsPath ? path.trim() : undefined)}>Create update draft</button>
            </div>
          </div>
        ) : (
          <p className="admin-panel__hint" data-testid="skill-update-none">
            No upstream update is known{status?.checked_at ? "" : " yet"}. Check for updates on the skill page first.
            {status?.error ? ` The last check failed (${status.error}).` : ""}
          </p>
        )}
      </div>
    </div>
  );
}
