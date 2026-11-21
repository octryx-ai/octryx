import { useEffect, useState } from "react";

import { loadWorkItem } from "./workPlanListApi";
import type { WorkItem } from "./workItemTypes";

// The list rows are lean on newer servers (no description, comments, watchers, components, linked issues or
// source_fields); the detail reads the item itself. Until it arrives the list row is shown, so the panel never
// waits empty. An item opened by link that is not in the loaded pages is already read by id (useWorkItemSelection),
// so only a lean list row is read again.

/** The list row overlaid by the full item; the full item's fields win. */
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
      // A failed read or a refusal: the list row stays the detail.
      .catch(() => undefined);
    return () => { current = false; };
  }, [itemId, fromList, reloadToken]);

  return mergeWorkItem(row, full && full.id === itemId ? full : null);
}
