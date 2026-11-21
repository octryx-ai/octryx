// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgeSources.test.mjs
//
// Knowledge › Sources: one table row per source
// with one state word (Syncing, Up to
// date, Needs attention, Paused, Never synced), a reason only when needed, what it reads, the items it serves, the
// last sync and the cadence. A launcher snapshot completes passes without a sync run, so "Never run" next to
// "3 full passes" must not appear; the last sync is read from the run and the cursor alike. A source that
// nothing keeps current is "Out of date" after STALE_AFTER_DAYS, with its age, and the page has no instance-wide
// "automatic sync is off" line. Requests are stubs; "now" is fixed.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import {
  lastSyncAt, servedItemsText, sourceCadence, sourceContainer, sourceName, sourceState,
} from "../../src/admin/components/workspaceKnowledge/sources/sourceState.ts";
import { STALE_AFTER_DAYS, syncAgeText, syncIsStale } from "../../src/admin/components/workspaceKnowledge/connectorFreshness.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
// The review's day: the snapshot below last synced 31 days earlier, the Jira source 5 days earlier.
const NOW = Date.parse("2026-11-06T21:00:00Z");
const DAY = 24 * 60 * 60 * 1000;

const base = (over = {}) => ({
  connector_key: "jira-shop", kind: "jira", state: "active", running: false, products: [], version: null,
  max_items_per_run: 100, scope: { project_keys: ["ORDERS"] }, schedule: { enabled: true, interval_minutes: 15, next_run_at: null },
  cursor: { pass_number: 3, token: null, pass_started_at: null, completed_passes: 2, last_completed_at: "2026-11-01T09:00:00Z" },
  last_run: { id: "r1", state: "completed", reason: null, report: { created: 1 }, started_at: "2026-11-01T09:58:00Z", finished_at: "2026-11-01T10:00:00Z" },
  served_items: 930, ...over,
});

// The snapshot of the m4 finding: three full passes by launcher upload, no sync run.
const SNAPSHOT = base({
  connector_key: "repo-acme-orders", kind: "git_repository", display_label: "acme-orders-server (main, 7b338db)",
  scope: { fetch_mode: "local_snapshot", remote: "https://bitbucket.org/acme/acme-orders-server.git" },
  schedule: { enabled: false, interval_minutes: 360, next_run_at: null },
  cursor: { pass_number: 4, token: null, pass_started_at: null, completed_passes: 3, last_completed_at: "2026-10-06T20:28:00Z" },
  last_run: null, served_items: 1,
});

test("'Up to date' only while a schedule keeps the source current; manual sources say when they synced (review)", () => {
  const manual = base({ schedule: { enabled: false, interval_minutes: 15, next_run_at: null } });
  assert.equal(sourceState(manual, false, true, NOW).word, "Synced");
  assert.equal(sourceCadence(manual), "manual");
  assert.equal(sourceState(base(), false, false, NOW).word, "Synced", "the instance runs no schedules");
  assert.equal(sourceState(base(), false, true, NOW).word, "Up to date");
});

test("A source nothing keeps current is 'Out of date' after the Problems threshold, and says how old it is", () => {
  const synced = Date.parse("2026-11-01T10:00:00Z");
  assert.equal(STALE_AFTER_DAYS, 14, "the same threshold as the Problems page's stale finding");
  assert.equal(syncIsStale(synced, synced + STALE_AFTER_DAYS * DAY), false, "exactly the threshold is not yet stale");
  assert.equal(syncIsStale(synced, synced + STALE_AFTER_DAYS * DAY + 1), true);
  assert.equal(syncIsStale(null, NOW), false, "never synced is its own state");
  assert.deepEqual([syncAgeText(NOW - 3600_000, NOW), syncAgeText(NOW - DAY, NOW), syncAgeText(NOW - 31 * DAY, NOW)],
    ["Synced today", "Synced 1 day ago", "Synced 31 days ago"]);

  const later = synced + 31 * DAY;
  const manual = sourceState(base({ schedule: { enabled: false, interval_minutes: 15, next_run_at: null } }), false, true, later);
  assert.deepEqual([manual.word, manual.tone, manual.reason], ["Out of date", "warning", "Synced 31 days ago. It has no schedule, so only Sync now syncs it."]);
  const off = sourceState(base(), false, false, later);
  assert.deepEqual([off.word, off.reason], ["Out of date", "Synced 31 days ago. Automatic sync is off on this instance, so only Sync now syncs it."],
    "the instance switch is said at the source it affects, not as a page-wide line");
  assert.equal(sourceState(base(), false, true, later).word, "Up to date", "a running schedule keeps it current; Problems reports an overdue one");
  assert.equal(sourceState(base({ state: "paused" }), false, true, later).word, "Paused");
  assert.equal(sourceState(base({ last_run: { ...base().last_run, state: "failed", reason: "source_unavailable" } }), false, false, later).word,
    "Needs attention", "a failure is reported first");
});

