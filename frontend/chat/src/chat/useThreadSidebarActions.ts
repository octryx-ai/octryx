import type { ThreadSummary } from "../chatThreadTypes";
import { buildChatSearch, threadHref } from "./appHelpers";

type ReadJsonFn = <T>(input: string, init?: RequestInit) => Promise<T>;

type LoadStateFn = (
  search?: string,
  options?: { preserveTrace?: boolean; silent?: boolean },
) => Promise<void>;

export function useThreadSidebarActions({
  selectedSessionId,
  selectedProjectId,
  selectedRuntimeTargetId,
  canDeleteThreads,
  readJson,
  loadState,
  prepareNewThread,
  beginComposerThreadSwitch,
  focusComposer,
}: {
  selectedSessionId: string | null;
  selectedProjectId: string;
  selectedRuntimeTargetId: string;
  canDeleteThreads: boolean;
  readJson: ReadJsonFn;
  loadState: LoadStateFn;
  prepareNewThread?: () => void;
  beginComposerThreadSwitch?: (targetSessionId: string) => void;
  focusComposer?: () => void;
}) {
  const handleThreadSelect = async (thread: ThreadSummary) => {
    beginComposerThreadSwitch?.(thread.id);
    const search = threadHref(thread);
    window.history.pushState({}, "", `/chat${search}`);
    await loadState(search, { preserveTrace: true });
  };

  const handleNewThread = async () => {
    const search = buildChatSearch({
      newThread: true,
      projectId: selectedProjectId,
      runtimeTargetId: selectedRuntimeTargetId,
    });
    if (!selectedSessionId && window.location.search === search) {
      // Already on this unsent draft: "New chat" returns to it, it never opens a second one.
      focusComposer?.();
      return;
    }
    prepareNewThread?.();
    beginComposerThreadSwitch?.("");
    window.history.pushState({}, "", `/chat${search}`);
    await loadState(search);
    focusComposer?.();
  };

  const handlePinThread = async (thread: ThreadSummary) => {
    await readJson<{ ok: boolean }>(
      `/chat/api/sessions/${thread.id}/${thread.isPinned ? "unpin" : "pin"}`,
      {
        method: "POST",
        body: JSON.stringify({}),
      },
    );
    await loadState(window.location.search, {
      preserveTrace: true,
      silent: true,
    });
  };

  /** Inline rename from the row: saves the title in place and never opens the chat. */
  const handleRenameThread = async (thread: ThreadSummary, title: string) => {
    const clean = title.trim();
    if (!clean || clean === thread.title) {
      return;
    }
    await readJson<unknown>(`/chat/api/sessions/${thread.id}/rename`, {
      method: "POST",
      body: JSON.stringify({ title: clean }),
    });
    await loadState(window.location.search, {
      preserveTrace: true,
      silent: true,
    });
  };

  const handleExportThread = (thread: ThreadSummary) => {
    window.open(
      `/chat/api/sessions/${thread.id}/export.pdf`,
      "_blank",
      "noopener,noreferrer",
    );
  };

  const handleExportAnalysisThread = (thread: ThreadSummary) => {
    window.open(
      `/chat/api/sessions/${thread.id}/export.analysis.json`,
      "_blank",
      "noopener,noreferrer",
    );
  };

  const handleDeleteThread = async (thread: ThreadSummary) => {
    if (!canDeleteThreads) {
      return;
    }
    await readJson<{ ok: boolean }>(`/chat/api/sessions/${thread.id}`, {
      method: "DELETE",
    });
    const deletingSelected = selectedSessionId === thread.id;
    if (deletingSelected) {
      const search = buildChatSearch({
        newThread: true,
        projectId: selectedProjectId,
        runtimeTargetId: selectedRuntimeTargetId,
      });
      window.history.replaceState({}, "", `/chat${search}`);
      await loadState(search);
      return;
    }
    await loadState(window.location.search, {
      preserveTrace: true,
      silent: true,
    });
  };

  return {
    handleThreadSelect,
    handleNewThread,
    handlePinThread,
    handleRenameThread,
    handleExportThread,
    handleExportAnalysisThread,
    handleDeleteThread,
  };
}
