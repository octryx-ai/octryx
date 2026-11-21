// Renders one thread row of a group with its toggle, bulk checkbox, rename field, actions menu and sub-chats.
import type { Dispatch, KeyboardEvent, MouseEvent, MutableRefObject, ReactNode, SetStateAction } from "react";

import type { ThreadSummary } from "../chatThreadTypes";
import { getThreadSignalKind } from "./threadSignalKind";
import { ThreadMarker, ThreadRenameInput, ThreadRowMeta } from "./ThreadRowParts";
import { threadTimeLabel } from "./threadTime";
import type { ThreadGroupBulk } from "./ThreadGroupBulkParts";
import { ThreadRowMenu } from "./ThreadRowMenu";
import {
  ThreadCheckboxBox,
  ThreadChevronIcon as ChevronIcon,
  ThreadMoreIcon as MoreIcon,
} from "./threadSidebarIcons";
import { threadTreeContainsSelected, type ThreadActionHandler } from "./threadGroupRowHandlers";

export type ThreadNodeRendererContext = {
  expandedParents: Record<string, boolean>;
  bulk?: ThreadGroupBulk;
  bulkMode: boolean;
  renamingThreadId: string | null;
  setRenamingThreadId: Dispatch<SetStateAction<string | null>>;
  openMenuThreadId: string | null;
  setOpenMenuThreadId: Dispatch<SetStateAction<string | null>>;
  menuTriggers: MutableRefObject<Record<string, HTMLButtonElement | null>>;
  canDeleteThreads: boolean;
  toggleParent: (threadId: string) => void;
  runAction: (thread: ThreadSummary, action: ThreadActionHandler) => Promise<void>;
  handleRowClick: (thread: ThreadSummary, selectable: boolean, event: MouseEvent<HTMLButtonElement>) => void;
  handleRowKeyDown: (thread: ThreadSummary, selectable: boolean, event: KeyboardEvent<HTMLButtonElement>) => void;
  startLongPress: (thread: ThreadSummary, selectable: boolean) => void;
  cancelLongPress: () => void;
  onRename: (thread: ThreadSummary, title: string) => void | Promise<void>;
  onPinToggle: ThreadActionHandler;
  onArchive: ThreadActionHandler;
  onExport: ThreadActionHandler;
  onExportAnalysis: ThreadActionHandler;
  onDelete: ThreadActionHandler;
  onEnterBulk?: (thread: ThreadSummary) => void;
  onRowHover?: (thread: ThreadSummary | null, row: HTMLElement | null) => void;
};
type Ctx = ThreadNodeRendererContext;

function renderBulkCheckbox(bulk: ThreadGroupBulk, thread: ThreadSummary, isChecked: boolean) {
  return (
    <label className="thread-card__checkbox">
      <input
        type="checkbox"
        checked={isChecked}
        tabIndex={-1}
        aria-hidden="true"
        onChange={() => undefined}
        onClick={(event) => {
          event.preventDefault();
          bulk.onToggleRow(thread, event.shiftKey);
        }}
      />
      <ThreadCheckboxBox />
    </label>
  );
}

function renderThreadCard(ctx: Ctx, thread: ThreadSummary, depth: number, isChecked: boolean) {
  const { bulkMode, renamingThreadId, setRenamingThreadId, onRename, handleRowClick, handleRowKeyDown } = ctx;
  const { startLongPress, cancelLongPress, onRowHover } = ctx;
  const selectable = depth === 0;
  const signalKind = getThreadSignalKind(thread);
  return renamingThreadId === thread.id ? (
    <div className="thread-card thread-card--renaming">
      <ThreadMarker kind={signalKind} stopReason={thread.latestTurnStopReason} />
      <ThreadRenameInput
        title={thread.title}
        onDone={(title) => {
          setRenamingThreadId(null);
          if (title !== null) {
            void onRename(thread, title);
          }
        }}
      />
    </div>
  ) : (
    <button
      type="button"
      className={`thread-card ${depth > 0 ? "thread-card--subthread" : ""} ${thread.isSelected && !bulkMode ? "thread-card--active" : ""} ${isChecked ? "thread-card--selected" : ""}`}
      onClick={(event) => handleRowClick(thread, selectable, event)}
      onKeyDown={(event) => handleRowKeyDown(thread, selectable, event)}
      onTouchStart={() => startLongPress(thread, selectable)}
      onTouchEnd={cancelLongPress}
      onTouchMove={cancelLongPress}
      onTouchCancel={cancelLongPress}
      onMouseEnter={(event) => onRowHover?.(thread, event.currentTarget)}
      onMouseLeave={() => onRowHover?.(null, null)}
      onFocus={() => onRowHover?.(null, null)}
    >
      <ThreadMarker kind={signalKind} stopReason={thread.latestTurnStopReason} />
      <span className="thread-card__title-text">{thread.title}</span>
      <ThreadRowMeta thread={thread} timeLabel={threadTimeLabel(thread.lastActivityAt ?? thread.startedAt)} />
    </button>
  );
}

