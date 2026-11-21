// The Work Item detail's reads: repository impact and lifecycle (which carries the item's pull requests), each with its
// own error, plus the audit timeline's reload key. A switch to another item returns to Overview and closes the start form.
import { useEffect, useState } from "react";

import { loadWorkItemChangeUnits } from "./workChangePlanApi";
import { loadWorkItemLifecycle } from "./workApi";
import type { WorkItemDetailTab } from "./WorkItemDetailPanel";
import type { WorkChangeUnit } from "./workPullRequestTypes";
import type { WorkItemLifecycle } from "./workItemTypes";

// The tab and start-form setters are React state setters, so listing them keeps the effect keyed by the item alone.
export function useWorkItemDetailData(
  itemId: string,
  setTab: (tab: WorkItemDetailTab) => void,
  setStarting: (starting: boolean) => void,
) {
  const [changeUnits, setChangeUnits] = useState<WorkChangeUnit[]>([]);
  const [lifecycle, setLifecycle] = useState<WorkItemLifecycle | null>(null);
  const [changeUnitError, setChangeUnitError] = useState<string | null>(null);
  const [lifecycleError, setLifecycleError] = useState<string | null>(null);
  const [timelineKey, setTimelineKey] = useState(0);

  useEffect(() => { setTab("overview"); setStarting(false); }, [itemId, setTab, setStarting]);

  useEffect(() => {
    let cancelled = false;
    setChangeUnitError(null);
    setLifecycleError(null);
    setLifecycle(null);
    void loadWorkItemChangeUnits(itemId)
      .then((units) => { if (!cancelled) setChangeUnits(units); })
      .catch((err) => { if (!cancelled) setChangeUnitError(err instanceof Error ? err.message : "Failed to load repository impact"); });
    void loadWorkItemLifecycle(itemId)
      .then((payload) => { if (!cancelled) setLifecycle(payload); })
      .catch((err) => { if (!cancelled) setLifecycleError(err instanceof Error ? err.message : "Failed to load lifecycle"); });
    return () => { cancelled = true; };
  }, [itemId]);

  const pullRequests = lifecycle?.pull_requests ?? [];
  return { changeUnits, pullRequests, lifecycle, changeUnitError, lifecycleError, timelineKey, setTimelineKey };
}

export type WorkItemDetailData = ReturnType<typeof useWorkItemDetailData>;
