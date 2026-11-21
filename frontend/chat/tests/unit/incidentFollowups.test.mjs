// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/incidentFollowups.test.mjs
//
// Follow-ups (frontend): the analysis runner (governed or the user's own seat session) and the max output tokens
// in the analysis settings, sent with the backend's `cost_cap_usd` key; the analysis view's `error_detail`, runner and
// model, flat evidence fields and the `analysis_runs_in_seat` answer with its command; the ServiceNow connector's
// assignment-group limit (`servicenow_assignment_groups`) and the intake's narrowing override with the effective groups.
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
  analysisCauseText,
  analysisRunnerText,
  analysisStateText,
  analyzeRefusalText,
  readAnalysis,
  readAnalysisView,
  reasonText,
  seatCommand,
  seatCommandToShow,
} from "../../src/chat/work/incident/incidentAnalysisModel.ts";
import {
  analysisSettingsError,
  analysisSettingsPayload,
  intakeErrorText,
  readAnalysisSettings,
} from "../../src/chat/work/incident/incidentSettingsModel.ts";
import {
  GROUPS_FIELD,
  addGroup,
  draftGroups,
  groupEntryProblem,
  removeGroup,
  serviceNowGroupsSaveFields,
  storedGroups,
} from "../../src/admin/components/connectorsTab/serviceNowGroupsModel.ts";
import { buildConnectorSaveBody } from "../../src/admin/hooks/connectorSaveBody.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (root, id) => root.findAll((node) => node.props && node.props["data-testid"] === id);
const json = (value) => JSON.parse(JSON.stringify(value));

// The backend's settings answer (routes: flat object; work_item_analysis/settings.py).
const SETTINGS = {
  project_id: "ws-1", model_policy: "analysis@1", cost_cap_usd: 2.5, auto_analyze: { servicenow_new_incidents: false, jira_label: null },
  ask_reporter: false, runner: "governed", max_output_tokens: 8192, source: "workspace", can_edit: true,
};
const SN_ITEM = {
  id: "wi-sn-1", project_id: "ws-1", source_type: "servicenow", source_instance: "servicenow.test", source_key: "INC0000001",
  source_url: "https://servicenow.test/r", title: "Login fails", description: "", source_status: "New", source_fields: {},
};
const VIEW = (overrides = {}) => ({
  id: "an-1", work_item_id: "wi-sn-1", status: "succeeded", error_code: null, error_detail: null, runner: "governed", model: null,
  reused: false, created_at: "2026-10-06T09:00:00Z", finished_at: "2026-10-06T09:01:00Z",
  analysis: { summary: "S", evidence: [{ claim: "C", title: "Runbook", locator: "p. 2", kind: "manual", url: "https://docs.test/r", verified: true }] },
  ...overrides,
});
const SEAT_ANSWER = { status: "skipped", error_code: "analysis_runs_in_seat", runner: "seat", command: "octryx-claude analyze INC0000001", work_item_id: "wi-sn-1" };
const PROVIDER_DETAIL = "analysis-alias: permanent: request_rejected (HTTP 400): BedrockException - `temperature` is deprecated for this model";

// ---- analysis settings model --------------------------------------------------------------------

test("analysis settings: runner and max output tokens read and sent; the cost cap is read and sent as cost_cap_usd", () => {
  const settings = readAnalysisSettings(SETTINGS);
  assert.deepEqual([settings.runner, settings.maxOutputTokens, settings.maxCostUsd], ["governed", "8192", 2.5]);
  assert.equal(readAnalysisSettings({ ...SETTINGS, runner: "seat" }).runner, "seat");
  assert.equal(readAnalysisSettings({ ...SETTINGS, runner: "other" }).runner, "governed", "an unknown runner reads as the default");
  assert.equal(readAnalysisSettings({ ...SETTINGS, max_output_tokens: undefined }).maxOutputTokens, "8192");
  const { cost_cap_usd: _ignored, ...uncapped } = SETTINGS;
  assert.equal(readAnalysisSettings({ ...uncapped, max_cost_usd: 3 }).maxCostUsd, null, "only cost_cap_usd is read");
  const payload = analysisSettingsPayload({ ...settings, runner: "seat", maxOutputTokens: " 16000 " });
  assert.deepEqual(payload, {
    model_policy: "analysis@1", cost_cap_usd: 2.5, auto_analyze: { servicenow_new_incidents: false, jira_label: null },
    ask_reporter: false, runner: "seat", max_output_tokens: 16000,
  });
  assert.equal("max_cost_usd" in payload, false, "the backend refuses max_cost_usd as an unknown key");
  for (const tokens of ["1023", "32001", "1.5", "", "abc", "-2000"]) {
    assert.match(analysisSettingsError({ ...settings, maxOutputTokens: tokens }), /whole number from 1024 to 32000/, tokens);
  }
  for (const tokens of ["1024", "32000", " 8192 "]) assert.equal(analysisSettingsError({ ...settings, maxOutputTokens: tokens }), null, tokens);
});

