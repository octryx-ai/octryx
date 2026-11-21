// Keyboard handling of the chat list: arrow keys move between rows, Cmd/Ctrl+A selects all in bulk mode.
import type { KeyboardEvent } from "react";

import type { ThreadRef } from "./threadSelection";
import type { ThreadBulkController } from "./useThreadBulk";

export function handleThreadsKeyDown(
  event: KeyboardEvent<HTMLDivElement>,
  bulkMode: boolean,
  threadBulk: ThreadBulkController,
  orderedRefs: ThreadRef[],
) {
  const target = event.target as HTMLElement;
  if (
    (event.key === "ArrowDown" || event.key === "ArrowUp") &&
    target.classList.contains("thread-card")
  ) {
    // ↑/↓ move between rows in visible order.
    event.preventDefault();
    const rows = Array.from(event.currentTarget.querySelectorAll<HTMLElement>("button.thread-card"));
    const next = rows.indexOf(target) + (event.key === "ArrowDown" ? 1 : -1);
    rows[Math.max(0, Math.min(rows.length - 1, next))]?.focus();
    return;
  }
  if (
    bulkMode &&
    (event.metaKey || event.ctrlKey) &&
    event.key.toLowerCase() === "a" &&
    !/INPUT|TEXTAREA/.test(target.tagName)
  ) {
    event.preventDefault();
    threadBulk.selectAll(orderedRefs);
  }
}
