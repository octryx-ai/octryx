// One open octryx-claude session from the terminal or VS Code: what it is doing, since when, and its last
// answer. Read-only: this page offers no way to answer or continue the session.

import { activityLabel, type TerminalSession } from "./mobileTerminalSessions";
import { shortTime } from "./mobileUsageModel";
import { runLine } from "./engineSeatModel";
import { RunLineSubline } from "./RunLine";
import { Icon } from "./icons";

export function TerminalPage({
  session,
  onBack,
}: {
  session: TerminalSession;
  onBack: () => void;
}) {
  return (
    <div className="m-screen">
      <header className="m-top">
        <button
          type="button"
          className="m-icon-button"
          aria-label="Back"
          onClick={onBack}
        >
          <Icon name="back" />
        </button>
        <div className="m-top-text">
          <strong>{session.title}</strong>
          <RunLineSubline line={runLine(session)} more={[session.device || "Terminal", session.workspace]} />
        </div>
      </header>
      <main className="m-body">
        <section className="m-panel">
          <span className="m-eyebrow">{activityLabel(session.activity)}</span>
          <p className="m-muted">
            Open for {shortTime(session.startedAt) || "a moment"}
            {session.branch ? ` · ${session.branch}` : ""}
          </p>
        </section>
        {session.lastText ? (
          <section className="m-panel">
            <span className="m-eyebrow">Last answer</span>
            <p className="m-ai">{session.lastText}</p>
          </section>
        ) : null}
      </main>
    </div>
  );
}
