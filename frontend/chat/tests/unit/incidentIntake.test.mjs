// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/incidentIntake.test.mjs
//
// ServiceNow intake, incident analysis and write-back UI.
// Work board: ServiceNow items carry a ServiceNow badge, number and link; a filter by source; "Start analysis" with its
// state and the analysis rendered with citations; "Send as work note" disabled with its reason while write-back is
// off, and only after an explicit confirmation when it is on. Settings: the ServiceNow intake card (tables, open-state
// filter, mapping, schedule, preview, sync now) and the analysis options (auto-analyze, ask the Jira reporter).
// Requests are stubs; fixtures use neutral `.test` names only.
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
  isServiceNowItem,
  serviceNowSourceView,
  sourceFilterOptions,
  sourceLabel,
  sourceMatches,
} from "../../src/chat/work/incident/workSourceModel.ts";
import {
  analysisInProgress,
  analysisStateText,
  analyzeRefusalText,
  citationOf,
  latestAnalysisNote,
  readAnalysis,
  readAnalysisView,
  readWorknotePreview,
  reasonText,
  worknoteRefusalText,
} from "../../src/chat/work/incident/incidentAnalysisModel.ts";
import {
  analysisSettingsError,
  analysisSettingsPayload,
  intakeErrorText,
  readAnalysisSettings,
} from "../../src/chat/work/incident/incidentSettingsModel.ts";
import { EMPTY_WORK_FILTERS, filterWorkItems } from "../../src/chat/work/workUtils.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (root, id) => root.findAll((node) => node.props && node.props["data-testid"] === id);
const json = (value) => JSON.parse(JSON.stringify(value));

const SN_ITEM = {
  id: "wi-sn-1", project_id: "ws-1", source_type: "servicenow", source_instance: "servicenow.test", source_key: "INC0000001",
  source_url: "https://servicenow.test/nav_to.do?uri=incident.do?sys_id=abc", title: "Login fails", description: "Users cannot log in.",
  source_status: "In Progress", priority: "2 - High", assignee: "", work_state: "development", sync_state: "unchanged",
  source_created_at: "2026-10-06T08:00:00Z",
  source_fields: { table: "incident", assignment_group: { display_value: "Service Desk", value: "sys-1" }, assigned_to: "Ada Admin" },
};
const JIRA_ITEM = { ...SN_ITEM, id: "wi-j-1", source_type: "jira", source_key: "BRD-1", source_url: "https://jira.test/browse/BRD-1", source_fields: {} };

// The backend's structured analysis (work_item_analysis/contract.py, after check_citations).
const ANALYSIS = {
  summary: "The login service rejects tokens after the certificate rotation.",
  impact: "All users of the portal.",
  likely_cause: { text: "Expired intermediate certificate", confidence: "medium" },
  affected_components: ["login-service", "gateway"],
  evidence: [
    { claim: "The manual requires the full chain.", source: { kind: "manual", title: "Gateway manual", locator: "p. 12", url: "https://docs.test/gw.pdf#page=12" }, verified: true },
    { claim: "The Helm values pin the old chain.", source: { kind: "repository", title: "platform", locator: "helm/values.yaml:10-14", url: null }, verified: true },
    { claim: "A similar outage was fixed before.", source: { kind: "ticket", title: "INC0000000", locator: "Cert rotation", url: "javascript:alert(1)" }, verified: false },
    { claim: "", source: { kind: "manual", title: "x", locator: "y" } },
    "not an object",
  ],
  similar_tickets: [{ key: "INC0000000", url: "https://servicenow.test/x", why: "Same certificate rotation", verified: true }, { why: "no key" }],
  next_steps: ["Renew the chain", "Restart the gateway"],
  open_questions: ["Since when does it fail?"],
};
// The backend's analysis view (work_item_analysis/runner.analysis_view).
const VIEW = (overrides = {}) => ({
  id: "an-1", work_item_id: "wi-sn-1", status: "succeeded", error_code: null, mode: "manual", reused: false,
  created_at: "2026-10-06T09:00:00Z", finished_at: "2026-10-06T09:01:00Z", analysis: ANALYSIS, ...overrides,
});
// The work-note preview (secure_work/servicenow/worknote.send_worknote without confirm).
const WORKNOTE_PREVIEW = { state: "needs_confirmation", preview: { mode: "table_api", table: "incident", number: "INC0000001", text: "Likely cause: the certificate chain." } };
const DISABLED = { status: 409, body: { detail: { state: "disabled", code: "servicenow_worknote_disabled", message: "Work notes to ServiceNow are off." } } };

