// A Claude Code session outside octryx on one of the person's Macs: its folder, its last
// answer, and a composer that takes it over. The message runs on that Mac in that session's profile and folder,
// resuming exactly this session; the chat continues in the person's private Workspace.

import { useState } from "react";
import { takeOver } from "./mobileApi";
import { type MobileError } from "./mobileSession";
import { billingLabel, type LocalSession } from "./mobileDeviceChats";
import { shortTime } from "./mobileUsageModel";
import { Icon } from "./icons";

const REFUSALS: Record<string, string> = {
  device_offline: "Your Mac is offline. Open it and check the VPN.",
  device_paused: "Octryx is paused on your Mac.",
  device_job_busy: "This session is still working on your last message.",
  local_session_not_found: "This session is no longer on your Mac.",
  takeover_not_allowed_on_device:
    "Take over is off for this profile on your Mac.",
  device_runs_platform_disabled:
    "Runs on Macs are switched off on the platform right now.",
};

export function LocalSessionPage({
  session,
  onBack,
  onStarted,
}: {
  session: LocalSession;
  onBack: () => void;
  onStarted: (threadId: string) => void;
}) {
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const where = [
    session.deviceName,
    session.folderName,
    billingLabel(`local:${session.profile}`),
  ]
    .filter(Boolean)
    .join(" · ");

  const submit = async () => {
    const message = draft.trim();
    if (!message || busy) return;
    setBusy(true);
    setError("");
    try {
      const started = await takeOver(session.id, message);
      onStarted(started.thread_id);
    } catch (reason) {
      const code = (reason as MobileError).code ?? "";
      setError(
        REFUSALS[code] ??
          (code ? code.replace(/_/g, " ") : "The message was not sent."),
      );
      setBusy(false);
    }
  };

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
          <span className="m-muted">{where}</span>
        </div>
      </header>
      <main className="m-body">
        <section className="m-panel">
          <span className="m-eyebrow">
            {session.online ? "Your Mac is online" : "Your Mac is offline"}
          </span>
          <p className="m-muted">
            {session.folder} · last change{" "}
            {shortTime(session.updatedAt) || "recently"}
          </p>
        </section>
        {session.lastText ? (
          <section className="m-panel">
            <span className="m-eyebrow">Last answer</span>
            <p className="m-ai">{session.lastText}</p>
          </section>
        ) : null}
        {session.takeoverAllowed ? (
          <p className="m-muted">
            Take over: your message continues this session on your Mac, in this
            folder and with this profile. Every change asks you here first, and
            your Mac shows a notification. The open terminal does not show these
            turns; avoid writing there at the same time.
          </p>
        ) : (
          <p className="m-muted">
            Take over is off for this profile. To allow it, run on your Mac:{" "}
            <code>octryx-claude profiles connect … --allow-takeover</code>
          </p>
        )}
        {error && (
          <p className="m-error" role="alert">
            {error}
          </p>
        )}
      </main>
      <footer className="m-compose">
        <textarea
          aria-label="Message"
          placeholder="Continue this session…"
          value={draft}
          rows={1}
          onChange={(event) => setDraft(event.target.value)}
        />
        <button
          type="button"
          className="m-send"
          aria-label="Send"
          disabled={
            !draft.trim() || busy || !session.online || !session.takeoverAllowed
          }
          onClick={() => void submit()}
        >
          <Icon name="send" size={20} />
        </button>
      </footer>
    </div>
  );
}
