// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/replyFormatUiPolish.test.mjs
//
// Reply format UI polish, from root's browser acceptance:
// 1. Action run history explains the checked-reply codes and any runtime stop, raw code kept;
// 2. a save blocked by the output format reveals and focuses the problem, and its message follows edits;
// 3. the field editor shows errors only after the author left a field (or tried to save), caps at 32;
// 4. the chat status card says "Reply format: checked" only for a satisfied checked reply;
// 5. a thread whose newest turn stopped never shows the done dot, and says why.
// Item 6 (trace drawer shadow) is CSS only and is checked in the browser by root.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement, useState } from "react";
import TestRenderer from "react-test-renderer";
import { knownRunError } from "../../src/admin/components/actionRunError.ts";
import * as format from "../../src/admin/components/agentsTab/agentReplyFormat.ts";
import { newReplyField } from "../../src/admin/components/agentsTab/agentReplyFields.ts";
import { parseTurnReplyContract } from "../../src/chat/run/turnReplyContract.ts";
import { getThreadSignalKind, threadSignalLabel } from "../../src/chat/threadSignalKind.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, TextEncoder, Error, ...extra,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return loadFile(path.join(SRC, relative));
}

// ---- 1. Action run error guidance -------------------------------------------------------------

const REPLY_CODES = {
  agent_reply_not_json: "The reply was not the required JSON",
  agent_reply_schema_mismatch: "The reply did not match the declared fields",
  agent_reply_contract_invalid: "The agent's reply format is not valid",
  agent_reply_contract_unchecked: "The reply could not be checked",
  agent_reply_contract_path_unsupported: "A step's agent needs a checked reply",
};

