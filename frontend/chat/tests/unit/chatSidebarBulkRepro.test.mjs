// Chat sidebar bulk actions: select-all is a server-side scope that carries the
// search, and a bulk action is one request that reports skipped threads and reloads once.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  bulkResultMessage,
  fetchThreadGroupCount,
  performThreadBulkAction,
  THREAD_BULK_URL,
} from "../../src/chat/threadBulkActions.ts";
import {
  bulkRequestBody,
  EMPTY_THREAD_SELECTION,
  selectedThreadCount,
  selectGroupScope,
  toggleThread,
} from "../../src/chat/threadSelection.ts";

const ALL_IDS = Array.from({ length: 67 }, (_, index) => `t${index + 1}`);

function jsonResponse(payload, status = 200) {
  return {
    ok: status < 400,
    status,
    statusText: status < 400 ? "OK" : "Server Error",
    json: async () => payload,
  };
}

function installBrowserStubs(fetchImpl) {
  const calls = [];
  globalThis.window = {
    location: { search: "" },
    history: { pushState() {}, replaceState() {} },
  };
  globalThis.fetch = async (input, init) => {
    calls.push({ url: String(input), method: init?.method ?? "GET", body: init?.body ? JSON.parse(init.body) : null });
    return fetchImpl(String(input), calls.length);
  };
  return calls;
}

async function readJson(input, init) {
  const response = await globalThis.fetch(input, init);
  if (!response.ok) throw new Error("Request failed");
  return response.json();
}

function selectionOf(ids) {
  return ids.reduce((selection, id) => toggleThread(selection, { id, projectId: "p1" }), EMPTY_THREAD_SELECTION);
}

test("select all in a group while searching selects only the matching threads", async () => {
  const calls = installBrowserStubs(() => jsonResponse({ projectId: "p1", count: 2, asOf: "2026-10-08T13:40:00Z" }));

  const { count, asOf } = await fetchThreadGroupCount(readJson, "p1", "budget");
  const selection = selectGroupScope(EMPTY_THREAD_SELECTION, { projectId: "p1", query: "budget", asOf, count });

  assert.match(calls[0].url, /\/chat\/api\/thread-groups\/count\?project_id=p1&q=budget$/);
  assert.equal(selectedThreadCount(selection), 2);
  assert.deepEqual(bulkRequestBody(selection, "archive").scopes, [
    { project_id: "p1", query: "budget", as_of: "2026-10-08T13:40:00Z", except_ids: [] },
  ]);
});

test("bulk archive attempts every selected thread and reloads once even when one fails", async () => {
  const calls = installBrowserStubs(() =>
    jsonResponse({
      affected_ids: ["t1", "t2", "t4", "t5"],
      skipped: [{ id: "t3", reason: "failed" }],
      counts: { affected: 4, skipped: 1 },
    }),
  );
  let reloads = 0;
  const loadState = async () => {
    reloads += 1;
  };
  const args = {
    readJson,
    loadState,
    selection: selectionOf(["t1", "t2", "t3", "t4", "t5"]),
    action: "archive",
    selectedSessionId: null,
    newThreadSearch: "?new=1",
  };

  const result = await performThreadBulkAction(args);

  assert.deepEqual(calls[0].body.ids, ["t1", "t2", "t3", "t4", "t5"]);
  assert.deepEqual(result.skipped, [{ id: "t3", reason: "failed" }]);
  assert.equal(bulkResultMessage("archive", result), "4 chats archived · 1 skipped: failed.");
  assert.equal(reloads, 1);

  // A failing request still reloads the list once, and the caller gets the error.
  installBrowserStubs(() => jsonResponse({ detail: "boom" }, 500));
  await assert.rejects(performThreadBulkAction(args));
  assert.equal(reloads, 2);
});

test("bulk archive of a whole group is one request, not one full chat-state build per thread", async () => {
  const calls = installBrowserStubs(() => jsonResponse({ affected_ids: ALL_IDS, skipped: [] }));

  await performThreadBulkAction({
    readJson,
    loadState: async () => {},
    selection: selectionOf(ALL_IDS),
    action: "archive",
    selectedSessionId: null,
    newThreadSearch: "?new=1",
  });

  const posts = calls.filter((call) => call.method === "POST");
  assert.equal(posts.length, 1);
  assert.equal(posts[0].url, THREAD_BULK_URL);
});

test("archiving the open chat navigates to a new chat instead of a silent reload", async () => {
  installBrowserStubs(() => jsonResponse({ affected_ids: ["t1"], skipped: [] }));
  const loads = [];

  await performThreadBulkAction({
    readJson,
    loadState: async (search, options) => {
      loads.push({ search, silent: Boolean(options?.silent) });
    },
    selection: selectionOf(["t1"]),
    action: "archive",
    selectedSessionId: "t1",
    newThreadSearch: "?new=1&project_id=p1",
  });

  assert.deepEqual(loads, [{ search: "?new=1&project_id=p1", silent: false }]);
});
