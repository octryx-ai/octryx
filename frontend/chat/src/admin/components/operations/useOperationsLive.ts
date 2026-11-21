import { useCallback, useEffect, useRef, useState } from "react";

import { isOpsRefusal, loadOperationsLive, type OpsOptions } from "./operationsApi";
import type { OperationsLive } from "./operationsTypes";

// One poll for the desktop page and the phone (contract §2): every 10 s, paused while the tab is hidden and
// refreshed at once when it shows again. A 403 on the admin route switches to the Workspace route for good.

export const POLL_MS = 10_000;

export type LiveState = {
  live: OperationsLive | null;
  error: string;
  // When the shown data arrived (ms), for "updated N s ago".
  loadedAt: number | null;
  // The clock of the last tick (ms), so "x ago" texts move between polls.
  now: number;
  viaWorkspace: boolean;
  reload: () => Promise<void>;
};

export function useOperationsLive(workspaceId: string, options: OpsOptions = {}): LiveState {
  const [live, setLive] = useState<OperationsLive | null>(null);
  const [error, setError] = useState("");
  const [loadedAt, setLoadedAt] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const [viaWorkspace, setViaWorkspace] = useState(false);
  const workspaceRoute = useRef(false);
  const renew = options.renew;

  const reload = useCallback(async () => {
    try {
      const result = await loadOperationsLive({ workspaceId, useWorkspaceRoute: workspaceRoute.current }, { renew });
      workspaceRoute.current = result.viaWorkspace;
      setViaWorkspace(result.viaWorkspace);
      setLive(result.live);
      setLoadedAt(Date.now());
      setError("");
    } catch (failure) {
      setError(isOpsRefusal(failure) || failure instanceof Error ? failure.message : "Operations could not be loaded.");
    }
  }, [workspaceId, renew]);

  useEffect(() => {
    setLive(null);
    setError("");
    void reload();
    const poll = window.setInterval(() => { if (!document.hidden) void reload(); }, POLL_MS);
    const tick = window.setInterval(() => { if (!document.hidden) setNow(Date.now()); }, 1000);
    const visible = () => { if (!document.hidden) { setNow(Date.now()); void reload(); } };
    document.addEventListener("visibilitychange", visible);
    return () => {
      window.clearInterval(poll);
      window.clearInterval(tick);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [reload]);

  return { live, error, loadedAt, now, viaWorkspace, reload };
}

/** "Updated 4 s ago" under the page title; "" before the first answer. */
export function updatedText(loadedAt: number | null, now: number): string {
  if (loadedAt === null) return "";
  const seconds = Math.max(0, Math.round((now - loadedAt) / 1000));
  return seconds < 2 ? "Updated just now" : seconds < 60 ? `Updated ${seconds} s ago` : `Updated ${Math.floor(seconds / 60)} min ago`;
}
