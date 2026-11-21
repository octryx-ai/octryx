// Parts of a sidebar thread group: the title row with its count, and the rows by time section with Load more.
import { Fragment, type ReactNode } from "react";

import type { ThreadGroup, ThreadSummary } from "../chatThreadTypes";
import { GroupBanner, GroupCheckbox, type ThreadGroupBulk } from "./ThreadGroupBulkParts";
import { ThreadDraftRow } from "./ThreadDraftRow";
import type { ThreadSection } from "./threadTime";
import {
  ThreadChevronIcon as ChevronIcon,
  ThreadFolderIcon as FolderIcon,
} from "./threadSidebarIcons";

export function ThreadGroupTitle({
  group, bulk, open, searching, groupThreadCount, onToggle,
}: {
  group: ThreadGroup;
  bulk?: ThreadGroupBulk;
  open: boolean;
  searching: boolean;
  groupThreadCount: number;
  onToggle: () => void;
}) {
  const groupCheckLabel =
    bulk && (bulk.checkState === "none" || bulk.checkState === "some")
      ? `Select the ${group.sessions.length} shown chats in ${group.projectName}`
      : `Clear selection in ${group.projectName}`;
  return (
    <div className="thread-group__title">
      {bulk ? (
        <GroupCheckbox
          state={bulk.checkState}
          label={groupCheckLabel}
          onChange={bulk.onGroupCheck}
        />
      ) : null}
      <button
        type="button"
        className="thread-group__title-button"
        onClick={onToggle}
        aria-expanded={open}
      >
        <ChevronIcon open={open} />
        <FolderIcon />
        <div className="thread-group__title-copy">
          <span className="thread-group__title-name">
            {group.projectName}
          </span>
          <span className="thread-group__title-meta">
            {searching
              ? `${groupThreadCount} ${groupThreadCount === 1 ? "match" : "matches"}`
              : groupThreadCount}
          </span>
        </div>
      </button>
    </div>
  );
}

export function ThreadGroupItems({
  group, bulk, sections, notShown, loadingMore, onDraftSelect, onLoadMore, renderThreadNode,
}: {
  group: ThreadGroup;
  bulk?: ThreadGroupBulk;
  sections: ThreadSection<ThreadSummary>[];
  notShown: number;
  loadingMore: boolean;
  onDraftSelect?: () => void;
  onLoadMore: () => void;
  renderThreadNode: (thread: ThreadSummary) => ReactNode;
}) {
  return (
    <div className="thread-group__items">
      {bulk?.banner ? (
        <GroupBanner
          banner={bulk.banner}
          onSelectScope={bulk.onSelectScope}
          onClearScope={bulk.onClearScope}
        />
      ) : null}
      {/* Only rows (and plain section labels) are owned by the tree: ARIA tree children. */}
      <div
        className="thread-group__tree"
        role="tree"
        aria-label={`Chats in ${group.projectName}`}
        aria-multiselectable={Boolean(bulk)}
      >
        {onDraftSelect && !bulk ? (
          <>
            <div className="thread-group__section-label">Today</div>
            <ThreadDraftRow onSelect={onDraftSelect} />
          </>
        ) : null}
        {sections.map((section) => (
          <Fragment key={section.label}>
            {section.label === "Today" && onDraftSelect && !bulk ? null : (
              <div className="thread-group__section-label">{section.label}</div>
            )}
            {section.threads.map((thread) => renderThreadNode(thread))}
          </Fragment>
        ))}
      </div>
      {group.hasMore && notShown > 0 ? (
        <button
          type="button"
          className="thread-group__load-more"
          disabled={loadingMore}
          onClick={onLoadMore}
        >
          {loadingMore
            ? "Loading…"
            : `Show ${Math.min(group.pageSize ?? 20, notShown)} more · ${notShown} not shown`}
        </button>
      ) : null}
    </div>
  );
}
