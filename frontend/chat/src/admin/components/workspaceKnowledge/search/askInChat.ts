import { writeComposerPrefill } from "../../../../chat/composerPrefill";
import type { EvidenceHit } from "../workspaceKnowledgeTypes";
import { hitPlace, hitSourceUrl } from "./searchFacets";

export const MAX_DRAFT_SOURCES = 5;

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

export function askInChatHref(workspaceId: string): string {
  return `/chat?${new URLSearchParams({ new: "true", project_id: workspaceId }).toString()}`;
}

type DraftStore = Pick<Storage, "getItem" | "setItem" | "removeItem">;

// composerPrefill keys the draft by Workspace, so the composer finds it whatever runtime and mode it boots with.
export function prepareAskInChat(workspaceId: string, query: string, hits: EvidenceHit[], store: DraftStore | null): string {
  writeComposerPrefill(store, workspaceId, askInChatDraft(query, hits));
  return askInChatHref(workspaceId);
}