test("one state per source, in a fixed order of precedence", () => {
  assert.equal(sourceState(base()).word, "Up to date");
  assert.equal(sourceState(base({ running: true })).word, "Syncing");
  assert.equal(sourceState(base(), true).word, "Syncing", "a sync started from this page");
  assert.equal(sourceState(base({ state: "paused" })).word, "Paused");
  const failed = sourceState(base({ last_run: { ...base().last_run, state: "failed", reason: "source_unauthorized" } }));
  assert.deepEqual([failed.word, failed.reason], ["Needs attention", "The source system rejected the connection's credential."]);
  const partial = sourceState(base({ last_run: { ...base().last_run, report: { created: 3, failed: 2 } } }));
  assert.equal(partial.word, "Needs attention");
  assert.match(partial.reason, /^The run completed with 2 failed issues/);
  const never = sourceState(base({ last_run: null, cursor: { pass_number: 0, pass_started_at: null, completed_passes: 0, last_completed_at: null } }));
  assert.deepEqual([never.word, never.reason, never.lastSyncAt], ["Never synced", null, null]);
  const open = sourceState(base({ cursor: { ...base().cursor, pass_started_at: "2026-11-06T10:00:00Z" } }));
  assert.deepEqual([open.word, open.reason], ["Syncing", "Continues with the next sync."]);
  assert.equal(sourceState(base()).reason, null, "no reason when nothing needs one");
});

test("m4: a snapshot without sync runs has synced, and its last pass is its last sync", () => {
  const state = sourceState(SNAPSHOT, false, true, Date.parse("2026-10-08T12:00:00Z"));
  assert.equal(state.word, "Synced", "fed by uploads, nothing keeps it current: it says when, not 'Up to date'");
  const month = sourceState(SNAPSHOT, false, true, NOW);
  assert.deepEqual([month.word, month.reason], ["Out of date", "Synced 31 days ago. Only a new upload by the launcher updates it."],
    "not 'Synced' a month later");
  assert.equal(state.lastSyncAt, Date.parse("2026-10-06T20:28:00Z"));
  assert.equal(sourceCadence(SNAPSHOT), "uploaded by the launcher");
  assert.equal(sourceName(SNAPSHOT), "acme-orders-server (main, 7b338db)");
  assert.equal(servedItemsText(SNAPSHOT), "1 file");
});

test("the last sync is the latest of run, clean pass and closed pass; naive server times are UTC", () => {
  assert.equal(lastSyncAt(base()), Date.parse("2026-11-01T10:00:00Z"));
  assert.equal(lastSyncAt(base({ cursor: { ...base().cursor, last_pass_closed_at: "2026-11-01T11:00:00" } })), Date.parse("2026-11-01T11:00:00Z"));
  assert.equal(lastSyncAt(base({ last_run: null, cursor: { pass_number: 0, completed_passes: 0, last_completed_at: null } })), null);
});

