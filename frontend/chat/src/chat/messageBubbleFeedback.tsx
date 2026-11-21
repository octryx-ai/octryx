import { useEffect, useState } from "react";

import type { ChatMessage } from "../chatThreadTypes";
import { ThumbDownIcon, ThumbUpIcon } from "./messageBubbleIcons";
import {
  ASPECT_LABELS,
  FEEDBACK_ASPECTS,
  MAX_FEEDBACK_TEXT_CHARS,
  buildFeedbackPayload,
  draftFromFeedback,
  feedbackSummary,
  toggleAspect,
} from "./messageFeedbackModel";
import type { FeedbackDraft, FeedbackRating, MessageFeedbackPayload } from "./messageFeedbackModel";

const VERDICT_TITLE = { liked: "liked", disliked: "not liked" } as const;

// Thumbs up/down under an answer. Choosing one opens a compact form: what was good, what was not
// good, and optional aspect chips (one click: liked, two: not liked, three: unmarked). The feedback
// is saved to the Workspace's memory; submitting again replaces it.
export function MessageFeedbackBar({ message, disabled, onSubmitFeedback, iconOnly = false }: {
  message: ChatMessage;
  disabled: boolean;
  onSubmitFeedback: (messageId: string, payload: MessageFeedbackPayload) => Promise<void>;
  iconOnly?: boolean;
}) {
  const feedback = message.feedback ?? null;
  const { open, setOpen, submitting, setSubmitting, draft, setDraft, notice, setNotice, error, setError } = useFeedbackState(message);
  const panelId = `message-feedback-${message.id}`;

  if (message.role !== "assistant" || message.id === "pending-assistant-message") {
    return null;
  }

  const choose = (rating: FeedbackRating) => {
    setDraft((current) => ({ ...current, rating }));
    setNotice(null);
    setError(null);
    setOpen(true);
  };
  const cancel = () => {
    setDraft(draftFromFeedback(feedback));
    setError(null);
    setOpen(false);
  };
  const payload = buildFeedbackPayload(draft);
  const submit = async () => {
    if (!payload) return;
    setSubmitting(true);
    setError(null);
    try {
      await onSubmitFeedback(message.id, payload);
      setOpen(false);
      setNotice("Thanks, your feedback is saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSubmitting(false);
    }
  };
  const shownRating = open ? draft.rating : feedback?.rating ?? null;
  const busy = disabled || submitting;

  return (
    <div className="message-feedback">
      <FeedbackChoices shownRating={shownRating} iconOnly={iconOnly} busy={busy} open={open} panelId={panelId} choose={choose} />
      {open ? (
        <FeedbackPanel panelId={panelId} draft={draft} setDraft={setDraft} busy={busy} submitting={submitting} error={error}
          payload={payload} hasFeedback={Boolean(feedback)} onSubmit={() => void submit()} onCancel={cancel} />
      ) : feedback && notice ? (
        <div className="message-feedback__saved" role="status">
          <span>{notice} {feedbackSummary(feedback)}</span>
          <button type="button" className="message-feedback__cancel" disabled={busy} onClick={() => choose(feedback.rating)}>
            Edit
          </button>
        </div>
      ) : null}
    </div>
  );
}

function FeedbackChoices({ shownRating, iconOnly, busy, open, panelId, choose }: {
  shownRating: FeedbackRating | null; iconOnly: boolean; busy: boolean; open: boolean; panelId: string;
  choose: (rating: FeedbackRating) => void;
}) {
  return (
    <div className="message-feedback__choices" role="group" aria-label="Message feedback">
      <button
        type="button"
        className={`message-feedback__button message-feedback__button--positive ${iconOnly ? "message-feedback__button--icon-only" : ""} ${shownRating === "good" ? "message-feedback__button--active" : ""}`}
        disabled={busy}
        title="This answer was good"
        aria-label="This answer was good"
        aria-pressed={shownRating === "good"}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => choose("good")}
      >
        <ThumbUpIcon />
        <span>Good</span>
      </button>
      <button
        type="button"
        className={`message-feedback__button message-feedback__button--negative ${iconOnly ? "message-feedback__button--icon-only" : ""} ${shownRating === "bad" ? "message-feedback__button--active" : ""}`}
        disabled={busy}
        title="This answer was not good"
        aria-label="This answer was not good"
        aria-pressed={shownRating === "bad"}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => choose("bad")}
      >
        <ThumbDownIcon />
        <span>Not good</span>
      </button>
    </div>
  );
}

