// Refreshing the Home Screen app (the app could not be refreshed). A web app added to the iPhone's
// Home Screen has no reload button and no pull-to-refresh, and iOS keeps it in memory: without this, neither fresh
// data on demand nor a newly deployed version reaches it.
//
// - pulling down at the top of any screen refreshes it (the open page listens to REFRESH_EVENT);
// - a new deployment is found by comparing the page's own script with the one /m serves now; pulling then reloads,
//   and coming back to the app shows a "reload" banner instead of reloading under the person's finger.

import { useEffect, useRef, useState } from "react";

export const REFRESH_EVENT = "octryx:refresh";
export const PULL_TRIGGER_PX = 70;
const MAX_PULL_PX = 110;

/** The main module script of a page (its hashed build file), or "" when none is found. */
export function scriptOf(html: string): string {
  const match =
    /<script[^>]*type="module"[^>]*src="([^"]+)"/i.exec(html) ??
    /<script[^>]*src="([^"]+)"[^>]*type="module"/i.exec(html);
  return match ? match[1] : "";
}

/** How far the indicator follows the finger: damped, and capped. */
export function pullDistance(startY: number, currentY: number): number {
  const delta = currentY - startY;
  if (delta <= 0) return 0;
  return Math.min(MAX_PULL_PX, Math.round(delta * 0.5));
}

function currentScript(): string {
  const element = document.querySelector<HTMLScriptElement>(
    'script[type="module"][src]',
  );
  return element ? new URL(element.src, location.href).pathname : "";
}

/** Whether /m now serves a different build than the one running. Never throws. */
export async function newVersionAvailable(): Promise<boolean> {
  try {
    const response = await fetch("/m/", {
      cache: "no-store",
      credentials: "same-origin",
    });
    if (!response.ok) return false;
    const served = scriptOf(await response.text());
    const running = currentScript();
    return (
      !!served &&
      !!running &&
      new URL(served, location.href).pathname !== running
    );
  } catch {
    return false;
  }
}

export type PullState = { distance: number; refreshing: boolean };

/** Pull-to-refresh on the document; ``onRefresh`` runs when a pull from the very top passes the trigger. */
export function usePullToRefresh(
  onRefresh: () => Promise<void>,
  enabled: boolean,
): PullState {
  const [state, setState] = useState<PullState>({
    distance: 0,
    refreshing: false,
  });
  const start = useRef<number | null>(null);
  const distance = useRef(0);
  const busy = useRef(false);
  const handler = useRef(onRefresh);
  handler.current = onRefresh;

  useEffect(() => {
    if (!enabled) return;
    const atTop = () => (document.scrollingElement?.scrollTop ?? 0) <= 0;
    const inSheet = (target: EventTarget | null) =>
      target instanceof Element && !!target.closest(".m-sheet, textarea");
    const onStart = (event: TouchEvent) => {
      start.current =
        !busy.current && atTop() && !inSheet(event.target)
          ? event.touches[0].clientY
          : null;
    };
    const onMove = (event: TouchEvent) => {
      if (start.current === null) return;
      distance.current = pullDistance(start.current, event.touches[0].clientY);
      setState((current) =>
        current.distance === distance.current
          ? current
          : { ...current, distance: distance.current },
      );
    };
    const onEnd = () => {
      if (start.current === null) return;
      start.current = null;
      const pulled = distance.current;
      distance.current = 0;
      if (pulled < PULL_TRIGGER_PX) {
        setState({ distance: 0, refreshing: false });
        return;
      }
      busy.current = true;
      setState({ distance: 0, refreshing: true });
      void handler
        .current()
        .catch(() => undefined)
        .finally(() => {
          busy.current = false;
          setState({ distance: 0, refreshing: false });
        });
    };
    window.addEventListener("touchstart", onStart, { passive: true });
    window.addEventListener("touchmove", onMove, { passive: true });
    window.addEventListener("touchend", onEnd);
    window.addEventListener("touchcancel", onEnd);
    return () => {
      window.removeEventListener("touchstart", onStart);
      window.removeEventListener("touchmove", onMove);
      window.removeEventListener("touchend", onEnd);
      window.removeEventListener("touchcancel", onEnd);
    };
  }, [enabled]);
  return state;
}

/** What a pull or the ↻ button does: a new deployment reloads the page; otherwise the open screen refreshes. */
export async function requestRefresh(): Promise<void> {
  if (await newVersionAvailable()) {
    location.reload();
    return;
  }
  window.dispatchEvent(new Event(REFRESH_EVENT));
  await new Promise((resolve) => window.setTimeout(resolve, 600));
}

/** Calls ``refresh`` whenever the person pulls to refresh or taps ↻ (while the screen is mounted). */
export function useRefreshEvent(refresh: () => unknown): void {
  const handler = useRef(refresh);
  handler.current = refresh;
  useEffect(() => {
    const listener = () => void handler.current();
    window.addEventListener(REFRESH_EVENT, listener);
    return () => window.removeEventListener(REFRESH_EVENT, listener);
  }, []);
}
