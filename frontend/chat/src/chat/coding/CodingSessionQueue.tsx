import type { CodingSessionSummary } from "./codingTypes";
import { codingSessionsNote, sessionCardFacts } from "./codingQueuePresenter";

// The session list: one card per session with its title, state word and next step; its metrics are its tooltip and
// sit in the session's Details.
export function CodingSessionList({
  sessions,
  selectedId,
  onSelect,
}: {
  sessions: CodingSessionSummary[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}) {
  return (
    <div className="coding-session-list" aria-label="Coding Sessions">
      {sessions.map((session) => (
        <button
          key={session.id}
          type="button"
          className={`coding-session-card ${selectedId === session.id ? "is-active" : ""}`}
          title={sessionCardFacts(session)}
          onClick={() => onSelect(session.id)}
        >
          <span className="coding-session-card__main">
            <span>
              <span className="work-card__key">{session.sourceKey}</span>
              <span className="coding-session-card__title">{session.title}</span>
            </span>
            <span className={`work-badge work-badge--${session.tone}`}>{session.statusLabel}</span>
          </span>
          {/* Title, state and the next step only; the counters are in the session's Details. */}
          <span className="coding-session-card__meta">
            <span>{session.nextAction}</span>
          </span>
        </button>
      ))}
    </div>
  );
}

// What the filter tabs' counts do not say, in one line, or nothing.
export function CodingSummary({ sessions }: { sessions: CodingSessionSummary[] }) {
  const note = codingSessionsNote(sessions);
  return note ? <p className="coding-sessions-note" role="note">{note}</p> : null;
}
