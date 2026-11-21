// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgeConnectorCorrections.test.mjs
//
// Frontend corrections from root's live acceptance (L1–L4, F3): server times are UTC even without a zone
// (the test runs in CEST, where a naive value read as local time is two hours early); the connectors panel shows
// the Workspace's Knowledge state with Enable Knowledge; a completed run with failed or deferred items is
// "completed with failures", not green; the freshness block states the listing mode and the last clean full pass
// and does not repeat the table's badge; the withheld explanation follows the reason and the enforcement.
process.env.TZ = "Europe/Zurich";

import assert from "node:assert/strict";

import { formatDateTime } from "../../src/admin/utils/dateTime.ts";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { apiTimeOf, formatApiTime } from "../../src/admin/components/workspaceKnowledge/apiTime.ts";
import {
  completedWithFailures,
  lastFullPassText,
  nextRunText,
  runModeText,
  runResultText,
  withheldText,
} from "../../src/admin/components/workspaceKnowledge/connectorFreshness.ts";
import { knowledgeStateOf } from "../../src/admin/components/workspaceKnowledge/knowledgeEnablement.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const NOW = Date.parse("2026-10-05T12:00:00Z");

const connector = (overrides = {}) => ({
  connector_key: "demo", kind: "confluence", scope: { spaces: ["DEMO"] }, products: [], version: null,
  max_items_per_run: 100, state: "active",
  cursor: { pass_number: 4, token: null, pass_started_at: null, last_completed_at: "2026-10-05T10:13:56", completed_passes: 3 },
  schedule: { enabled: true, interval_minutes: 15, next_run_at: "2026-10-05T12:10:00" },
  running: false,
  last_run: {
    id: "run-1", state: "completed", reason: null, started_at: "2026-10-05T10:13:55", finished_at: "2026-10-05T10:13:56",
    report: { created: 0, updated: 0, unchanged: 9, retired: 1, skipped: 0, failed: 0, listed: 9, mode: "full", pass_completed: true, withheld: 0 },
  },
  ...overrides,
});

// ---- L1: UTC --------------------------------------------------------------------------------------

test("A naive server time is UTC; a time with a zone is read as written; garbage is not a time", () => {
  assert.equal(apiTimeOf("2026-10-05T10:13:56"), Date.parse("2026-10-05T10:13:56Z"));
  assert.equal(apiTimeOf("2026-10-05 10:13:56.123456"), Date.parse("2026-10-05T10:13:56.123Z"));
  assert.equal(apiTimeOf("2026-10-05T10:13"), Date.parse("2026-10-05T10:13:00Z"));
  assert.equal(apiTimeOf("2026-10-05T10:13:56Z"), Date.parse("2026-10-05T10:13:56Z"));
  assert.equal(apiTimeOf("2026-10-05T12:13:56+02:00"), Date.parse("2026-10-05T10:13:56Z"));
  for (const value of [null, undefined, "", "soon", "2026-13-45T99:00:00"]) assert.equal(apiTimeOf(value), null, String(value));
  assert.equal(formatApiTime("2026-10-05T10:13:56"), formatDateTime("2026-10-05T10:13:56Z"));
  assert.match(formatApiTime("2026-10-05T10:13:56"), /12:13/, "shown in CEST as 12:13, not 10:13");
  assert.equal(formatApiTime("soon"), "—");
});

test("The next run is due only when its UTC time has passed; an unreadable time is not 'due now'", () => {
  // 12:10 UTC is ten minutes ahead; read as local CEST time it would be 10:10 UTC and "due now".
  assert.match(nextRunText(connector(), "on", NOW), /^Every 15 min; next run \d/);
  assert.doesNotMatch(nextRunText(connector(), "on", NOW), /due now/);
  assert.match(nextRunText(connector({ schedule: { enabled: true, interval_minutes: 15, next_run_at: "2026-10-05T11:59:00Z" } }), "on", NOW), /next run due now/);
  assert.match(nextRunText(connector({ schedule: { enabled: true, interval_minutes: 15, next_run_at: "later" } }), "on", NOW), /next run time not readable/);
});

