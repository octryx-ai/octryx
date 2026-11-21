// The phone's page stack above the tabs (a chat, a Work item, a run): opening one pushes a browser history entry, so
// the system back gesture (Android, a browser) goes back a page; the app's own ‹ does the same through the history.

import { useCallback, useEffect, useRef, useState } from "react";

type Entry = { mDepth?: number } | null;

export function useDetailStack<T>() {
  const [stack, setStack] = useState<T[]>([]);
  const depth = useRef(0);
  depth.current = stack.length;

  useEffect(() => {
    const onPop = (event: PopStateEvent) => {
      const wanted = Math.max(0, Number((event.state as Entry)?.mDepth ?? 0));
      // Every back goes at least one page back (entries of a stack a tab reset may still be in the history).
      setStack((current) => (current.length ? current.slice(0, Math.min(wanted, current.length - 1)) : current));
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const open = useCallback((page: T) => {
    setStack((current) => [...current, page]);
    window.history.pushState({ mDepth: depth.current + 1 }, "");
  }, []);

  // The page on top becomes another one (a new chat that started, a chat that opened from a run's step).
  const replace = useCallback((page: T) => {
    setStack((current) => (current.length ? [...current.slice(0, -1), page] : [page]));
    if (!depth.current) window.history.pushState({ mDepth: 1 }, "");
  }, []);

  const back = useCallback(() => {
    if (depth.current > 0 && (window.history.state as Entry)?.mDepth) window.history.back();
    else setStack((current) => current.slice(0, -1));
  }, []);

  // A tab or a notification starts over from the tab's page.
  const reset = useCallback(() => setStack([]), []);

  return { page: stack.length ? stack[stack.length - 1] : null, open, replace, back, reset };
}