// The open form: what was good, what was not, the aspect chips, submit and cancel.
function FeedbackPanel({ panelId, draft, setDraft, busy, submitting, error, payload, hasFeedback, onSubmit, onCancel }: {
  panelId: string; draft: FeedbackDraft; setDraft: (draft: FeedbackDraft) => void; busy: boolean; submitting: boolean;
  error: string | null; payload: MessageFeedbackPayload | null; hasFeedback: boolean; onSubmit: () => void; onCancel: () => void;
}) {
  return (
    <div className="message-feedback__panel" id={panelId}>
      <div className="message-feedback__panel-copy">
        <div className="message-feedback__panel-title">
          {draft.rating === "good" ? "The answer was good" : "The answer was not good"}
        </div>
        <div className="message-feedback__panel-body">
          Both fields are optional. Your feedback is kept in this Workspace's memory.
        </div>
      </div>
      <label className="message-feedback__field">
        <span>What was good?</span>
        <textarea
          rows={2}
          value={draft.liked}
          maxLength={MAX_FEEDBACK_TEXT_CHARS}
          disabled={busy}
          onChange={(event) => setDraft({ ...draft, liked: event.target.value })}
        />
      </label>
      <label className="message-feedback__field">
        <span>What was not good?</span>
        <textarea
          rows={2}
          value={draft.disliked}
          maxLength={MAX_FEEDBACK_TEXT_CHARS}
          disabled={busy}
          onChange={(event) => setDraft({ ...draft, disliked: event.target.value })}
        />
      </label>
      <AspectChips draft={draft} setDraft={setDraft} busy={busy} />
      {error ? <div className="message-feedback__error" role="alert">{error}</div> : null}
      <div className="message-feedback__actions">
        <button type="button" className="message-feedback__submit" disabled={busy || !payload} onClick={onSubmit}>
          {hasFeedback ? "Update feedback" : "Submit feedback"}
        </button>
        <button type="button" className="message-feedback__cancel" disabled={submitting} onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

// The form's state; the draft follows the message's saved feedback.
function useFeedbackState(message: ChatMessage) {
  const feedback = message.feedback ?? null;
  const [open, setOpen] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [draft, setDraft] = useState<FeedbackDraft>(() => draftFromFeedback(feedback));
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDraft(draftFromFeedback(message.feedback));
  }, [message.id, message.feedback]);
  return { open, setOpen, submitting, setSubmitting, draft, setDraft, notice, setNotice, error, setError };
}

// One chip per aspect; a click moves it from not marked to liked to not liked.
function AspectChips({ draft, setDraft, busy }: { draft: FeedbackDraft; setDraft: (draft: FeedbackDraft) => void; busy: boolean }) {
  return (
    <div className="message-feedback__chips" role="group" aria-label="Aspects">
      {FEEDBACK_ASPECTS.map((aspect) => {
        const verdict = draft.aspects[aspect];
        return (
          <button
            key={aspect}
            type="button"
            className={`message-feedback__chip ${verdict ? `message-feedback__chip--${verdict}` : ""}`}
            disabled={busy}
            aria-pressed={verdict !== undefined}
            title={verdict ? `${ASPECT_LABELS[aspect]}: ${VERDICT_TITLE[verdict]}` : `${ASPECT_LABELS[aspect]}: not marked`}
            onClick={() => setDraft({ ...draft, aspects: toggleAspect(draft.aspects, aspect) })}
          >
            {verdict === "liked" ? "+ " : verdict === "disliked" ? "− " : ""}
            {ASPECT_LABELS[aspect]}
          </button>
        );
      })}
    </div>
  );
}
