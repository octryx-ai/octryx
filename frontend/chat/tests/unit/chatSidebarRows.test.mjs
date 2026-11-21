// Chat sidebar rows: markers, legend, time labels.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  getThreadSignalKind,
  THREAD_MARKERS,
  threadMarkerKind,
  threadSignalLabel,
  UNMARKED_THREAD_SIGNALS,
} from "../../src/chat/threadSignalKind.ts";
import { threadTimeLabel, threadTimeSection } from "../../src/chat/threadTime.ts";

// One thread per branch of getThreadSignalKind.
const SIGNAL_INPUTS = [
  { runStatus: "in_progress" },
  { runStatus: "awaiting_approval" },
  { runCompletionReason: "human_input_required" },
  { runStatus: "failed" },
  { latestTurnStopped: true },
  { runStatus: "stopped" },
  { runStatus: "completed" },
  { status: "running" },
  { status: "error" },
  { status: "pending_approval" },
  { stopReason: "user_cancelled" },
  { status: "archived" },
  {},
];

test("the legend lists every marker the code can emit; the rest carries no marker", () => {
  const emitted = new Set(SIGNAL_INPUTS.map((input) => getThreadSignalKind({ status: "active", ...input })));
  const legendKinds = new Set(THREAD_MARKERS.map((marker) => marker.kind));

  for (const kind of emitted) {
    assert.ok(legendKinds.has(kind) || UNMARKED_THREAD_SIGNALS.includes(kind), `unexplained kind ${kind}`);
  }
  for (const kind of legendKinds) {
    assert.ok(emitted.has(kind), `legend entry ${kind} is never emitted`);
  }
});

test("markers have text labels; done and stopped show nothing (no green dot)", () => {
  assert.equal(threadSignalLabel("running"), "Running");
  assert.equal(threadSignalLabel("attention"), "Needs you");
  assert.equal(threadSignalLabel("error"), "Failed");
  assert.equal(threadSignalLabel("turn-stopped"), "Last turn stopped by a safety or quality check");
  assert.equal(threadMarkerKind("done"), null);
  assert.equal(threadMarkerKind("stopped"), null);
  assert.equal(threadSignalLabel("stopped"), null);
});

test("last activity reads as a time today, Yesterday, a weekday, then a date", () => {
  const now = new Date(2026, 9, 8, 15, 40);
  const at = (days, hours = 0) => new Date(now.getTime() - days * 86400000 - hours * 3600000).toISOString();

  assert.equal(threadTimeSection(at(0, 1), now), "Today");
  assert.match(threadTimeLabel(at(0, 1), now), /^\d\d:\d\d$/);
  assert.equal(threadTimeSection(at(1), now), "Yesterday");
  assert.equal(threadTimeLabel(at(1), now), "Yesterday");
  assert.equal(threadTimeSection(at(4), now), "Previous 7 days");
  assert.match(threadTimeLabel(at(4), now), /^[A-Z][a-z]{2}$/);
  assert.equal(threadTimeSection(at(30), now), "Earlier");
  assert.match(threadTimeLabel(at(30), now), /^\d{1,2} [A-Z][a-z]+$/);
  // A server timestamp without a zone is UTC.
  assert.equal(threadTimeSection("2026-10-08T12:00:00", now), threadTimeSection("2026-10-08T12:00:00Z", now));
  assert.equal(threadTimeLabel(null, now), "");
});
