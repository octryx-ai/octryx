// "Ask in chat" opens a new chat in the same Workspace with the question and the sources the search
// found written into the composer; nothing is sent until the person presses Send.
import assert from "node:assert/strict";
import { test } from "node:test";

import { takeComposerPrefill } from "../../src/chat/composerPrefill.ts";
import { askInChatDraft, askInChatHref, MAX_DRAFT_SOURCES, prepareAskInChat } from "../../src/admin/components/workspaceKnowledge/search/askInChat.ts";

const hit = (key, extra = {}) => ({
  evidence_key: key, text: "x", citation: "", source_title: `Doc ${key}`, source_url: null, products: [], version: null,
  kind: null, pages: null, section: null, found_by: [], relevance: null, similarity: null, ...extra,
});

test("the draft is the question and the top sources with place and link", () => {
  const draft = askInChatDraft("  How does onboarding work?  ", [
    hit("a", { origin: { kind: "confluence", url: "https://wiki/a" }, section: "Doc a > Steps" }),
    hit("b", { pages: [3, 3] }),
  ]);
  assert.equal(draft, "How does onboarding work?\n\nUse these sources from the Knowledge search:\n"
    + "1. Doc a (§ Steps) — https://wiki/a\n2. Doc b (p. 3)");
  assert.equal(askInChatDraft("Only the question", []), "Only the question");
  const many = askInChatDraft("q", Array.from({ length: 9 }, (_, index) => hit(String(index))));
  assert.equal(many.split("\n").filter((line) => /^\d+\. /.test(line)).length, MAX_DRAFT_SOURCES);
});

test("the draft is handed to a new chat of the Workspace, once; the address opens that chat", () => {
  const saved = new Map();
  const store = { getItem: (key) => saved.get(key) ?? null, setItem: (key, value) => saved.set(key, value), removeItem: (key) => saved.delete(key) };
  const href = prepareAskInChat("ws-1", "q", [hit("a")], store);
  assert.equal(href, "/chat?new=true&project_id=ws-1");
  assert.equal(href, askInChatHref("ws-1"));
  assert.equal(takeComposerPrefill(store, "ws-2"), "", "another Workspace's chat does not take it");
  assert.equal(takeComposerPrefill(store, "ws-1"), "q\n\nUse these sources from the Knowledge search:\n1. Doc a");
  assert.equal(takeComposerPrefill(store, "ws-1"), "", "taken once");
  prepareAskInChat("ws-1", "old", [], store);
  assert.equal(takeComposerPrefill(store, "ws-1", Date.now() + 3 * 60_000), "", "a stale hand-off is dropped");
  const blocked = { getItem: () => null, setItem: () => { throw new Error("blocked"); }, removeItem: () => {} };
  assert.equal(prepareAskInChat("ws-1", "q", [], blocked), href, "blocked storage still opens the chat");
});
