// Chat sidebar bulk actions: one request per action, the
// list reloads once, and the server's result (affected and skipped ids) is what the user sees.
import {
  bulkRequestBody,
  type ThreadBulkAction,
  type ThreadSelection,
} from "./threadSelection";

type ReadJsonFn = <T>(input: string, init?: RequestInit) => Promise<T>;

type LoadStateFn = (
  search?: string,
  options?: { preserveTrace?: boolean; silent?: boolean },
) => Promise<void>;

export type ThreadBulkSkipReason = "running" | "not_found" | "failed";

export type ThreadBulkResult = {
  affectedIds: string[];
  skipped: Array<{ id: string; reason: ThreadBulkSkipReason }>;
  running: number;
  subChats: number;
  byProject: Array<{ projectId: string; projectName: string; count: number }>;
};

type ThreadBulkPayload = {
  affected_ids?: string[];
  skipped?: Array<{ id: string; reason: ThreadBulkSkipReason }>;
  counts?: { running?: number; sub_chats?: number };
  by_project?: Array<{ project_id: string; project_name: string; count: number }>;
};

export const THREAD_BULK_URL = "/chat/api/threads/bulk";

function toResult(payload: ThreadBulkPayload): ThreadBulkResult {
  return {
    affectedIds: payload.affected_ids ?? [],
    skipped: payload.skipped ?? [],
    running: payload.counts?.running ?? 0,
    subChats: payload.counts?.sub_chats ?? 0,
    byProject: (payload.by_project ?? []).map((row) => ({
      projectId: row.project_id,
      projectName: row.project_name,
      count: row.count,
    })),
  };
}

async function postBulk(readJson: ReadJsonFn, body: unknown): Promise<ThreadBulkResult> {
  return toResult(
    await readJson<ThreadBulkPayload>(THREAD_BULK_URL, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  );
}

/** What the server would do: the confirm dialog shows these numbers, nothing changes. */
export function previewThreadBulkAction(
  readJson: ReadJsonFn,
  selection: ThreadSelection,
  action: ThreadBulkAction,
): Promise<ThreadBulkResult> {
  return postBulk(readJson, bulkRequestBody(selection, action, true));
}

/**
 * Runs the action in one request and reloads the list exactly once, also when the request
 * fails. When the open chat is among the affected ids, the reload navigates to `newThreadSearch`.
 */
export async function performThreadBulkAction({
  readJson,
  loadState,
  selection,
  action,
  selectedSessionId,
  newThreadSearch,
  forgetThreads,
}: {
  readJson: ReadJsonFn;
  loadState: LoadStateFn;
  selection: ThreadSelection;
  action: ThreadBulkAction;
  selectedSessionId: string | null;
  newThreadSearch: string;
  /** Drops the affected rows from the list at once (loaded pages included). */
  forgetThreads?: (ids: string[]) => void;
}): Promise<ThreadBulkResult> {
  let result: ThreadBulkResult | null = null;
  try {
    result = await postBulk(readJson, bulkRequestBody(selection, action));
    if (action !== "restore") {
      forgetThreads?.(result.affectedIds);
    }
    return result;
  } finally {
    const leftOpenChat =
      action !== "restore" && Boolean(selectedSessionId && result?.affectedIds.includes(selectedSessionId));
    if (leftOpenChat) {
      window.history.replaceState({}, "", `/chat${newThreadSearch}`);
      await loadState(newThreadSearch);
    } else {
      await loadState(window.location.search, { preserveTrace: true, silent: true });
    }
  }
}

export async function restoreThreads({
  readJson,
  loadState,
  ids,
}: {
  readJson: ReadJsonFn;
  loadState: LoadStateFn;
  ids: string[];
}): Promise<ThreadBulkResult> {
  try {
    return await postBulk(readJson, { action: "restore", ids, scopes: [] });
  } finally {
    await loadState(window.location.search, { preserveTrace: true, silent: true });
  }
}

/** The server count of a Workspace (optionally for a search) and the server time it holds for. */
export async function fetchThreadGroupCount(
  readJson: ReadJsonFn,
  projectId: string,
  query: string,
): Promise<{ count: number; asOf: string }> {
  const params = new URLSearchParams({ project_id: projectId, q: query });
  const payload = await readJson<{ count?: number; asOf?: string }>(
    `/chat/api/thread-groups/count?${params.toString()}`,
  );
  return { count: payload.count ?? 0, asOf: payload.asOf ?? "" };
}

function plural(count: number, one: string, many: string) {
  return `${count} ${count === 1 ? one : many}`;
}

const SKIP_REASON_LABEL: Record<ThreadBulkSkipReason, string> = {
  running: "running",
  not_found: "no longer available",
  failed: "failed",
};

/** "69 chats archived · 2 skipped: running" — partial results are always reported. */
export function bulkResultMessage(action: ThreadBulkAction, result: ThreadBulkResult): string {
  const verb = action === "delete" ? "deleted" : action === "restore" ? "restored" : "archived";
  const done = `${plural(result.affectedIds.length, "chat", "chats")} ${verb}`;
  if (!result.skipped.length) {
    return `${done}.`;
  }
  const reasons = Array.from(new Set(result.skipped.map((item) => SKIP_REASON_LABEL[item.reason] ?? item.reason)));
  return `${done} · ${result.skipped.length} skipped: ${reasons.join(", ")}.`;
}