// ---- source --------------------------------------------------------------------------------------

test("sources: labels, filter options and matching; an empty source type is a Jira item", () => {
  assert.equal(sourceLabel("servicenow"), "ServiceNow");
  assert.equal(sourceLabel("JIRA"), "Jira");
  assert.equal(sourceLabel(""), "Jira");
  assert.equal(sourceLabel("github"), "github");
  assert.equal(isServiceNowItem(SN_ITEM), true);
  assert.equal(isServiceNowItem(JIRA_ITEM), false);
  assert.deepEqual(json(sourceFilterOptions([SN_ITEM, JIRA_ITEM, { source_type: "" }])), {
    values: ["jira", "servicenow"], labels: { jira: "Jira", servicenow: "ServiceNow" },
  });
  assert.equal(sourceMatches({ source_type: "" }, "jira"), true);
  assert.equal(sourceMatches(SN_ITEM, "jira"), false);
  assert.equal(sourceMatches(SN_ITEM, ""), true);
  const filtered = filterWorkItems([SN_ITEM, JIRA_ITEM], { ...EMPTY_WORK_FILTERS, sourceType: "servicenow" });
  assert.deepEqual(filtered.map((item) => item.id), ["wi-sn-1"]);
  assert.equal(filterWorkItems([SN_ITEM, JIRA_ITEM], EMPTY_WORK_FILTERS).length, 2);
});

test("the ServiceNow fields are read from the item and source_fields, display values included; unsafe links dropped", () => {
  assert.deepEqual(json(serviceNowSourceView(SN_ITEM)), {
    number: "INC0000001", table: "Incident", state: "In Progress", priority: "2 - High", assignmentGroup: "Service Desk",
    assignedTo: "Ada Admin", openedAt: "2026-10-06T08:00:00Z", url: "https://servicenow.test/nav_to.do?uri=incident.do?sys_id=abc",
  });
  const sparse = serviceNowSourceView({ ...SN_ITEM, source_url: "javascript:x", source_status: "", priority: "", source_created_at: null,
    assignee_display: "Bea", source_fields: { sys_class_name: "change_request", state: "New", priority: "3", opened_at: "2026-10-01T00:00:00Z" } });
  assert.deepEqual([sparse.table, sparse.state, sparse.priority, sparse.assignedTo, sparse.openedAt, sparse.url],
    ["Change request", "New", "3", "Bea", "2026-10-01T00:00:00Z", null]);
  assert.equal(serviceNowSourceView({ ...SN_ITEM, source_fields: { table: "problem" } }).table, "problem");
});

// ---- analysis model ------------------------------------------------------------------------------

test("the analysis is read with its citations; unsafe links dropped; unconfirmed citations marked", () => {
  const analysis = readAnalysis(ANALYSIS);
  assert.deepEqual(json(analysis.evidence), [
    { text: "The manual requires the full chain.", citation: { label: "Gateway manual, p. 12", url: "https://docs.test/gw.pdf#page=12", verified: true } },
    { text: "The Helm values pin the old chain.", citation: { label: "platform, helm/values.yaml:10-14", url: null, verified: true } },
    { text: "A similar outage was fixed before.", citation: { label: "INC0000000, Cert rotation", url: null, verified: false } },
  ]);
  assert.deepEqual([analysis.likelyCause, analysis.confidence], ["Expired intermediate certificate", "medium"]);
  assert.deepEqual(json(analysis.similarTickets), [{ number: "INC0000000", title: "Same certificate rotation", url: "https://servicenow.test/x", verified: true }]);
  assert.equal(readAnalysis({ likely_cause: "Plain cause", summary: "S" }).likelyCause, "Plain cause");
  assert.equal(readAnalysis({}), null, "nothing to show");
  assert.equal(readAnalysis(null), null);
  assert.equal(citationOf({ title: "Runbook" }).label, "Runbook");
  assert.equal(citationOf({ locator: "L3-9" }).label, "L3-9");
  assert.equal(citationOf({ title: "T", locator: "L" }, "yes").verified, null, "only a boolean counts");
  assert.equal(citationOf({ kind: "manual" }), null);
  assert.equal(citationOf("x"), null);
});