test("1: checked-reply codes and runtime stops are explained; everything else stays unclassified", () => {
  for (const [code, summary] of Object.entries(REPLY_CODES)) {
    const known = knownRunError({ status: "error", error: code });
    assert.equal(known?.summary, summary, code);
    assert.match(known.guidance, /\./, code);
    assert.equal(knownRunError({ status: "success", error: code }), null, `${code} on a successful run`);
  }
  assert.match(knownRunError({ status: "error", error: "agent_reply_not_json" }).guidance, /single JSON object its reply format requires/);
  assert.match(knownRunError({ status: "error", error: "agent_reply_contract_invalid" }).guidance, /administrator to fix the agent's reply format/);
  for (const stop of ["step_tool_required", "step_stalled", "answer_evidence_uncited", "answer_evidence_invented_url"]) {
    const generic = knownRunError({ status: "error", error: stop });
    assert.equal(generic?.summary, "Stopped by a safety or quality check", stop);
    assert.match(generic.guidance, /^The agent's turn was stopped by a safety or quality check/);
  }
  // A stop the run's own output records as its turn outcome (a reason this page does not list yet).
  const recorded = { status: "error", error: "future_check_failed", output: { turn_outcome: { state: "stopped", reason: "future_check_failed" } } };
  assert.equal(knownRunError(recorded)?.summary, "Stopped by a safety or quality check");
  for (const [label, run] of [
    ["unrecorded unknown code", { status: "error", error: "future_check_failed" }],
    ["mismatched output reason", { ...recorded, output: { turn_outcome: { state: "stopped", reason: "other" } } }],
    ["finished outcome", { ...recorded, output: { turn_outcome: { state: "finished", reason: "future_check_failed" } } }],
    ["odd code shape", { status: "error", error: "Bad Code!", output: { turn_outcome: { state: "stopped", reason: "Bad Code!" } } }],
    ["lookalike", { status: "error", error: " agent_reply_not_json" }],
    ["prototype key", { status: "error", error: "constructor" }],
  ]) {
    assert.equal(knownRunError(run), null, label);
  }
});

test("1: the run history shows the cause, the guidance and the raw code under technical details", () => {
  const { AdminTaskRunsTable } = load("admin/components/AdminTaskRunsTable.tsx");
  const run = {
    id: "run-1-0000000000", task_id: "task-1", session_id: "sess-1", status: "error", started_by: "u",
    started_at: "2026-10-04T19:51:17", completed_at: null, error: "agent_reply_not_json", duration_seconds: 2,
    steps_log: [], queue_priority: 5, queue_status: "completed", queue_required_domain: "any", queued_at: null,
    estimated_wait_seconds: null, queue_wait_reason: null,
  };
  let view;
  act(() => {
    view = TestRenderer.create(createElement(AdminTaskRunsTable, {
      taskId: "task-1", runs: [run], expandedRun: run.id, statusColor: {}, cancellingRun: null,
      setExpandedRun: () => {}, handleCancelRun: async () => {},
    }));
  });
  const row = view.root.find((node) => node.type === "tr" && String(node.props.className || "").includes("task-run--clickable"));
  assert.equal(text(row.findAllByType("td")[5]), "The reply was not the required JSON");
  const detail = view.root.find((node) => node.props["data-testid"] === "action-run-error");
  assert.match(text(detail), /Run the action again, or ask an administrator to review the agent's reply format/);
  assert.equal(text(detail.findByType("details").findByType("pre")), "agent_reply_not_json");
  act(() => view.unmount());
});

// ---- 2 + 3. Output format field ---------------------------------------------------------------

test("2: a format save message follows the fields; other messages are left alone", () => {
  const named = (name) => ({ ...newReplyField(), name });
  const invalid = { mode: "json_object", fields: [named("Bad")], baseline: "absent" };
  const blocked = format.replyFormatForSave(invalid);
  assert.equal(blocked.ok, false);
  assert.ok(blocked.error.startsWith(format.REPLY_FORMAT_ERROR_PREFIX));

  const stillInvalid = { ...invalid, fields: [named("a"), named("a")] };
  assert.equal(format.formErrorAfterReplyFormatChange(blocked.error, stillInvalid), 'Output format: The field name "a" is used more than once.');
  assert.equal(format.formErrorAfterReplyFormatChange(blocked.error, { ...invalid, fields: [named("summary")] }), null, "cleared once valid");
  assert.equal(format.formErrorAfterReplyFormatChange(blocked.error, { ...invalid, mode: "text" }), null, "cleared by choosing free text");
  assert.equal(format.formErrorAfterReplyFormatChange("Agent name is required", stillInvalid), "Agent name is required");
  assert.equal(format.formErrorAfterReplyFormatChange(null, stillInvalid), null, "no message appears just from editing");
});

const { AgentReplyFormatField } = load("admin/components/agentsTab/AgentReplyFormatField.tsx");

function mountField(initial) {
  let current;
  let setSignal;
  const calls = [];
  function Harness() {
    const [value, setValue] = useState(initial);
    const [signal, setRevealSignal] = useState(0);
    current = value;
    setSignal = setRevealSignal;
    return createElement(AgentReplyFormatField, { value, onChange: setValue, revealSignal: signal });
  }
  let view;
  act(() => {
    view = TestRenderer.create(createElement(Harness), {
      // Stand-ins for the DOM controls, so focus and scroll calls are observable.
      createNodeMock: (element) => {
        const label = element.props["aria-label"] ?? [].concat(element.props.children ?? []).join("").trim();
        return { focus: () => calls.push(["focus", label]), scrollIntoView: () => calls.push(["scroll", label]) };
      },
    });
  });
  const byLabel = (label) => view.root.find((node) => node.props["aria-label"] === label);
  const rowErrors = () => view.root.findAll((node) => node.props["data-testid"] === "agent-reply-format-row-error").map(text);
  return { view, calls, byLabel, rowErrors, current: () => current, reveal: () => act(() => setSignal((count) => count + 1)) };
}

test("2+3: errors wait for the author; a blocked save reveals them and focuses the first problem", () => {
  const ui = mountField({ mode: "json_object", fields: [
    { ...newReplyField(), name: "summary" }, { ...newReplyField(), name: "" }, { ...newReplyField(), name: "Bad" },
  ], baseline: "absent" });
  assert.deepEqual(ui.rowErrors(), [], "nothing before the author interacted");
  assert.equal(ui.view.root.findAll((node) => node.props["data-testid"] === "agent-reply-format-preview").length, 0, "no example while invalid");

  act(() => ui.byLabel("Field 3 name").props.onBlur());
  assert.deepEqual(ui.rowErrors(), ['The field name "Bad" must start with a lowercase letter and use only letters, digits and underscores (at most 64 characters).']);
  assert.equal(ui.byLabel("Field 3 name").props["aria-invalid"], true);

  ui.reveal();
  assert.deepEqual(ui.rowErrors(), ["Field 2 needs a name.", ui.rowErrors()[1]], "every problem after a blocked save");
  assert.deepEqual(ui.calls, [["scroll", "Field 2 name"], ["focus", "Field 2 name"]], "the first problem is brought into view");

  act(() => ui.byLabel("Field 2 name").props.onChange({ target: { value: "count" } }));
  act(() => ui.byLabel("Field 3 name").props.onChange({ target: { value: "tags" } }));
  assert.deepEqual(ui.rowErrors(), [], "fixed fields clear their messages");
  assert.equal(ui.calls.length, 2, "editing never moves the focus");
  assert.ok(ui.view.root.find((node) => node.props["data-testid"] === "agent-reply-format-preview"));
  act(() => ui.view.unmount());
});

test("3: one row per field under column headers; adding stops at 32 with a hint", () => {
  const ui = mountField({ mode: "json_object", fields: Array.from({ length: 31 }, (_, i) => ({ ...newReplyField(), name: `f${i}` })), baseline: "absent" });
  const head = ui.view.root.find((node) => String(node.props.className || "").includes("agent-reply-format__head"));
  assert.deepEqual(head.findAllByType("span").map(text).filter(Boolean), ["Field name", "Type", "Required"]);
  const rows = ui.view.root.findAll((node) => node.props.className === "agent-reply-format__item");
  assert.equal(rows.length, 31);
  const firstRow = rows[0];
  assert.deepEqual(
    firstRow.findAll((node) => ["input", "select", "button"].includes(node.type)).map((node) => node.props["aria-label"]),
    ["Field 1 name", "Field 1 type", "Field 1 required", "Remove field 1"],
    "name, type, required and remove in one row",
  );
  const add = () => ui.view.root.find((node) => node.type === "button" && text(node) === "+ Add field");
  assert.equal(add().props.disabled, false);
  act(() => add().props.onClick());
  assert.equal(ui.current().fields.length, 32);
  assert.equal(add().props.disabled, true);
  assert.equal(text(ui.view.root.find((node) => node.props["data-testid"] === "agent-reply-format-full")), "At most 32 fields.");
  act(() => ui.byLabel("Remove field 32").props.onClick());
  assert.equal(add().props.disabled, false);
  act(() => ui.view.unmount());
});

test("3: removing every field says what to do, without waiting for a save", () => {
  const ui = mountField({ mode: "json_object", fields: [{ ...newReplyField(), name: "only" }], baseline: "absent" });
  act(() => ui.byLabel("Remove field 1").props.onClick());
  assert.equal(text(ui.view.root.find((node) => node.props["data-testid"] === "agent-reply-format-error")), "Add at least one field, or choose Free text.");
  ui.reveal();
  assert.deepEqual(ui.calls.at(-1), ["focus", "+ Add field"], "with no field to focus, the add button gets the focus");
  act(() => ui.view.unmount());
});

// ---- 4. Checked reply on the chat status card -------------------------------------------------

test("4: the reply-contract record is read strictly", () => {
  assert.deepEqual(parseTurnReplyContract({ kind: "json_object", status: "satisfied", reason: null }), { status: "satisfied", reason: null });
  assert.deepEqual(parseTurnReplyContract({ kind: "json_object", status: "violated", reason: "agent_reply_not_json" }), { status: "violated", reason: "agent_reply_not_json" });
  for (const value of [null, undefined, "satisfied", [], { kind: "text", status: "satisfied", reason: null },
    { kind: "json_object", status: "satisfied", reason: "x" }, { kind: "json_object", status: "violated", reason: null },
    { kind: "json_object", status: "violated", reason: "<b>" }, { kind: "json_object", status: "passed", reason: null }]) {
    assert.equal(parseTurnReplyContract(value), null, JSON.stringify(value));
  }
});

test("4: the status card says the reply format was checked only when it was satisfied", async () => {
  const { TurnExecutionStatusCard } = load("chat/run/TurnExecutionStatusCard.tsx", { window: { location: { origin: "http://localhost" } } });
  const { parseTurnExecutionSummary } = await import("../../src/chat/run/turnExecutionSummaryParse.ts");
  const { buildSummaryFixture } = await import("../e2e/turnExecutionSummaryFixtures.mjs");
  const card = (replyContract) => {
    const payload = { ...buildSummaryFixture({ traceId: "t", sessionId: "s", reasonCode: "runtime_finished" }), reply_contract: replyContract };
    const summary = parseTurnExecutionSummary(payload);
    let view;
    act(() => { view = TestRenderer.create(createElement(TurnExecutionStatusCard, { load: { status: "ready", summary }, onRetry: () => {} })); });
    const marks = view.root.findAll((node) => node.props["data-reply-format"] === "checked").map(text);
    act(() => view.unmount());
    return marks;
  };
  assert.deepEqual(card({ kind: "json_object", status: "satisfied", reason: null }), ["Reply format: checked"]);
  assert.deepEqual(card(null), [], "free-text agents are unchanged");
  assert.deepEqual(card({ kind: "json_object", status: "violated", reason: "agent_reply_not_json" }), []);
});

// ---- 5. Thread list dot -----------------------------------------------------------------------

test("5: a thread whose newest turn stopped is never shown as done, and says why", () => {
  const thread = (overrides) => ({ id: "t", title: "T", preview: "", messageCount: 1, projectName: "", runtimeLabel: "",
    startedAt: null, isSelected: false, status: "active", runStatus: "completed", ...overrides });
  assert.equal(getThreadSignalKind(thread({})), "done");
  assert.equal(getThreadSignalKind(thread({ latestTurnStopped: true })), "turn-stopped");
  assert.equal(getThreadSignalKind(thread({ latestTurnStopped: true, runStatus: "" })), "turn-stopped");
  assert.equal(getThreadSignalKind(thread({ latestTurnStopped: true, runStatus: "in_progress" })), "running", "current activity first");
  assert.equal(getThreadSignalKind(thread({ latestTurnStopped: true, runStatus: "failed" })), "error");
  assert.equal(getThreadSignalKind(thread({ latestTurnStopped: false })), "done");
  assert.equal(getThreadSignalKind(thread({ latestTurnStopped: "true" })), "done", "only an explicit true");
  assert.equal(threadSignalLabel("turn-stopped"), "Last turn stopped by a safety or quality check");
  assert.equal(threadSignalLabel("done"), null);
});
