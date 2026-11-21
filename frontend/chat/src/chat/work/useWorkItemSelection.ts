import { useEffect, useState } from "react";

import { loadWorkItem } from "./workPlanListApi";
import type { WorkItem } from "./workItemTypes";

export type WorkItemSelection = {
  item: WorkItem | null;
  loading: boolean;
  error: string | null;
};

// The full Work Item behind a selected id. The Work Item list loads at most 1000 records,
// so a plan row or a `work_item_id` link can point outside it; then the item is read by id from the
// scoped detail endpoint. A plan summary is never used in its place.
export function useWorkItemSelection(
  selectedItemId: string | null,
  items: WorkItem[],
  reloadToken: number,
  load: (workItemId: string) => Promise<WorkItem> = loadWorkItem,
): WorkItemSelection {
  const listed = selectedItemId ? items.find((item) => item.id === selectedItemId) || null : null;
  const isListed = listed !== null;
  const [fetched, setFetched] = useState<{ id: string; item: WorkItem | null; error: string | null } | null>(null);

  useEffect(() => {
    if (!selectedItemId || isListed) return undefined;
    let active = true;
    setFetched({ id: selectedItemId, item: null, error: null });
    load(selectedItemId)
      .then((item) => {
        if (active) setFetched({ id: selectedItemId, item, error: null });
      })
      .catch((err: unknown) => {
        if (active) {
          setFetched({ id: selectedItemId, item: null, error: err instanceof Error ? err.message : "The Work Item could not be loaded." });
        }
      });
    return () => {
      active = false;
    };
  }, [selectedItemId, isListed, reloadToken, load]);

  if (!selectedItemId) return { item: null, loading: false, error: null };
  if (listed) return { item: listed, loading: false, error: null };
  if (!fetched || fetched.id !== selectedItemId) return { item: null, loading: true, error: null };
  return { item: fetched.item, loading: !fetched.item && !fetched.error, error: fetched.error };
}
