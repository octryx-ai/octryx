import { SegmentedTabs } from "../../../layout/SegmentedTabs";

import { SkillDetailSide } from "./SkillDetailSide";
import { SkillDetailHead, SkillDetailTabBody, SkillDraftBar } from "./SkillDetailParts";
import type { CategoryCatalog } from "./skillCatalogTypes";
import { workingVersion } from "./skillDetailModel";
import { runUpstreamCheck, useSkillDetail } from "./useSkillDetail";
import type { DetailTab } from "./useSkillDetail";
import "./skillDetail.css";
const TABS: { id: DetailTab; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "files", label: "Files" },
  { id: "versions", label: "Versions & review" },
  { id: "workspaces", label: "Workspaces" },
  { id: "security", label: "Security" },
  { id: "delivery", label: "Delivery" },
  { id: "usage", label: "Usage" },
];

// The full-page skill detail (mock `renderDetail`): head with state, upstream check and the edit entry, the
// draft bar while a draft or review is open, the sub-tabs over the working version (open draft, else published) and
// the right column with catalog facts, availability, provenance and the security summary.
export function SkillDetailPage({ skillId, initialSub, categories, revision = 0, onBack, onEdit, onReviewUpdate, onOpenReview, onOpenCategory, onOpenWorkspaces, onChanged }: {
  skillId: string;
  initialSub?: DetailTab;
  categories: CategoryCatalog;
  /** Changes when the skill changed elsewhere (a publish in the review drawer): the page reloads. */
  revision?: number;
  onBack: () => void;
  onEdit: (skillId: string) => void;
  onReviewUpdate: (skillId: string) => void;
  onOpenReview: (skillId: string) => void;
  onOpenCategory: (key: string) => void;
  onOpenWorkspaces: () => void;
  onChanged: () => void | Promise<void>;
}) {
  const state = useSkillDetail(skillId, initialSub, revision, onChanged);
  const { detail, sub, setSub, problem, message, check, busy, changed } = state;

  if (problem && !detail) return <p className="workspace-classification__message" role="alert" data-testid="skill-detail-error">{problem}</p>;
  if (!detail) return <p className="admin-panel__hint" role="status">Loading the skill…</p>;

  const working = workingVersion(detail);
  const open = detail.open;
  const runCheck = () => runUpstreamCheck(state, detail.id, onChanged);

  return (
    <div data-testid="skill-detail">
      <SkillDetailHead detail={detail} working={working} busy={busy} onBack={onBack} onEdit={onEdit} onReviewUpdate={onReviewUpdate}
        onCheck={() => void runCheck()} />
      {check ? <p className={`skills__hint ${check.tone === "error" ? "skills__er" : check.tone === "update" ? "skills__wa" : "skills__ok"}`}
        role="status" data-testid="skill-detail-check-result">{check.text}</p> : null}
      {message ? <p className="skills__hint" role="status" data-testid="skill-detail-message">{message}</p> : null}
      {problem ? <p className="policies__warn" role="alert">{problem}</p> : null}

      {open ? <SkillDraftBar detail={detail} open={open} onEdit={onEdit} onOpenReview={onOpenReview} /> : null}

      <div className="skills__detail">
        <div style={{ minWidth: 0 }}>
          <div className="skills__detail-head">
            <SegmentedTabs label="Skill sections" idPrefix="skill-detail" value={sub} testId="skill-detail-tabs"
              onChange={(key) => setSub(key as DetailTab)}
              tabs={TABS.map((item) => ({ key: item.id, label: item.label, testId: `skill-detail-tab-${item.id}` }))} />
          </div>
          <SkillDetailTabBody detail={detail} working={working} sub={sub} categories={categories} changed={changed} onOpenWorkspaces={onOpenWorkspaces} />
        </div>
        <SkillDetailSide key={detail.tags.join(",")} detail={detail} version={working} onOpenCategory={onOpenCategory}
          onOpenSecurity={() => setSub("security")} onChanged={changed} />
      </div>
    </div>
  );
}