// ---- analysis view model ------------------------------------------------------------------------

test("analysis view: error_detail as the cause of a failure; runner and model; the seat answer's command", () => {
  const failed = readAnalysisView(VIEW({ status: "failed", error_code: "analysis_runtime_error", error_detail: ` ${PROVIDER_DETAIL} `, analysis: null }));
  assert.equal(failed.detail, PROVIDER_DETAIL);
  assert.equal(analysisCauseText(failed), `Cause: ${PROVIDER_DETAIL}`);
  assert.equal(analysisStateText(failed), "The analysis failed: the analysis run stopped with an error");
  assert.equal(analysisCauseText(readAnalysisView(VIEW({ status: "failed" }))), null, "no detail: no cause line");
  assert.equal(analysisCauseText(readAnalysisView(VIEW({ error_detail: "x" }))), null, "a done analysis shows no cause");
  assert.equal(analysisCauseText(readAnalysisView({ status: "running", error_detail: "x" })), null);
  const seatRun = readAnalysisView(VIEW({ runner: "seat", model: "claude-opus" }));
  assert.equal(analysisRunnerText(seatRun), "Ran in a seat session (model claude-opus).");
  assert.equal(analysisRunnerText(readAnalysisView(VIEW({ runner: "seat" }))), "Ran in a seat session.");
  assert.equal(analysisRunnerText(readAnalysisView(VIEW())), null, "governed runs say nothing extra");
  const seat = readAnalysisView(SEAT_ANSWER);
  assert.deepEqual([seat.state, seat.reason, seat.runner, seat.command], ["skipped", "analysis_runs_in_seat", "seat", SEAT_ANSWER.command]);
  assert.equal(analysisStateText(seat),
    "Not analysed: this Workspace analyses in each user's own seat session, not on the server. Run: octryx-claude analyze INC0000001");
  assert.equal(analysisStateText(readAnalysisView({ ...SEAT_ANSWER, command: null })),
    "Not analysed: this Workspace analyses in each user's own seat session, not on the server");
  assert.equal(reasonText("analysis_runs_in_seat"), "this Workspace analyses in each user's own seat session, not on the server");
  assert.equal(analyzeRefusalText({ status: 409, code: "analysis_runs_in_seat" }),
    "Not started: this Workspace analyses in each user's own seat session, not on the server.");
});

test("analysis evidence: flat title/locator/url fields are cited; the nested source wins when present", () => {
  const flat = readAnalysis({ summary: "S", evidence: [
    { claim: "Flat", title: "Runbook", locator: "p. 2", kind: "manual", url: "https://docs.test/r", verified: true },
    { claim: "Both", source: { title: "Nested", locator: "L1" }, title: "Flat", locator: "L9", url: "https://docs.test/flat", verified: false },
    { claim: "Unsafe", title: "T", url: "javascript:alert(1)" },
    { claim: "Uncited" },
  ] });
  assert.deepEqual(json(flat.evidence), [
    { text: "Flat", citation: { label: "Runbook, p. 2", url: "https://docs.test/r", verified: true } },
    { text: "Both", citation: { label: "Nested, L1", url: null, verified: false } },
    { text: "Unsafe", citation: { label: "T", url: null, verified: null } },
    { text: "Uncited", citation: null },
  ]);
});

test("seat command: the backend's key rule; the server's answer first, else the item's own for a seat Workspace", () => {
  assert.equal(seatCommand("INC0000103"), "octryx-claude analyze INC0000103");
  assert.equal(seatCommand("BRD-1.2_x"), "octryx-claude analyze BRD-1.2_x");
  for (const key of ["", "-x", "INC 1", "a;rm -rf", "x".repeat(65), null]) assert.equal(seatCommand(key), null, String(key));
  const none = readAnalysisView({ status: "none" });
  assert.equal(seatCommandToShow(none, "seat", "INC1"), "octryx-claude analyze INC1");
  assert.equal(seatCommandToShow(none, "governed", "INC1"), null);
  assert.equal(seatCommandToShow(none, null, "INC1"), null);
  assert.equal(seatCommandToShow(readAnalysisView(SEAT_ANSWER), null, "OTHER"), SEAT_ANSWER.command, "the server's command");
});

