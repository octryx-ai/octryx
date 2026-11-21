// Chat sidebar selection model. Pure, no React.
//
// A selection is explicit ids plus per-Workspace *scopes*. A scope means "all chats of this
// Workspace that match `query` and started at or before `asOf`, except `exceptIds`"; the server
// resolves it, so unloaded rows are covered without the client holding their ids. Only top-level
// chats are selectable: sub-chats go with their parent.

export type ThreadScope = {
  projectId: string;
  query: string;
  asOf: string;
  exceptIds: string[];
  /** Server count of the scope when it was chosen (the banner number). */
  count: number;
};

export type ThreadSelection = {
  /** Selected thread id → its Workspace (project) id; "" is "No project". */
  ids: Record<string, string>;
  /** Scopes by Workspace id. */
  scopes: Record<string, ThreadScope>;
};

export type ThreadRef = { id: string; projectId: string };

export type GroupCheckState = "none" | "some" | "visible" | "scope";

export type ThreadBulkAction = "archive" | "delete" | "restore";

export const EMPTY_THREAD_SELECTION: ThreadSelection = { ids: {}, scopes: {} };

export function isThreadSelected(selection: ThreadSelection, thread: ThreadRef): boolean {
  const scope = selection.scopes[thread.projectId];
  if (scope) {
    return !scope.exceptIds.includes(thread.id);
  }
  return thread.id in selection.ids;
}

export function selectedThreadCount(selection: ThreadSelection): number {
  const scoped = Object.values(selection.scopes).reduce(
    (total, scope) => total + Math.max(0, scope.count - scope.exceptIds.length),
    0,
  );
  return Object.keys(selection.ids).length + scoped;
}

export function toggleThread(selection: ThreadSelection, thread: ThreadRef): ThreadSelection {
  const scope = selection.scopes[thread.projectId];
  if (scope) {
    const exceptIds = scope.exceptIds.includes(thread.id)
      ? scope.exceptIds.filter((id) => id !== thread.id)
      : [...scope.exceptIds, thread.id];
    return { ...selection, scopes: { ...selection.scopes, [thread.projectId]: { ...scope, exceptIds } } };
  }
  const ids = { ...selection.ids };
  if (thread.id in ids) {
    delete ids[thread.id];
  } else {
    ids[thread.id] = thread.projectId;
  }
  return { ...selection, ids };
}

/** Adds every thread (range select, select all visible); a scoped Workspace un-excludes them. */
export function selectThreads(selection: ThreadSelection, threads: ThreadRef[]): ThreadSelection {
  const ids = { ...selection.ids };
  const scopes = { ...selection.scopes };
  for (const thread of threads) {
    const scope = scopes[thread.projectId];
    if (scope) {
      scopes[thread.projectId] = { ...scope, exceptIds: scope.exceptIds.filter((id) => id !== thread.id) };
    } else {
      ids[thread.id] = thread.projectId;
    }
  }
  return { ids, scopes };
}

/** The ids between the anchor and the target in visible order, both included. */
export function rangeThreadRefs(ordered: ThreadRef[], anchorId: string | null, targetId: string): ThreadRef[] {
  const targetIndex = ordered.findIndex((thread) => thread.id === targetId);
  const anchorIndex = anchorId ? ordered.findIndex((thread) => thread.id === anchorId) : -1;
  if (targetIndex < 0) {
    return [];
  }
  if (anchorIndex < 0) {
    return [ordered[targetIndex]];
  }
  const [start, end] = anchorIndex < targetIndex ? [anchorIndex, targetIndex] : [targetIndex, anchorIndex];
  return ordered.slice(start, end + 1);
}

export function groupCheckState(
  selection: ThreadSelection,
  projectId: string,
  visibleIds: string[],
): GroupCheckState {
  const scope = selection.scopes[projectId];
  if (scope) {
    return scope.exceptIds.length ? "some" : "scope";
  }
  const selected = visibleIds.filter((id) => id in selection.ids).length;
  if (!selected) {
    return "none";
  }
  return selected === visibleIds.length ? "visible" : "some";
}

export function clearGroup(selection: ThreadSelection, projectId: string): ThreadSelection {
  const ids = Object.fromEntries(Object.entries(selection.ids).filter(([, owner]) => owner !== projectId));
  const scopes = { ...selection.scopes };
  delete scopes[projectId];
  return { ids, scopes };
}

/** The group header checkbox: none/some → select the shown chats; all shown or a scope → clear. */
export function toggleGroupVisible(
  selection: ThreadSelection,
  projectId: string,
  visibleIds: string[],
): ThreadSelection {
  const state = groupCheckState(selection, projectId, visibleIds);
  const cleared = clearGroup(selection, projectId);
  if (state === "visible" || state === "scope") {
    return cleared;
  }
  return selectThreads(
    cleared,
    visibleIds.map((id) => ({ id, projectId })),
  );
}

export function selectGroupScope(
  selection: ThreadSelection,
  scope: Omit<ThreadScope, "exceptIds">,
): ThreadSelection {
  const cleared = clearGroup(selection, scope.projectId);
  return { ...cleared, scopes: { ...cleared.scopes, [scope.projectId]: { ...scope, exceptIds: [] } } };
}

/** A scope belongs to one query: changing the search drops the scopes, explicit ids stay. */
export function dropScopes(selection: ThreadSelection): ThreadSelection {
  return Object.keys(selection.scopes).length ? { ...selection, scopes: {} } : selection;
}

export type ThreadBulkRequestBody = {
  action: ThreadBulkAction;
  ids: string[];
  scopes: Array<{ project_id: string; query: string; as_of: string; except_ids: string[] }>;
  dry_run?: boolean;
};

export function bulkRequestBody(
  selection: ThreadSelection,
  action: ThreadBulkAction,
  dryRun = false,
): ThreadBulkRequestBody {
  return {
    action,
    ids: Object.keys(selection.ids),
    scopes: Object.values(selection.scopes).map((scope) => ({
      project_id: scope.projectId,
      query: scope.query,
      as_of: scope.asOf,
      except_ids: scope.exceptIds,
    })),
    ...(dryRun ? { dry_run: true } : {}),
  };
}
