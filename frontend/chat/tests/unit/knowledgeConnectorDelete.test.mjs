import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { connectorsApi } from "../../src/admin/components/workspaceKnowledge/connectorsApi.ts";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function stubFetch(status, body) {
  const calls = [];
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
  };
  return calls;
}

test("deleting a connector sends DELETE to its encoded workspace path and answers the kept sources", async () => {
  const deleted = { state: "deleted", connector_key: "ops", kind: "jira", retained_sources: 3, removed_sync_items: 3, removed_runs: 2 };
  const calls = stubFetch(200, deleted);

  assert.deepEqual(await connectorsApi.remove("a/b", "ops"), deleted);
  assert.equal(calls[0].url, "/api/v1/workspaces/a%2Fb/knowledge/connectors/ops");
  assert.equal(calls[0].init.method, "DELETE");
});

test("a refused delete names its fixed reason in plain words", async () => {
  stubFetch(409, { detail: { state: "refused", reason: "run_in_progress" } });

  await assert.rejects(connectorsApi.remove("ws", "ops"), (error) => {
    assert.equal(error.reason, "run_in_progress");
    assert.match(error.message, /already in progress/);
    return true;
  });
});
