// The sections of the policy-set lifecycle drawer: the timeline, the changes with the Cedar diff, the checks with the
// change note, the review, the version history and the footer actions.
import { approvalModeHistoryText } from "../approvalRule/approvalRule";
import { createDraft, rollbackVersion } from "./policyEngineApi";
import { STATE_LABELS } from "./policyEngineStatus";
import type { PolicyVersion } from "./policyEngineVersions";
import type { DiffLine, HistoryRow, Review } from "./policyLifecycleModel";
import type { PolicyItem } from "./policyCatalogModel";
import { formatDateTime } from "../../utils/dateTime";

const CHANGE_BADGES: Record<string, { label: string; tone: string }> = {
  new: { label: "New", tone: "active" }, changed: { label: "Changed", tone: "running" }, removed: { label: "Removed", tone: "danger" },
};
const STATE_TONES: Record<string, string> = { draft: "attention", in_review: "running", published: "active", retired: "neutral" };

type Act = (action: () => Promise<unknown>, done: string) => Promise<void>;

// Draft → In review (or Approved under the single-admin rule) → Published, with the current step marked.
export function LifecycleTimeline({ state, changes, selfApproval, published }: {
  state: string | null;
  changes: PolicyItem[];
  selfApproval: boolean;
  published: PolicyVersion | null;
}) {
  const step = (index: number, title: string, text: string) => {
    const current = index === (state === "draft" ? 0 : state === "in_review" ? 1 : 2);
    const done = index < (state === "draft" ? 0 : state === "in_review" ? 1 : 3);
    return <div className={`policies__timeline-step${current ? " policies__timeline-step--current" : done ? " policies__timeline-step--done" : ""}`}><b>{index + 1} · {title}</b>{text}</div>;
  };
  return (
    <div className="policies__timeline">
      {step(0, "Draft", `Editing · ${changes.length} change${changes.length === 1 ? "" : "s"}`)}
      {step(1, selfApproval ? "Approved" : "In review", selfApproval ? "You approve it yourself (approval rule: single admin)" : "Another platform admin approves (four-eyes)")}
      {step(2, "Published", `Test cases run again${published ? `; v${published.version} is retired` : ""}`)}
    </div>
  );
}

export function LifecycleChanges({ changes, published, diff }: {
  changes: PolicyItem[];
  published: PolicyVersion | null;
  diff: DiffLine[] | null;
}) {
  return (
      <section className="work-detail__section">
        <h3>Changes against {published ? `published v${published.version}` : "nothing published"}</h3>
        {changes.length ? changes.map((item) => (
          <div key={item.id} className="policies__summary" data-testid="lifecycle-change">
            <span className={`work-badge work-badge--${CHANGE_BADGES[item.change!].tone}`}>{CHANGE_BADGES[item.change!].label}</span> {item.name}
          </div>
        )) : <p>No policy changed yet.</p>}
        <details className="policies__advanced">
          <summary>Cedar diff</summary>
          {diff ? (
            <pre className="policies__code" data-testid="lifecycle-diff">
              {diff.filter((line) => line.kind !== "same").length ? diff.map((line, index) => (
                line.kind === "same" ? `  ${line.text}\n` : <span key={index} className={`policies__code-${line.kind}`}>{line.kind === "added" ? "+ " : "- "}{line.text}{"\n"}</span>
              )) : "No difference."}
            </pre>
          ) : <p>The texts are too large to compare here; use Advanced · Edit the whole set as Cedar.</p>}
        </details>
      </section>
  );
}