test("the analysis view: the runner's statuses, polling only while running, plain-words states and reasons", () => {
  assert.equal(readAnalysisView({ status: "great" }), null);
  assert.equal(readAnalysisView(null), null);
  const view = readAnalysisView(VIEW());
  assert.deepEqual([view.state, view.reason, view.startedAt, view.finishedAt, view.reused], ["done", null, "2026-10-06T09:00:00Z", "2026-10-06T09:01:00Z", false]);
  assert.equal(readAnalysisView(VIEW({ reused: "yes" })).reused, false, "only an explicit true");
  assert.equal(analysisInProgress(readAnalysisView({ status: "running" })), true);
  assert.equal(analysisInProgress(view), false);
  assert.equal(analysisInProgress(null), false);
  assert.equal(analysisStateText(readAnalysisView({ status: "none" })), "No analysis yet.");
  assert.equal(analysisStateText(readAnalysisView({ status: "running" })), "Analysis running…");
  assert.equal(analysisStateText(readAnalysisView({ status: "queued" })), "Analysis running…");
  assert.equal(analysisStateText(view), "Analysis done.");
  assert.equal(analysisStateText(readAnalysisView(VIEW({ reused: true }))), "Analysis done (already up to date for this item version).");
  assert.equal(analysisStateText(readAnalysisView({ status: "failed", error_code: "analysis_uncited" })),
    "The analysis failed: the analysis cited nothing the tools had shown");
  assert.equal(analysisStateText(readAnalysisView({ status: "failed" })), "The analysis failed.");
  assert.equal(analysisStateText(readAnalysisView({ status: "needs_configuration", error_code: "model_policy_unresolved" })),
    "The analysis needs configuration: no model policy is set for the analysis in this Workspace");
  assert.equal(analysisStateText(readAnalysisView({ status: "denied", error_code: "x_policy" })), "The analysis was refused: refused (x_policy)");
  assert.equal(analysisStateText(readAnalysisView({ status: "skipped", error_code: "auto_rate_limited" })),
    "Not analysed: this item was analysed automatically within the last 24 hours");
  assert.equal(reasonText(null), "");
  assert.equal(analyzeRefusalText({ status: 409, code: "analysis_slot_busy" }), "Not started: an analysis of this item is already running.");
  assert.equal(analyzeRefusalText({ status: 404 }), "This server does not offer the incident analysis yet.");
  assert.equal(analyzeRefusalText({ status: 403 }), "You may not start an analysis in this Workspace.");
  assert.equal(analyzeRefusalText({ status: 500, message: "boom" }), "Not started: boom.");
});

test("the work note: availability comes from the server's preview; refusals in words", () => {
  assert.deepEqual(json(readWorknotePreview(WORKNOTE_PREVIEW)), { available: true, number: "INC0000001", text: "Likely cause: the certificate chain." });
  assert.equal(readWorknotePreview({ state: "posted" }), null);
  assert.equal(readWorknotePreview({ state: "posted", preview: { text: "T" } }), null, "only a needs_confirmation answer offers the send");
  assert.equal(readWorknotePreview({ state: "needs_confirmation", preview: { text: " " } }), null);
  assert.equal(worknoteRefusalText({ status: 409, code: "servicenow_worknote_disabled", message: "x" }), "Work notes to ServiceNow are switched off for this connector");
  assert.equal(worknoteRefusalText({ status: 409, code: "servicenow_worknote_already_posted" }), "This analysis was already sent as a work note");
  assert.equal(worknoteRefusalText({ status: 422, code: "servicenow_worknote_secret_detected" }), "The summary contains secret material and is never sent");
  assert.equal(worknoteRefusalText({ status: 404, code: null }), "This server does not offer work notes to ServiceNow yet");
  assert.equal(worknoteRefusalText({ status: 404, code: "servicenow_worknote_no_analysis_note" }), "There is no analysis to send yet");
  assert.equal(worknoteRefusalText({ status: 403 }), "You may not send work notes in this Workspace");
  assert.equal(worknoteRefusalText({ status: 502, code: "x_new", message: "ServiceNow answered HTTP 500." }), "ServiceNow answered HTTP 500.");
});

