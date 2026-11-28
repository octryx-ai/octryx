// Only a session the person chose is written as work_item_id, so the page's own first pick never ends up in a shared link.

export function selectedWorkItemIdFromSearch(search: string): string | null {
  return new URLSearchParams(search).get("work_item_id") || null;
}

export function addressSelectionAfterRead({ asked, shown }: { asked: string | null; shown: string | null }): string | null {
  return asked && shown === asked ? asked : null;
}

export function codingSelectionHref(href: string, workItemId: string | null): string {
  const next = new URL(href);
  next.searchParams.set("area", "coding");
  if (workItemId) next.searchParams.set("work_item_id", workItemId);
  else next.searchParams.delete("work_item_id");
  return next.toString();
}