test("what it reads, what it serves and how it syncs, each on one line", () => {
  assert.equal(sourceContainer(base()), "ORDERS");
  assert.equal(sourceContainer(base({ kind: "confluence", scope: { spaces: ["TEAM", "DOC17"], page_trees: [{ space_key: "TEAM", root_page_id: "1" }] } })),
    "TEAM, DOC17 · 1 page tree");
  assert.equal(sourceContainer(base({ kind: "servicenow", scope: { knowledge_bases: ["a", "b"], tables: ["incident", "change"] } })),
    "2 knowledge bases · incident, change");
  assert.equal(servedItemsText(base()), "930 issues");
  assert.equal(servedItemsText(base({ served_items: undefined })), null, "no count reported");
  assert.equal(sourceCadence(base()), "every 15 min");
  assert.equal(sourceCadence(base({ schedule: { enabled: false, interval_minutes: 60, next_run_at: null } })), "manual");
});

// Date inside the mounted modules, with Date.now() fixed at `now`.
function fixedDate(now) {
  return class extends Date {
    constructor(...args) { super(...(args.length ? args : [now])); }
    static now() { return now; }
  };
}

function loader(extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Intl, ...extra,
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
  return (relative) => loadFile(path.join(SRC, relative));
}

async function mount(listing, { focused = [], now = NOW } = {}) {
  const fetch = async (url) => ({
    ok: true, status: 200,
    json: async () => {
      const key = String(url).match(/connectors\/([^/]+)\/runs\/last$/)?.[1];
      return key ? { connector_key: key, run: listing.connectors.find((item) => item.connector_key === key)?.last_run ?? null } : listing;
    },
  });
  const events = { addEventListener() {}, removeEventListener() {} };
  const load = loader({ fetch, document: events, window: { ...events, confirm: () => false, innerWidth: 1400 }, Date: fixedDate(now) });
  const { AdminNavigationContext } = load("admin/adminNavigation.ts");
  const { KnowledgeConnectorsPanel } = load("admin/components/workspaceKnowledge/KnowledgeConnectorsPanel.tsx");
  const opened = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(AdminNavigationContext.Provider, { value: { openAdminTab: (tab) => opened.push(tab) } },
      createElement(KnowledgeConnectorsPanel, { workspaceId: "ws-1" })), {
      createNodeMock: (element) => ({ focus: () => focused.push(element.props["data-testid"] ?? element.type), querySelectorAll: () => [] }),
    });
  });
  await act(async () => {});
  return { view, opened };
}

const cell = (row, column) => row.findAll((node) => node.type === "td")[column];

test("rendered: one table row per source with kind, reads, items, last sync and state; no 'Never run' next to passes; S1: a month-old snapshot is out of date", async () => {
  const { view, opened } = await mount({ connectors: [base(), SNAPSHOT], may_author: true, knowledge: { state: "ready" }, instance_scheduler_enabled: false });
  const table = byTestId(view, "sources-table")[0];
  assert.deepEqual(table.findAll((node) => node.type === "th").map(text), ["Source", "Kind", "Reads", "Items", "Last sync", "State", "Actions"]);
  const rows = table.findAll((node) => node.type === "tr" && node.props["data-row-key"]);
  assert.deepEqual(rows.map((row) => row.props["data-row-key"]), ["jira-shop", "repo-acme-orders", "__uploads"]);
  const labels = byTestId(view, "knowledge-source-state");
  assert.deepEqual(labels.map(text), ["Synced", "Out of date"], "the instance runs no schedules: not 'Up to date'; 31 days: not 'Synced'");
  assert.deepEqual(labels.map((node) => node.props["data-tone"]), ["neutral", "attention"]);
  assert.equal(labels[1].props.title, "Synced 31 days ago. Only a new upload by the launcher updates it.");
  assert.match(text(cell(rows[0], 4)), /^.+ · every 15 min$/);
  assert.match(text(cell(rows[1], 4)), /^.+ · uploaded by the launcher$/);
  assert.equal(text(cell(rows[1], 3)), "1 file");
  for (const row of rows) assert.doesNotMatch(text(row), /Never run|full pass|not synced/, "m4: a row never contradicts itself");
  assert.equal(byTestId(view, "sources-scheduler-off").length, 0, "no page-wide line; the source and Problems say it");
  assert.doesNotMatch(text(view.root), /Automatic sync is off on this instance\. An admin can switch it on\./);
  assert.equal(byTestId(view, "connector-knowledge-state").length, 0, "ready Knowledge shows no pill");
  assert.doesNotMatch(text(view.root), /Knowledge enabled|Checked /);
  const primaries = view.root.findAll((node) => node.type === "button" && /--primary/.test(node.props.className ?? ""));
  assert.deepEqual(primaries.map(text), ["Add source"], "one primary action on the page");
  assert.equal(byTestId(view, "source-panel").length, 0, "a source opens on demand");
  assert.equal(text(cell(rows[2], 1)), "Upload");
  act(() => rows[2].props.onClick());
  assert.deepEqual(opened, ["knowledgeSources"], "the uploads row opens Documents");
  act(() => view.unmount());
});

