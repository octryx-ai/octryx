// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/actionRunErrorGuidance.test.mjs
//
// Action run error guidance, rendered with the real run table, row and detail. The three exact
// agent refusal codes on an error run show a short cause in the table and corrective guidance in the
// details, with the original error kept under "Technical details". Anything else — other statuses,
// unknown text, lookalikes — stays unclassified and shows its original text. The details toggle is a
// labelled button; cancellation, queue reasons and session links are unchanged.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { knownRunError } from "../../src/admin/components/actionRunError.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ADMIN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/admin");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const CODES = ["agent_definition_inactive", "agent_definition_not_published", "agent_definition_execution_mode_not_configured"];

test("only the three exact codes on an error run are explained; everything else stays unclassified", () => {
  const summaries = CODES.map((code) => knownRunError({ status: "error", error: code })?.summary);
  assert.deepEqual(summaries, [
    "The selected agent was turned off",
    "The selected agent had no published revision",
    "Agent execution is not configured",
  ]);
  assert.match(knownRunError({ status: "error", error: CODES[0] }).guidance, /activate it on the agent's page/);
  assert.match(knownRunError({ status: "error", error: CODES[1] }).guidance, /publish a revision/);
  assert.match(knownRunError({ status: "error", error: CODES[2] }).guidance, /Ask a workspace administrator to configure the agent execution mode/);
  for (const code of CODES) {
    // An explanation, not a claim about cost or retries.
    assert.doesNotMatch(knownRunError({ status: "error", error: code }).guidance, /cost|charge|retr/i, code);
    for (const status of ["success", "cancelled", "queued", "running", "failed", "skipped", undefined]) {
      assert.equal(knownRunError({ status, error: code }), null, `${status} ${code}`);
    }
  }
  for (const error of [
    " agent_definition_inactive", "agent_definition_inactive ", "AGENT_DEFINITION_INACTIVE", "agent_definition_inactive: details",
    "scheduled_task_failed: agent_definition_inactive", "agent_definition", "toString", "constructor", "__proto__", "", null, undefined, 7,
  ]) {
    assert.equal(knownRunError({ status: "error", error }), null, String(error));
  }
});

function load(relative) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    // Exact file-name case, so a wrong-case path also fails on case-insensitive hosts.
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date,
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
  return loadFile(path.join(ADMIN, relative));
}
const { AdminTaskRunsTable } = load("components/AdminTaskRunsTable.tsx");

const run = (id, overrides = {}) => ({
  id: `${id}-0000000000`, task_id: "task-1", session_id: null, status: "error", started_by: "u",
  started_at: "2026-10-04T10:00:00", completed_at: null, error: null, duration_seconds: 1.5, steps_log: [],
  queue_priority: 5, queue_status: "completed", queue_required_domain: "any", queued_at: null,
  estimated_wait_seconds: null, queue_wait_reason: null, ...overrides,
});

function render(runs, { expandedRun = null } = {}) {
  const calls = [];
  let view;
  act(() => {
    view = TestRenderer.create(createElement(AdminTaskRunsTable, {
      taskId: "task-1", runs, expandedRun, statusColor: {}, cancellingRun: null,
      setExpandedRun: (value) => calls.push(["expand", value]),
      handleCancelRun: async (taskId, runId) => { calls.push(["cancel", taskId, runId]); },
    }));
  });
  const rows = view.root.findAll((node) => node.type === "tr" && String(node.props.className || "").includes("task-run--clickable"));
  return {
    view, calls, rows,
    errorCell: (row) => text(row.findAllByType("td")[5]),
    toggle: (row) => row.findAll((node) => node.type === "button" && node.props["aria-expanded"] !== undefined)[0],
    detail: () => view.root.findAll((node) => node.props["data-testid"] === "action-run-error")[0] ?? null,
  };
}

