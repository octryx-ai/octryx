import { writeComposerPrefill } from "../../../../chat/composerPrefill";
import type { EvidenceHit } from "../workspaceKnowledgeTypes";
import { hitPlace, hitSourceUrl } from "./searchFacets";

// "Ask in chat": a new chat in the same Workspace with the question and the sources the search found
// written into the composer. Nothing is sent; the person reads the draft and presses Send.

export const MAX_DRAFT_SOURCES = 5;

/** The composer draft: the question, then the top sources with their place and link. */
export function askInChatDraft(query: string, hits: EvidenceHit[]): string {
  const sources = hits.slice(0, MAX_DRAFT_SOURCES).map((hit, index) => {
    const place = hitPlace(hit);
    const url = hitSourceUrl(hit);
    return `${index + 1}. ${hit.source_title}${place ? ` (${place})` : ""}${url ? ` — ${url}` : ""}`;
  });
  const question = query.trim();
  return sources.length
    ? `${question}\n\nUse these sources from the Knowledge search:\n${sources.join("\n")}`
    : question;
}

/** The address of a new chat in the Workspace. */
export function askInChatHref(workspaceId: string): string {
  return `/chat?${new URLSearchParams({ new: "true", project_id: workspaceId }).toString()}`;
}

type DraftStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;

/**
 * Hands the draft to the new chat's composer (chat/composerPrefill.ts: keyed by Workspace, so the composer finds it
 * whatever runtime and mode it boots with) and returns the address to open. A blocked storage still opens the chat.
 */
export function prepareAskInChat(workspaceId: string, query: string, hits: EvidenceHit[], store: DraftStore | null): string {
  writeComposerPrefill(store, workspaceId, askInChatDraft(query, hits));
  return askInChatHref(workspaceId);
}
