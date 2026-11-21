// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgeConnectorFreshness.test.mjs
//
// Confluence Cloud knowledge freshness, frontend: the selected connector shows its last run (time, outcome,
// new/changed/removed/withheld), its next scheduled run and whether this instance runs schedules at all, read
// truthfully from the listing (and "not reported" when the listing does not say); withheld restricted pages are explained;
// the schedule is chosen from presets (15 min / 1 h / 6 h / daily, other stored values stay custom); a pasted
// Confluence page address is refused with the space key it belongs to, never rewritten silently.
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
import {
  instanceSchedulerState,
  nextRunText,
  pageCountsText,
  runPageCounts,
  withheldText,
} from "../../src/admin/components/workspaceKnowledge/connectorFreshness.ts";
import {
  initialForm,
  schedulePresetOf,
  spaceKeyFromUrl,
  validate,
} from "../../src/admin/components/workspaceKnowledge/connectorFormModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const NOW = Date.parse("2026-10-04T12:00:00Z");

const connector = (overrides = {}) => ({
  connector_key: "demo", kind: "confluence", scope: { spaces: ["DEMO"] }, products: [], version: null,
  max_items_per_run: 100, state: "active",
  cursor: { pass_number: 1, token: null, pass_started_at: null, last_completed_at: null, completed_passes: 1 },
  schedule: { enabled: true, interval_minutes: 60, next_run_at: "2026-10-04T13:00:00Z" },
  running: false,
  last_run: {
    id: "run-1", state: "completed", reason: null, started_at: "2026-10-04T11:00:00Z", finished_at: "2026-10-04T11:01:00Z",
    report: { created: 3, updated: 1, unchanged: 4, retired: 1, skipped: 2, failed: 0, listed: 9, skipped_reasons: { restricted_acl: 2 } },
  },
  ...overrides,
});

// ---- model ------------------------------------------------------------------------------------

test("the instance switch is read from the server, connector first, else the listing; never guessed", () => {
  assert.equal(instanceSchedulerState({ instance_scheduler_enabled: true }), "on");
  assert.equal(instanceSchedulerState({ instance_scheduler_enabled: false }), "off");
  for (const listing of [null, {}, { instance_scheduler_enabled: "true" }, { instance_scheduler_enabled: 1 }]) {
    assert.equal(instanceSchedulerState(listing), "unknown", JSON.stringify(listing));
  }
  const own = connector({ schedule: { enabled: true, interval_minutes: 60, next_run_at: null, instance_enabled: false } });
  assert.equal(instanceSchedulerState({ instance_scheduler_enabled: true }, own), "off", "the connector's own report wins");
});

test("run counts map to new/changed/removed/withheld; a dedicated withheld count wins over the skip reason", () => {
  assert.deepEqual(runPageCounts(connector().last_run.report), { new: 3, changed: 1, removed: 1, withheld: 2 });
  assert.deepEqual(runPageCounts({ created: 1, withheld: 5, skipped_reasons: { restricted_acl: 2 } }).withheld, 5);
  assert.deepEqual(runPageCounts({ withheld: 0, skipped_reasons: { restricted_acl: 2 } }).withheld, 0, "an explicit 0 is not replaced");
  assert.deepEqual(runPageCounts({ skipped: 4, skipped_reasons: { excluded: 4 } }).withheld, 0, "other skips are not withheld");
  assert.deepEqual(runPageCounts(null), { new: 0, changed: 0, removed: 0, withheld: 0 });
  assert.deepEqual(runPageCounts({ created: -1, updated: "3", retired: Number.NaN }), { new: 0, changed: 0, removed: 0, withheld: 0 });
  assert.equal(pageCountsText("confluence", runPageCounts(connector().last_run.report)), "pages: 3 new · 1 changed · 1 removed · 2 withheld");
  assert.match(pageCountsText("jira", runPageCounts({})), /^issues: 0 new/);
});

test("withheld pages are explained; none withheld says nothing", () => {
  // F3 changed the input to the run report; the unmatched-principals text is unchanged.
  const unmatched = (withheld) => ({ withheld, withheld_reasons: { acl_unresolved: withheld }, acl_enforced: true });
  assert.equal(withheldText("confluence", { withheld: 0 }), null);
  assert.match(withheldText("confluence", unmatched(1)), /^1 restricted page not indexed: it is restricted in Confluence/);
  assert.match(withheldText("confluence", unmatched(3)), /^3 restricted pages not indexed: they are restricted in Confluence to people this Workspace cannot match/);
  assert.match(withheldText("jira", unmatched(2)), /^2 restricted issues not indexed/);
});