function renderThreadMenu(ctx: Ctx, thread: ThreadSummary, selectable: boolean) {
  const { menuTriggers, openMenuThreadId, setOpenMenuThreadId, setRenamingThreadId, canDeleteThreads } = ctx;
  const { runAction, onPinToggle, onArchive, onExport, onExportAnalysis, onDelete, onEnterBulk } = ctx;
  return (
    <div
      className="thread-card__menu-shell"
      onClick={(event) => event.stopPropagation()}
    >
      <button
        ref={(element) => {
          menuTriggers.current[thread.id] = element;
        }}
        type="button"
        className={`thread-card__menu-trigger ${openMenuThreadId === thread.id ? "thread-card__menu-trigger--open" : ""}`}
        aria-label={`Actions for ${thread.title}`}
        aria-haspopup="menu"
        aria-expanded={openMenuThreadId === thread.id}
        onClick={() =>
          setOpenMenuThreadId((current) =>
            current === thread.id ? null : thread.id,
          )
        }
      >
        <MoreIcon />
      </button>
      {openMenuThreadId === thread.id ? (
        <ThreadRowMenu
          thread={thread}
          anchor={menuTriggers.current[thread.id] ?? null}
          canDeleteThreads={canDeleteThreads}
          onClose={() => setOpenMenuThreadId(null)}
          onPinToggle={() => void runAction(thread, onPinToggle)}
          onRename={() => {
            setOpenMenuThreadId(null);
            setRenamingThreadId(thread.id);
          }}
          onSelect={
            selectable && onEnterBulk
              ? () => {
                  setOpenMenuThreadId(null);
                  onEnterBulk(thread);
                }
              : undefined
          }
          onArchive={() => void runAction(thread, onArchive)}
          onExport={() => void runAction(thread, onExport)}
          onExportAnalysis={() => void runAction(thread, onExportAnalysis)}
          onDelete={() => void runAction(thread, onDelete)}
        />
      ) : null}
    </div>
  );
}

function renderThreadNode(ctx: Ctx, thread: ThreadSummary, depth: number): ReactNode {
  const { expandedParents, bulk, bulkMode, renamingThreadId, toggleParent } = ctx;
  const subThreads = thread.subThreads ?? [];
  const hasSubThreads = subThreads.length > 0;
  // Sub-chats start folded (a run's items can be many); they open by themselves only when one of them
  // is the open chat, so it stays visible. Opening the parent alone keeps them folded.
  const isExpanded =
    expandedParents[thread.id] ?? subThreads.some((child) => threadTreeContainsSelected(child));
  // Only top-level chats are selectable: sub-chats go with their parent.
  const selectable = depth === 0;
  const isChecked = Boolean(bulk && selectable && bulk.isSelected(thread.id));
  return (
    <div
      key={thread.id}
      className="thread-node"
      role="treeitem"
      aria-selected={bulkMode ? isChecked : thread.isSelected}
      {...(bulkMode && selectable ? { "aria-checked": isChecked } : {})}
    >
      <div
        className={`thread-node__row ${depth > 0 ? "thread-node__row--child" : ""}`}
      >
        {hasSubThreads ? (
          <button
            type="button"
            className="thread-node__toggle"
            onClick={() => toggleParent(thread.id)}
            aria-label={isExpanded ? "Collapse subchats" : "Expand subchats"}
            title={isExpanded ? "Collapse subchats" : "Expand subchats"}
          >
            <ChevronIcon open={isExpanded} />
          </button>
        ) : depth > 0 ? (
          <span className="thread-node__toggle thread-node__toggle--placeholder" />
        ) : null}
        {bulk && selectable ? renderBulkCheckbox(bulk, thread, isChecked) : null}
        {renderThreadCard(ctx, thread, depth, isChecked)}
        {!bulkMode && renamingThreadId !== thread.id ? renderThreadMenu(ctx, thread, selectable) : null}
      </div>
      {hasSubThreads && isExpanded ? (
        <div className="thread-subtree" role="group">
          {subThreads.map((child) => renderThreadNode(ctx, child, depth + 1))}
        </div>
      ) : null}
      {hasSubThreads && !isExpanded ? (
        <button
          type="button"
          className="thread-node__more"
          onClick={() => toggleParent(thread.id)}
          data-testid="thread-subchats-folded"
        >
          {subThreads.length === 1 ? "1 subchat" : `${subThreads.length} subchats`}
        </button>
      ) : null}
    </div>
  );
}

export function createThreadNodeRenderer(context: ThreadNodeRendererContext) {
  const renderNode = (thread: ThreadSummary, depth = 0): ReactNode => renderThreadNode(context, thread, depth);
  return renderNode;
}
