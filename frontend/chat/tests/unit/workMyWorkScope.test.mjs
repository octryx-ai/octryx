// Review: Work items open on My work, not All items; the person's last choice per Workspace is kept in this
// browser and wins; a server that cannot keep who they are in Jira opens on all items. Requests are stubs.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { useMyWork } from "../../src/chat/work/myWork/useMyWork.ts";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;

async function mount(workspaceId, status, body, stored = {}) {
  const previous = { fetch: globalThis.fetch, window: globalThis.window };
  globalThis.fetch = async () => ({ status, json: async () => body });
  globalThis.window = { localStorage: { getItem: (key) => stored[key] ?? null, setItem: (key, value) => { stored[key] = value; } } };
  let current;
  let view;
  function Probe() { current = useMyWork(workspaceId); return null; }
  await act(async () => { view = TestRenderer.create(createElement(Probe)); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  return { get: () => current, stored, done: () => { act(() => view.unmount()); Object.assign(globalThis, previous); } };
}

test("the page opens on My work, also before the person said who they are in Jira", async () => {
  const set = await mount("ws-1", 200, { source_type: "jira", account_id: "acc-alex", display_name: "Alex" });
  assert.equal(set.get().scope, "mine");
  set.done();
  const unset = await mount("ws-1", 200, { source_type: "jira", account_id: null });
  assert.equal(unset.get().scope, "mine", "My work then offers the choice");
  unset.done();
});

test("the person's last choice is kept per Workspace and wins", async () => {
  const first = await mount("ws-1", 200, { account_id: "acc-alex" });
  await act(async () => first.get().setScope("all"));
  assert.equal(first.get().scope, "all");
  assert.deepEqual(first.stored, { "octryx.work.scope.ws-1": "all" });
  first.done();
  const again = await mount("ws-1", 200, { account_id: "acc-alex" }, { "octryx.work.scope.ws-1": "all" });
  assert.equal(again.get().scope, "all");
  again.done();
  const other = await mount("ws-2", 200, { account_id: "acc-alex" }, { "octryx.work.scope.ws-1": "all" });
  assert.equal(other.get().scope, "mine", "another Workspace has its own choice");
  other.done();
});

test("a server that cannot keep who the person is in Jira opens on all items", async () => {
  const view = await mount("ws-1", 404, { detail: "Not Found" }, { "octryx.work.scope.ws-1": "mine" });
  assert.equal(view.get().scope, "all");
  view.done();
});