test("the next run states the schedule, the pause and the instance switch truthfully", () => {
  assert.equal(nextRunText(connector(), "on", NOW), `Every 1 h; next run ${formatDateTime("2026-10-04T13:00:00Z")}.`);
  assert.equal(nextRunText(connector({ schedule: { enabled: true, interval_minutes: 15, next_run_at: "2026-10-04T11:00:00Z" } }), "on", NOW),
    "Every 15 min; next run due now.");
  assert.match(nextRunText(connector(), "off", NOW), /^Every 1 h is set, but scheduled runs are switched off for this instance/);
  assert.doesNotMatch(nextRunText(connector(), "unknown", NOW), /does not report|OCTRYX_/);
  assert.match(nextRunText(connector({ state: "paused" }), "on", NOW), /^No scheduled syncs while the source is paused/);
  assert.match(nextRunText(connector({ schedule: { enabled: false, interval_minutes: 60, next_run_at: null } }), "on", NOW), /^Not scheduled: it syncs only when someone uses Sync now/);
  assert.match(nextRunText(connector({ schedule: undefined }), "on", NOW), /^Not scheduled/, "a connector without a schedule block reads as off");
});

test("schedule presets and the Cloud space key in a pasted address", () => {
  assert.deepEqual(["15", "60", "360", "1440", "90", "abc"].map(schedulePresetOf), ["15", "60", "360", "1440", "custom", "custom"]);
  assert.equal(spaceKeyFromUrl("https://acme.atlassian.net/wiki/spaces/DEMO/pages/123/Title"), "DEMO");
  assert.equal(spaceKeyFromUrl("https://wiki.acme.test/spaces/~jdoe/overview"), "~jdoe");
  assert.equal(spaceKeyFromUrl("DEMO"), null);
  assert.equal(spaceKeyFromUrl("https://acme.atlassian.net/wiki/home"), null);
  const form = { ...initialForm(null), key: "team-wiki", keys: "https://acme.atlassian.net/wiki/spaces/DEMO/pages/123" };
  assert.match(validate(form).problem, /is a page address, not a space key\. Its space key is DEMO: enter DEMO\./);
  assert.deepEqual(validate({ ...form, keys: "DEMO" }).config.spaces, ["DEMO"], "nothing is rewritten: the key itself is accepted");
});

// ---- rendered ---------------------------------------------------------------------------------

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
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, ...extra,
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

test("rendered: the freshness block shows the last run, the next run, the instance switch and the withheld note", () => {
  const { KnowledgeConnectorFreshness } = load("admin/components/workspaceKnowledge/KnowledgeConnectorFreshness.tsx");
  let view;
  act(() => { view = TestRenderer.create(createElement(KnowledgeConnectorFreshness, { connector: connector(), instance: "off" })); });
  const part = (id) => view.root.find((node) => node.props["data-testid"] === id);
  assert.match(text(part("freshness-last-run")), /^pages: 3 new · 1 changed · 1 removed · 2 withheld/);
  assert.match(text(part("freshness-next-run")), /switched off for this instance/);
  assert.equal(part("freshness-instance").props["data-instance"], "off");
  assert.match(text(part("freshness-withheld")), /^2 restricted pages not indexed/);
  act(() => view.update(createElement(KnowledgeConnectorFreshness, { connector: connector({ last_run: null, running: true }), instance: "unknown" })));
  assert.match(text(part("freshness-last-run")), /^Not run yet\. A run is in progress\./);
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "freshness-withheld").length, 0);
  act(() => view.unmount());
});

async function mountPanel(listing) {
  const calls = [];
  const fetch = async (url) => {
    calls.push(String(url));
    const body = String(url).endsWith("/runs/last") ? { connector_key: "demo", run: { ...connector().last_run, outcomes: [] } } : listing;
    return { ok: true, status: 200, json: async () => body };
  };
  const { KnowledgeConnectorsPanel } = load("admin/components/workspaceKnowledge/KnowledgeConnectorsPanel.tsx", { fetch, window: { confirm: () => false } });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(KnowledgeConnectorsPanel, { workspaceId: "ws-1" })); });
  return { view, calls };
}