test("the latest analysis note on the item is the fallback (kind analysis only)", () => {
  assert.equal(latestAnalysisNote(SN_ITEM), null);
  const item = { source_fields: { platform_notes: [
    { kind: "analysis", note: "old", at: "1" }, { note: "progress" }, { kind: "analysis", note: "new", at: "2" }, { kind: "analysis", note: " " }, { note: "a later progress note" },
  ] } };
  assert.deepEqual(latestAnalysisNote(item), { at: "2", text: "new" });
});

// ---- settings model -----------------------------------------------------------------------------

// The backend's GET answer (routes/secure_work_servicenow.py; defaults from secure_work/servicenow/config.py).
const INTAKE_BODY = {
  tables: ["incident"], excluded_states: ["Canceled", "Cancelled", "Closed", "Resolved"], sysparm_query: "",
  state_mapping: { new: "intake", "in progress": "development", "on hold": "blocked", resolved: "done", closed: "done" },
  schedule_enabled: false, interval_minutes: 15, max_items: 200,
};
const INTAKE = { project_id: "ws-1", configured: true, intake: INTAKE_BODY };

const SUMMARY = (overrides = {}) => ({ open: 3, imported: 2, updated: 1, unchanged: 0, closed: 1, skipped_closed: 0, skipped_invalid: 0, unmapped_states: 0, complete: true, tables: ["incident"], ...overrides });

const SETTINGS = {
  model_policy: "analysis@1", cost_cap_usd: 1, auto_analyze: { servicenow_new_incidents: false, jira_label: null }, ask_reporter: false,
  runner: "governed", max_output_tokens: 8192,
};

test("analysis settings: opt-in auto-analysis, a single Jira label, ask the reporter; the whole object is sent back", () => {
  assert.equal(readAnalysisSettings({}), null);
  const settings = readAnalysisSettings({ settings: SETTINGS, source: "workspace" });
  assert.deepEqual(json(settings), { servicenowNewIncidents: false, jiraLabelOn: false, jiraLabel: "octryx", askReporter: false,
    runner: "governed", maxOutputTokens: "8192", modelPolicy: "analysis@1", maxCostUsd: 1, canEdit: true });
  assert.deepEqual(json(readAnalysisSettings(SETTINGS)), json(settings), "a bare settings object reads the same");
  assert.equal(readAnalysisSettings({ settings: SETTINGS, can_edit: false }).canEdit, false);
  assert.deepEqual(analysisSettingsPayload(settings), { ...SETTINGS });
  assert.deepEqual(analysisSettingsPayload({ ...settings, jiraLabelOn: true, jiraLabel: " triage ", servicenowNewIncidents: true, askReporter: true }),
    { model_policy: "analysis@1", cost_cap_usd: 1, auto_analyze: { servicenow_new_incidents: true, jira_label: "triage" }, ask_reporter: true,
      runner: "governed", max_output_tokens: 8192 });
  const unset = readAnalysisSettings({ settings: { ...SETTINGS, model_policy: null, cost_cap_usd: 0 } });
  assert.deepEqual([unset.modelPolicy, unset.maxCostUsd], [null, null]);
  assert.deepEqual(analysisSettingsPayload(unset), { model_policy: null, auto_analyze: SETTINGS.auto_analyze, ask_reporter: false,
    runner: "governed", max_output_tokens: 8192 });
  assert.equal(readAnalysisSettings({ auto_analyze: { jira_label: "X" } }).jiraLabelOn, true);
  assert.match(analysisSettingsError({ ...settings, jiraLabelOn: true, jiraLabel: "two words" }), /one Jira label/);
  assert.match(analysisSettingsError({ ...settings, jiraLabelOn: true, jiraLabel: "a,b" }), /one Jira label/);
  assert.match(analysisSettingsError({ ...settings, jiraLabelOn: true, jiraLabel: "x".repeat(65) }), /one Jira label/);
  assert.equal(analysisSettingsError({ ...settings, jiraLabelOn: false, jiraLabel: "two words" }), null);
  assert.equal(analysisSettingsError({ ...settings, jiraLabelOn: true, jiraLabel: "PRJ" }), null);
});

