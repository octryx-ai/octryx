// The phone's openers from lists: a chat (or its taken-over Mac session), a local session and an attention entry.
import { useCallback } from "react";
import type { AttentionItem } from "../chat/companion/companionTypes";
import { takeOverTarget, type DeviceThread, type LocalSession } from "./mobileDeviceChats";
import { type LiveSession } from "./mobileLiveSessions";
import type { Detail } from "./mobileDetailPages";

export function useMobileOpeners({
  threads,
  liveSessions,
  localSessions,
  openPage,
}: {
  threads: DeviceThread[];
  liveSessions: LiveSession[];
  localSessions: LocalSession[];
  openPage: (page: Detail) => void;
}) {
  const openThread = useCallback(
    (thread: DeviceThread) => {
      const target = takeOverTarget(localSessions, thread.id);
      openPage({
        kind: "chat",
        id: thread.id,
        title: thread.title,
        projectId: thread.projectId,
        // A taken-over session (or a fork of one) runs on the Mac, never on the Server.
        onServer: !target && thread.executionTarget?.kind !== "device",
        ...(target ?? {}),
      });
    },
    [localSessions, openPage],
  );

  const openLocal = useCallback(
    (local: LocalSession) =>
      openPage(
        local.threadId
          ? { kind: "chat", id: local.threadId, title: local.title, projectId: "", localSessionId: local.id }
          : { kind: "local", session: local },
      ),
    [openPage],
  );

  const openItem = useCallback(
    (item: AttentionItem) => {
      const thread = threads.find((candidate) => candidate.id === item.sessionId);
      // A session's answer opens its live conversation (its newest message is the item).
      const live = item.kind === "live" ? liveSessions.find((entry) => entry.last?.id === item.id) : undefined;
      if (live) openPage({ kind: "live", session: live });
      // A run's decision, approval or result opens the run itself, where it is answered.
      else if (item.runId) openPage({ kind: "run", runId: item.runId, title: item.workItem ? `${item.workItem.key} · ${item.workItem.title}` : item.title });
      else if (thread) openThread(thread);
      else if (item.link?.href.startsWith("/")) window.location.href = item.link.href;
    },
    [threads, liveSessions, openPage, openThread],
  );

  return { openThread, openLocal, openItem };
}
