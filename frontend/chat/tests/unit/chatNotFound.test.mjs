import assert from "node:assert/strict";
import test from "node:test";

import { CHAT_NOT_FOUND_TEXT, chatNotFoundNotice } from "../../src/chat/chatNotFound.ts";

test("a requested chat that cannot be opened says so instead of opening another chat", () => {
  assert.equal(chatNotFoundNotice({ requestedSessionNotFound: true, selectedSession: null }), CHAT_NOT_FOUND_TEXT);
  assert.equal(chatNotFoundNotice({ requestedSessionNotFound: false, selectedSession: null }), "");
  assert.equal(chatNotFoundNotice({ requestedSessionNotFound: true, selectedSession: { id: "s1" } }), "");
  assert.equal(chatNotFoundNotice({}), "");
  assert.equal(chatNotFoundNotice(null), "");
});