// ---- rendered -----------------------------------------------------------------------------------

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
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl, JSON,
      encodeURIComponent, FormData, setInterval, clearInterval, setTimeout,
      CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
      ...extra,
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

const windowStub = (search = "") => ({
  location: { origin: "http://localhost", search, href: `http://localhost/chat?area=work${search ? `&${search.slice(1)}` : ""}` },
  localStorage: { getItem: () => null, setItem: () => {} },
  history: { state: null, replaceState: () => {} },
  addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => {}, setTimeout: () => 0,
});

function server(answer) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const call = { url: String(url), method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null };
    calls.push(call);
    const { status, body } = answer(call);
    return { ok: status < 400, status, statusText: "", json: async () => body };
  };
  return { fetch, calls };
}
const tick = (ms = 0) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });
const click = (node) => act(async () => { node.props.onClick(); });
const button = (root, label) => root.find((node) => node.type === "button" && text(node).trim() === label);

async function renderAnalysis(srv, item = SN_ITEM, pollMs = 20) {
  const { WorkItemAnalysis } = load("chat/work/incident/WorkItemAnalysis.tsx", { fetch: srv.fetch, window: windowStub() });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(WorkItemAnalysis, { item, pollMs })); });
  await tick();
  return view;
}
const isWorknote = (call) => call.url.endsWith("/servicenow-worknote");

test("rendered analysis: the stored analysis with citations; write-back disabled with the server's reason", async () => {
  const srv = server((call) => (isWorknote(call) ? DISABLED : { status: 200, body: VIEW() }));
  const view = await renderAnalysis(srv);
  try {
    assert.ok(srv.calls[0].url.endsWith("/api/v1/secure-work/work-items/wi-sn-1/analysis"));
    assert.equal(text(byTestId(view.root, "analysis-state")[0]), "Analysis done.");
    assert.equal(text(byTestId(view.root, "analysis-start")[0]), "Analyse again");
    const evidence = byTestId(view.root, "analysis-evidence")[0].findAllByType("li");
    assert.equal(text(evidence[0]), "The manual requires the full chain. [Gateway manual, p. 12]");
    assert.equal(evidence[0].findByType("a").props.href, "https://docs.test/gw.pdf#page=12");
    assert.equal(evidence[0].findByType("a").props.rel, "noopener noreferrer");
    assert.equal(evidence[2].findAllByType("a").length, 0, "an unsafe link is not rendered");
    assert.match(text(evidence[2]), /\(not confirmed by a tool result\)/);
    assert.equal(text(byTestId(view.root, "analysis-similar")[0].findAllByType("li")[0]), "INC0000000: Same certificate rotation");
    assert.match(text(byTestId(view.root, "analysis-cause")[0]), /Expired intermediate certificate \(confidence: medium\)/);
    assert.deepEqual(byTestId(view.root, "analysis-questions")[0].findAllByType("li").map(text), ["Since when does it fail?"]);
    // The preview (no confirm) was asked; nothing was confirmed.
    const worknoteCalls = srv.calls.filter(isWorknote);
    assert.deepEqual(worknoteCalls.map((call) => call.body), [{ confirm: false }]);
    assert.equal(byTestId(view.root, "worknote-send")[0].props.disabled, true);
    assert.equal(text(byTestId(view.root, "worknote-disabled")[0]), "Disabled: Work notes to ServiceNow are switched off for this connector.");
  } finally { act(() => view.unmount()); }
});

