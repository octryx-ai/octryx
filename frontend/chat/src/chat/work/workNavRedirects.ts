import type { WorkNavKey } from "./workTypes";

// Where a Work address lands: `?work_view=` names one of today's pages (the names `workViewOf` writes); a
// `change_plan_id` link opens Plans. Any other name opens the home page.

export type WorkItemsMode = "board" | "table";
export type WorkPlansTab = "all" | "review";
export type WorkLocation = { nav: WorkNavKey; itemsMode: WorkItemsMode; plansTab: WorkPlansTab };

// Work opens on Runs: what waits for the person comes first.
const HOME: WorkLocation = { nav: "runs", itemsMode: "board", plansTab: "all" };

const ADDRESSES: Record<string, Partial<WorkLocation>> = {
  runs: { nav: "runs" },
  epics: { nav: "epics" },
  board: { nav: "board", itemsMode: "board" },
  table: { nav: "board", itemsMode: "table" },
  plans: { nav: "changePlans", plansTab: "all" },
  reviews: { nav: "changePlans", plansTab: "review" },
  intake: { nav: "intake" },
  writeback: { nav: "writeback" },
};

export function workLocation(search: string): WorkLocation {
  const params = new URLSearchParams(search);
  const requested = params.get("work_view") ?? "";
  if (Object.hasOwn(ADDRESSES, requested)) return { ...HOME, ...ADDRESSES[requested] };
  if (params.get("change_plan_id")) return { ...HOME, nav: "changePlans" };
  return HOME;
}

/** The `work_view` that reopens this page; `workLocation` reads it back to the same page. */
export function workViewOf(location: Pick<WorkLocation, "nav" | "itemsMode" | "plansTab">): string {
  if (location.nav === "board") return location.itemsMode;
  if (location.nav === "changePlans") return location.plansTab === "review" ? "reviews" : "plans";
  return location.nav;
}

/** Keeps the chosen Work page in the address, so a remount, a reload or a shared link opens the same page. */
export function writeWorkView(location: Pick<WorkLocation, "nav" | "itemsMode" | "plansTab">) {
  const next = new URL(window.location.href);
  next.searchParams.set("work_view", workViewOf(location));
  if (next.toString() !== window.location.href) window.history.replaceState(window.history.state, "", next.toString());
}

/** The plugin page the address opens (`plugin_page=<install>:<page>`, plugins contract §4), or null. */
export function readPluginPage(search: string): string | null {
  try {
    return new URLSearchParams(search).get("plugin_page")?.trim() || null;
  } catch {
    return null;
  }
}

/** Keeps the open plugin page in the address, so a reload reopens it; a Work page removes it. */
export function writePluginPage(key: string | null) {
  const next = new URL(window.location.href);
  if (key) next.searchParams.set("plugin_page", key);
  else next.searchParams.delete("plugin_page");
  if (next.toString() !== window.location.href) window.history.replaceState(window.history.state, "", next.toString());
}
