// A hung admin read (an exhausted API pool) or a 503 ends with words the page shows (plus Retry), never "Loading…"
// forever or the raw "Service Unavailable".
import assert from "node:assert/strict";
import { test } from "node:test";

import { readJson } from "../../src/admin/utils/adminPanelHelpers.ts";

const withFetch = async (impl, run) => {
  const original = globalThis.fetch;
  globalThis.fetch = impl;
  try { await run(); } finally { globalThis.fetch = original; }
};

test("a read that never answers ends with a timeout in words; a write is never cut off by it", async () => {
  const signals = [];
  await withFetch((_url, init) => {
    signals.push(init.signal);
    if (init.signal?.aborted) return Promise.reject(init.signal.reason);
    return new Promise((_, reject) => init.signal?.addEventListener("abort", () => reject(init.signal.reason)));
  }, async () => {
    const original = AbortSignal.timeout;
    AbortSignal.timeout = () => AbortSignal.abort(new DOMException("t", "TimeoutError"));
    try {
      await assert.rejects(readJson("/admin/chat/api/panel/connectors"),
        (error) => error.code === "timeout" && /did not answer within 30 seconds\. Try again/.test(error.message));
    } finally { AbortSignal.timeout = original; }
  });
  await withFetch((_url, init) => { signals.push(init.signal); return Promise.resolve(new Response("{}", { status: 200 })); },
    () => readJson("/admin/chat/api/panel/connectors", { method: "PUT", body: "{}" }));
  assert.equal(signals.at(-1), undefined);
});

test("a busy server reads as words, not 'Service Unavailable'; a refusal keeps its own detail", async () => {
  await withFetch(() => Promise.resolve(new Response("", { status: 503, statusText: "Service Unavailable" })), () =>
    assert.rejects(readJson("/admin/chat/api/panel/connectors"), /busy or restarting \(503\)\. Try again in a moment/));
  await withFetch(() => Promise.resolve(new Response(JSON.stringify({ detail: "Unknown connector" }), { status: 404 })), () =>
    assert.rejects(readJson("/admin/chat/api/panel/connectors/x"), /^Error: Unknown connector$/));
});
