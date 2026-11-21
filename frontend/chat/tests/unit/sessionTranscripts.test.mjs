// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/sessionTranscripts.test.mjs
//
// Full session transcripts (Workspace switch): what the view shows for each transcript line, the stream
// tabs, paging (every read is audited, so nothing is loaded twice), and the switch's partial save and refusals.
import assert from "node:assert/strict";
import { test } from "node:test";

import { appendPage, initialPaging, nextRequest, orderStreams, pagingFailed, readTranscriptList, readTranscriptPage, readTranscriptSettings, redactionSegments, retentionProblem, settingsChangeBody, settingsSaveErrors, streamLabel, transcriptFilterQuery } from "../../src/chat/transcripts/transcriptModel.ts";
import { entryItems } from "../../src/chat/transcripts/transcriptEntryItems.ts";
import { mergeItems } from "../../src/chat/transcripts/useTranscriptItems.ts";

test("messages are open, thinking and tool blocks are folded", () => {
  const user = entryItems(1, { type: "user", message: { content: "fix the build" }, timestamp: "2026-11-14T10:00:00Z" });
  assert.deepEqual(user.map((item) => [item.kind, item.label, item.body, item.collapsed]), [["user", "You", "fix the build", false]]);

  const assistant = entryItems(2, {
    type: "assistant",
    message: { content: [
      { type: "thinking", thinking: "look at the logs" },
      { type: "text", text: "I will run the tests." },
      { type: "tool_use", id: "t1", name: "Bash", input: { command: "npm test", description: "run" } },
    ] },
  });
  assert.deepEqual(assistant.map((item) => [item.kind, item.label, item.collapsed]), [
    ["thinking", "Thinking", true], ["assistant", "Claude", false], ["tool_use", "Bash", true],
  ]);
  assert.equal(assistant[2].summary, "npm test");
  assert.match(assistant[2].body, /"command": "npm test"/);
  assert.equal(assistant[1].markdown, true);
});

test("a tool result carries its content and the structured toolUseResult, and marks errors", () => {
  const [result] = entryItems(3, {
    type: "user",
    message: { content: [{ type: "tool_result", tool_use_id: "t1", content: [{ type: "text", text: "1 failed" }], is_error: true }] },
    toolUseResult: { stdout: "1 failed", stderr: "AssertionError" },
  });
  assert.equal(result.kind, "tool_result");
  assert.equal(result.collapsed, true);
  assert.equal(result.error, true);
  assert.match(result.body, /^1 failed/);
  assert.match(result.body, /stderr:\nAssertionError/);

  const [file] = entryItems(4, {
    type: "user",
    message: { content: [{ type: "tool_result", tool_use_id: "t2", content: "" }] },
    toolUseResult: { file: { filePath: "/repo/a.ts", content: "export {}" } },
  });
  assert.equal(file.body, "/repo/a.ts\n\nexport {}");
});

test("special and bookkeeping lines get their own words and stay folded", () => {
  const [omitted] = entryItems(5, { type: "octryx_omitted", reason: "line_too_large", bytes: 13 * 1024 * 1024 });
  assert.equal(omitted.label, "Line too large, not stored");
  assert.equal(omitted.summary, "13.0 MB");
  const [unparsed] = entryItems(6, { type: "octryx_unparsed", text: "{broken" });
  assert.deepEqual([unparsed.label, unparsed.body, unparsed.collapsed], ["Line could not be read", "{broken", true]);
  const [system] = entryItems(7, { type: "system", subtype: "compact_boundary" });
  assert.deepEqual([system.kind, system.summary, system.collapsed], ["system", "Compact boundary", true]);
  const [summary] = entryItems(8, { type: "summary", summary: "Fixed the build" });
  assert.deepEqual([summary.kind, summary.label, summary.collapsed], ["other", "Summary", true]);
  assert.equal(entryItems(9, "not an object")[0].kind, "unparsed");
});

