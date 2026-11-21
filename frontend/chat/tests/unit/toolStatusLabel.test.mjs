// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/toolStatusLabel.test.mjs
//
// A tool call that waits for the person (propose_write_plan) is streamed as "awaiting_approval" since; the
// trace and the inline cards must say so in words, never print the raw status or call it an error.
import assert from "node:assert/strict";
import { test } from "node:test";

import { toolStatusLabel } from "../../src/chat/toolStatusLabel.ts";

test("a call waiting for approval reads as waiting, not as an error or a raw code", () => {
  assert.equal(toolStatusLabel("awaiting_approval"), "Waiting for approval");
  assert.equal(toolStatusLabel("AWAITING_APPROVAL"), "Waiting for approval");
});

test("the known statuses keep their words and an unknown one loses its underscores", () => {
  assert.equal(toolStatusLabel("success"), "OK");
  assert.equal(toolStatusLabel("failed"), "Error");
  assert.equal(toolStatusLabel("mixed"), "Partial");
  assert.equal(toolStatusLabel("needs_review"), "needs review");
  assert.equal(toolStatusLabel(undefined), "");
});
