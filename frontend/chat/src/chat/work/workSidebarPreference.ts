// Whether the Work navigation sidebar is collapsed, remembered in the browser.

const SIDEBAR_COLLAPSED_STORAGE_KEY = "octryx.work.sidebarCollapsed";

export function readSidebarCollapsedPreference(): boolean {
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY) === "true";
  } catch {
    return false;
  }
}

export function storeSidebarCollapsedPreference(value: boolean) {
  try {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(value));
  } catch {
    // The visible state still updates when persistent storage is unavailable.
  }
}