// The checks the store runs before publishing and, on a draft, the change note.
export function LifecycleChecks({ working, schemaVersion, state, note, setNote, selfApproval }: {
  working: PolicyVersion;
  schemaVersion: string;
  state: string | null;
  note: string;
  setNote: (note: string) => void;
  selfApproval: boolean;
}) {
  const report = working.testReport ?? null;
  return (
      <section className="work-detail__section">
        <h3>Checks</h3>
        <div className="policies__summary" data-testid="lifecycle-checks">
          ✓ Validates against schema {schemaVersion} · {report && report.total ? (report.ok ? `✓ ${report.passed}/${report.total} saved test cases pass` : <span className="policies__fail">✗ {report.failed} of {report.total} saved test cases fail (publishing is blocked)</span>) : "no saved test cases"} · ✓ only <b>forbid</b> policies
        </div>
        {state === "draft" ? (
          <>
            <label className="admin-panel__field"><span>Change note</span>
              <input value={note} maxLength={500} data-testid="lifecycle-note" onChange={(event) => setNote(event.target.value)} /></label>
            <div className="policies__note">{selfApproval
              ? "Publishing freezes the text. The approval rule lets you approve and publish your own version in one step; it is recorded as self-approved."
              : "After you submit, the text is frozen. A platform admin other than you (author and submitter) must approve before anyone can publish."}</div>
          </>
        ) : null}
      </section>
  );
}

export function LifecycleReview({ review }: { review: Review }) {
  return (
      <section className="work-detail__section" data-testid="lifecycle-review">
        <h3>Review</h3>
        <p>Submitted by <b>{review.submitter?.name ?? review.requestedBy?.name ?? "—"}</b>{review.requestedAt ? ` on ${formatDateTime(review.requestedAt)}` : ""} · status <b>{review.status}</b>{review.decidedBy ? ` by ${review.decidedBy.name}` : ""}.</p>
        {review.comment ? <p>Comment: {review.comment}</p> : null}
        <p>May approve: {[...(review.singleAdmin ? ["you (approval rule: single admin)"] : []), ...review.candidates.map((item) => item.name)].join(", ") || "no other platform admin exists yet"}.</p>
        <div className="policies__note" data-testid="lifecycle-four-eyes">
          {!review.singleAdmin && (review.viewer.isSubmitter || review.viewer.isAuthor) ? "You wrote or submitted this version — another platform admin must approve it. " : ""}{review.rule}
        </div>
      </section>
  );
}

// Every version with its state, note, author and reviewer; roll back a retired one, retire the published one.
export function LifecycleHistory({ rows, busy, act }: { rows: HistoryRow[]; busy: boolean; act: Act }) {
  const open = rows.some((row) => row.state === "draft" || row.state === "in_review");
  return (
    <section className="work-detail__section">
      <h3>History</h3>
      <table className="admin-panel__table" data-testid="lifecycle-history">
        <thead><tr><th scope="col">Version</th><th scope="col">State</th><th scope="col">Note</th><th scope="col">Author · reviewer</th><th scope="col"><span className="classification-policy__sr">Actions</span></th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.version} data-testid="lifecycle-history-row">
              <td>v{row.version}</td>
              <td><span className={`work-badge work-badge--${STATE_TONES[row.state] ?? "neutral"}`}>{STATE_LABELS[row.state] ?? row.state}</span></td>
              <td className="admin-panel__cell--muted">{row.note || "—"}</td>
              <td className="admin-panel__cell--muted">{row.authorName || "—"}{row.reviewerName ? ` · ${row.reviewerName}` : ""}{approvalModeHistoryText(row.approvalMode) ? ` (${approvalModeHistoryText(row.approvalMode)})` : ""}</td>
              <td>
                {row.state === "retired" ? <button type="button" className="admin-panel__action-btn" data-testid={`lifecycle-rollback-${row.version}`} disabled={busy || open}
                  onClick={() => void act(() => rollbackVersion(row.version), `Draft created from version ${row.version}; review and publish it.`)}>Roll back</button> : null}
                {row.state === "published" ? <button type="button" className="admin-panel__action-btn" data-testid={`lifecycle-retire-${row.version}`} disabled={busy || open}
                  title="Removing every custom policy widens access, so it goes through review: this creates an empty draft to submit and publish."
                  onClick={() => void act(() => createDraft("", `Retire version ${row.version}`), `Empty draft created: submit it for review; publishing it retires version ${row.version}.`)}>Retire (via review)</button> : null}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="admin-panel__hint">Roll back creates a new draft from that version; it goes through review like any draft.</p>
    </section>
  );
}