// ---- F3: withheld reasons ------------------------------------------------------------------------

test("The withheld explanation follows the Workspace's enforcement and the reason", () => {
  const off = withheldText("confluence", { withheld: 2, withheld_reasons: { restricted_acl: 2 }, acl_enforced: false });
  assert.match(off, /^2 restricted pages withheld\. This Workspace does not enforce Confluence permissions, so restricted pages are not indexed\./);
  assert.doesNotMatch(off, /cannot match/);
  const unmatched = withheldText("confluence", { withheld: 1, withheld_reasons: { acl_unresolved: 1 }, acl_enforced: true });
  assert.match(unmatched, /restricted in Confluence to people this Workspace cannot match to its members/);
  // No enforcement flag in the answer. Only unresolved principals still name the matching; otherwise only what is known.
  assert.match(withheldText("confluence", { withheld: 1, skipped_reasons: { acl_unresolved: 1 } }), /cannot match/);
  const generic = withheldText("confluence", { skipped_reasons: { restricted_acl: 3 } });
  assert.match(generic, /^3 restricted pages not indexed: they are restricted in Confluence, so they are withheld/);
  assert.doesNotMatch(generic, /cannot match|does not enforce/);
  assert.equal(withheldText("confluence", { withheld: 0, acl_enforced: false }), null);
});

// ---- L3: completed with failures -----------------------------------------------------------------

test("A completed run with failed or deferred items is not a clean pass", () => {
  const run = (report, state = "completed") => ({ state, report });
  assert.equal(completedWithFailures(run({ failed: 0 })), false);
  assert.equal(completedWithFailures(run({ failed: 2 })), true);
  assert.equal(completedWithFailures(run({ deferred: 1 })), true);
  assert.equal(completedWithFailures(run({ failed: 2 }, "failed")), false, "a failed run keeps its own state");
  assert.equal(runResultText(run({ failed: 0 })), "The run completed a full pass.");
  assert.equal(runResultText(run({ failed: 2 }), "confluence"),
    "The run completed with 2 failed pages: it does not count as a full pass, and they are retried on the next run.");
  assert.match(runResultText(run({ failed: 1, deferred: 3 }), "confluence"), /^The run completed with 1 failed and 3 deferred pages:/);
});

// ---- L4: mode and last full pass -----------------------------------------------------------------

test("The run's listing mode and the last clean full pass are stated; a pass with failures does not count", () => {
  assert.equal(runModeText("confluence", { mode: "full" }), "Full pass: listed every page in scope");
  assert.equal(runModeText("confluence", { mode: "incremental" }), "Incremental: changed pages first, then a listing of the scope");
  assert.match(runModeText("confluence", { mode: "incremental_fallback" }), /^Full listing: the change query failed/);
  assert.match(runModeText("confluence", { mode: "incremental", pass_completed: false }), /listing not finished; the next run continues it/);
  assert.equal(runModeText("confluence", {}), null, "no mode reported");
  assert.equal(runModeText("confluence", { mode: "sideways" }), null);

  const clean = connector().cursor;
  assert.equal(lastFullPassText("confluence", clean), formatApiTime("2026-10-05T10:13:56"));
  const failedLater = { ...clean, last_pass_closed_at: "2026-10-05T11:00:00Z", last_pass_failures: 2 };
  assert.match(lastFullPassText("confluence", failedLater), /The pass that closed .* had 2 failed or deferred pages, so it does not count; they are retried on the next run\./);
  assert.doesNotMatch(lastFullPassText("confluence", { ...failedLater, last_pass_failures: 0 }), /does not count/);
  assert.doesNotMatch(lastFullPassText("confluence", { ...failedLater, last_pass_closed_at: "2026-10-05T09:00:00Z" }), /does not count/,
    "an older failed pass before the clean one is history");
  assert.match(lastFullPassText("confluence", { pass_number: 1, completed_passes: 0, last_completed_at: null, last_pass_closed_at: "2026-10-05T11:00:00Z", last_pass_failures: 1 }),
    /^No full pass has completed yet\. The pass that closed/);
});

