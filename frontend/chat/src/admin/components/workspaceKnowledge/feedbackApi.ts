import { knowledgeBase, request } from "./workspaceKnowledgeRequest";

// The Workspace's answer feedback (admin or owner only): what people liked and disliked about answers.
export const FEEDBACK_ASPECTS = ["correctness", "sources", "completeness", "clarity", "tool_use", "speed"] as const;
export type FeedbackAspect = (typeof FEEDBACK_ASPECTS)[number];
export type FeedbackRating = "good" | "bad";

export type AnswerFeedbackItem = {
  id: string;
  memory_item_id: string | null;
  memory_state: string | null;
  rating: FeedbackRating;
  // Erased once the feedback memory is forgotten.
  liked: string | null;
  disliked: string | null;
  aspects: Partial<Record<FeedbackAspect, "liked" | "disliked">>;
  workflow_key: string | null;
  workflow_id: string | null;
  execution_profile_id: string | null;
  provider: string | null;
  model: string | null;
  session_id: string;
  message_id: string;
  session_link: string | null;
  recorded_by: string | null;
  created_at: string | null;
  updated_at: string | null;
};

export type AnswerFeedbackList = { workspace_id: string; items: AnswerFeedbackItem[] };

export type AnswerFeedbackSummary = {
  workspace_id: string;
  total: number;
  good: number;
  bad: number;
  by_workflow: Array<{ workflow_key: string | null; good: number; bad: number }>;
  by_aspect: Array<{ aspect: FeedbackAspect; liked: number; disliked: number }>;
};

export type FeedbackFilters = { rating?: FeedbackRating | ""; aspect?: FeedbackAspect | ""; workflowKey?: string };

// Only set filters go on the query string; the backend refuses unknown values instead of guessing.
export function feedbackQuery(filters: FeedbackFilters): string {
  const params = new URLSearchParams();
  if (filters.rating) params.set("rating", filters.rating);
  if (filters.aspect) params.set("aspect", filters.aspect);
  const workflow = filters.workflowKey?.trim();
  if (workflow) params.set("workflow_key", workflow);
  const query = params.toString();
  return query ? `?${query}` : "";
}

function feedbackBase(workspaceId: string): string {
  return `${knowledgeBase(workspaceId)}/feedback`;
}

export const feedbackApi = {
  list: (workspaceId: string, filters: FeedbackFilters) =>
    request<AnswerFeedbackList>(`${feedbackBase(workspaceId)}${feedbackQuery(filters)}`),
  summary: (workspaceId: string, filters: FeedbackFilters) =>
    request<AnswerFeedbackSummary>(`${feedbackBase(workspaceId)}/summary${feedbackQuery(filters)}`),
};
