// Whether the Agents area's second-level menu is collapsed, kept like Work's and Coding's (one key per area).
const SIDEBAR_COLLAPSED_STORAGE_KEY = "octryx.agents.sidebarCollapsed";

export function readAgentsSidebarCollapsed(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function storeAgentsSidebarCollapsed(value: boolean) {
  try {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(value));
  } catch {
    // The visible state still updates when persistent storage is unavailable.
  }
}