test("rendered: Up to date only while a schedule runs; Paused and Never synced are plain words", async () => {
  const paused = base({ connector_key: "paused-one", state: "paused" });
  const never = base({ connector_key: "new-one", last_run: null, cursor: { pass_number: 0, token: null, pass_started_at: null, completed_passes: 0, last_completed_at: null } });
  const { view } = await mount({ connectors: [base(), paused, never], may_author: true, knowledge: { state: "ready" }, instance_scheduler_enabled: true });
  const labels = byTestId(view, "knowledge-source-state");
  assert.deepEqual(labels.map(text), ["Up to date", "Paused", "Never synced"]);
  assert.deepEqual(labels.map((node) => node.props["data-tone"]), ["neutral", "neutral", "neutral"], "colour only for exceptions");
  act(() => view.unmount());
});

test("rendered: a source that needs attention has its reason as tooltip; its panel shows why and its setup", async () => {
  const failing = base({ last_run: { ...base().last_run, state: "failed", reason: "source_unavailable" } });
  const focused = [];
  const { view } = await mount({ connectors: [failing], may_author: true, knowledge: { state: "ready" } }, { focused });
  const label = byTestId(view, "knowledge-source-state")[0];
  assert.equal(text(label), "Needs attention");
  assert.equal(label.props["data-tone"], "attention");
  assert.equal(label.props.title, "The source system is unavailable.");
  assert.equal(byTestId(view, "sources-scheduler-off").length, 0, "nothing said when the server does not report it");
  const row = view.root.find((node) => node.type === "tr" && node.props["data-row-key"] === "jira-shop");
  await act(async () => row.props.onClick());
  const panel = byTestId(view, "source-panel")[0];
  assert.equal(panel.props.role, "dialog");
  assert.ok(focused.includes("source-panel"), "focus moves into the panel");
  assert.equal(text(byTestId(view, "knowledge-source-reason")[0]), "The source system is unavailable.");
  assert.match(byTestId(view, "source-panel-open-page")[0].props.href, /source=jira-shop&source_view=page$/);
  const tab = (label) => panel.find((node) => node.props.role === "tab" && text(node) === label);
  act(() => tab("Setup").props.onClick());
  const setup = byTestId(view, "source-setup")[0];
  // The panel title names the source; the tab repeats no raw key as a heading.
  assert.match(text(setup), /^Reads/);
  assert.doesNotMatch(text(panel), /Setup of|Last run of|Freshness of/);
  assert.match(text(setup), /at most 100 items/);
  act(() => byTestId(view, "source-panel-close")[0].props.onClick());
  assert.equal(byTestId(view, "source-panel").length, 0);
  act(() => view.unmount());
});

test("rendered: Add source opens the form in the side panel with focus, not at the bottom of the page", async () => {
  const focused = [];
  const { view } = await mount({ connectors: [base()], may_author: true, knowledge: { state: "ready" } }, { focused });
  const add = byTestId(view, "sources-add")[0];
  act(() => add.props.onClick());
  const panel = byTestId(view, "source-form-panel")[0];
  assert.ok(panel.findByType("form"));
  assert.ok(focused.includes("source-form-panel"));
  assert.equal(byTestId(view, "knowledge-first-source").length, 0, "the connect-first line only for the first source");
  act(() => view.unmount());
});
