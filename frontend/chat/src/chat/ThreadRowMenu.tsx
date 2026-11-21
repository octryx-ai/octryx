import { useLayoutEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { createPortal } from "react-dom";

import type { ThreadSummary } from "../chatThreadTypes";
import {
  ArchiveIcon,
  BrainIcon,
  ExportIcon,
  PencilIcon,
  PinIcon,
  TrashIcon,
} from "./ChatShellIcons";
import { SelectChatsIcon } from "./threadSidebarIcons";

function MenuItem({
  icon,
  label,
  shortcut,
  danger = false,
  onClick,
}: {
  icon: ReactNode;
  label: string;
  shortcut?: string;
  danger?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      className={danger ? "thread-card__menu-danger" : undefined}
      onClick={onClick}
    >
      <span className="thread-card__menu-item-icon">{icon}</span>
      <span>{label}</span>
      {shortcut ? (
        <kbd className="thread-card__menu-kbd" aria-hidden="true">
          {shortcut}
        </kbd>
      ) : null}
    </button>
  );
}

/** Below the trigger, flipped above it near the bottom of the window; never clipped by the list. */
function useMenuPosition(anchor: HTMLElement | null) {
  const menuRef = useRef<HTMLDivElement>(null);
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null);
  useLayoutEffect(() => {
    const menu = menuRef.current;
    if (!menu || !anchor) {
      return;
    }
    const rect = anchor.getBoundingClientRect();
    const height = menu.offsetHeight;
    const width = menu.offsetWidth;
    const below = rect.bottom + 4;
    const top = below + height > window.innerHeight ? rect.top - height - 4 : below;
    setPosition({
      top: Math.max(8, top),
      left: Math.max(8, Math.min(window.innerWidth - width - 8, rect.right - width + 4)),
    });
    menu.querySelector<HTMLButtonElement>("[role=menuitem]")?.focus();
  }, [anchor]);
  return { menuRef, position };
}

/** The "…" menu of one chat row. `onSelect` is absent for sub-chats (they go with their parent). */
export function ThreadRowMenu({
  thread,
  anchor,
  canDeleteThreads,
  onClose,
  onPinToggle,
  onRename,
  onSelect,
  onArchive,
  onExport,
  onExportAnalysis,
  onDelete,
}: {
  thread: ThreadSummary;
  anchor: HTMLElement | null;
  canDeleteThreads: boolean;
  /** Esc and Tab close the menu; Esc returns the focus to the trigger. */
  onClose: () => void;
  onPinToggle: () => void;
  onRename: () => void;
  onSelect?: () => void;
  onArchive: () => void;
  onExport: () => void;
  onExportAnalysis: () => void;
  onDelete: () => void;
}) {
  const { menuRef, position } = useMenuPosition(anchor);
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const items = Array.from(event.currentTarget.querySelectorAll<HTMLButtonElement>("[role=menuitem]"));
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      items[(index + step + items.length) % items.length]?.focus();
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      items[event.key === "Home" ? 0 : items.length - 1]?.focus();
    } else if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      onClose();
      anchor?.focus();
    } else if (event.key === "Tab") {
      onClose();
    }
  };
  return createPortal(
    <div
      ref={menuRef}
      className="thread-card__menu"
      role="menu"
      aria-label={`Actions for ${thread.title}`}
      style={position ? { top: position.top, left: position.left } : { visibility: "hidden" }}
      onKeyDown={onKeyDown}
      onClick={(event) => event.stopPropagation()}
    >
      <MenuItem icon={<PinIcon />} label={thread.isPinned ? "Unpin" : "Pin"} shortcut="P" onClick={onPinToggle} />
      <MenuItem icon={<PencilIcon />} label="Rename" shortcut="F2" onClick={onRename} />
      {onSelect ? <MenuItem icon={<SelectChatsIcon />} label="Select" shortcut="X" onClick={onSelect} /> : null}
      {thread.status !== "archived" ? (
        <MenuItem icon={<ArchiveIcon />} label="Archive" shortcut="E" onClick={onArchive} />
      ) : null}
      <hr />
      <MenuItem icon={<ExportIcon />} label="Export evidence PDF" onClick={onExport} />
      <MenuItem icon={<BrainIcon />} label="Export analysis JSON" onClick={onExportAnalysis} />
      {canDeleteThreads ? (
        <>
          <hr />
          <MenuItem icon={<TrashIcon />} label="Delete…" danger onClick={onDelete} />
        </>
      ) : null}
    </div>,
    document.body,
  );
}
