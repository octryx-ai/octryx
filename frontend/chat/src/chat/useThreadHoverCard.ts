import { useCallback, useEffect, useRef, useState, type RefObject } from "react";

import type { ThreadSummary } from "../chatThreadTypes";

const HOVER_DELAY_MS = 550;

export type ThreadHoverState = { thread: ThreadSummary; workspace: string; top: number; left: number };

export function useThreadHoverCard(sidebarRef: RefObject<HTMLElement | null>, disabled: boolean) {
  const [hover, setHover] = useState<ThreadHoverState | null>(null);
  const timer = useRef<number | null>(null);

  const clear = useCallback(() => {
    if (timer.current !== null) {
      window.clearTimeout(timer.current);
      timer.current = null;
    }
    setHover(null);
  }, []);

  useEffect(() => {
    if (disabled) {
      clear();
    }
  }, [clear, disabled]);

  useEffect(() => clear, [clear]);

  const onRowHover = useCallback(
    (workspace: string) => (thread: ThreadSummary | null, row: HTMLElement | null) => {
      clear();
      if (!thread || !row || disabled || window.matchMedia?.("(max-width: 760px)").matches) {
        return;
      }
      timer.current = window.setTimeout(() => {
        const rowRect = row.getBoundingClientRect();
        const sidebarRect = sidebarRef.current?.getBoundingClientRect();
        setHover({
          thread,
          workspace,
          top: Math.min(window.innerHeight - 120, rowRect.top - 4),
          left: (sidebarRect?.right ?? rowRect.right) + 8,
        });
      }, HOVER_DELAY_MS);
    },
    [clear, disabled, sidebarRef],
  );

  return { hover, onRowHover };
}
