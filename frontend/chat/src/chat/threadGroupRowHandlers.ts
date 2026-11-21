// Thread tree helpers and the row interaction handlers of a thread group: click, long-press and keyboard shortcuts.
import type { Dispatch, KeyboardEvent, MouseEvent, MutableRefObject, SetStateAction } from "react";

import type { ThreadSummary } from "../chatThreadTypes";
import type { ThreadGroupBulk } from "./ThreadGroupBulkParts";

export function threadTreeContainsSelected(thread: ThreadSummary): boolean {
  if (thread.isSelected) {
    return true;
  }
  return (thread.subThreads ?? []).some((child) =>
    threadTreeContainsSelected(child),
  );
}

export function countThreadTree(threads: ThreadSummary[]): number {
  return threads.reduce(
    (total, thread) => total + 1 + countThreadTree(thread.subThreads ?? []),
    0,
  );
}

export type ThreadActionHandler = (thread: ThreadSummary) => void | Promise<void>;

export function createThreadRowHandlers({
  bulk,
  onEnterBulk,
  onSelect,
  onPinToggle,
  onArchive,
  longPress,
  setRenamingThreadId,
}: {
  bulk?: ThreadGroupBulk;
  onEnterBulk?: (thread: ThreadSummary) => void;
  onSelect: (thread: ThreadSummary) => void | Promise<void>;
  onPinToggle: (thread: ThreadSummary) => void | Promise<void>;
  onArchive: ThreadActionHandler;
  longPress: MutableRefObject<{ timer: number | null; fired: boolean }>;
  setRenamingThreadId: Dispatch<SetStateAction<string | null>>;
}) {
const handleRowClick = (
  thread: ThreadSummary,
  selectable: boolean,
  event: MouseEvent<HTMLButtonElement>,
) => {
  if (longPress.current.fired) {
    longPress.current.fired = false;
    event.preventDefault();
    return;
  }
  if (bulk) {
    // In bulk mode a row click toggles; it never navigates.
    if (selectable) {
      event.preventDefault();
      bulk.onToggleRow(thread, event.shiftKey);
    }
    return;
  }
  if (selectable && onEnterBulk && (event.shiftKey || event.metaKey || event.ctrlKey)) {
    event.preventDefault();
    onEnterBulk(thread);
    return;
  }
  void onSelect(thread);
};

const startLongPress = (thread: ThreadSummary, selectable: boolean) => {
  if (bulk || !selectable || !onEnterBulk) {
    return;
  }
  cancelLongPress();
  longPress.current.timer = window.setTimeout(() => {
    longPress.current = { timer: null, fired: true };
    onEnterBulk(thread);
  }, 480);
};

const cancelLongPress = () => {
  if (longPress.current.timer !== null) {
    window.clearTimeout(longPress.current.timer);
    longPress.current.timer = null;
  }
};

const handleRowKeyDown = (
  thread: ThreadSummary,
  selectable: boolean,
  event: KeyboardEvent<HTMLButtonElement>,
) => {
  if (!bulk && selectable && onEnterBulk && event.key.toLowerCase() === "x") {
    event.preventDefault();
    onEnterBulk(thread);
  }
  if (!bulk && event.key === "F2") {
    event.preventDefault();
    setRenamingThreadId(thread.id);
  }
  if (!bulk && !event.metaKey && !event.ctrlKey && !event.altKey) {
    const key = event.key.toLowerCase();
    if (key === "p") {
      event.preventDefault();
      void onPinToggle(thread);
    } else if (key === "e" && thread.status !== "archived") {
      event.preventDefault();
      void onArchive(thread);
    }
  }
};

  return { handleRowClick, startLongPress, cancelLongPress, handleRowKeyDown };
}
