import { KindBadge, TrustBadge } from "./SkillBadges";
import { SkillDeliveryTab } from "./SkillDeliveryTab";
import { SkillDetailUsage } from "./SkillDetailUsage";
import { SkillFilesTab } from "./SkillFilesTab";
import { SkillOverviewTab } from "./SkillOverviewTab";
import { SkillSecurityTab } from "./SkillSecurityTab";
import { SkillVersionsTab } from "./SkillVersionsTab";
import { SkillWorkspacesTab } from "./SkillWorkspacesTab";
import { STATE_LABELS, categoryLabels, hasOpenConflicts, stateBadge } from "./skillCatalogModel";
import type { CategoryCatalog, SkillDetail, SkillVersion } from "./skillCatalogTypes";
import { descriptionOf } from "./skillDetailModel";
import type { DetailTab } from "./useSkillDetail";

// The head: name, kind, the published and open versions, trust, update badge, and the check / review / edit actions.
export function SkillDetailHead({ detail, working, busy, onBack, onEdit, onReviewUpdate, onCheck }: {
  detail: SkillDetail;
  working: SkillVersion | null;
  busy: boolean;
  onBack: () => void;
  onEdit: (skillId: string) => void;
  onReviewUpdate: (skillId: string) => void;
  onCheck: () => void;
}) {
  const open = detail.open;
  const mcp = detail.kind === "mcp_server";
  const updateable = Boolean(detail.upstream_status?.update_available || open?.merge_report);
  const states = [detail.published, open].filter((row): row is SkillVersion => Boolean(row));
  return (
    <div className="skills__detail-head">
      <div>
        <button type="button" className="skills__plain" data-testid="skill-detail-back" onClick={onBack}>← Catalog</button>
        <div className="policies__row" style={{ marginTop: ".35rem", flexWrap: "wrap" }}>
          <span className="skills__detail-name">{detail.name}</span>
          <KindBadge kind={detail.kind} />
          {states.map((row) => (
            <span key={row.version} className="policies__row">
              <span className="skills__mono admin-panel__cell--muted">v{row.version}</span>
              <span className={stateBadge(row.state)}>{STATE_LABELS[row.state]}</span>
            </span>
          ))}
          {states.length ? null : <span className={stateBadge("retired")}>Retired</span>}
          <TrustBadge source={detail.source} />
          {detail.upstream_status?.update_available ? <span className="work-badge work-badge--attention">Update available</span> : null}
        </div>
        <div className="policies__summary" style={{ marginTop: ".3rem" }}>{descriptionOf(working)}</div>
      </div>
      <div className="policies__row" style={{ flexWrap: "wrap" }}>
        {detail.source ? <button type="button" className="admin-panel__action-btn" disabled={busy} data-testid="skill-detail-check"
          onClick={onCheck}>Check for updates</button> : null}
        {updateable ? <button type="button" className="admin-panel__action-btn" data-testid="skill-detail-review-update"
          onClick={() => onReviewUpdate(detail.id)}>Review update</button> : null}
        {open?.state === "in_review" ? null : (
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="skill-detail-edit"
            onClick={() => onEdit(detail.id)}>{open ? "Continue draft" : mcp ? "Edit launch spec (new draft)" : "Edit (new draft)"}</button>
        )}
      </div>
    </div>
  );
}

// While a draft or review is open: its state, note and conflicts, with continue and open review.
export function SkillDraftBar({ detail, open, onEdit, onOpenReview }: {
  detail: SkillDetail;
  open: SkillVersion;
  onEdit: (skillId: string) => void;
  onOpenReview: (skillId: string) => void;
}) {
  return (
    <div className="policies__draft-bar" data-testid="skill-detail-draft-bar">
      <div className="policies__row">
        <span>
          <strong>Draft v{open.version}</strong> · {STATE_LABELS[open.state].toLowerCase()}
          {open.note ? ` · ${open.note}` : ""}
          {open.merge_report ? (hasOpenConflicts(open.merge_report) ? " · open merge conflicts" : " · conflicts resolved") : ""}
          {open.state === "in_review" ? (detail.review?.single_admin ? " · ready to publish" : " · waiting for another platform admin") : ""}
        </span>
      </div>
      <div className="policies__row">
        {open.state === "draft" ? <button type="button" className="admin-panel__action-btn" data-testid="skill-detail-continue"
          onClick={() => onEdit(detail.id)}>Continue editing</button> : null}
        <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" data-testid="skill-detail-open-review"
          onClick={() => onOpenReview(detail.id)}>Open review ▸</button>
      </div>
    </div>
  );
}

// The selected sub-tab over the working version.
export function SkillDetailTabBody({ detail, working, sub, categories, changed, onOpenWorkspaces }: {
  detail: SkillDetail;
  working: SkillVersion | null;
  sub: DetailTab;
  categories: CategoryCatalog;
  changed: (text: string) => Promise<void>;
  onOpenWorkspaces: () => void;
}) {
  return (
    !working ? <div className="admin-panel__empty-state">This skill has no version.</div>
      : sub === "overview" ? <SkillOverviewTab key={working.digest} skillId={detail.id} kind={detail.kind} version={working} />
      : sub === "files" ? <SkillFilesTab key={working.digest} skillId={detail.id} version={working} />
      : sub === "versions" ? <SkillVersionsTab detail={detail} onChanged={changed} />
      : sub === "workspaces" ? <SkillWorkspacesTab skillId={detail.id} kind={detail.kind} labels={categoryLabels(categories.categories)}
        extension={working.extension} onOpenWorkspaces={onOpenWorkspaces} />
      : sub === "security" ? <SkillSecurityTab key={working.digest} detail={detail} version={working} onChanged={changed} />
      : sub === "delivery" ? <SkillDeliveryTab key={working.digest} skillId={detail.id} name={detail.name} version={working} />
      : <SkillDetailUsage skillId={detail.id} kind={detail.kind} />
  );
}
