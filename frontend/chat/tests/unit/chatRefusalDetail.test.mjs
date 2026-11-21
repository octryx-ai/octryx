// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/chatRefusalDetail.test.mjs
//
// A typed turn refusal (an inactive agent) answers 409 with a detail record; the chat shows
// its operator text, never "[object Object]". Plain-text details are unchanged.
import assert from "node:assert/strict";
import { test } from "node:test";
import { readJson, responseDetailText } from "../../src/chat/chatApiClient.ts";

const INACTIVE = {
  code: "agent_definition_inactive",
  message: "This agent is inactive, so it cannot start new turns. Activate it on its agent page to use it again.",
  definition_id: "agent-1",
};

function respondWith(status, body) {
  globalThis.fetch = async () => new Response(JSON.stringify(body), { status, statusText: "Conflict" });
}

test("a typed refusal record shows its message", async () => {
  respondWith(409, { detail: INACTIVE });
  await assert.rejects(readJson("/chat/api/send", { method: "POST", body: "{}" }), { message: INACTIVE.message });
});

test("plain-text details and unreadable records use their fallbacks", async () => {
  respondWith(409, { detail: "This thread is already running" });
  await assert.rejects(readJson("/chat/api/send"), { message: "This thread is already running" });
  respondWith(409, { detail: { code: "agent_definition_inactive" } });
  await assert.rejects(readJson("/chat/api/send"), { message: "Conflict" });
  assert.equal(responseDetailText(null), "");
  assert.equal(responseDetailText({ message: 42 }), "");
});
