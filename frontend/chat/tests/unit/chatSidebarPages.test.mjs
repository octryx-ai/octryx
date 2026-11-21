// Chat sidebar sections and paging.
import assert from "node:assert/strict";
import { test } from "node:test";

import { mergeBootstrapState } from "../../src/chat/mergeChatState.ts";
import {
  appendThreadGroupPage,
  mergeThreadGroupPages,
  removeThreadsFromGroups,
} from "../../src/chat/threadGroupPages.ts";
import { sectionThreads } from "../../src/chat/threadTime.ts";

const rows = (prefix, count, start = 0) =>
  Array.from({ length: count }, (_, index) => ({ id: `${prefix}${start + index + 1}` }));

const group = (projectId, sessions, total, extra = {}) => ({
  projectId,
  projectName: "Atlas Research",
  sessions,
  totalThreadCount: total,
  loadedThreadCount: sessions.length,
  nextOffset: sessions.length,
  hasMore: sessions.length < total,
  pageSize: 20,
  ...extra,
});

test("a refresh after 'Show 20 more' keeps the 40 loaded rows", () => {
  const loaded = appendThreadGroupPage([group("atlas", rows("t", 20), 67)], group("atlas", rows("t", 20, 20), 67));
  assert.equal(loaded[0].sessions.length, 40);

  const refreshed = mergeThreadGroupPages(loaded, [group("atlas", rows("t", 20), 67)]);

  assert.equal(refreshed[0].sessions.length, 40);
  assert.equal(refreshed[0].nextOffset, 40);
  assert.equal(refreshed[0].hasMore, true);
  assert.deepEqual(refreshed[0].sessions.slice(19, 21).map((row) => row.id), ["t20", "t21"]);
});

test("an empty list clears; an acknowledgement without a list keeps it", () => {
  const before = [group("atlas", rows("t", 1), 1)];

  assert.deepEqual(mergeThreadGroupPages(before, []), []);
  assert.equal(mergeThreadGroupPages(before, null), before);
  const state = mergeBootstrapState({
    previousState: { activeThreadGroups: before },
    nextState: { activeThreadGroups: null, archivedThreads: null, archivedThreadCount: null },
  });
  assert.equal(state.activeThreadGroups, before);
});

test("archiving the last thread of a group removes the group at once", () => {
  const groups = [group("atlas", rows("t", 1), 1), group("harbor", rows("h", 2), 2)];

  const after = removeThreadsFromGroups(groups, ["t1", "h1"]);

  assert.deepEqual(after.map((candidate) => candidate.projectId), ["harbor"]);
  assert.equal(after[0].totalThreadCount, 1);
});

test("groups are keyed by Workspace id, not by name", () => {
  const merged = mergeThreadGroupPages(
    [group("a", rows("a", 40), 50), group("b", rows("b", 1), 1)],
    [group("a", rows("a", 20), 50), group("b", rows("b", 1), 1)],
  );

  assert.deepEqual(merged.map((candidate) => candidate.sessions.length), [40, 1]);
});

test("sections: Pinned first, then Today / Yesterday / Previous 7 days / Earlier; empty ones are left out", () => {
  const now = new Date(2026, 9, 8, 15, 40);
  const ago = (days) => new Date(now.getTime() - days * 86400000).toISOString();
  const threads = [
    { id: "pin", isPinned: true, lastActivityAt: ago(40) },
    { id: "today", lastActivityAt: ago(0) },
    { id: "old", lastActivityAt: ago(30) },
    { id: "week", lastActivityAt: ago(3) },
  ];

  const sections = sectionThreads(threads, now);

  assert.deepEqual(
    sections.map((section) => [section.label, section.threads.map((thread) => thread.id)]),
    [
      ["Pinned", ["pin"]],
      ["Today", ["today"]],
      ["Previous 7 days", ["week"]],
      ["Earlier", ["old"]],
    ],
  );
});
