// Which coding session the address names. Opening Coding sessions shows the first session,
// but that pick is the page's, not the person's: only a session the person chose (a click, a link, a session just
// started) is written as `work_item_id`, so a shared link opens what they chose and nothing is added unasked.

/** The work item an address names (`work_item_id`). */
export function selectedWorkItemIdFromSearch(search: string): string | null {
  return new URLSearchParams(search).get("work_item_id") || null;
}

/**
 * The selection the address keeps after the session list is read: the session that was asked for, when the list
 * shows it. A session picked for the person (the first one) is never written; an asked-for one that is gone leaves.
 */
export function addressSelectionAfterRead({ asked, shown }: { asked: string | null; shown: string | null }): string | null {
  return asked && shown === asked ? asked : null;
}

/** The same address with `work_item_id` set to the chosen session (or removed), on the Coding area. */
export function codingSelectionHref(href: string, workItemId: string | null): string {
  const next = new URL(href);
  next.searchParams.set("area", "coding");
  if (workItemId) next.searchParams.set("work_item_id", workItemId);
  else next.searchParams.delete("work_item_id");
  return next.toString();
}
