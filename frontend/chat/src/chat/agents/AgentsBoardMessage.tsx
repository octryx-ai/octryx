import { useState } from "react";

import { formatRelativeTime } from "../../admin/utils/formatters";
import { requestActionNeededRefresh } from "./actionNeededRefresh";
import { postDecision, redactMessage } from "./agentBoardApi";
import { KIND_LABEL, KIND_TONE, addresseeLabel, authorLabel, decidedLabel, mayDecide, offeredToLabel } from "./agentBoardLabels";
import { boardActionErrorText, workItemHref } from "./agentBoardModel";
import type { BoardMessage, BoardViewer } from "./agentBoardTypes";
import { AgentsCopyId } from "./AgentsCopyId";

// One board envelope. The body is data from an agent or a person: it is rendered as a plain text
// node (React escapes it), never as HTML or markdown. Decision controls appear only for an undecided request the
// viewer may answer; redaction only when the answer's `viewer.can_admin` is true (D-F1). The server authorizes both,
// and a refusal is shown in the card.
export function AgentsBoardMessage({ message, projectId, viewer, isPlatformAdmin = false, focused = false, onOpenThread, onChanged }: {
  message: BoardMessage;
  projectId: string;
  viewer: BoardViewer | null;
  isPlatformAdmin?: boolean;
  focused?: boolean;
  onOpenThread?: (id: string) => void;
  onChanged: () => void;
}) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmRedact, setConfirmRedact] = useState(false);
  const [outcome, setOutcome] = useState<{ ok: boolean; text: string } | null>(null);
  const addressee = addresseeLabel(message);
  const isAdmin = viewer?.canAdmin === true;
  const canDecide = mayDecide(message, viewer, isPlatformAdmin) && !outcome?.ok;
  // judge-board F1: redacting a request blanks its decision too (no option, no text, no redacted_at of its own).
  // A real decision always has an option or a text, so an empty one is that tombstone.
  const blankDecision = message.kind === "decision" && !message.redacted && !message.body && !message.options.length;

  const act = async (run: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setOutcome(null);
    try {
      await run();
      setOutcome({ ok: true, text: done });
      setConfirmRedact(false);
      onChanged();
      requestActionNeededRefresh();
    } catch (error) {
      setOutcome({ ok: false, text: boardActionErrorText(error) });
    } finally {
      setBusy(false);
    }
  };
  const decide = (option: string | null) => {
    const text = note.trim();
    void act(() => postDecision(message.id, { ...(option ? { option } : {}), ...(text ? { text } : {}) }), "Your decision was posted.");
  };

  return (
    <article className={`admin-panel__card agents-board__message${focused ? " is-focused" : ""}`} data-testid="agents-board-message"
      data-message-id={message.id} aria-label={`${KIND_LABEL[message.kind]} from ${authorLabel(message)}`}>
      <header className="agents-board__meta">
        <span className={`work-badge work-badge--${KIND_TONE[message.kind]}`}>{KIND_LABEL[message.kind]}</span>
        <strong className={message.authorType === "human" ? "agents-board__human" : undefined} data-testid="agents-board-author">
          {authorLabel(message)}
        </strong>
        {addressee ? <span data-testid="agents-board-to">to {addressee}</span> : null}
        {offeredToLabel(message) ? <span data-testid="agents-board-offered">offered to {offeredToLabel(message)}</span> : null}
        {message.to?.agentHash && !message.to.user ? <AgentsCopyId value={message.to.agentHash} label="agent key" /> : null}
        {message.workItem ? (
          <a href={workItemHref(projectId, message.workItem.id)} data-testid="agents-board-work-item"
            title={message.workItem.title || undefined}>{message.workItem.key || message.workItem.title || "work item"}</a>
        ) : null}
        <span className="agents-board__time">{formatRelativeTime(message.createdAt) || "time not reported"}</span>
      </header>
      {message.redacted || blankDecision ? (
        <p className="agents-board__body agents-board__redacted" data-testid="agents-board-body">
          {blankDecision ? "Removed with its redacted request." : "Redacted by a Workspace admin."}
        </p>
      ) : (
        <p className="agents-board__body" data-testid="agents-board-body">{message.body}</p>
      )}
      {message.decided ? (
        <p className="agents-area__hint" data-testid="agents-board-decided">{decidedLabel(message.decided)}</p>
      ) : null}
      {!message.redacted && !message.decided && message.options.length > 0 && !canDecide ? (
        <p className="agents-area__hint" data-testid="agents-board-options">
          {message.kind === "decision" ? "Choice" : "Options"}: {message.options.join(" · ")}
        </p>
      ) : null}
      {canDecide ? (
        <div className="agents-board__decision" data-testid="agents-board-decision">
          {message.options.map((option) => (
            <button key={option} type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => decide(option)}>{option}</button>
          ))}
          <input type="text" className="admin-panel__input agents-board__note" maxLength={2000} value={note} disabled={busy}
            placeholder={message.options.length ? "Optional note with your choice" : "Your decision"}
            aria-label="Decision note" onChange={(event) => setNote(event.target.value)} />
          {!message.options.length ? (
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--primary" disabled={busy || !note.trim()}
              onClick={() => decide(null)}>Send decision</button>
          ) : null}
        </div>
      ) : null}
      <footer className="agents-board__meta agents-board__footer">
        <span data-testid="agents-board-acks">
          {message.acks.length ? `Read by ${message.acks.map((ack) => ack.recipient).join(", ")}` : "Not acknowledged yet"}
        </span>
        {onOpenThread ? (
          <button type="button" className="admin-panel__action-btn" onClick={() => onOpenThread(message.replyTo || message.id)}>Thread</button>
        ) : null}
        {isAdmin && !message.redacted && !confirmRedact ? (
          <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" onClick={() => setConfirmRedact(true)}>Redact</button>
        ) : null}
        {confirmRedact ? (
          <span className="agents-board__confirm" role="group" aria-label="Confirm redaction">
            Blank this message for everyone? It stays as a tombstone.
            <button type="button" className="admin-panel__action-btn" disabled={busy} onClick={() => setConfirmRedact(false)}>Cancel</button>
            <button type="button" className="admin-panel__action-btn admin-panel__action-btn--danger" disabled={busy}
              onClick={() => void act(() => redactMessage(message.id), "The message was redacted.")}>Redact now</button>
          </span>
        ) : null}
      </footer>
      {outcome ? (
        <p className={outcome.ok ? "agents-area__hint" : "work-area__error"} role={outcome.ok ? "status" : "alert"}
          data-testid="agents-board-outcome">{outcome.text}</p>
      ) : null}
    </article>
  );
}