test("rendered analysis: start posts once and shows the result; a running analysis is polled; a Jira item asks no work note", async () => {
  let reads = 0;
  const srv = server((call) => {
    if (call.method === "POST") return { status: 200, body: { status: "running", error_code: null, analysis: null } };
    reads += 1;
    if (reads === 1) return { status: 404, body: { detail: "Not Found" } };
    return { status: 200, body: reads < 3 ? { status: "running", analysis: null } : VIEW() };
  });
  const view = await renderAnalysis(srv, JIRA_ITEM);
  try {
    assert.equal(text(byTestId(view.root, "analysis-state")[0]), "No analysis yet.", "a 404 read is no analysis yet");
    assert.equal(byTestId(view.root, "analysis-message").length, 0);
    assert.equal(byTestId(view.root, "worknote-send").length, 0, "Jira items take no ServiceNow work note");
    await click(byTestId(view.root, "analysis-start")[0]);
    assert.deepEqual(srv.calls.filter((call) => call.method === "POST").map((call) => call.url.replace(/^.*\/work-items/, "")), ["/wi-j-1/analyze"]);
    assert.equal(byTestId(view.root, "analysis-start")[0].props.disabled, true, "no second start while running");
    await tick(120);
    assert.equal(text(byTestId(view.root, "analysis-state")[0]), "Analysis done.");
    const after = srv.calls.length;
    await tick(80);
    assert.equal(srv.calls.length, after, "no polling once done");
    assert.equal(srv.calls.filter(isWorknote).length, 0);
  } finally { act(() => view.unmount()); }
});

// An item without an analysis: the server answers 200 {status: "none"} (no 404, so no console error on every open).
test("rendered analysis: the server's none view is no analysis yet, with the start and without an error", async () => {
  const srv = server((call) => (call.method === "GET" && call.url.endsWith("/analysis")
    ? { status: 200, body: { work_item_id: "wi-j-1", status: "none", analysis: null, content_is_data: "x" } }
    : { status: 200, body: {} }));
  const view = await renderAnalysis(srv, JIRA_ITEM);
  try {
    assert.equal(text(byTestId(view.root, "analysis-state")[0]), "No analysis yet.");
    assert.equal(text(byTestId(view.root, "analysis-start")[0]), "Start analysis");
    assert.equal(byTestId(view.root, "analysis-message").length, 0, "no error for an item without analysis");
    assert.equal(byTestId(view.root, "analysis-body").length, 0);
  } finally { act(() => view.unmount()); }
});

test("rendered analysis: a refused start and a failed read say why; the note on the item is the fallback", async () => {
  const refused = server((call) => (call.method === "POST" && !isWorknote(call)
    ? { status: 409, body: { detail: { code: "analysis_slot_busy", message: "busy" } } }
    : { status: 404, body: { detail: "Not Found" } }));
  const view = await renderAnalysis(refused, JIRA_ITEM);
  try {
    await click(byTestId(view.root, "analysis-start")[0]);
    assert.equal(text(byTestId(view.root, "analysis-message")[0]), "Not started: an analysis of this item is already running.");
    assert.equal(byTestId(view.root, "analysis-message")[0].props.role, "alert");
  } finally { act(() => view.unmount()); }
  const broken = await renderAnalysis(server(() => ({ status: 500, body: { detail: "boom" } })), JIRA_ITEM);
  try {
    assert.equal(text(byTestId(broken.root, "analysis-message")[0]), "Not loaded: boom.");
  } finally { act(() => broken.unmount()); }
  const withNote = { ...SN_ITEM, source_fields: { platform_notes: [{ kind: "analysis", note: "Plain analysis text.", at: "2026-10-06T09:00:00Z" }] } };
  const noted = await renderAnalysis(server((call) => (isWorknote(call) ? DISABLED : { status: 404, body: { detail: "Not Found" } })), withNote);
  try {
    assert.match(text(byTestId(noted.root, "analysis-note")[0]), /written by an agent.*Plain analysis text\./);
    assert.equal(text(byTestId(noted.root, "analysis-start")[0]), "Analyse again");
  } finally { act(() => noted.unmount()); }
});

