// The chat sidebar's thread list: loaded pages, server search across all chats and bulk selection.

import type { ThreadGroup } from "../chatThreadTypes";
import { buildChatSearch } from "./appHelpers";
import { readJson } from "./chatApiClient";
import { useThreadBulk } from "./useThreadBulk";
import { useThreadGroupPagination } from "./useThreadGroupPagination";
import { useThreadSearch } from "./useThreadSearch";

type BulkArgs = Parameters<typeof useThreadBulk>[0];

export function useSidebarThreads({
  setChatState,
  threadSearchQuery,
  filteredThreadGroups,
  loadState,
  canDeleteThreads,
  selectedSessionId,
  newChatProjectId,
  selectedRuntimeTargetId,
}: {
  setChatState: Parameters<typeof useThreadGroupPagination>[0]["setChatState"];
  threadSearchQuery: string;
  filteredThreadGroups: ThreadGroup[];
  loadState: BulkArgs["loadState"];
  canDeleteThreads: boolean;
  selectedSessionId: string | null;
  newChatProjectId: string;
  selectedRuntimeTargetId: string;
}) {
  const { forgetThreads, handleLoadThreadGroupPage } = useThreadGroupPagination({
    setChatState,
  });
  const threadSearch = useThreadSearch({ readJson, query: threadSearchQuery });
  const searchingThreads = threadSearchQuery.trim().length > 0;
  // A search shows the server's matches across all chats; the loaded rows filter only until it answers.
  const sidebarThreadGroups =
    searchingThreads && threadSearch.groups ? threadSearch.groups : filteredThreadGroups;
  const threadBulk = useThreadBulk({
    readJson,
    loadState,
    canDeleteThreads,
    threadSearchQuery,
    selectedSessionId,
    newThreadSearch: buildChatSearch({
      newThread: true,
      projectId: newChatProjectId,
      runtimeTargetId: selectedRuntimeTargetId,
    }),
    forgetThreads: (ids) => {
      forgetThreads(ids);
      threadSearch.forget(ids);
    },
  });
  return {
    sidebarThreadGroups,
    threadBulk,
    handleLoadThreadGroupPage: searchingThreads ? threadSearch.loadMore : handleLoadThreadGroupPage,
  };
}
