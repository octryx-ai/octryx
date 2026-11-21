// Chats: every chat of the chosen Workspace (Server and Mac chats, terminal sessions), searchable, a new chat one tap
// away, and below what runs on the person's Macs outside Octryx (live sessions, sessions that can be taken over).

import { useState, type ReactNode } from "react";
import { ChatRows, LiveRows, LocalRows } from "./ChatList";
import { Icon } from "./icons";
import type { DeviceThread, LocalSession } from "./mobileDeviceChats";
import type { LiveSession } from "./mobileLiveSessions";
import type { TerminalSession } from "./mobileTerminalSessions";
import { TabHeader } from "./PageHeader";

type Props = {
  switcher: ReactNode;
  threads: DeviceThread[];
  sessions: TerminalSession[];
  liveSessions: LiveSession[];
  localSessions: LocalSession[];
  loading: boolean;
  onOpenThread: (thread: DeviceThread) => void;
  onOpenSession: (session: TerminalSession) => void;
  onOpenLive: (session: LiveSession) => void;
  onOpenLocal: (session: LocalSession) => void;
  onNewChat: () => void;
};

const matches = (text: string | null | undefined, query: string) => String(text ?? "").toLowerCase().includes(query);

export function ChatsPage({
  switcher,
  threads,
  sessions,
  liveSessions,
  localSessions,
  loading,
  onOpenThread,
  onOpenSession,
  onOpenLive,
  onOpenLocal,
  onNewChat,
}: Props) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const shownThreads = q ? threads.filter((thread) => matches(thread.title, q) || matches(thread.projectName, q)) : threads;
  const shownSessions = q ? sessions.filter((session) => matches(session.title, q)) : sessions;
  const total = threads.length + sessions.length;
  const shown = shownThreads.length + shownSessions.length;
  return (
    <>
      <TabHeader
        title="Chats"
        switcher={switcher}
        actions={
          <button type="button" className="m-pill-button" onClick={onNewChat}>
            <Icon name="plus" size={18} />
            New chat
          </button>
        }
      />
      <main className="m-body">
        {total > 0 && (
          <label className="m-search">
            <Icon name="search" size={18} />
            <input
              type="search"
              aria-label="Search chats"
              placeholder="Search chats"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
            />
          </label>
        )}
        <section aria-label="Chats">
          {loading && total === 0 && <p className="m-empty">Loading…</p>}
          {!loading && total === 0 && (
            <div className="m-empty">
              <p>No chats in this Workspace yet. Start one on the Server or on one of your Macs.</p>
              <button type="button" className="m-secondary" onClick={onNewChat}>
                Start a chat
              </button>
            </div>
          )}
          {total > 0 && shown === 0 && <p className="m-empty">No chat matches “{query.trim()}”.</p>}
          <ChatRows threads={shownThreads} sessions={shownSessions} onOpenThread={onOpenThread} onOpenSession={onOpenSession} />
        </section>
        {liveSessions.length > 0 && (
          <section aria-labelledby="m-live">
            <h2 id="m-live" className="m-section">
              Running on your Macs
            </h2>
            <LiveRows sessions={liveSessions} onOpen={onOpenLive} />
          </section>
        )}
        {localSessions.length > 0 && (
          <section aria-labelledby="m-local">
            <h2 id="m-local" className="m-section">
              Claude Code on your Macs
            </h2>
            <LocalRows sessions={localSessions} onOpen={onOpenLocal} />
          </section>
        )}
      </main>
    </>
  );
}
