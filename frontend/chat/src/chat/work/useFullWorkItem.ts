import { useEffect, useState } from "react";

import { loadWorkItem } from "./workPlanListApi";
import type { WorkItem } from "./workItemTypes";

// List rows are lean on newer servers, so the detail reads the item itself; until then the row is shown.

export function mergeWorkItem(row: WorkItem | null, full: WorkItem | null): WorkItem | null {
  if (!full) return row;
  if (!row) return full;
  return { ...row, ...full };
}

export function useFullWorkItem(itemId: string | null, row: WorkItem | null, fromList: boolean, reloadToken = 0): WorkItem | null {
  const [full, setFull] = useState<WorkItem | null>(null);

  useEffect(() => {
    let current = true;
    setFull(null);
    if (!itemId || !fromList) return undefined;
    void loadWorkItem(itemId)
      .then((item) => { if (current && item && item.id === itemId) setFull(item); })
      .catch(() => undefined);
    return () => { current = false; };
  }, [itemId, fromList, reloadToken]);

  return mergeWorkItem(row, full && full.id === itemId ? full : null);
}