test("redactions are cut out as marked segments", () => {
  const segments = redactionSegments("key=[redacted] and [REDACTED]; [redacted: output of a secret command or credential file] end");
  assert.deepEqual(segments.filter((segment) => segment.redacted).map((segment) => segment.text), [
    "[redacted]", "[REDACTED]", "[redacted: output of a secret command or credential file]",
  ]);
  assert.equal(segments.map((segment) => segment.text).join(""), "key=[redacted] and [REDACTED]; [redacted: output of a secret command or credential file] end");
});

test("stream tabs: Main first, subagents by a short id", () => {
  assert.equal(streamLabel("main"), "Main");
  assert.equal(streamLabel("agent-a161095550378ad66"), "Subagent a161095");
  const ordered = orderStreams([
    { stream: "agent-b", lines: 1, firstLine: 1, lastLine: 1 },
    { stream: "main", lines: 9, firstLine: 1, lastLine: 9 },
  ]);
  assert.deepEqual(ordered.map((entry) => entry.stream), ["main", "agent-b"]);
});

test("paging asks one page at a time, never repeats lines, and stops at the end or on 404", () => {
  let paging = initialPaging();
  assert.deepEqual(nextRequest(paging), { fromLine: 1, limit: 200 });
  assert.equal(nextRequest({ ...paging, loading: true }), null);
  paging = appendPage(paging, readTranscriptPage({ lines: [{ line: 1, entry: {} }, { line: 2, entry: {} }], next_from_line: 2 }));
  paging = appendPage(paging, readTranscriptPage({ lines: [{ line: 2, entry: {} }, { line: 3, entry: {} }], next_from_line: null }));
  assert.deepEqual(paging.lines.map((entry) => entry.line), [1, 2, 3]);
  assert.equal(nextRequest(paging), null);
  const missing = pagingFailed(initialPaging(), 404);
  assert.equal(missing.problem, "missing");
  assert.equal(nextRequest(missing), null);
  const failed = pagingFailed(initialPaging(), 500);
  assert.deepEqual(nextRequest(failed), { fromLine: 1, limit: 200 });
});

test("list: items read as sent, merged without duplicates newest first, filter query only with values", () => {
  const items = readTranscriptList({ items: [
    { session_id: "s1", device_job_id: "dj_1", last_at: "2026-11-14T10:00:00Z", bytes_stored: 10,
      streams: [{ stream: "main", lines: 3, first_line: 1, last_line: 3 }] },
  ] });
  assert.equal(items[0].deviceJobId, "dj_1");
  assert.equal(items[0].streams[0].lines, 3);
  assert.equal(readTranscriptList({}), null);
  const merged = mergeItems([items, [{ ...items[0] }, { ...items[0], sessionId: "s2", lastAt: "2026-11-14T11:00:00Z" }]]);
  assert.deepEqual(merged.map((item) => item.sessionId), ["s2", "s1"]);
  assert.equal(transcriptFilterQuery({ sessionId: "", deviceJobId: null }), "");
  assert.equal(transcriptFilterQuery({ workflowRunId: "r1" }), "workflow_run_id=r1");
});

test("switch: partial save, bounds, and a 422 shown at its field", () => {
  const answer = readTranscriptSettings({ session_transcripts: { enabled: false, retention_days: 30 }, source: "default", can_edit: false });
  assert.deepEqual(answer, { enabled: false, retentionDays: 30, source: "default", canEdit: false });
  assert.equal(readTranscriptSettings({ session_transcripts: { enabled: "yes", retention_days: 30 } }), null);
  assert.deepEqual(settingsChangeBody(answer, { enabled: true, retentionDays: 30 }), { enabled: true });
  assert.deepEqual(settingsChangeBody(answer, { enabled: false, retentionDays: 90 }), { retention_days: 90 });
  assert.equal(retentionProblem(0) !== null, true);
  assert.equal(retentionProblem(3651) !== null, true);
  assert.equal(retentionProblem(2.5) !== null, true);
  assert.equal(retentionProblem(3650), null);
  const errors = settingsSaveErrors(422, { detail: { errors: [
    { code: "invalid_retention_days", field: "agent_gateway_policy.session_transcripts.retention_days" },
  ] } });
  assert.match(errors.retentionDays, /1 to 3650/);
  assert.equal(errors.general, undefined);
  assert.match(settingsSaveErrors(403, null).general, /admins and owners/);
});
