import assert from "node:assert/strict";
import { test } from "node:test";

import { participantLabels } from "../../src/chat/messageBubbleState.ts";

const prompt = (fields) => ({ id: "m1", role: "user", content: "write a note", createdAt: null, toolEvents: [], ...fields });

test("a user message carries the name of the person who wrote it, not of the viewer", () => {
  const { participantTitle } = participantLabels(prompt({ authorName: "Previous Owner" }), true, "New Owner");
  assert.equal(participantTitle, "Previous Owner");
});

test("a message the server has not stored yet is the viewer's own", () => {
  const { participantTitle } = participantLabels(prompt({ authorName: null }), true, "New Owner");
  assert.equal(participantTitle, "New Owner");
});

test("a stored message whose author has no resolvable name never shows the viewer's name", () => {
  const { participantTitle } = participantLabels(prompt({ authorId: "u-other", authorName: null }), true, "New Owner");
  assert.equal(participantTitle, "Team member");
});

test("the platform's workflow continuation stays the platform's", () => {
  const { participantTitle } = participantLabels(prompt({ origin: "workflow", authorName: "Previous Owner" }), true,
    "New Owner");
  assert.equal(participantTitle, "Octryx");
});