test("rendered write-back: available only after the server's preview; the exact text is confirmed, then sent once", async () => {
  const withNote = { ...SN_ITEM, source_fields: { platform_notes: [{ kind: "analysis", note: "Analysis text.", at: "2026-10-06T10:00:00" }] } };
  const srv = server((call) => {
    if (isWorknote(call)) return { status: 200, body: call.body.confirm ? { state: "posted" } : WORKNOTE_PREVIEW };
    return { status: 200, body: VIEW() };
  });
  const view = await renderAnalysis(srv, withNote);
  try {
    assert.equal(byTestId(view.root, "worknote-disabled").length, 0);
    assert.deepEqual(srv.calls.filter(isWorknote).map((call) => call.body), [{ note_at: "2026-10-06T10:00:00", confirm: false }]);
    await click(byTestId(view.root, "worknote-send")[0]);
    assert.equal(srv.calls.filter(isWorknote).length, 1, "opening the confirmation sends nothing");
    assert.match(text(byTestId(view.root, "worknote-confirm")[0]), /^Send this summary to INC0000001 as a work note\?Likely cause: the certificate chain\.Only the summary is sent/);
    await click(button(view.root, "Cancel"));
    assert.equal(byTestId(view.root, "worknote-confirm").length, 0);
    await click(byTestId(view.root, "worknote-send")[0]);
    await click(button(view.root, "Send work note"));
    assert.deepEqual(srv.calls.filter(isWorknote).map((call) => call.body).at(-1), { note_at: "2026-10-06T10:00:00", confirm: true });
    assert.equal(text(byTestId(view.root, "analysis-message")[0]), "Sent the analysis summary to INC0000001 as a work note.");
    assert.equal(byTestId(view.root, "worknote-send")[0].props.disabled, true, "sent once");
    assert.equal(text(byTestId(view.root, "worknote-disabled")[0]), "Disabled: This analysis was already sent as a work note.");
  } finally { act(() => view.unmount()); }
});

test("rendered write-back: a refused post says why and keeps the confirmation", async () => {
  const srv = server((call) => {
    if (isWorknote(call)) return call.body.confirm ? { status: 502, body: { detail: { code: "servicenow_worknote_failed", message: "ServiceNow answered HTTP 500." } } } : { status: 200, body: WORKNOTE_PREVIEW };
    return { status: 200, body: VIEW() };
  });
  const view = await renderAnalysis(srv);
  try {
    await click(byTestId(view.root, "worknote-send")[0]);
    await click(button(view.root, "Send work note"));
    assert.equal(text(byTestId(view.root, "analysis-message")[0]), "Not sent: ServiceNow did not accept the work note.");
    assert.equal(byTestId(view.root, "worknote-confirm").length, 1);
  } finally { act(() => view.unmount()); }
});

test("rendered ServiceNow source: fields by name and the record link", async () => {
  const { WorkItemServiceNowSource } = load("chat/work/incident/WorkItemServiceNowSource.tsx", { window: windowStub() });
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkItemServiceNowSource, { item: SN_ITEM, projects: [{ id: "ws-1", name: "Ops" }] })); });
  try {
    assert.match(text(byTestId(view.root, "servicenow-source")[0]), /WorkspaceOpsNumberINC0000001Record typeIncidentStateIn Progress.*Assignment groupService DeskAssigned toAda Admin/);
    assert.equal(byTestId(view.root, "servicenow-link")[0].props.href, SN_ITEM.source_url);
  } finally { act(() => view.unmount()); }
});

test("rendered board card: a ServiceNow item shows the badge, not the source status; its column names our state", () => {
  const { WorkBoard } = load("chat/work/WorkAreaViews.tsx", { window: windowStub() });
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkBoard, { items: [SN_ITEM, JIRA_ITEM], syncConfigs: [], onOpenItem: () => {} })); });
  try {
    const cards = view.root.findAll((node) => node.type === "button" && node.props.className === "work-card");
    const card = (key) => cards.find((entry) => text(entry).includes(key));
    assert.equal(byTestId(card("INC0000001"), "work-source-badge").length, 1);
    assert.doesNotMatch(text(card("INC0000001")), /Development/, "the column names the state, the card does not repeat it");
    const column = view.root.findAll((node) => node.type === "section" && node.props["data-state"] === "development")[0];
    assert.match(text(column), /INC0000001/, "in the Development column");
    assert.equal(byTestId(card("BRD-1"), "work-source-badge").length, 0);
    assert.doesNotMatch(text(card("INC0000001")), /ServiceNow: In Progress/);
    assert.doesNotMatch(text(card("BRD-1")), /Jira: /);
  } finally { act(() => view.unmount()); }
});