test("rendered panel: the instance switch comes from the listing, and the form's hint says the same", async () => {
  for (const [listed, expected, hint] of [
    // The form only says the state that changes what a schedule does; the rest is in the page help.
    [false, "off", /Automatic sync is off on this instance/],
    [true, "on", null],
    [undefined, "unknown", null],
  ]) {
    const listing = { connectors: [connector()], may_author: true, ...(listed === undefined ? {} : { instance_scheduler_enabled: listed }) };
    const { view } = await mountPanel(listing);
    // A source opens on demand in its side panel; the freshness is its own tab there.
    const row = view.root.find((node) => node.type === "tr" && node.props["data-row-key"] === "demo");
    await act(async () => { row.props.onClick(); });
    act(() => view.root.find((node) => node.props.role === "tab" && text(node) === "Freshness").props.onClick());
    const instance = view.root.findAll((node) => node.props["data-testid"] === "freshness-instance");
    if (expected === "unknown") assert.equal(instance.length, 0, "an unreported switch shows no row");
    else assert.equal(instance[0].props["data-instance"], expected);
    assert.equal(view.root.findAll((node) => node.props["data-testid"] === "schedule-instance-hint").length, 0,
      "the source form opens only on Add source");
    act(() => view.root.find((node) => node.props["data-testid"] === "source-panel-close").props.onClick());
    const add = view.root.findAll((node) => node.type === "button" && text(node) === "Add source")[0];
    await act(async () => { add.props.onClick(); });
    const shown = view.root.findAll((node) => node.props["data-testid"] === "schedule-instance-hint");
    if (hint) assert.match(text(shown[0]), hint);
    else assert.equal(shown.length, 0, `no hint when the switch is ${expected}`);
    act(() => view.unmount());
  }
});

test("rendered form: presets set the interval; a stored non-preset interval stays custom and editable", async () => {
  const { KnowledgeConnectorForm } = load("admin/components/workspaceKnowledge/KnowledgeConnectorForm.tsx");
  const saved = [];
  const onSave = async (key, config) => { saved.push(config); return true; };
  let view;
  const editing = connector({ schedule: { enabled: true, interval_minutes: 90, next_run_at: null } });
  act(() => { view = TestRenderer.create(createElement(KnowledgeConnectorForm, { editing, busy: false, onSave, onCancel: () => {}, instance: "on" })); });
  const select = () => view.root.find((node) => node.type === "select" && node.props["aria-label"] === "Schedule interval");
  const minutes = () => view.root.findAll((node) => node.type === "input" && node.props["aria-label"] === "Schedule interval in minutes");
  assert.deepEqual(select().findAllByType("option").map(text), ["Every 15 minutes", "Every hour", "Every 6 hours", "Daily", "Custom interval…"]);
  assert.equal(select().props.value, "custom");
  assert.equal(minutes()[0].props.value, "90", "kept as stored, never rounded to a preset");
  act(() => select().props.onChange({ target: { value: "1440" } }));
  assert.equal(minutes().length, 0, "a preset needs no minutes field");
  await act(async () => { await view.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
  assert.deepEqual([saved[0].schedule_enabled, saved[0].schedule_interval_minutes], [true, 1440]);
  act(() => select().props.onChange({ target: { value: "custom" } }));
  assert.equal(minutes().length, 1, "choosing custom shows the minutes field");
  act(() => view.unmount());
});

test("rendered scope: the Confluence space key help names the key of a pasted page address", () => {
  const { KnowledgeConnectorScopeFields } = load("admin/components/workspaceKnowledge/KnowledgeConnectorScopeFields.tsx");
  const render = (keys, kind = "confluence") => {
    let view;
    act(() => { view = TestRenderer.create(createElement(KnowledgeConnectorScopeFields, { form: { ...initialForm(null), kind, keys }, set: () => {} })); });
    const help = view.root.findAll((node) => node.props["data-testid"] === "space-key-help").map(text)[0] ?? null;
    act(() => view.unmount());
    return help;
  };
  assert.equal(render(""), null, "where a key comes from is in the page help, not in the form");
  assert.match(render("https://acme.atlassian.net/wiki/spaces/DEMO/pages/1"), /The pasted address belongs to the space DEMO; enter that key instead\./);
  assert.equal(render("DEMO"), null);
  assert.equal(render("PLAT", "jira"), null, "Jira keeps its own fields");
});
