import { checkSource } from "./skillCatalogApi";
import { refusalText, shortCommit } from "./skillCatalogModel";
import type { SkillRow } from "./skillCatalogTypes";
import type { SourceRow } from "./skillDeliveryTypes";
import { checkOneText, serverTime, trackingLabel, trustBadge } from "./skillTabsModel";

type OpenSkill = (skillId: string, sub?: "usage") => void;

// The skills imported from a source, each opening its page.
export function SkillList({ items, onOpenSkill }: { items: SkillRow[]; onOpenSkill: OpenSkill }) {
  return (
    <div className="policies__row" style={{ gap: ".3rem" }}>
      {items.map((row) => (
        <button key={row.id} type="button" className="skills__plain skills__mono" onClick={() => onOpenSkill(row.id)}>{row.name}</button>
      ))}
    </div>
  );
}

// The last check's error, the updates to review (one button per skill), up to date, and a moved path.
function SourceStatus({ source, items, onReviewUpdate }: { source: SourceRow; items: SkillRow[]; onReviewUpdate: (skillId: string) => void }) {
  const updates = items.filter((row) => row.update_available);
  const moved = items.some((row) => row.upstream_status?.path_moved);
  return (
    <>
      {source.last_error ? <div><span className="work-badge work-badge--attention" title={refusalText({ code: source.last_error })}>{source.last_error}</span></div> : null}
      {updates.map((row) => (
        <button key={row.id} type="button" className="work-badge work-badge--attention" style={{ cursor: "pointer", border: 0 }}
          data-testid={`source-update-${row.name}`} onClick={() => onReviewUpdate(row.id)}
          title={`Review the update of ${row.name}`}>Update available{updates.length > 1 ? ` · ${row.name}` : ""}</button>
      ))}
      {!source.last_error && !updates.length ? <span className="work-badge work-badge--active">up to date</span> : null}
      {moved ? <div className="policies__sub">tracked path moved</div> : null}
    </>
  );
}

// One upstream source: trust, ref and path, licence, its skills, tracking, the last check, status and actions.
export function SourceTableRow({ source, items, busy, onOpenSkill, onReviewUpdate, onCheck, onEdit }: {
  source: SourceRow;
  items: SkillRow[];
  busy: boolean;
  onOpenSkill: OpenSkill;
  onReviewUpdate: (skillId: string) => void;
  onCheck: (action: () => Promise<unknown>, describe: (raw: unknown) => string) => void;
  onEdit: (source: SourceRow) => void;
}) {
  const trust = trustBadge(source.trust);
  return (
    <tr data-testid={`source-row-${source.id}`}>
      <td>
        <div className="policies__name">{source.label}</div>
        <div className="policies__sub skills__mono">{source.url ?? source.kind}</div>
        <span className={`${trust.className} skills__trust`}>{trust.label}</span>
      </td>
      <td className="skills__mono">{source.ref ?? "—"}<br /><span className="admin-panel__cell--muted">{source.base_path || "—"}</span></td>
      <td>{source.licence_detected ? <span className="work-badge work-badge--neutral">{source.licence_detected}</span> : <span className="admin-panel__cell--muted">—</span>}</td>
      <td>{items.length || source.skills}{items.length ? <SkillList items={items} onOpenSkill={onOpenSkill} /> : null}</td>
      <td>{trackingLabel(items)}</td>
      <td className="admin-panel__cell--muted">{serverTime(source.last_checked_at)}
        {source.last_seen_commit ? <div className="policies__sub skills__mono">{shortCommit(source.last_seen_commit)}</div> : null}</td>
      <td><SourceStatus source={source} items={items} onReviewUpdate={onReviewUpdate} /></td>
      <td>
        <div className="policies__row">
          <button type="button" className="admin-panel__action-btn" disabled={busy} data-testid={`source-check-${source.id}`}
            onClick={() => onCheck(() => checkSource(source.id), (raw) => checkOneText(source.label, raw))}>Check now</button>
          <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => onEdit(source)}>Edit</button>
        </div>
      </td>
    </tr>
  );
}

// The uploads pseudo-source: uploaded files and skills written here, without upstream.
export function UploadsRow({ uploads, onOpenSkill }: { uploads: SkillRow[]; onOpenSkill: OpenSkill }) {
  return (
    <tr data-testid="source-row-uploads">
      <td><div className="policies__name">Uploaded files</div><div className="policies__sub">SKILL.md or .zip uploads and skills written here</div></td>
      <td className="admin-panel__cell--muted">—</td>
      <td><span className="work-badge work-badge--neutral">per skill</span></td>
      <td>{uploads.length}<SkillList items={uploads} onOpenSkill={onOpenSkill} /></td>
      <td>—</td>
      <td className="admin-panel__cell--muted">—</td>
      <td><span className="work-badge work-badge--neutral">no upstream</span></td>
      <td />
    </tr>
  );
}