test("a known refusal shows its cause in the table and guidance with the original error in the details", () => {
  const known = run("a", { error: "agent_definition_inactive" });
  let ui = render([known]);
  assert.equal(ui.errorCell(ui.rows[0]), "The selected agent was turned off");
  assert.equal(ui.detail(), null, "collapsed until opened");

  ui = render([known], { expandedRun: known.id });
  const detail = ui.detail();
  assert.equal(text(detail.findByProps({ className: "action-run-error__summary" })), "The selected agent was turned off");
  assert.match(text(detail.findByProps({ className: "action-run-error__guidance" })), /^The agent this action uses was inactive/);
  const technical = detail.findByType("details");
  assert.equal(technical.props.open, undefined, "technical details stay collapsed");
  assert.equal(text(technical.findByType("summary")), "Technical details");
  assert.equal(text(technical.findByType("pre")), "agent_definition_inactive", "the original error is kept for support");
  assert.equal(ui.view.root.findAll((node) => node.type === "a").length, 0, "no agent link is derived for a past run");
});

test("unknown and lookalike errors stay unclassified and show their original text as text", () => {
  const raw = '<img src=x onerror="alert(1)"> agent_definition_inactive and a very long tail of detail text';
  const unknown = run("b", { error: raw });
  let ui = render([unknown]);
  assert.equal(ui.errorCell(ui.rows[0]), raw.slice(0, 60), "the table cell is unchanged for unknown errors");
  ui = render([unknown], { expandedRun: unknown.id });
  const detail = ui.detail();
  assert.equal(text(detail.findByProps({ className: "action-run-error__summary" })), "Error reported by the run");
  assert.deepEqual(detail.findByType("pre").children, [raw], "rendered as a text child, never as markup");
  assert.equal(detail.findAll((node) => node.props.className === "action-run-error__guidance").length, 0, "no invented remedy");

  const cancelled = run("c", { status: "cancelled", error: "agent_definition_inactive" });
  ui = render([cancelled]);
  assert.equal(ui.errorCell(ui.rows[0]), "agent_definition_inactive", "a known code on another status is not explained");
});

test("the details toggle is a labelled button that toggles once; row click, cancel and session links are unchanged", async () => {
  const queued = run("d", { status: "queued", error: null, session_id: "sess-1", queue_status: "pending", queue_wait_reason: "no_available_workers" });
  const ui = render([queued]);
  const [row] = ui.rows;
  const toggle = ui.toggle(row);
  assert.deepEqual([toggle.props.type, toggle.props["aria-label"], toggle.props["aria-expanded"]], ["button", "Show run details", false]);
  act(() => { toggle.props.onClick(); });
  // The button sits in the cell that stops propagation, so the row's own toggle does not also fire.
  let stopped = false;
  toggle.parent.props.onClick({ stopPropagation: () => { stopped = true; } });
  assert.ok(stopped);
  act(() => { row.props.onClick(); });
  assert.deepEqual(ui.calls, [["expand", queued.id], ["expand", queued.id]], "button and row each toggle once");

  const cancel = row.findAll((node) => node.type === "button" && text(node) === "Cancel")[0];
  await act(async () => { await cancel.props.onClick(); });
  assert.deepEqual(ui.calls.at(-1), ["cancel", "task-1", queued.id]);
  const link = row.findByType("a");
  assert.deepEqual([link.props.href, link.props.target], ["/chat?session_id=sess-1", "_blank"]);
  assert.ok(text(row).includes("no worker is available to start it"), "queue reason unchanged");

  const open = render([queued], { expandedRun: queued.id });
  const openToggle = open.toggle(open.rows[0]);
  assert.deepEqual([openToggle.props["aria-label"], openToggle.props["aria-expanded"]], ["Hide run details", true]);
  const detailRow = open.view.root.findAll((node) => node.type === "tr" && node.props.id === openToggle.props["aria-controls"]);
  assert.equal(detailRow.length, 1, "aria-controls names the details row");
});
