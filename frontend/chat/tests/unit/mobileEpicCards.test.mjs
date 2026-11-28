// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/mobileEpicCards.test.mjs
//
// The phone's Epic summary card: which Epics of the task list get a card, and the line and mini bar from the
// platform's progress answer. Names and numbers are invented.
import assert from "node:assert/strict";
import { test } from "node:test";

import { epicsShown, MAX_EPIC_CARDS, readEpicCard } from "../../src/mobile/mobileEpicCards.ts";
import { readCases } from "../../src/mobile/mobileTasksModel.ts";

const page = { items: [
  { id: "e1", source_key: "OCX-1", title: "Checkout", issue_type: "Epic" },
  { id: "s1", source_key: "OCX-2", title: "A story", issue_type: "Story" },
  { id: "e2", source_key: "OCX-3", title: "Billing", issue_type: "epic" },
  { id: "e3", source_key: "OCX-4", title: "Search", issue_type: " EPIC " },
  { id: "e4", source_key: "OCX-5", title: "Reports", issue_type: "Epic" },
] };

test("only Epics (any case) get a card, at most a few", () => {
  const cases = readCases(page, null, { keepOrder: true });
  assert.equal(cases[0].issueType, "Epic");
  assert.deepEqual(epicsShown(cases).map((item) => item.id), ["e1", "e2", "e3"]);
  assert.equal(MAX_EPIC_CARDS, 3);
  assert.deepEqual(epicsShown(cases, 1).map((item) => item.id), ["e1"]);
  assert.deepEqual(epicsShown([]), []);
});

test("the card line reads done/total, in progress, in review, open, and who is needed", () => {
  const [epic] = readCases(page, null, { keepOrder: true });
  const card = readEpicCard(epic, {
    epic: { id: "e1", key: "OCX-1", title: "Checkout v2" },
    summary: { done: 6, in_review: 2, in_progress: 3, open: 3, total: 14, needs_you: 0 },
    stories: [],
  });
  assert.equal(card.line, "Checkout v2 · 6/14 done · 3 in progress · 2 in review · 3 open");
  assert.deepEqual(card.segments.map((s) => [s.lane, s.count]), [["done", 6], ["in_review", 2], ["in_progress", 3], ["open", 3]]);
  assert.equal(card.item.id, "e1");
  const needed = readEpicCard(epic, { summary: { done: 0, in_review: 0, in_progress: 1, open: 0, total: 1, needs_you: 1 } });
  assert.equal(needed.line, "Checkout · 0/1 done · 1 in progress · 0 in review · 0 open · 1 needs you");
});
