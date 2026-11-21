// (local stack during an API restart): a failed first bootstrap rendered an empty shell without the
// user's rights ("No workspaces available", no Admin). The app now says why, in words, and tries again.
import assert from "node:assert/strict";
import { test } from "node:test";

import { bootstrapFailureText } from "../../src/chat/bootstrapFailure.ts";

test("a server that is down, restarting or overloaded reads as not reachable, never as missing access", () => {
  for (const error of [new TypeError("Failed to fetch"), Object.assign(new Error("Bad Gateway"), { status: 502 }),
    Object.assign(new Error("Service Unavailable"), { status: 503 })]) {
    assert.equal(bootstrapFailureText(error), "Octryx is not reachable right now. The server may be restarting.");
  }
});

test("a refusal keeps the server's own words", () => {
  assert.equal(bootstrapFailureText(Object.assign(new Error("Account disabled"), { status: 403 })),
    "Octryx could not load your workspace: Account disabled");
});