// ---- rendered ------------------------------------------------------------------------------------

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
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, ...extra,
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

const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
const badges = (view) => view.root.findAll((node) => typeof node.props.className === "string" && node.props.className.startsWith("admin-panel__badge "));

test("rendered L3: the run badge says 'completed with failures' as a warning; a clean run stays green", () => {
  const { RunBadge } = load("admin/components/workspaceKnowledge/KnowledgeConnectorRun.tsx");
  const badge = (report) => {
    let view;
    act(() => { view = TestRenderer.create(createElement(RunBadge, { run: { ...connector().last_run, report } })); });
    const [node] = badges(view);
    return { label: text(node), className: node.props.className };
  };
  assert.deepEqual(badge({ failed: 0 }), { label: "completed", className: "admin-panel__badge admin-panel__badge--active" });
  assert.deepEqual(badge({ failed: 2 }), { label: "completed with failures", className: "admin-panel__badge admin-panel__badge--warning" });
  assert.equal(badge({ deferred: 1 }).label, "completed with failures");
});

test("rendered L4/L6: the freshness block states mode and last full pass, and repeats no run badge or run time", () => {
  const { KnowledgeConnectorFreshness } = load("admin/components/workspaceKnowledge/KnowledgeConnectorFreshness.tsx");
  let view;
  act(() => { view = TestRenderer.create(createElement(KnowledgeConnectorFreshness, { connector: connector(), instance: "on" })); });
  assert.equal(text(byTestId(view, "freshness-last-run")[0]), "Full pass: listed every page in scope · pages: 0 new · 0 changed · 1 removed · 0 withheld");
  const fullPass = text(byTestId(view, "freshness-full-pass")[0]);
  assert.ok(fullPass.startsWith(formatApiTime("2026-10-05T10:13:56")), fullPass);
  assert.doesNotMatch(fullPass, /Sync now performs a full pass/, "what a full pass does is page help");
  assert.equal(badges(view).length, 0, "the state badge stays in the table and the last-run section");
  act(() => view.unmount());
});

async function mountPanel(listing, { enableAnswer } = {}) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method ?? "GET" });
    if (String(url).endsWith("/knowledge/enable")) return { ok: enableAnswer.status === 200, status: enableAnswer.status, json: async () => enableAnswer.body };
    const body = String(url).endsWith("/runs/last") ? { connector_key: "demo", run: { ...connector().last_run, outcomes: [] } } : listing;
    return { ok: true, status: 200, json: async () => body };
  };
  const { KnowledgeConnectorsPanel } = load("admin/components/workspaceKnowledge/KnowledgeConnectorsPanel.tsx", { fetch, window: { confirm: () => false } });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(KnowledgeConnectorsPanel, { workspaceId: "ws-1" })); });
  return { view, calls };
}

const enableButtons = (view) => view.root.findAll((node) => node.type === "button" && text(node) === "Enable Knowledge");

test("The listing's knowledge state is read strictly; the server's unknown is 'not recorded', a missing field 'not reported'", () => {
  assert.deepEqual(knowledgeStateOf({ knowledge: { state: "ready", outcome: "postgres_index", checked_at: "2026-10-05T10:00:00Z" } }),
    { state: "ready", outcome: "postgres_index", checkedAt: "2026-10-05T10:00:00Z" });
  assert.equal(knowledgeStateOf({ knowledge: { state: "unknown", outcome: null, checked_at: null } }).state, "not_recorded");
  assert.equal(knowledgeStateOf({ knowledge: { state: "needs_configuration", outcome: "postgres_index_unavailable" } }).outcome, "postgres_index_unavailable");
  assert.equal(knowledgeStateOf({ knowledge: { state: "needs_configuration", outcome: "<script>" } }).outcome, null, "only a closed code is shown");
  for (const listing of [{}, null, { knowledge: { state: "sort of" } }, { knowledge: { state: "toString" } }]) {
    assert.equal(knowledgeStateOf(listing).state, "not_reported", JSON.stringify(listing));
  }
});

