// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/deviceContextMeter.test.mjs
//
// A runner or device thread shows how full its context is after the latest model call (the launcher's `context`
// events), so the person sees when to compact.
import assert from "node:assert/strict";
import { test } from "node:test";
import { contextUse } from "../../src/chat/devices/deviceTurnView.ts";

const job = (events) => ({ events: events.map((body, index) => ({ seq: index + 1, type: "job_event", body })) });

test("the newest context event of the thread decides the meter", () => {
  const use = contextUse(job([
    { kind: "context", used: 20000, window: 200000 },
    { kind: "text", text: "answer" },
    { kind: "context", used: 50000, window: 200000 },
  ]));
  assert.deepEqual(use, { used: 50000, window: 200000, percent: 25 });
});

test("a thread without a usable context event has no meter", () => {
  assert.equal(contextUse(job([{ kind: "text", text: "answer" }])), null);
  assert.equal(contextUse(job([{ kind: "context", used: 10, window: 0 }])), null);
});

test("the meter never shows more than full", () => {
  assert.equal(contextUse(job([{ kind: "context", used: 250000, window: 200000 }])).percent, 100);
});
