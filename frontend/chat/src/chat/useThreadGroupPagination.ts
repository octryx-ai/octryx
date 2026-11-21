import type { Dispatch, SetStateAction } from "react";

import type { ChatState } from "../types";
import type { ThreadGroup } from "../chatThreadTypes";
import { readJson } from "./chatApiClient";
import { appendThreadGroupPage, removeThreadsFromGroups } from "./threadGroupPages";

type ThreadGroupPage = ThreadGroup & {
  projectId: string;
  totalThreadCount: number;
  loadedThreadCount: number;
  nextOffset: number;
  hasMore: boolean;
  pageSize: number;
};

export function useThreadGroupPagination({
  setChatState,
}: {
  setChatState: Dispatch<SetStateAction<ChatState | null>>;
}) {
  const handleLoadThreadGroupPage = async (group: ThreadGroup) => {
    const params = new URLSearchParams();
    params.set("project_id", group.projectId ?? "");
    params.set("offset", String(group.nextOffset ?? group.sessions.length));
    params.set("limit", String(group.pageSize ?? 20));
    const page = await readJson<ThreadGroupPage>(`/chat/api/thread-groups?${params.toString()}`);
    setChatState((current) => {
      if (!current) {
        return current;
      }
      return {
        ...current,
        activeThreadGroups: appendThreadGroupPage(current.activeThreadGroups, page),
      };
    });
  };

  /** Archived or deleted rows leave the list before the reload answers. */
  const forgetThreads = (ids: string[]) => {
    setChatState((current) =>
      current
        ? { ...current, activeThreadGroups: removeThreadsFromGroups(current.activeThreadGroups, ids) }
        : current,
    );
  };

  return {
    forgetThreads,
    handleLoadThreadGroupPage,
  };
}