test("rendered L2: the panel shows the Knowledge state only when it is not ready, with Enable Knowledge; it reads a 503 answer", async () => {
  const ready = await mountPanel({ connectors: [connector()], may_author: true, knowledge: { state: "ready", outcome: "existing", checked_at: "2026-10-05T10:00:00" } });
  assert.equal(byTestId(ready.view, "connector-knowledge-state").length, 0, "ready shows no 'Knowledge enabled · Checked …' pill");
  assert.doesNotMatch(text(ready.view.root), /Knowledge enabled|Checked /);
  assert.equal(enableButtons(ready.view).length, 0);
  act(() => ready.view.unmount());

  const reader = await mountPanel({ connectors: [connector()], may_author: false, knowledge: { state: "unknown", outcome: null, checked_at: null } });
  assert.equal(byTestId(reader.view, "connector-knowledge-state")[0].props["data-state"], "not_recorded");
  assert.match(text(byTestId(reader.view, "connector-knowledge-state")[0]), /Knowledge not enabled/);
  assert.equal(enableButtons(reader.view).length, 0, "readers cannot enable");
  assert.match(text(byTestId(reader.view, "connector-knowledge-state")[0]), /A Workspace admin or owner can enable it\./);
  act(() => reader.view.unmount());

  const author = await mountPanel({ connectors: [connector()], may_author: true, knowledge: { state: "unknown", outcome: null, checked_at: null } },
    { enableAnswer: { status: 503, body: { workspace_id: "ws-1", state: "needs_configuration", outcome: "postgres_index_unavailable" } } });
  await act(async () => { enableButtons(author.view)[0].props.onClick(); });
  assert.deepEqual(author.calls.filter((call) => call.method === "POST").map((call) => call.url), ["/api/v1/workspaces/ws-1/knowledge/enable"]);
  const [note] = byTestId(author.view, "connector-knowledge-state");
  assert.equal(note.props["data-state"], "needs_configuration");
  assert.match(text(note), /needs configuration by an operator.*postgres_index_unavailable/);
  assert.equal(enableButtons(author.view).length, 1, "still not ready: the retry stays");
  act(() => author.view.unmount());

  const older = await mountPanel({ connectors: [], may_author: true });
  assert.equal(byTestId(older.view, "connector-knowledge-state").length, 0, "an answer without connectors shows nothing");
  act(() => older.view.unmount());
});

test("rendered L1: the table's schedule cell reads next_run_at as UTC", async () => {
  const { ScheduleCell } = load("admin/components/workspaceKnowledge/KnowledgeConnectorCells.tsx");
  const future = new Date(Date.now() + 30 * 60 * 1000).toISOString().replace(/\.\d+Z$/, "");
  let view;
  act(() => { view = TestRenderer.create(createElement(ScheduleCell, { connector: connector({ schedule: { enabled: true, interval_minutes: 15, next_run_at: future } }) })); });
  assert.match(text(view.root.findByProps({ className: "admin-panel__muted" })), /^next due /, "30 min ahead in UTC is not due, also in CEST");
  act(() => view.update(createElement(ScheduleCell, { connector: connector({ schedule: { enabled: true, interval_minutes: 15, next_run_at: "later" } }) })));
  assert.equal(text(view.root.findByProps({ className: "admin-panel__muted" })), "next run time not readable");
  act(() => view.unmount());
});
