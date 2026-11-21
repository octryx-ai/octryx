import { useState } from "react";

import { useWorkItemSelection } from "./useWorkItemSelection";
import { readWorkDetailParam, writeWorkDetailLink } from "./workDetailLink";
import type { WorkChangePlanSummary } from "./workPlanListTypes";
import type { WorkItem } from "./workItemTypes";

// The Work detail selection: which Work Item is open and which of its Change Plans is
// selected by exact id, kept in the address (`work_item_id`, `change_plan_id`).
export function useWorkDetailSelection(items: WorkItem[], reloadToken: number) {
  const [selectedItemId, setSelectedItemId] = useState<string | null>(() => readWorkDetailParam("work_item_id"));
  const [selectedPlanId, setSelectedPlanId] = useState<string | null>(() => readWorkDetailParam("change_plan_id"));
  // Bumped after a successful plan decision or new version, so plan lists and counts reload
  // without refetching the open Work Item (which would remount the detail).
  const [planRevision, setPlanRevision] = useState(0);
  const selection = useWorkItemSelection(selectedItemId, items, reloadToken);

  function show(workItemId: string | null, changePlanId: string | null) {
    setSelectedItemId(workItemId);
    setSelectedPlanId(workItemId ? changePlanId : null);
    writeWorkDetailLink(workItemId, changePlanId);
  }

  return {
    selectedItemId,
    selectedPlanId,
    selection,
    planRevision,
    markPlansChanged: () => setPlanRevision((revision) => revision + 1),
    openItem: (item: WorkItem) => show(item.id, null),
    // A plan row is only a summary: the detail loads the full Work Item by id and selects this plan.
    openPlan: (plan: WorkChangePlanSummary) => show(plan.work_item_id, plan.id),
    selectPlanVersion: (planId: string) => {
      if (selectedItemId) show(selectedItemId, planId);
    },
    close: () => show(null, null),
  };
}
