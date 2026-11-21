// A Workspace's thread group in the sidebar: title with count, sections by time, thread rows and Load more.
import type { ThreadGroup, ThreadSummary } from "../chatThreadTypes";
import type { ThreadGroupBulk } from "./ThreadGroupBulkParts";
import { createThreadNodeRenderer } from "./ThreadGroupNode";
import { ThreadGroupItems, ThreadGroupTitle } from "./ThreadGroupSectionParts";
import { createThreadRowHandlers, type ThreadActionHandler } from "./threadGroupRowHandlers";
import { createThreadGroupActions, useThreadGroupSectionState } from "./useThreadGroupSectionState";

type ThreadGroupSectionProps = {
  group: ThreadGroup;
  onSelect: (thread: ThreadSummary) => void | Promise<void>;
  onPinToggle: (thread: ThreadSummary) => void | Promise<void>;
  /** Inline rename: the new title; the open chat does not change. */
  onRename: (thread: ThreadSummary, title: string) => void | Promise<void>;
  onArchive: ThreadActionHandler;
  onExport: ThreadActionHandler;
  onExportAnalysis: ThreadActionHandler;
  onDelete: ThreadActionHandler;
  canDeleteThreads?: boolean;
  bulk?: ThreadGroupBulk;
  /** A search is active: the group total is its match count, and the group is open. */
  searching?: boolean;
  onEnterBulk?: (thread: ThreadSummary) => void;
  onLoadMore?: () => void | Promise<void>;
  /** Set when the unsent new chat belongs to this Workspace: its draft row leads the group. */
  onDraftSelect?: () => void;
  /** Desktop hover card: the hovered row (null when it leaves). */
  onRowHover?: (thread: ThreadSummary | null, row: HTMLElement | null) => void;
};

export function ThreadGroupSection({
  group,
  onSelect,
  onPinToggle,
  onRename,
  onArchive,
  onExport,
  onExportAnalysis,
  onDelete,
  canDeleteThreads = false,
  bulk,
  searching = false,
  onEnterBulk,
  onLoadMore,
  onDraftSelect,
  onRowHover,
}: ThreadGroupSectionProps) {
  const bulkMode = Boolean(bulk);
  const state = useThreadGroupSectionState(group, onDraftSelect);
  const { setOpenMenuThreadId, loadingMore, groupThreadCount } = state;
  const notShown = Math.max(0, groupThreadCount - group.sessions.length);
  const open = state.groupOpen || searching;

  const { toggleParent, runAction, handleLoadMore } = createThreadGroupActions(state, onLoadMore);

  const rowHandlers = createThreadRowHandlers({
    bulk, onEnterBulk, onSelect, onPinToggle, onArchive, longPress: state.longPress,
    setRenamingThreadId: state.setRenamingThreadId,
  });

  const renderThreadNode = createThreadNodeRenderer({
    ...rowHandlers, expandedParents: state.expandedParents, bulk, bulkMode, renamingThreadId: state.renamingThreadId,
    setRenamingThreadId: state.setRenamingThreadId, openMenuThreadId: state.openMenuThreadId, setOpenMenuThreadId,
    menuTriggers: state.menuTriggers, canDeleteThreads, toggleParent, runAction, onRename, onPinToggle, onArchive,
    onExport, onExportAnalysis, onDelete, onEnterBulk, onRowHover,
  });

  return (
    <section className="thread-group" aria-label={group.projectName}>
      <ThreadGroupTitle group={group} bulk={bulk} open={open} searching={searching} groupThreadCount={groupThreadCount}
        onToggle={() => state.setGroupOpen((value) => !value)} />
      {open ? (
        <ThreadGroupItems group={group} bulk={bulk} sections={state.sections} notShown={notShown}
          loadingMore={loadingMore} onDraftSelect={onDraftSelect} onLoadMore={() => void handleLoadMore()}
          renderThreadNode={renderThreadNode} />
      ) : null}
    </section>
  );
}
