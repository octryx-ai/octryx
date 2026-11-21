// Chat sidebar selection model.
import assert from "node:assert/strict";
import { test } from "node:test";

import { threadGroupBanner } from "../../src/chat/threadGroupBulk.ts";
import {
  bulkRequestBody,
  dropScopes,
  EMPTY_THREAD_SELECTION,
  groupCheckState,
  isThreadSelected,
  rangeThreadRefs,
  selectedThreadCount,
  selectGroupScope,
  selectThreads,
  toggleGroupVisible,
  toggleThread,
} from "../../src/chat/threadSelection.ts";

const SHOWN = Array.from({ length: 20 }, (_, index) => `a${index + 1}`);
const ATLAS = {
  projectId: "atlas",
  projectName: "Atlas Research",
  sessions: SHOWN.map((id) => ({ id })),
  totalThreadCount: 67,
};

test("the group checkbox selects the shown chats, then offers all of the Workspace", () => {
  const selection = toggleGroupVisible(EMPTY_THREAD_SELECTION, "atlas", SHOWN);

  assert.equal(groupCheckState(selection, "atlas", SHOWN), "visible");
  assert.equal(selectedThreadCount(selection), 20);
  assert.deepEqual(threadGroupBanner({ selection, group: ATLAS, query: "", searchCount: undefined }), {
    kind: "offer",
    shown: 20,
    total: 67,
    label: "in Atlas Research",
  });
  // A second click clears the group.
  assert.equal(selectedThreadCount(toggleGroupVisible(selection, "atlas", SHOWN)), 0);
});

test("select all becomes a scope; unticking a row makes an exclusion (66 of 67)", () => {
  const scoped = selectGroupScope(toggleGroupVisible(EMPTY_THREAD_SELECTION, "atlas", SHOWN), {
    projectId: "atlas",
    query: "",
    asOf: "2026-10-08T13:40:00Z",
    count: 67,
  });
  assert.deepEqual(scoped.ids, {});
  assert.equal(groupCheckState(scoped, "atlas", SHOWN), "scope");

  const unticked = toggleThread(scoped, { id: "a3", projectId: "atlas" });

  assert.equal(selectedThreadCount(unticked), 66);
  assert.equal(isThreadSelected(unticked, { id: "a3", projectId: "atlas" }), false);
  assert.equal(groupCheckState(unticked, "atlas", SHOWN), "some");
  assert.deepEqual(threadGroupBanner({ selection: unticked, group: ATLAS, query: "", searchCount: undefined }), {
    kind: "scope",
    selected: 66,
    total: 67,
    notLoaded: 47,
    label: "in Atlas Research",
  });
  assert.deepEqual(bulkRequestBody(unticked, "archive"), {
    action: "archive",
    ids: [],
    scopes: [{ project_id: "atlas", query: "", as_of: "2026-10-08T13:40:00Z", except_ids: ["a3"] }],
  });
});

test("a scope and explicit ids of another Workspace add up", () => {
  const selection = toggleThread(
    selectGroupScope(EMPTY_THREAD_SELECTION, { projectId: "atlas", query: "", asOf: "x", count: 67 }),
    { id: "h2", projectId: "harbor" },
  );

  assert.equal(selectedThreadCount(selection), 68);
  assert.deepEqual(bulkRequestBody(selection, "delete", true).ids, ["h2"]);
  assert.equal(bulkRequestBody(selection, "delete", true).dry_run, true);
});

test("shift-click selects the range between the anchor and the row in visible order", () => {
  const ordered = ["a1", "a2", "a3", "a4", "h1"].map((id) => ({ id, projectId: id.startsWith("h") ? "harbor" : "atlas" }));

  const range = rangeThreadRefs(ordered, "h1", "a2");
  const selection = selectThreads(EMPTY_THREAD_SELECTION, range);

  assert.deepEqual(Object.keys(selection.ids).sort(), ["a2", "a3", "a4", "h1"]);
  assert.deepEqual(rangeThreadRefs(ordered, null, "a3").map((ref) => ref.id), ["a3"]);
});

test("a new search drops scopes but keeps explicit ids; search offers use the server count", () => {
  const selection = toggleThread(
    selectGroupScope(EMPTY_THREAD_SELECTION, { projectId: "atlas", query: "budget", asOf: "x", count: 3 }),
    { id: "h1", projectId: "harbor" },
  );

  assert.deepEqual(dropScopes(selection), { ids: { h1: "harbor" }, scopes: {} });

  const filtered = { ...ATLAS, sessions: [{ id: "a1" }, { id: "a2" }] };
  const shown = toggleGroupVisible(EMPTY_THREAD_SELECTION, "atlas", ["a1", "a2"]);
  assert.equal(threadGroupBanner({ selection: shown, group: filtered, query: "budget", searchCount: undefined }), null);
  assert.deepEqual(threadGroupBanner({ selection: shown, group: filtered, query: "budget", searchCount: 3 }), {
    kind: "offer",
    shown: 2,
    total: 3,
    label: "matching “budget”",
  });
});
