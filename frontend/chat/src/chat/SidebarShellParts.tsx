// Presentational parts of the chat sidebar: the pane header, the count row and the thread list body.
import type { ReactNode, RefObject } from "react";

import type { ThreadGroup } from "../chatThreadTypes";
import { ThreadDraftRow } from "./ThreadDraftRow";
import { ArchiveIcon, PlusIcon } from "./ChatShellIcons";
import { InfoIcon, SelectChatsIcon } from "./threadSidebarIcons";

function SidebarCollapseIcon({ collapsed }: { collapsed: boolean }) {
  return (
    <svg viewBox="0 0 20 20" aria-hidden="true">
      <path d={collapsed ? "M7 5l5 5-5 5" : "M13 5l-5 5 5 5"} />
    </svg>
  );
}

export function SidebarHeader({
  dashboardUrl,
  collapsed,
  onToggleCollapsed,
}: {
  dashboardUrl: string | undefined;
  collapsed: boolean;
  onToggleCollapsed: () => void;
}) {
  return (
    <div className="sidebar__header">
      <div className="sidebar__chrome sidebar__chrome--chat-workspace">
        <a
          className="brand brand--chat-workspace"
          href={dashboardUrl || "/chat"}
        >
          <div className="brand__copy">
            <div className="brand__title">Chats</div>
          </div>
        </a>
        <button
          type="button"
          className="sidebar__collapse-btn"
          onClick={onToggleCollapsed}
          aria-expanded={!collapsed}
          aria-label={collapsed ? "Expand chats" : "Collapse chats"}
          title={collapsed ? "Expand chats" : "Collapse chats"}
        >
          <SidebarCollapseIcon collapsed={collapsed} />
        </button>
      </div>
    </div>
  );
}

export function SidebarSectionRow({
  threadCountLabel,
  groupCountLabel,
  legendButtonRef,
  legendOpen,
  onToggleLegend,
  onSelectChats,
  onNewChat,
}: {
  threadCountLabel: string;
  groupCountLabel: string;
  legendButtonRef: RefObject<HTMLButtonElement>;
  legendOpen: boolean;
  onToggleLegend: () => void;
  onSelectChats: () => void;
  onNewChat: () => void;
}) {
  return (
    <div className="sidebar__section-row">
      {/* The pane's title above already says "Chats"; this line only counts. */}
      <div className="sidebar__section-heading">
        <div className="sidebar__section-meta">
          {threadCountLabel} · {groupCountLabel}
        </div>
      </div>
      <div className="sidebar__section-actions">
        <button
          ref={legendButtonRef}
          type="button"
          className="icon-button sidebar__icon-btn"
          title="What the row markers mean"
          aria-label="What the row markers mean"
          aria-expanded={legendOpen}
          onClick={onToggleLegend}
        >
          <InfoIcon />
        </button>
        <button
          type="button"
          className="icon-button sidebar__icon-btn"
          title="Select chats"
          aria-label="Select chats"
          aria-pressed={false}
          onClick={onSelectChats}
        >
          <SelectChatsIcon />
        </button>
        <button
          type="button"
          className="icon-button sidebar__icon-btn"
          title="New chat"
          aria-label="New chat"
          onClick={onNewChat}
        >
          <PlusIcon />
        </button>
      </div>
    </div>
  );
}

function OtherGroups({ otherGroups, otherThreadCount, renderGroup, searchActive }: {
  otherGroups: ThreadGroup[];
  otherThreadCount: number;
  renderGroup: (group: ThreadGroup) => ReactNode;
  searchActive: boolean;
}) {
  return (
    <details
      className="sidebar__other-groups"
      open={searchActive || undefined}
    >
      <summary>
        Other workspaces (inactive or unavailable) · {otherGroups.length} ·{" "}
        {otherThreadCount}{" "}
        {otherThreadCount === 1 ? "chat" : "chats"}
      </summary>
      {otherGroups.map(renderGroup)}
    </details>
  );
}

export function SidebarThreadList({
  showStandaloneDraft,
  onNewChat,
  activeGroups,
  otherGroups,
  otherThreadCount,
  hasGroups,
  renderGroup,
  searchActive,
  searchQuery,
  showArchivedLink,
  archivedCount,
  onOpenArchived,
}: {
  showStandaloneDraft: boolean;
  onNewChat: () => void;
  activeGroups: ThreadGroup[];
  otherGroups: ThreadGroup[];
  otherThreadCount: number;
  hasGroups: boolean;
  renderGroup: (group: ThreadGroup) => ReactNode;
  searchActive: boolean;
  searchQuery: string;
  showArchivedLink: boolean;
  archivedCount: number;
  onOpenArchived: () => void;
}) {
  return (
    <>
    {showStandaloneDraft ? (
      <div role="tree" aria-label="New chat">
        <ThreadDraftRow onSelect={onNewChat} />
      </div>
    ) : null}
    {activeGroups.map(renderGroup)}
    {hasGroups ? (
      <>
        {otherGroups.length ? (
          <OtherGroups otherGroups={otherGroups} otherThreadCount={otherThreadCount} renderGroup={renderGroup}
            searchActive={searchActive} />
        ) : null}
      </>
    ) : (
      <div className="sidebar__empty">
        {searchActive ? `No chat matches “${searchQuery}”.` : "No chats yet."}
      </div>
    )}
    {showArchivedLink ? (
      <button type="button" className="sidebar__archived-link" onClick={onOpenArchived}>
        <ArchiveIcon />
        <span>Archived chats</span>
        <span className="thread-group__title-meta">{archivedCount}</span>
      </button>
    ) : null}
    </>
  );
}
