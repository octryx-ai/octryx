import { knowledgeBase, request } from "../workspaceKnowledgeRequest";

// The short cited answer above the hits (POST …/knowledge/answer). The page sends the evidence keys of
// its top hits, never their text: the server reads them again with the reader's own access and keeps only sentences
// that cite them. Every outcome is a fixed state; anything the page does not understand counts as unavailable.

export const ANSWER_PASSAGES = 10;

export type AnswerState = "ok" | "no_answer" | "needs_configuration" | "denied" | "unavailable";
export type AnswerSentence = { text: string; cites: string[] };
export type KnowledgeAnswer = { state: AnswerState; sentences: AnswerSentence[]; cited_keys: string[] };

const STATES: AnswerState[] = ["ok", "no_answer", "needs_configuration", "denied", "unavailable"];
export const UNAVAILABLE_ANSWER: KnowledgeAnswer = { state: "unavailable", sentences: [], cited_keys: [] };

/** The keys the answer may rest on: the top hits in ranked order, without repeats. */
export function answerEvidenceKeys(hits: { evidence_key: string }[]): string[] {
  return [...new Set(hits.map((hit) => hit.evidence_key).filter(Boolean))].slice(0, ANSWER_PASSAGES);
}

// Passage numbers a model wrote into the text ("… is 16 [1][2].") number the prompt, not the page: removed, the
// citations are `cites` (the server removes them too).
const INLINE_MARKERS = /\s*(?:\[\s*\d+(?:\s*[,;]\s*\d+)*\s*\])+/g;

export function plainSentence(text: string): string {
  return text.replace(INLINE_MARKERS, "").replace(/\s+([.,;:!?])/g, "$1").trim();
}

const strings = (value: unknown): string[] =>
  Array.isArray(value) ? value.filter((entry): entry is string => typeof entry === "string" && entry !== "") : [];

/** The server's answer, checked: an "ok" without one cited sentence is "no_answer"; unknown shapes are unavailable. */
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

/** The one plain sentence shown instead of an answer; "" for an answer with sentences. */
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

/** Each cited key with its number in the list on the page; null when the filters hide that hit. */
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