test("rendered analysis settings: opt-in options saved as the whole object; an invalid label blocks the save", async () => {
  let stored = { settings: SETTINGS, source: "workspace" };
  const srv = server((call) => {
    if (call.method === "PUT") { stored = { settings: call.body, source: "workspace" }; return { status: 200, body: stored }; }
    return { status: 200, body: stored };
  });
  const { IncidentAnalysisSettingsCard } = load("chat/work/incident/IncidentAnalysisSettingsCard.tsx", { fetch: srv.fetch, window: windowStub() });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(IncidentAnalysisSettingsCard, { projectId: "ws-1" })); });
  await tick();
  try {
    assert.ok(srv.calls[0].url.endsWith("/api/v1/secure-work/work-item-analysis-settings/ws-1"));
    assert.match(text(view.root), /capped at \$1\.00 per run/);
    assert.equal(byTestId(view.root, "analysis-settings-no-policy").length, 0);
    assert.equal(byTestId(view.root, "auto-jira-label")[0].props.disabled, true);
    await act(async () => { byTestId(view.root, "auto-servicenow")[0].props.onChange({ target: { checked: true } }); });
    await act(async () => { byTestId(view.root, "auto-jira")[0].props.onChange({ target: { checked: true } }); });
    await act(async () => { byTestId(view.root, "auto-jira-label")[0].props.onChange({ target: { value: "two words" } }); });
    assert.equal(byTestId(view.root, "analysis-settings-save")[0].props.disabled, true);
    assert.match(text(byTestId(view.root, "analysis-settings-invalid")[0]), /one Jira label/);
    await act(async () => { byTestId(view.root, "auto-jira-label")[0].props.onChange({ target: { value: "PRJ" } }); });
    await act(async () => { byTestId(view.root, "ask-reporter")[0].props.onChange({ target: { checked: true } }); });
    await click(byTestId(view.root, "analysis-settings-save")[0]);
    assert.deepEqual(srv.calls.find((call) => call.method === "PUT").body,
      { model_policy: "analysis@1", cost_cap_usd: 1, auto_analyze: { servicenow_new_incidents: true, jira_label: "PRJ" }, ask_reporter: true,
        runner: "governed", max_output_tokens: 8192 });
    assert.equal(text(byTestId(view.root, "analysis-settings-message")[0]), "Saved the analysis settings.");
  } finally { act(() => view.unmount()); }
});

test("rendered analysis settings: without a model policy it says analyses need configuration; read-only when the server says so", async () => {
  const srv = server(() => ({ status: 200, body: { settings: { ...SETTINGS, model_policy: null }, can_edit: false } }));
  const { IncidentAnalysisSettingsCard } = load("chat/work/incident/IncidentAnalysisSettingsCard.tsx", { fetch: srv.fetch, window: windowStub() });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(IncidentAnalysisSettingsCard, { projectId: "ws-1" })); });
  await tick();
  try {
    assert.match(text(byTestId(view.root, "analysis-settings-no-policy")[0]), /needs configuration until a Workspace admin sets one/);
    assert.equal(byTestId(view.root, "analysis-settings-save").length, 0);
    assert.equal(byTestId(view.root, "auto-servicenow")[0].props.disabled, true);
  } finally { act(() => view.unmount()); }
  const missing = server(() => ({ status: 404, body: { detail: "Not Found" } }));
  const { IncidentAnalysisSettingsCard: Card } = load("chat/work/incident/IncidentAnalysisSettingsCard.tsx", { fetch: missing.fetch, window: windowStub() });
  let gone;
  await act(async () => { gone = TestRenderer.create(createElement(Card, { projectId: "ws-1" })); });
  await tick();
  try {
    assert.match(text(byTestId(gone.root, "analysis-settings-error")[0]), /does not offer the incident analysis settings yet/);
  } finally { act(() => gone.unmount()); }
});

