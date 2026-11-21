// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/healthPhrase.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { healthPhrase, healthTone } from "../../src/admin/utils/healthPhrase.ts";

test("a stored check reads as words, never as a latency figure", () => {
  const now = new Date().toISOString();
  assert.equal(healthPhrase({ status: "ok", last_checked: now }), "Working · checked just now");
  assert.equal(healthPhrase({ status: "error", error: "Sign-in rejected" }), "Failing · Sign-in rejected");
  assert.equal(healthPhrase({ status: "no_test" }), "No test available");
  assert.equal(healthPhrase(null), "Not checked yet");
  assert.equal(healthPhrase({ status: "ok" }, false), "Paused");
  assert.equal(healthTone({ status: "no_test" }), "muted");
  assert.equal(healthTone({ status: "error" }), "error");
});
