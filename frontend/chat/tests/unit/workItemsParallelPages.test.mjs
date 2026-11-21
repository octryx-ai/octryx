// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workItemsParallelPages.test.mjs
//
// Perf step 1: the Work board read ~950 items as five pages of 200 one after another. The first page tells the
// total, so pages 2..n are requested together; the result keeps the offset order, the limit and the stop rules.
import assert from "node:assert/strict";
import { test } from "node:test";

import { loadWorkItems } from "../../src/chat/work/workApi.ts";

const row = (index) => ({ id: `wi-${index}`, title: `Item ${index}`, work_state: "ready" });
const ALL = Array.from({ length: 950 }, (_, index) => row(index));

// A fetch that holds every answer until the test releases it, so it can see how many requests are open at once.
function heldServer(all = ALL, { total = true, fail = null } = {}) {
  const open = [];
  const calls = [];
  globalThis.fetch = (url) => {
    calls.push(String(url));
    const params = new URL(String(url), "http://x").searchParams;
    const offset = Number(params.get("offset"));
    const limit = Number(params.get("limit"));
    return new Promise((resolve) => {
      open.push(() => {
        if (fail === offset) {
          resolve({ ok: false, status: 503, statusText: "Unavailable", json: async () => ({ detail: "down" }) });
          return;
        }
        const items = all.slice(offset, offset + limit);
        const next = offset + items.length < all.length ? offset + items.length : null;
        const body = { items, limit, offset, next_offset: next, ...(total ? { total: all.length } : {}) };
        resolve({ ok: true, status: 200, statusText: "", json: async () => body });
      });
    });
  };
  const settle = () => new Promise((resolve) => setImmediate(resolve));
  const releaseAll = async () => {
    while (open.length) open.splice(0).forEach((release) => release());
    await settle();
  };
  return { open, calls, settle, releaseAll };
}

test("after the first page tells the total, pages 2..5 are requested together and joined in order", async () => {
  const server = heldServer();
  const done = loadWorkItems(1000, "ws-1");
  await server.settle();
  assert.equal(server.calls.length, 1, "the first page alone, since it tells the total");
  server.open.shift()();
  await server.settle();
  assert.equal(server.open.length, 4, "the four remaining pages are in flight at the same time");
  assert.deepEqual(server.calls.slice(1).map((url) => new URL(url, "http://x").searchParams.get("offset")),
    ["200", "400", "600", "800"]);
  assert.match(server.calls[4], /limit=150&offset=800&project_id=ws-1$/, "the last page asks only for what is left");
  // Answer out of order: the result still follows the offsets.
  server.open.reverse().splice(0).forEach((release) => release());
  const items = await done;
  assert.equal(items.length, 950);
  assert.deepEqual(items.map((item) => item.id), ALL.map((item) => item.id));
  assert.equal(server.calls.length, 5, "five requests in two round trips");
});

test("the limit caps the pages that are asked for", async () => {
  const server = heldServer();
  const done = loadWorkItems(450, "ws-1");
  await server.settle();
  server.open.shift()();
  await server.settle();
  assert.equal(server.open.length, 2);
  assert.match(server.calls[2], /limit=50&offset=400/);
  await server.releaseAll();
  assert.equal((await done).length, 450);
});

test("one page or fewer needs one request; a server without a total is paged one by one", async () => {
  const small = heldServer(ALL.slice(0, 120));
  const one = loadWorkItems(1000);
  await small.releaseAll();
  assert.equal((await one).length, 120);
  assert.equal(small.calls.length, 1);

  const legacy = heldServer(ALL.slice(0, 450), { total: false });
  const paged = loadWorkItems(1000);
  await legacy.settle();
  legacy.open.shift()();
  await legacy.settle();
  assert.equal(legacy.open.length, 1, "without a total only the next page is asked for");
  await legacy.releaseAll();
  await legacy.releaseAll();
  assert.equal((await paged).length, 450);
  assert.equal(legacy.calls.length, 3);
});

test("a failed page fails the load", async () => {
  const server = heldServer(ALL, { fail: 600 });
  const done = loadWorkItems(1000);
  const outcome = done.then(() => "loaded", (error) => error);
  await server.releaseAll();
  await server.releaseAll();
  const error = await outcome;
  assert.ok(error instanceof Error, "the load rejects");
});
