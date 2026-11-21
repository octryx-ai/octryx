// Browser state of the Coding page: the selected session in the address and the collapsed-sidebar preference.

import { codingSelectionHref, selectedWorkItemIdFromSearch } from "./codingSelectionAddress";

const SIDEBAR_COLLAPSED_STORAGE_KEY = "octryx.coding.sidebarCollapsed";

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

export function selectedWorkItemIdFromUrl(): string | null {
  return selectedWorkItemIdFromSearch(window.location.search);
}

// Writes a session the person chose into the address (or removes one that is gone); see codingSelectionAddress.ts.
export function replaceCodingWorkItemUrl(workItemId: string | null) {
  const nextUrl = codingSelectionHref(window.location.href, workItemId);
  if (nextUrl !== window.location.href) window.history.replaceState({}, "", nextUrl);
}
