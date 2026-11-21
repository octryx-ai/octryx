import { useEffect, useState } from "react";

import { SegmentedTabs } from "../../layout/SegmentedTabs";
import { loadChangePlanSummaries } from "./workPlanListApi";
import { DEFAULT_PLAN_LIST_FILTER, planListQuery, planTotal } from "./workPlanListModel";
import { PLAN_STATUS } from "./planStatus";
import { WorkPlanList } from "./WorkPlanList";
import type { WorkChangePlanSummary } from "./workPlanListTypes";

export type WorkPlansTab = "all" | "review";

// Work → Delivery → Plans: one page with two tabs over the same plans, All plans and Waiting for
// review (`queue=review`). Who may approve is the Approval rule, not set here.
export function WorkPlansPage({ tab, onTab, projectId, reloadKey, selectedPlanId, onOpenPlan, onOpenApprovalRule, onOpenWorkItems }: {
  tab: WorkPlansTab;
  onTab: (tab: WorkPlansTab) => void;
  projectId: string;
  reloadKey: string | number;
  selectedPlanId: string | null;
  onOpenPlan: (plan: WorkChangePlanSummary) => void;
  onOpenApprovalRule: () => void;
  onOpenWorkItems?: () => void;
}) {
  const [counts, setCounts] = useState<Record<string, number> | null>(null);
  useEffect(() => {
    let active = true;
    loadChangePlanSummaries({ ...planListQuery("plans", DEFAULT_PLAN_LIST_FILTER), projectId, limit: 1 })
      .then((page) => active && setCounts(page.status_counts))
      .catch(() => active && setCounts(null));
    return () => { active = false; };
  }, [projectId, reloadKey]);
  const total = counts ? planTotal(counts) : null;
  const waiting = counts ? counts[PLAN_STATUS.readyForReview] ?? 0 : null;
  return (
    <div className="work-intake">
      {total ? (
        <SegmentedTabs label="Plans" idPrefix="work-plans" value={tab} onChange={(key) => onTab(key as WorkPlansTab)}
          tabs={[{ key: "all", label: "All plans", count: total }, { key: "review", label: "Waiting for review", count: waiting ?? undefined }]} />
      ) : null}
      <WorkPlanList mode={total === 0 ? "plans" : tab === "review" ? "reviews" : "plans"} projectId={projectId} reloadKey={reloadKey}
        selectedPlanId={selectedPlanId} onOpenPlan={onOpenPlan} onOpenWorkItems={onOpenWorkItems} />
      {total ? (
        <p className="admin-panel__hint">
          Who may approve is set in the <button type="button" className="work-link" onClick={onOpenApprovalRule}>Approval rule</button>.
        </p>
      ) : null}
    </div>
  );
}
