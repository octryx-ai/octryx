// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/actionQueueWaitReason.test.mjs
//
// Queue waiting reason: a still-queued run shows plain text for the dispatcher's closed
// codes; an unknown, raw or secret-like value shows nothing; a run that is no longer queued shows
// no reason; no zero estimate is invented. Rendered with the real runs panel and rows.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { queueWaitReasonText } from "../../src/admin/components/queueWaitReason.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ADMIN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/admin");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const SECRET_LIKE = "redis://user:hunter2@cache refused";
const CODES = {
  no_available_workers: "no worker is available to start it",
  required_worker_unavailable: "the worker it requires is not available",
  paused_due_to_rate_limit: "paused by a rate limit",
  routing_policy_missing: "no routing policy assigns it to a worker",
  no_configured_route: "no worker route is configured for it",
};

test("each closed code has plain text; anything else, or a run no longer queued, has none", () => {
  for (const [code, message] of Object.entries(CODES)) {
    assert.equal(queueWaitReasonText({ status: "queued", queue_wait_reason: code }), message);
    for (const status of ["running", "success", "error", "cancelled"]) {
      assert.equal(queueWaitReasonText({ status, queue_wait_reason: code }), null, `${status} ${code}`);
    }
  }
  for (const value of [SECRET_LIKE, "toString", "constructor", "NO_AVAILABLE_WORKERS", "", null, undefined, 42]) {
    assert.equal(queueWaitReasonText({ status: "queued", queue_wait_reason: value }), null, String(value));
  }
});

function loadPanel() {
  const cache = new Map();
  const load = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
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
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return load(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return load(path.join(ADMIN, "components/AdminTaskRunsPanel.tsx")).AdminTaskRunsPanel;
}
const AdminTaskRunsPanel = loadPanel();

const run = (id, overrides = {}) => ({
  id: `${id}-0000000000`, task_id: "task-1", session_id: null, status: "queued", started_by: "u",
  started_at: null, completed_at: null, error: null, duration_seconds: null, steps_log: [],
  queue_priority: 5, queue_status: "pending", queue_required_domain: "any", queued_at: "2026-10-04T10:00:00",
  estimated_wait_seconds: 0, queue_wait_reason: null, ...overrides,
});

function render(runs) {
  const noop = () => {};
  let view;
  act(() => {
    view = TestRenderer.create(createElement(AdminTaskRunsPanel, {
      isExpanded: true, runCount: runs.length, taskId: "task-1", runsLoading: null, runsError: null, runs,
      expandedRun: null, setExpandedRun: noop, statusColor: {}, setTaskRuns: noop,
      loadTaskRuns: async () => {}, cancellingRun: null, handleCancelRun: async () => {},
    }));
  });
  const rows = view.root.findAll((node) => node.type === "tr" && String(node.props.className || "").includes("task-run--clickable"));
  return {
    all: text(view.root),
    queueCells: rows.map((row) => text(row.findAllByType("td")[2])),
    note: view.root.findAll((node) => node.props["data-testid"] === "task-runs-queued-note").map(text)[0] ?? null,
  };
}

test("a known waiting reason is shown in the row and the note no longer claims it is unknown", () => {
  const ui = render([run("a", { queue_wait_reason: "no_available_workers" })]);
  assert.deepEqual(ui.queueCells, ["p5 · waiting · no worker is available to start it"], "no ~0s estimate");
  assert.ok(ui.note.includes("each row says why it is still waiting."));
  assert.ok(!ui.note.includes("does not report why"));
});

test("unknown or secret-like reasons are never rendered, and the note says the reason is unknown", () => {
  const ui = render([
    run("a", { queue_wait_reason: SECRET_LIKE }),
    run("b", { queue_wait_reason: "required_worker_unavailable", queue_required_domain: "jira" }),
  ]);
  assert.deepEqual(ui.queueCells, [
    "p5 · waiting",
    "p5 · waiting · needs a jira worker · the worker it requires is not available",
  ]);
  assert.ok(!ui.all.includes("hunter2"));
  assert.ok(ui.note.includes("this list does not report why it is still waiting."), "one queued run is unexplained");
});

test("a run that is no longer queued shows no obsolete waiting reason", () => {
  const ui = render([
    run("a", { status: "cancelled", queue_wait_reason: "no_available_workers" }),
    run("b", { status: "success", queue_status: "completed", queue_wait_reason: "paused_due_to_rate_limit", estimated_wait_seconds: 30 }),
  ]);
  assert.deepEqual(ui.queueCells, ["p5", "p5 · ~30s"]);
  assert.equal(ui.note, null);
  for (const message of Object.values(CODES)) assert.ok(!ui.all.includes(message), message);
});
