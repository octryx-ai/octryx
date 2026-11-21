// Pull to refresh for the whole app, and a banner when a new version was deployed while it stayed open
// (``pullToRefresh``).

import { useEffect, useState, type ReactNode } from "react";
import {
  PULL_TRIGGER_PX,
  newVersionAvailable,
  requestRefresh,
  usePullToRefresh,
} from "./pullToRefresh";

export function RefreshShell({ children }: { children: ReactNode }) {
  const pull = usePullToRefresh(requestRefresh, true);
  const [updateReady, setUpdateReady] = useState(false);
  useEffect(() => {
    const check = () => {
      if (document.visibilityState === "visible")
        void newVersionAvailable().then(
          (ready) => ready && setUpdateReady(true),
        );
    };
    check();
    document.addEventListener("visibilitychange", check);
    return () => document.removeEventListener("visibilitychange", check);
  }, []);
  const label = pull.refreshing
    ? "Refreshing…"
    : pull.distance >= PULL_TRIGGER_PX / 2 + 15
      ? "Release to refresh"
      : "Pull to refresh";
  return (
    <>
      {(pull.distance > 0 || pull.refreshing) && (
        <div
          className="m-pull"
          role="status"
          style={{ height: pull.refreshing ? 44 : pull.distance }}
        >
          <span>{label}</span>
        </div>
      )}
      {updateReady && (
        <button
          type="button"
          className="m-update"
          onClick={() => location.reload()}
        >
          A new version is ready · Reload
        </button>
      )}
      {children}
    </>
  );
}
