// Work detail address: `work_item_id` opens a Work Item, `change_plan_id` selects one of its
// Change Plans by exact id. Both are kept in the address so a reload or a shared link reopens them.
export function readWorkDetailParam(name: "work_item_id" | "change_plan_id"): string | null {
  return new URLSearchParams(window.location.search).get(name);
}

export function writeWorkDetailLink(workItemId: string | null, changePlanId: string | null) {
  const nextUrl = new URL(window.location.href);
  if (workItemId) {
    nextUrl.searchParams.set("area", "work");
    nextUrl.searchParams.set("work_item_id", workItemId);
  } else {
    nextUrl.searchParams.delete("work_item_id");
    nextUrl.searchParams.delete(WORK_ITEM_VIEW_PARAM);
  }
  if (workItemId && changePlanId) nextUrl.searchParams.set("change_plan_id", changePlanId);
  else nextUrl.searchParams.delete("change_plan_id");
  window.history.replaceState(null, "", nextUrl.toString());
}

// "Open as page": the same detail full width instead of the side panel over the list.
export const WORK_ITEM_VIEW_PARAM = "work_item_view";

export function isWorkItemPage(search: string): boolean {
  return new URLSearchParams(search).get(WORK_ITEM_VIEW_PARAM) === "page";
}

/** The address of the open Work Item as a page: today's address plus work_item_view=page. */
export function workItemPageHref(search: string, pathname = "/chat"): string {
  const params = new URLSearchParams(search);
  params.set(WORK_ITEM_VIEW_PARAM, "page");
  return `${pathname}?${params.toString()}`;
}
