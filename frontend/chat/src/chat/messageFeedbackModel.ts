// Answer feedback: whether an answer was good or bad, what was good, what was not good, and which
// aspects were liked or disliked. The closed values mirror the backend contract
// (backend/app/models/project/knowledge_answer_feedback.py); the backend refuses anything else.
import type { MessageFeedback } from "../chatThreadTypes";

export const FEEDBACK_ASPECTS = [
  "correctness",
  "sources",
  "completeness",
  "clarity",
  "tool_use",
  "speed",
] as const;

export type FeedbackAspect = (typeof FEEDBACK_ASPECTS)[number];
export type FeedbackRating = "good" | "bad";
export type AspectVerdict = "liked" | "disliked";
export type FeedbackAspects = Partial<Record<FeedbackAspect, AspectVerdict>>;

// Each text is bounded by the backend; the form enforces the same bound.
export const MAX_FEEDBACK_TEXT_CHARS = 800;

export const ASPECT_LABELS: Record<FeedbackAspect, string> = {
  correctness: "Correctness",
  sources: "Sources",
  completeness: "Completeness",
  clarity: "Clarity",
  tool_use: "Tool use",
  speed: "Speed",
};

export type MessageFeedbackPayload = {
  rating: FeedbackRating;
  liked: string | null;
  disliked: string | null;
  aspects: FeedbackAspects;
};

export type FeedbackDraft = {
  rating: FeedbackRating | null;
  liked: string;
  disliked: string;
  aspects: FeedbackAspects;
};

function isAspect(value: string): value is FeedbackAspect {
  return (FEEDBACK_ASPECTS as readonly string[]).includes(value);
}

function isVerdict(value: unknown): value is AspectVerdict {
  return value === "liked" || value === "disliked";
}

// The editable draft of a stored feedback; unknown aspects or verdicts are dropped, never guessed.
export function draftFromFeedback(feedback?: MessageFeedback | null): FeedbackDraft {
  const aspects: FeedbackAspects = {};
  for (const [aspect, verdict] of Object.entries(feedback?.aspects ?? {})) {
    if (isAspect(aspect) && isVerdict(verdict)) aspects[aspect] = verdict;
  }
  const rating = feedback?.rating === "good" || feedback?.rating === "bad" ? feedback.rating : null;
  return { rating, liked: feedback?.liked ?? "", disliked: feedback?.disliked ?? "", aspects };
}

// One click on an aspect chip: not marked -> liked -> disliked -> not marked.
export function toggleAspect(aspects: FeedbackAspects, aspect: FeedbackAspect): FeedbackAspects {
  const next = { ...aspects };
  const current = next[aspect];
  if (current === undefined) next[aspect] = "liked";
  else if (current === "liked") next[aspect] = "disliked";
  else delete next[aspect];
  return next;
}

export function feedbackTextTooLong(text: string): boolean {
  return text.trim().length > MAX_FEEDBACK_TEXT_CHARS;
}

// The request body, or null while the draft cannot be sent (no rating, or a text over the bound).
export function buildFeedbackPayload(draft: FeedbackDraft): MessageFeedbackPayload | null {
  if (!draft.rating || feedbackTextTooLong(draft.liked) || feedbackTextTooLong(draft.disliked)) return null;
  const aspects: FeedbackAspects = {};
  for (const aspect of FEEDBACK_ASPECTS) {
    const verdict = draft.aspects[aspect];
    if (verdict) aspects[aspect] = verdict;
  }
  return {
    rating: draft.rating,
    liked: draft.liked.trim() || null,
    disliked: draft.disliked.trim() || null,
    aspects,
  };
}

export function feedbackSummary(feedback: MessageFeedback): string {
  return feedback.rating === "good" ? "You rated this answer good." : "You rated this answer bad.";
}
