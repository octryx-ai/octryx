import { useEffect, useRef } from "react";

// Runs `load` at once, then every `pollMs` while the page is visible, and again as soon as it becomes visible
// (board 10 s, claims 10 s). `key` restarts the cycle (Workspace, filters); `isCurrent` turns false when the
// cycle ends, so a late answer of an old cycle is dropped.
export function useVisiblePolling(
  load: (isCurrent: () => boolean) => void,
  key: string | null,
  pollMs: number,
) {
  const latest = useRef(load);
  latest.current = load;

  useEffect(() => {
    if (key === null) return undefined;
    let current = true;
    const isCurrent = () => current;
    const visible = () => document.visibilityState !== "hidden";
    latest.current(isCurrent);
    const timer = setInterval(() => {
      if (visible()) latest.current(isCurrent);
    }, pollMs);
    const onVisibility = () => {
      if (visible()) latest.current(isCurrent);
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => { current = false; clearInterval(timer); document.removeEventListener("visibilitychange", onVisibility); };
  }, [key, pollMs]);
}
