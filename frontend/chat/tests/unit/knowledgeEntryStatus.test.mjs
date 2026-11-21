// Knowledge → Search status line (S5): "6 sources · up to date" instead of "50+ documents · 187 jobs
// waiting (5966 indexing jobs done)" and "About these numbers"; the indexing backlog only while there is one.
import assert from "node:assert/strict";
import { test } from "node:test";
import { statusItems } from "../../src/chat/knowledge/knowledgeEntryStatus.ts";

const NOW = Date.parse("2026-11-06T21:00:00Z");
const document = (id) => ({ source_id: id, source_key: id, display_title: id, revision_count: 1, latest_revision_ordinal: 1 });
const listing = (count, more = false, backlog = {}) =>
  ({ sources: Array.from({ length: count }, (_, i) => document(`s${i}`)), projection_backlog: backlog, next_cursor: more ? "next" : null });
const connector = (key, over = {}) => ({
  connector_key: key, kind: "confluence", state: "active", running: false, products: [], version: null, max_items_per_run: 100,
  scope: { spaces: ["OPS"] }, schedule: { enabled: true, interval_minutes: 360, next_run_at: null },
  cursor: { pass_number: 3, token: null, pass_started_at: null, completed_passes: 2, last_completed_at: "2026-11-06T09:00:00Z" },
  last_run: { id: "r1", state: "completed", reason: null, report: { created: 1 }, started_at: "2026-11-06T09:58:00Z", finished_at: "2026-11-06T10:00:00Z" },
  ...over,
});
const sources = (...connectors) => ({ connectors, instance_scheduler_enabled: true });
const six = () => sources(...["a", "b", "c", "d", "e", "f"].map((key) => connector(key)));
const input = (patch) => ({ listing: null, sourcesFailed: false, connectors: null, connectorsFailed: false, ...patch });
const line = (patch) => statusItems(input(patch), NOW).map((item) => item.text);
const tones = (patch) => statusItems(input(patch), NOW).map((item) => item.tone);

test("the line counts sources, not documents, and says up to date (S5)", () => {
  const done = { listing: listing(50, true, { applied: 5966 }), connectors: six() };
  assert.deepEqual(line(done), ["6 sources", "up to date"]);
  assert.deepEqual(tones(done), ["plain", "plain"]);
  assert.deepEqual(statusItems(input(done), NOW).map((item) => item.label), ["Sources", "State"]);
  assert.deepEqual(line({ listing: listing(3, false, { applied: 3 }), connectors: sources(connector("a")) }), ["1 source", "up to date"]);
});

test("only a backlog adds the indexing state, muted, with no other job counts", () => {
  const busy = { listing: listing(50, true, { applied: 5966, pending: 180, claimed: 7 }), connectors: six() };
  assert.deepEqual(line(busy), ["6 sources", "Indexing: 187 waiting"]);
  assert.deepEqual(tones(busy), ["plain", "muted"]);
  assert.doesNotMatch(line(busy).join(" "), /5966|documents|jobs/);
});

test("what needs someone to act comes first", () => {
  const failedRun = connector("b", { last_run: { ...connector("b").last_run, state: "failed", reason: "source_unauthorized" } });
  const attention = { listing: listing(2, false, { pending: 4, dead_letter: 1 }), connectors: sources(connector("a"), failedRun) };
  assert.deepEqual(line(attention), ["2 sources", "1 needs attention"]);
  assert.deepEqual(tones(attention), ["plain", "attention"]);
  const deadLetter = { listing: listing(2, false, { applied: 4, pending: 4, dead_letter: 2 }), connectors: six() };
  assert.deepEqual(line(deadLetter), ["6 sources", "Indexing: 2 failed"]);
  const stale = connector("m", { schedule: { enabled: false, interval_minutes: 360, next_run_at: null },
    cursor: { ...connector("m").cursor, last_completed_at: "2026-09-01T09:00:00Z" },
    last_run: { ...connector("m").last_run, started_at: "2026-09-01T09:58:00Z", finished_at: "2026-09-01T10:00:00Z" } });
  assert.deepEqual(line({ listing: listing(2), connectors: sources(connector("a"), stale) }), ["2 sources", "1 out of date"]);
});

test("passing states stay muted; manual and paused sources are not called up to date", () => {
  assert.deepEqual(line({ listing: listing(2), connectors: sources(connector("a"), connector("b", { running: true })) }),
    ["2 sources", "syncing"]);
  const never = connector("n", { last_run: null, cursor: { pass_number: 0, pass_started_at: null, completed_passes: 0, last_completed_at: null } });
  assert.deepEqual(line({ listing: listing(0), connectors: sources(never) }), ["1 source", "1 never synced"]);
  const manual = connector("h", { schedule: { enabled: false, interval_minutes: 360, next_run_at: null } });
  assert.deepEqual(line({ listing: listing(2), connectors: sources(connector("a"), manual) }), ["2 sources", "synced"]);
  assert.deepEqual(line({ listing: listing(2), connectors: sources(connector("a", { state: "paused" })) }), ["1 source", "paused"]);
  // The instance runs no schedules: nothing keeps a source current.
  assert.deepEqual(line({ listing: listing(2), connectors: { ...sources(connector("a")), instance_scheduler_enabled: false } }),
    ["1 source", "synced"]);
});

test("loading, empty, upload-only and failed reads stay truthful", () => {
  assert.deepEqual(line({}), ["Loading sources…"]);
  assert.deepEqual(line({ connectors: six() }), ["6 sources"], "no state before the backlog is known");
  assert.deepEqual(line({ listing: listing(0), connectors: sources() }), ["No sources yet"]);
  assert.deepEqual(line({ listing: listing(3, false, { applied: 3 }), connectors: sources() }), ["No connected sources"]);
  assert.deepEqual(line({ listing: listing(3, false, { pending: 2 }), connectors: sources() }), ["No connected sources", "Indexing: 2 waiting"]);
  assert.deepEqual(line({ listing: listing(3), connectorsFailed: true }), ["Sources unavailable"]);
  assert.deepEqual(tones({ listing: listing(3), connectorsFailed: true }), ["attention"]);
  assert.deepEqual(line({ sourcesFailed: true, connectors: six() }), ["6 sources", "up to date"]);
});
