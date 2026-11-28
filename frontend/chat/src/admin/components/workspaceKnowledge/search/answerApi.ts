import { knowledgeBase, request } from "../workspaceKnowledgeRequest";

// Only evidence keys are sent: the server rereads them with the reader's own access.

export const ANSWER_PASSAGES = 10;

export type AnswerState = "ok" | "no_answer" | "needs_configuration" | "denied" | "unavailable";
export type AnswerSentence = { text: string; cites: string[] };
export type KnowledgeAnswer = { state: AnswerState; sentences: AnswerSentence[]; cited_keys: string[] };

const STATES: AnswerState[] = ["ok", "no_answer", "needs_configuration", "denied", "unavailable"];
export const UNAVAILABLE_ANSWER: KnowledgeAnswer = { state: "unavailable", sentences: [], cited_keys: [] };

export function answerEvidenceKeys(hits: { evidence_key: string }[]): string[] {
  return [...new Set(hits.map((hit) => hit.evidence_key).filter(Boolean))].slice(0, ANSWER_PASSAGES);
}

// Inline [n] markers number the prompt, not the page; the citations are in cites.
const INLINE_MARKERS = /\s*(?:\[\s*\d+(?:\s*[,;]\s*\d+)*\s*\])+/g;

export function plainSentence(text: string): string {
  return text.replace(INLINE_MARKERS, "").replace(/\s+([.,;:!?])/g, "$1").trim();
}

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string" && entry !== "") : [];

export function readKnowledgeAnswer(payload: unknown): KnowledgeAnswer {
  if (!payload || typeof payload !== "object") return UNAVAILABLE_ANSWER;
  const raw = payload as { state?: unknown; sentences?: unknown };
  const state = STATES.find((entry) => entry === raw.state);
  if (!state) return UNAVAILABLE_ANSWER;
  if (state !== "ok") return { state, sentences: [], cited_keys: [] };
  const sentences = (Array.isArray(raw.sentences) ? raw.sentences : [])
    .map((entry) => ({ text: typeof entry?.text === "string" ? plainSentence(entry.text) : "", cites: strings(entry?.cites) }))
    .filter((sentence) => sentence.text && sentence.cites.length);
  if (!sentences.length) return { state: "no_answer", sentences: [], cited_keys: [] };
  return { state, sentences, cited_keys: [...new Set(sentences.flatMap((sentence) => sentence.cites))] };
}

export function answerStateText(state: AnswerState): string {
  switch (state) {
    case "ok": return "";
    case "no_answer": return "No answer from these passages.";
    case "needs_configuration": return "No short answer: no model is set up for this Workspace yet.";
    case "denied": return "No short answer: this Workspace's data may not be sent to a model.";
    default: return "No short answer right now. The passages below are the result.";
  }
}

export type AnswerMarker = { key: string; number: number | null };

export function answerMarkers(cites: string[], numberOf: ReadonlyMap<string, number>): AnswerMarker[] {
  return cites.map((key) => ({ key, number: numberOf.get(key) ?? null }));
}

export async function requestKnowledgeAnswer(
  workspaceId: string, queryText: string, evidenceKeys: string[],
): Promise<KnowledgeAnswer> {
  const payload = await request<unknown>(`${knowledgeBase(workspaceId)}/answer`, {
    method: "POST",
    body: JSON.stringify({ query_text: queryText, evidence_keys: evidenceKeys }),
  });
  return readKnowledgeAnswer(payload);
}
