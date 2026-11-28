import { useRef } from "react";

import type { AdminTab } from "../types/adminPanelTypes.governance";
import { adminTabLoadsShellData, loadAdminTabData } from "./useAdminTabLoader.dispatch";
import type { UseAdminTabLoaderArgs } from "./useAdminTabLoader.types";

type LoadCounter = { current: number };

/** Only the latest load ends the loading state, so switching tabs never ends the new tab's loading early. */
export async function runTabLoad(counter: LoadCounter, tab: AdminTab, args: UseAdminTabLoaderArgs) {
  const { setLoadingTab, setTabError } = args;
  const load = ++counter.current;
  setTabError(null);
  // A panel that loads its own data stays mounted: toggling "Loading…" would remount it and repeat its requests.
  if (!adminTabLoadsShellData(tab)) {
    setLoadingTab(false);
    return;
  }
  setLoadingTab(true);
  try {
    await loadAdminTabData(tab, args);
  } catch (err) {
    if (load === counter.current) setTabError(err instanceof Error ? err.message : "Failed to load");
  } finally {
    if (load === counter.current) setLoadingTab(false);
  }
}

export function useAdminTabLoader(args: UseAdminTabLoaderArgs) {
  const counter = useRef(0);
  return (tab: AdminTab) => runTabLoad(counter, tab, args);
}
