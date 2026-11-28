import type { ThreadGroup } from "../chatThreadTypes";
import type { ThreadGroupBanner, ThreadGroupBulk } from "./ThreadGroupBulkParts";
import { groupCheckState, isThreadSelected, type ThreadRef, type ThreadSelection } from "./threadSelection";
import type { ThreadBulkController } from "./useThreadBulk";

export function threadGroupBanner({
  selection,
  group,
  query,
  searchCount,
}: {
  selection: ThreadSelection;
  group: ThreadGroup;
  query: string;
  searchCount: number | undefined;
}): ThreadGroupBanner | null {
  const projectId = group.projectId ?? "";
  const visibleIds = group.sessions.map((thread) => thread.id);
  const label = query ? `matching “${query}”` : `in ${group.projectName}`;
  const scope = selection.scopes[projectId];
  if (scope) {
    return {
      kind: "scope",
      selected: Math.max(0, scope.count - scope.exceptIds.length),
      total: scope.count,
      notLoaded: query ? 0 : Math.max(0, scope.count - visibleIds.length),
      label,
    };
  }
  if (groupCheckState(selection, projectId, visibleIds) !== "visible") {
    return null;
  }
  const total = query ? searchCount : (group.totalThreadCount ?? visibleIds.length);
  if (total === undefined || total <= visibleIds.length) {
    return null;
  }
  return { kind: "offer", shown: visibleIds.length, total, label };
}

export function threadGroupBulk(
  threadBulk: ThreadBulkController,
  group: ThreadGroup,
  orderedRefs: ThreadRef[],
): ThreadGroupBulk {
  const projectId = group.projectId ?? "";
  const visibleIds = group.sessions.map((thread) => thread.id);
  return {
    checkState: groupCheckState(threadBulk.selection, projectId, visibleIds),
    isSelected: (threadId) => isThreadSelected(threadBulk.selection, { id: threadId, projectId }),
    onToggleRow: (thread, shift) => threadBulk.toggle({ id: thread.id, projectId }, shift, orderedRefs),
    onGroupCheck: () => threadBulk.groupCheck(projectId, visibleIds),
    banner: threadGroupBanner({
      selection: threadBulk.selection,
      group,
      query: threadBulk.query,
      searchCount: threadBulk.searchOffers[projectId],
    }),
    onSelectScope: () => void threadBulk.selectScope(projectId),
    onClearScope: () => threadBulk.clearScope(projectId),
  };
}
