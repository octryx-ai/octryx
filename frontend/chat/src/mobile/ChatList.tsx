// The person's chats as rows (Home shows the newest, Chats all of them): Server chats and chats on a Mac, the
// octryx-claude sessions in a terminal, the Claude Code sessions running on the Macs and the ones that can be taken over.
// A dot only where something is going on (running blue, failed red); an idle chat has a quiet ring.

import { runLine, runLineText, threadRunLineText } from "./engineSeatModel";
import { activityDot, activityLabel, homeRows, type TerminalSession } from "./mobileTerminalSessions";
import { billingLabel, isFork, type DeviceThread, type LocalSession } from "./mobileDeviceChats";
import { shortTime } from "./mobileUsageModel";
import { type LiveSession } from "./mobileLiveSessions";

const STATE_DOT: Record<string, string> = {
  running: "m-dot-blue",
  awaiting_subagents: "m-dot-blue",
  failed: "m-dot-red",
};

export function ChatRows({
  threads,
  sessions,
  limit,
  onOpenThread,
  onOpenSession,
}: {
  threads: DeviceThread[];
  sessions: TerminalSession[];
  limit?: number;
  onOpenThread: (thread: DeviceThread) => void;
  onOpenSession: (session: TerminalSession) => void;
}) {
  const rows = homeRows(sessions, threads).slice(0, limit ?? Infinity);
  if (!rows.length) return null;
  return (
    <ul className="m-rows m-group">
      {rows.map((row) =>
        row.kind === "session" ? (
          <li key={`s-${row.session.id}`}>
            <button type="button" className="m-row" onClick={() => onOpenSession(row.session)}>
              <i className={`m-dot ${activityDot(row.session.activity)}`} aria-hidden="true" />
              <span className="m-row-text">
                <b>{row.session.title}</b>
                <span>
                  {[activityLabel(row.session.activity), row.session.device || "Terminal", runLineText(runLine(row.session))]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </span>
              <span className="m-when">{shortTime(row.session.activityAt || row.session.lastSeenAt)}</span>
            </button>
          </li>
        ) : (
          <li key={`t-${row.thread.id}`}>
            <button type="button" className="m-row" onClick={() => onOpenThread(row.thread)}>
              <i
                className={`m-dot ${STATE_DOT[row.thread.runStatus || row.thread.status] ?? "m-dot-idle"}`}
                aria-hidden="true"
              />
              <span className="m-row-text">
                <b>
                  {row.thread.title || "Untitled chat"}
                  {isFork(row.thread.title || "") && <span className="m-tag">Fork</span>}
                </b>
                <span>
                  {[
                    threadRunLineText(row.thread.executionTarget) || "Server",
                    row.thread.projectName,
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                </span>
              </span>
              <span className="m-when">{shortTime(row.thread.lastActivityAt || row.thread.startedAt)}</span>
            </button>
          </li>
        ),
      )}
    </ul>
  );
}

export function LiveRows({ sessions, onOpen }: { sessions: LiveSession[]; onOpen: (session: LiveSession) => void }) {
  if (!sessions.length) return null;
  return (
    <ul className="m-rows m-group">
      {sessions.map((session) => (
        <li key={`v-${session.deviceId}-${session.peer}`}>
          <button type="button" className="m-row" onClick={() => onOpen(session)}>
            <i
              className={`m-dot ${!session.fresh ? "m-dot-idle" : session.status === "busy" ? "m-dot-blue" : "m-dot-green"}`}
              aria-hidden="true"
            />
            <span className="m-row-text">
              <b>{session.name}</b>
              <span>
                {session.last
                  ? `${session.last.direction === "in" ? "" : "You: "}${session.last.text}`
                  : runLineText(runLine(session), session.folderName, session.deviceName)}
              </span>
            </span>
            <span className="m-when">{session.fresh ? session.status || "" : "Offline"}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}

export function LocalRows({ sessions, onOpen }: { sessions: LocalSession[]; onOpen: (session: LocalSession) => void }) {
  if (!sessions.length) return null;
  return (
    <ul className="m-rows m-group">
      {sessions.map((session) => (
        <li key={`l-${session.id}`}>
          <button type="button" className="m-row" onClick={() => onOpen(session)}>
            <i className={`m-dot ${session.online ? "m-dot-green" : "m-dot-idle"}`} aria-hidden="true" />
            <span className="m-row-text">
              <b>{session.title}</b>
              <span>
                {[session.folderName, session.deviceName, billingLabel(`local:${session.profile}`)].filter(Boolean).join(" · ")}
              </span>
            </span>
            <span className="m-when">{shortTime(session.updatedAt)}</span>
          </button>
        </li>
      ))}
    </ul>
  );
}