// ---- connector assignment groups model ----------------------------------------------------------

const POLICY = { tool_instructions: "", extra_tools: [], disabled_tools: [] };
function servicenow(publicFields = {}) {
  return {
    tool_name: "servicenow", label: "ServiceNow", description: "ServiceNow tables",
    fields: ["servicenow_url", "servicenow_auth_mode", "servicenow_token", "servicenow_allowed_tables", GROUPS_FIELD],
    secret_fields: ["servicenow_token"], supports_test: true, builtin_tools: [], tools: [], tool_policy: POLICY,
    is_active: true, policy_active: true, configured: true,
    public_fields: { servicenow_url: "https://servicenow.test", servicenow_auth_mode: "bearer_token", servicenow_allowed_tables: ["incident"], ...publicFields },
    secret_status: { servicenow_token: true }, db_id: null, policy_id: null,
  };
}

test("groups model: the backend's entry rules (non-empty, 100 characters, no ^ , control characters or javascript:, 50, no duplicates)", () => {
  assert.equal(groupEntryProblem("Service Desk", []), null);
  assert.equal(groupEntryProblem("0123456789abcdef0123456789ABCDEF", []), null, "a sys_id");
  assert.match(groupEntryProblem("   ", []), /Enter a group/);
  assert.equal(groupEntryProblem("x".repeat(100), []), null);
  assert.match(groupEntryProblem("x".repeat(101), []), /at most 100 characters/);
  for (const bad of ["a^b", "a,b", "a\u0001b", "a\u007fb", "JavaScript:alert(1)"]) assert.match(groupEntryProblem(bad, []), /must not contain/, JSON.stringify(bad));
  assert.match(groupEntryProblem("service desk", ["Service Desk"]), /already in the list/);
  const fifty = Array.from({ length: 50 }, (_, index) => `G${index}`);
  assert.match(groupEntryProblem("New", fifty), /At most 50 groups/);
  assert.equal(groupEntryProblem("New", fifty.slice(1)), null);
  assert.deepEqual(addGroup(["A"], "  Network   Ops "), { groups: ["A", "Network Ops"], problem: null });
  assert.deepEqual(json(addGroup(["A"], "a")), { groups: ["A"], problem: "This group is already in the list." });
  assert.deepEqual(removeGroup(["A", "B", "C"], 1), ["A", "C"]);
});

test("groups model: stored list, draft list and the save body (untouched: nothing; all removed: []; added: the list)", () => {
  const none = servicenow({ [GROUPS_FIELD]: [] });
  const stored = servicenow({ [GROUPS_FIELD]: ["Service Desk", "  "] });
  assert.deepEqual(storedGroups(stored), ["Service Desk"]);
  assert.deepEqual(storedGroups(servicenow()), []);
  assert.deepEqual(storedGroups(servicenow({ [GROUPS_FIELD]: "Service Desk" })), [], "only a list counts");
  assert.deepEqual(draftGroups(stored, {}), ["Service Desk"]);
  assert.deepEqual(draftGroups(stored, { [GROUPS_FIELD]: '["A","B"]' }), ["A", "B"]);
  assert.deepEqual(draftGroups(stored, { [GROUPS_FIELD]: "not json" }), ["Service Desk"]);
  assert.deepEqual(serviceNowGroupsSaveFields(none, {}), {}, "untouched");
  assert.deepEqual(serviceNowGroupsSaveFields(none, { [GROUPS_FIELD]: "[]" }), {}, "the prefill of an empty list changes nothing");
  assert.deepEqual(serviceNowGroupsSaveFields(stored, {}), {}, "untouched, stored: kept");
  assert.deepEqual(serviceNowGroupsSaveFields(stored, { [GROUPS_FIELD]: "[]" }), { [GROUPS_FIELD]: [] }, "all removed: an explicit clear");
  assert.deepEqual(serviceNowGroupsSaveFields(none, { [GROUPS_FIELD]: '["Network"]' }), { [GROUPS_FIELD]: ["Network"] });
  // Through the whole save body: owned by the ServiceNow models, never sent raw by the generic loop.
  assert.deepEqual(buildConnectorSaveBody(stored, { [GROUPS_FIELD]: "[]" }, POLICY)[GROUPS_FIELD], []);
  assert.deepEqual(buildConnectorSaveBody(none, { [GROUPS_FIELD]: '["A", "B"]' }, POLICY)[GROUPS_FIELD], ["A", "B"]);
  assert.equal(GROUPS_FIELD in buildConnectorSaveBody(none, { [GROUPS_FIELD]: "[]" }, POLICY), false);
});

