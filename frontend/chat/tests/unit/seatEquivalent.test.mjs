// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/seatEquivalent.test.mjs
// The seat's API equivalent: a seat call costs the platform nothing; the UI shows what it would
// cost via the API at list price, always apart from the API cost, never added to it, and never an estimate for a model
// without a list price (its calls are counted instead).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  hasSeat,
  readSeat,
  readSeatLabels,
  seatAmountText,
  seatHeading,
  seatSentence,
  seatShort,
  sumSeat,
  unpricedHeading,
  unpricedText,
  usdText,
} from "../../src/chat/cost/seatEquivalent.ts";

test("the figure is labelled as what the call would cost via the API at list price", () => {
  const figures = readSeat({ seat_api_equivalent: 10.4, seat_unpriced_calls: 0 }, "seat_api_equivalent", "seat_unpriced_calls");
  assert.equal(seatSentence(figures), "Seat: would cost via API (list price) $10.40");
  assert.equal(seatHeading(), "Seat: would cost via API (list price)");
  assert.equal(seatShort(figures), "Seat $10.40 (list price)");
  for (const text of [seatSentence(figures), seatShort(figures), seatHeading()]) {
    assert.doesNotMatch(text, /sav|subscription|ratio|%|×/i, "no subscription price, ratio or savings");
  }
});

test("a model without a list price gets no estimate, only its call count", () => {
  const only = { equivalentUsd: 0, unpricedCalls: 3 };
  assert.equal(seatAmountText(only), "", "never $0.00, which would read as an estimate");
  assert.equal(unpricedText(3), "no list price (seat only) · 3 calls");
  assert.equal(unpricedText(1), "no list price (seat only) · 1 call");
  assert.equal(unpricedText(0), "");
  assert.equal(seatSentence(only), "Seat: no list price (seat only) · 3 calls");
  assert.equal(seatShort(only), "Seat: 3 calls, no list price");
  assert.equal(seatSentence({ equivalentUsd: 2, unpricedCalls: 1 }),
    "Seat: would cost via API (list price) $2.00 · no list price (seat only) · 1 call");
  assert.equal(unpricedHeading(), "No list price (seat only)");
});

test("the backend's labels win where a response sends them", () => {
  const labels = readSeatLabels({ api_equivalent_usd: "would cost through the API", unpriced_calls: "unpriced" });
  assert.equal(seatHeading(labels), "Seat: would cost through the API");
  assert.equal(unpricedText(2, labels), "unpriced · 2 calls");
  assert.deepEqual(readSeatLabels({ api_equivalent_usd: " ", unpriced_calls: 4 }), readSeatLabels(null));
});

test("seat figures sum only with seat figures; bad values read as nothing", () => {
  assert.deepEqual(sumSeat([{ equivalentUsd: 1.25, unpricedCalls: 1 }, { equivalentUsd: 0.75, unpricedCalls: 2 }]),
    { equivalentUsd: 2, unpricedCalls: 3 });
  assert.deepEqual(sumSeat([]), { equivalentUsd: 0, unpricedCalls: 0 });
  assert.deepEqual(readSeat({ a: "5", b: -2 }, "a", "b"), { equivalentUsd: 0, unpricedCalls: 0 });
  assert.equal(hasSeat({ equivalentUsd: 0, unpricedCalls: 0 }), false);
  assert.equal(seatSentence({ equivalentUsd: 0, unpricedCalls: 0 }), "");
  assert.equal(seatShort({ equivalentUsd: 0, unpricedCalls: 0 }), "");
});

test("money reads like the rest of the cost views", () => {
  assert.equal(usdText(63.444), "$63.44");
  assert.equal(usdText(0.004), "<$0.01");
  assert.equal(usdText(0), "$0.00");
  assert.equal(usdText(Number.NaN), "$0.00");
});