// ---- intake groups model ------------------------------------------------------------------------

const INTAKE_BODY = {
  tables: ["incident"], excluded_states: ["Closed"], sysparm_query: "", state_mapping: { new: "intake" },
  schedule_enabled: false, interval_minutes: 15, max_items: 200, assignment_groups: [],
};
const SCOPE = (overrides = {}) => ({ connector: ["Service Desk", "Network"], intake: [], effective: ["Service Desk", "Network"], ...overrides });
const INTAKE = (scope = SCOPE(), intake = {}) => ({ project_id: "ws-1", configured: true, intake: { ...INTAKE_BODY, ...intake }, assignment_group_scope: scope });

// ---- rendered -----------------------------------------------------------------------------------

function makeLoader(extra = {}, stubs = {}) {
  const cache = new Map();
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name.endsWith(suffix));
    if (stub) return stub[1];
    if (name.startsWith(".")) {
      const base = path.resolve(dir, name);
      for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return load(base + ext);
    }
    return require(name);
  };
  const load = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl, JSON,
      encodeURIComponent, setInterval, clearInterval, setTimeout, requestAnimationFrame: (callback) => callback(),
      document: { getElementById: () => null },
      window: { location: { origin: "http://localhost", search: "" }, setTimeout: () => 0, confirm: () => true, addEventListener: () => {}, removeEventListener: () => {} },
      ...extra,
      require: (name) => resolve(name, path.dirname(file)),
    });
    return module.exports;
  };
  return (relative) => load(path.join(SRC, relative));
}

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
const isSettings = (call) => call.url.includes("/work-item-analysis-settings/");

async function mount(component, props, srv) {
  const exports = makeLoader({ fetch: srv.fetch })(component);
  const name = path.basename(component, ".tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(exports[name], props)); });
  await tick();
  return view;
}

test("rendered analysis: a seat Workspace shows the command instead of the start button; governed keeps the button", async () => {
  const seat = server((call) => (isSettings(call) ? { status: 200, body: { ...SETTINGS, runner: "seat" } } : { status: 404, body: { detail: "Not Found" } }));
  const view = await mount("chat/work/incident/WorkItemAnalysis.tsx", { item: { ...SN_ITEM, source_fields: {} }, pollMs: 20 }, seat);
  try {
    assert.ok(seat.calls.some((call) => call.url.endsWith("/work-item-analysis-settings/ws-1")), "the item's Workspace settings");
    assert.equal(byTestId(view.root, "analysis-start").length, 0);
    assert.equal(text(byTestId(view.root, "analysis-seat-command")[0]), "octryx-claude analyze INC0000001");
    assert.match(text(byTestId(view.root, "analysis-seat")[0]), /^This Workspace analyses in your own seat session\. Run this in a terminal:/);
    assert.equal(seat.calls.filter((call) => call.method === "POST" && call.url.endsWith("/analyze")).length, 0);
  } finally { act(() => view.unmount()); }
  const governed = server((call) => (isSettings(call) ? { status: 200, body: SETTINGS } : { status: 404, body: { detail: "Not Found" } }));
  const gov = await mount("chat/work/incident/WorkItemAnalysis.tsx", { item: SN_ITEM, pollMs: 20 }, governed);
  try {
    assert.equal(text(byTestId(gov.root, "analysis-start")[0]), "Start analysis");
    assert.equal(byTestId(gov.root, "analysis-seat").length, 0);
  } finally { act(() => gov.unmount()); }
});

test("rendered analysis: unreadable settings keep the button; the server's seat answer then shows its command", async () => {
  const srv = server((call) => {
    if (isSettings(call)) return { status: 403, body: { detail: "Forbidden" } };
    if (call.method === "POST") return { status: 200, body: SEAT_ANSWER };
    return { status: 404, body: { detail: "Not Found" } };
  });
  const view = await mount("chat/work/incident/WorkItemAnalysis.tsx", { item: { ...SN_ITEM, source_key: "OTHER-1" }, pollMs: 20 }, srv);
  try {
    await click(byTestId(view.root, "analysis-start")[0]);
    assert.equal(byTestId(view.root, "analysis-start").length, 0, "the button gives way to the command");
    assert.equal(text(byTestId(view.root, "analysis-seat-command")[0]), "octryx-claude analyze INC0000001", "the server's command");
    assert.match(text(byTestId(view.root, "analysis-state")[0]), /Run: octryx-claude analyze INC0000001$/);
  } finally { act(() => view.unmount()); }
});

test("rendered analysis: a failure shows the server's cause; a seat analysis says where it ran", async () => {
  const failed = server((call) => (isSettings(call) ? { status: 200, body: SETTINGS }
    : { status: 200, body: VIEW({ status: "failed", error_code: "analysis_runtime_error", error_detail: PROVIDER_DETAIL, analysis: null }) }));
  const view = await mount("chat/work/incident/WorkItemAnalysis.tsx", { item: { ...SN_ITEM, source_type: "jira" }, pollMs: 20 }, failed);
  try {
    assert.equal(text(byTestId(view.root, "analysis-state")[0]), "The analysis failed: the analysis run stopped with an error");
    assert.equal(text(byTestId(view.root, "analysis-cause-detail")[0]), `Cause: ${PROVIDER_DETAIL}`);
    assert.equal(byTestId(view.root, "analysis-runner").length, 0);
  } finally { act(() => view.unmount()); }
  const seatRun = server((call) => (isSettings(call) ? { status: 200, body: SETTINGS } : { status: 200, body: VIEW({ runner: "seat", model: "claude-opus" }) }));
  const ran = await mount("chat/work/incident/WorkItemAnalysis.tsx", { item: { ...SN_ITEM, source_type: "jira" }, pollMs: 20 }, seatRun);
  try {
    assert.equal(text(byTestId(ran.root, "analysis-runner")[0]), "Ran in a seat session (model claude-opus).");
    assert.equal(byTestId(ran.root, "analysis-cause-detail").length, 0);
    assert.equal(text(byTestId(ran.root, "analysis-evidence")[0].findAllByType("li")[0]), "C [Runbook, p. 2]", "flat evidence fields cited");
  } finally { act(() => ran.unmount()); }
});

test("rendered analysis settings: the runner and the max output tokens are saved; seat says auto-analysis does not run", async () => {
  const srv = server((call) => ({ status: 200, body: call.method === "PUT" ? { ...SETTINGS, ...call.body } : SETTINGS }));
  const view = await mount("chat/work/incident/IncidentAnalysisSettingsCard.tsx", { projectId: "ws-1" }, srv);
  try {
    assert.equal(byTestId(view.root, "analysis-runner-governed")[0].props.checked, true);
    assert.equal(byTestId(view.root, "analysis-settings-seat").length, 0);
    assert.equal(byTestId(view.root, "analysis-max-output-tokens")[0].props.value, "8192");
    await act(async () => { byTestId(view.root, "analysis-runner-seat")[0].props.onChange(); });
    assert.match(text(byTestId(view.root, "analysis-settings-seat")[0]), /automatic analysis does not run/);
    assert.match(text(view.root), /Analyse new ServiceNow incidents automatically.*\(not with the Seat runner\)/);
    assert.equal(byTestId(view.root, "auto-servicenow")[0].props.disabled, false, "the options stay editable");
    await act(async () => { byTestId(view.root, "analysis-max-output-tokens")[0].props.onChange({ target: { value: "40000" } }); });
    assert.equal(byTestId(view.root, "analysis-settings-save")[0].props.disabled, true);
    assert.match(text(byTestId(view.root, "analysis-settings-invalid")[0]), /from 1024 to 32000/);
    await act(async () => { byTestId(view.root, "analysis-max-output-tokens")[0].props.onChange({ target: { value: "4096" } }); });
    await click(byTestId(view.root, "analysis-settings-save")[0]);
    assert.deepEqual(srv.calls.find((call) => call.method === "PUT").body, {
      model_policy: "analysis@1", cost_cap_usd: 2.5, auto_analyze: { servicenow_new_incidents: false, jira_label: null },
      ask_reporter: false, runner: "seat", max_output_tokens: 4096,
    });
  } finally { act(() => view.unmount()); }
});

function intakeServer(initial, { refuse = null } = {}) {
  let stored = initial;
  return server((call) => {
    if (call.url.endsWith("/runs")) return { status: 200, body: { runs: [] } };
    if (call.method === "PUT") {
      if (refuse) return refuse;
      const groups = call.body.assignment_groups;
      stored = { ...stored, intake: { ...stored.intake, ...call.body }, assignment_group_scope: SCOPE({ intake: groups, effective: groups.length ? groups : SCOPE().connector }) };
      return { status: 200, body: stored };
    }
    return { status: 200, body: stored };
  });
}
const typeGroup = async (view, testId, value) => {
  await act(async () => { byTestId(view.root, `${testId}-input`)[0].props.onChange({ target: { value } }); });
  await act(async () => { byTestId(view.root, `${testId}-input`)[0].props.onKeyDown({ key: "Enter", preventDefault: () => {} }); });
};

const Null = () => null;
function mountConnector(connector) {
  const loadModule = makeLoader({}, {
    "/ConfiguredConnectorHeader": { ConfiguredConnectorHeader: Null },
    "/ConfiguredConnectorHealthTools": { ConfiguredConnectorHealthTools: Null },
    "/ConfiguredConnectorToolList": { ConfiguredConnectorToolList: Null },
    "/ConfiguredConnectorGithubPanel": { ConfiguredConnectorGithubPanel: Null },
  });
  const { ConfiguredConnectorCard } = loadModule("admin/components/connectorsTab/ConfiguredConnectorCard.tsx");
  // The draft is prefilled as the admin hook does on expand (useAdminConnectorCoreActions): lists as indented JSON.
  let draft = Object.fromEntries(Object.entries(connector.public_fields)
    .map(([key, value]) => [key, typeof value === "string" ? value : JSON.stringify(value, null, 2)]));
  const saves = [];
  let view;
  const ctx = {
    CONNECTOR_COLORS: {}, connectorHealthHistory: {}, connectorTestResult: {}, connectorSaving: null, connectorTesting: null,
    expandedConnector: connector.tool_name, getConnectorDraft: () => draft,
    setConnectorField: (_tool, field, value) => { draft = { ...draft, [field]: value }; act(() => view.update(render())); },
    handleSaveConnector: async (_toolName, saved) => { saves.push(buildConnectorSaveBody(saved, draft, POLICY)); return { state: "saved" }; },
    handleTestConnector: async () => {},
  };
  const render = () => createElement(ConfiguredConnectorCard, { connector, ctx });
  act(() => { view = TestRenderer.create(render()); });
  return {
    view: () => view, saves,
    save: async () => { await act(async () => { view.root.find((node) => node.type === "button" && text(node) === "Save").props.onClick(); }); },
  };
}

test("rendered connector: assignment groups as chips; Enter adds, invalid entries say why, remove all clears; saved as a list", async () => {
  const card = mountConnector(servicenow({ [GROUPS_FIELD]: ["Service Desk"] }));
  const root = () => card.view().root;
  assert.deepEqual(byTestId(root(), "servicenow-assignment-groups-chip").map((chip) => text(chip.findByType("span"))), ["Service Desk"]);
  assert.match(text(byTestId(root(), "servicenow-assignment-groups")[0]),
    /Only incidents, changes and records of these assignment groups are read \(chat, Knowledge MCP, source sync, intake\)\. Names or sys_ids\. Empty: no limit\./);
  assert.doesNotMatch(text(root()), /servicenow assignment groups/i, "no raw field in the generic panel");
  await typeGroup(card.view(), "servicenow-assignment-groups", "Ops^ORactive=true");
  assert.match(text(byTestId(root(), "servicenow-assignment-groups-problem")[0]), /must not contain/);
  await typeGroup(card.view(), "servicenow-assignment-groups", "Network");
  assert.equal(byTestId(root(), "servicenow-assignment-groups-problem").length, 0);
  assert.equal(byTestId(root(), "servicenow-assignment-groups-input")[0].props.value, "", "the input is cleared after adding");
  await card.save();
  assert.deepEqual(card.saves.at(-1)[GROUPS_FIELD], ["Service Desk", "Network"]);
  for (const group of ["Service Desk", "Network"]) {
    await click(root().find((node) => node.type === "button" && node.props["aria-label"] === `Remove ${group}`));
  }
  assert.equal(text(byTestId(root(), "servicenow-assignment-groups-empty")[0]), "No limit: records of every assignment group are read.");
  await card.save();
  assert.deepEqual(card.saves.at(-1)[GROUPS_FIELD], [], "removing every stored group is an explicit clear");
  const fresh = mountConnector(servicenow({ [GROUPS_FIELD]: [] }));
  await fresh.save();
  assert.equal(GROUPS_FIELD in fresh.saves.at(-1), false, "untouched and nothing stored: nothing sent");
});
