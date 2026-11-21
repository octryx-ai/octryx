// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminPolishStates.test.mjs
//
// Admin polish:
// 2. list type labels are plural and consistent; 3. a paused Action's disabled Execute says why;
// 4. run-error guidance on a paused Action starts with resuming it and never advises running it again first;
// 5. run status colours use the theme's status ink tokens (readable on the light theme);
// 6. the thread dot names the stop cause when a closed reason is known, generic otherwise;
// 7. switching the Atlassian sign-in method clears the typed secret, so a Cloud API token is never sent as a PAT.
// The type column's fit is layout only and is checked in the browser.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { FIELD_TYPE_OPTIONS, fieldTypeLabel } from "../../src/admin/components/agentsTab/agentReplyFields.ts";
import { knownRunError } from "../../src/admin/components/actionRunError.ts";
import { threadSignalLabel } from "../../src/chat/threadSignalKind.ts";
import { buildConnectorSaveBody } from "../../src/admin/hooks/connectorSaveBody.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
globalThis.requestAnimationFrame = (callback) => callback();

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

function makeLoader(stubs = {}) {
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
      module, exports: module.exports, console, Date, URL, URLSearchParams, requestAnimationFrame: globalThis.requestAnimationFrame,
      document: { getElementById: () => null }, require: (name) => resolve(name, path.dirname(file)),
    });
    return module.exports;
  };
  return (relative) => load(path.join(SRC, relative));
}

// ---- 2. list labels -----------------------------------------------------------------------------

test("2: list type labels are plural and consistent", () => {
  const labels = Object.fromEntries(FIELD_TYPE_OPTIONS.map((option) => [option.value, option.label]));
  assert.deepEqual(
    ["list:string", "list:integer", "list:number", "list:boolean"].map((value) => labels[value]),
    ["List of texts", "List of whole numbers", "List of numbers", "List of yes/no values"],
  );
  assert.equal(fieldTypeLabel({ type: "integer", list: true }), "List of whole numbers");
  assert.equal(fieldTypeLabel({ type: "integer", list: false }), "Whole number", "single values unchanged");
});

// ---- 3 + 5. Action card -------------------------------------------------------------------------

const TASK = {
  id: "task-1", name: "Digest", description: "", task_type: "agent_run", agent_type: "change", schedule: null,
  is_active: false, config: {}, run_count: 2, running_count: 0, last_run_status: "success", last_run_at: "2026-10-04T10:00:00Z",
  step_count: 0, project_id: "ws-1",
};

function card(task) {
  const { AdminTaskCard } = makeLoader()("admin/components/AdminTaskCard.tsx");
  const noop = () => {};
  let view;
  act(() => {
    view = TestRenderer.create(createElement(AdminTaskCard, {
      task, isExpanded: false, runs: [], triggeringTask: null, agentModeNameByKey: new Map(),
      onExpandTask: noop, onTriggerTask: noop, onOpenTaskForm: noop, setShowTaskForm: noop, onToggleTask: noop, onDeleteTask: noop,
    }));
  });
  return view;
}

test("3: a paused Action's disabled Execute says to resume it; an active one says Execute now", () => {
  const execute = (view) => view.root.find((node) => node.type === "button" && /Execute/.test(text(node)));
  const paused = execute(card(TASK));
  assert.deepEqual([paused.props.disabled, paused.props.title, paused.props["aria-label"]], [true, "Paused – resume to run", "Paused – resume to run"]);
  const active = execute(card({ ...TASK, is_active: true }));
  assert.deepEqual([active.props.disabled, active.props.title, active.props["aria-label"]], [false, "Execute now", "Execute now"]);
});

test("5: run status colours are theme ink tokens, never fixed light hexes", () => {
  const dotColor = (status) => {
    const view = card({ ...TASK, last_run_status: status });
    const dot = view.root.find((node) => node.type === "span" && text(node) === "●");
    return dot.props.style.color;
  };
  assert.equal(dotColor("success"), "var(--status-active-ink)");
  assert.equal(dotColor("failed"), "var(--status-error-ink)");
  assert.equal(dotColor("queued"), "var(--status-running-ink)");
  assert.equal(dotColor("cancelled"), "var(--status-idle-ink)");
});

// ---- 4. paused guidance -------------------------------------------------------------------------

const CODES = [
  "agent_definition_inactive", "agent_definition_not_published", "agent_definition_execution_mode_not_configured",
  "agent_reply_not_json", "agent_reply_schema_mismatch", "agent_reply_contract_invalid", "agent_reply_contract_unchecked",
  "agent_reply_contract_path_unsupported", "answer_evidence_invented_url",
];

test("4: on a paused Action the next step starts with resuming it; the cause and the summary stay the same", () => {
  for (const code of CODES) {
    const active = knownRunError({ status: "error", error: code });
    const paused = knownRunError({ status: "error", error: code }, { paused: true });
    assert.equal(paused.summary, active.summary, code);
    assert.match(paused.guidance, /resume the action/i, code);
    assert.doesNotMatch(paused.guidance, /(^|[.;] )Run the action again|then run the action again/, `${code}: no run-again before resuming`);
    const cause = active.guidance.split(". ")[0];
    assert.ok(paused.guidance.startsWith(cause), `${code}: the cause is unchanged`);
  }
  assert.match(knownRunError({ status: "error", error: "agent_reply_not_json" }).guidance, /Run the action again, or ask an administrator/,
    "an active Action keeps its guidance");
});

test("4: the run history passes the paused state down to the guidance", () => {
  const { AdminTaskRunsTable } = makeLoader()("admin/components/AdminTaskRunsTable.tsx");
  const run = {
    id: "run-1-0000000000", task_id: "task-1", session_id: null, status: "error", started_by: "u", started_at: null,
    completed_at: null, error: "agent_reply_not_json", duration_seconds: 1, steps_log: [], queue_priority: 5,
    queue_status: "completed", queue_required_domain: "any", queued_at: null, estimated_wait_seconds: null, queue_wait_reason: null,
  };
  const guidance = (taskPaused) => {
    let view;
    act(() => {
      view = TestRenderer.create(createElement(AdminTaskRunsTable, {
        taskId: "task-1", runs: [run], expandedRun: run.id, statusColor: {}, cancellingRun: null,
        setExpandedRun: () => {}, handleCancelRun: async () => {}, taskPaused,
      }));
    });
    const found = text(view.root.find((node) => node.props.className === "action-run-error__guidance"));
    act(() => view.unmount());
    return found;
  };
  assert.match(guidance(true), /Resume the action first, then run it again/);
  assert.match(guidance(false), /Run the action again, or ask an administrator/);
});

// ---- 6. thread dot label --------------------------------------------------------------------------

test("6: the thread dot names a known stop cause and stays generic otherwise", () => {
  assert.equal(threadSignalLabel("turn-stopped", "agent_reply_not_json"), "Last turn stopped: reply format not met");
  assert.equal(threadSignalLabel("turn-stopped", "agent_reply_contract_invalid"), "Last turn stopped: reply format not valid");
  assert.equal(threadSignalLabel("turn-stopped", "answer_evidence_invented_url"), "Last turn stopped: evidence check");
  assert.equal(threadSignalLabel("turn-stopped", "step_stalled"), "Last turn stopped: step check");
  for (const reason of [undefined, null, "", "unknown_reason", "constructor", 7]) {
    assert.equal(threadSignalLabel("turn-stopped", reason), "Last turn stopped by a safety or quality check", String(reason));
  }
  assert.equal(threadSignalLabel("done", "agent_reply_not_json"), null);
});

// ---- 7. Atlassian shared token field --------------------------------------------------------------

const POLICY = { tool_instructions: "", extra_tools: [], disabled_tools: [] };

function mountConfluence(connector) {
  const loadModule = makeLoader({
    "/ConfiguredConnectorHeader": { ConfiguredConnectorHeader: () => null },
    "/ConfiguredConnectorHealthTools": { ConfiguredConnectorHealthTools: () => null },
    "/ConfiguredConnectorToolList": { ConfiguredConnectorToolList: () => null },
    "/ConfiguredConnectorGithubPanel": { ConfiguredConnectorGithubPanel: () => null },
  });
  const { ConfiguredConnectorCard } = loadModule("admin/components/connectorsTab/ConfiguredConnectorCard.tsx");
  let draft = {};
  for (const [key, value] of Object.entries(connector.public_fields)) draft[key] = typeof value === "string" ? value : JSON.stringify(value);
  const saves = [];
  let view;
  const ctx = {
    CONNECTOR_COLORS: {}, connectorHealthHistory: {}, connectorTestResult: {}, connectorSaving: null, connectorTesting: null,
    expandedConnector: connector.tool_name, getConnectorDraft: () => draft,
    setConnectorField: (_tool, field, value) => { draft = { ...draft, [field]: value }; act(() => view.update(render())); },
    handleSaveConnector: async (_tool, saved) => { saves.push(buildConnectorSaveBody(saved, draft, POLICY)); return { state: "saved" }; },
    handleTestConnector: async () => {},
  };
  const render = () => createElement(ConfiguredConnectorCard, { connector, ctx });
  act(() => { view = TestRenderer.create(render()); });
  const id = (field) => `connector-field-confluence-${field}`;
  const input = (field) => view.root.find((node) => node.type === "input" && node.props.id === id(field));
  const choose = (name, value) => act(() => view.root.find((node) => node.type === "input" && node.props.type === "radio"
    && node.props.name === id(name) && node.props.value === value).props.onChange());
  const type = (field, value) => act(() => input(field).props.onChange({ target: { value } }));
  const save = async () => { await act(async () => { view.root.find((node) => node.type === "button" && text(node) === "Save").props.onClick(); }); };
  return { draft: () => draft, input, choose, type, save, saves };
}

const confluence = (publicFields = {}, secrets = {}) => ({
  tool_name: "confluence", label: "Confluence", description: "Confluence", supports_test: true, builtin_tools: [], tools: [],
  fields: ["confluence_url", "confluence_auth_mode", "confluence_username", "confluence_password", "confluence_token", "confluence_allowed_spaces"],
  secret_fields: ["confluence_password", "confluence_token"], tool_policy: POLICY, is_active: true, policy_active: true, configured: true,
  public_fields: { confluence_url: "https://wiki.acme.test", confluence_allowed_spaces: ["ENG"], ...publicFields },
  secret_status: { confluence_password: false, confluence_token: false, ...secrets }, db_id: null, policy_id: null,
});

test("7: a token typed for Cloud is cleared when switching to a personal access token, and never sent as one", async () => {
  const card = mountConfluence(confluence());
  card.choose("confluence_auth_mode", "cloud");
  card.type("confluence_username", "bot@acme.test");
  card.type("confluence_token", "cloud-api-token");
  card.choose("confluence_auth_mode", "own");
  card.choose("__confluence_auth_location", "bearer_pat");
  assert.equal(card.draft().confluence_token, "", "the typed API token is gone");
  assert.equal(card.input("confluence_token").props.value, "", "the masked field does not look filled");
  assert.doesNotMatch(card.input("confluence_token").props.placeholder, /stored/);
  await card.save();
  assert.equal(card.saves.length, 0, "a save without a new token is refused locally");
  card.type("confluence_token", "pat-123");
  await card.save();
  assert.deepEqual([card.saves[0].confluence_auth_mode, card.saves[0].confluence_token], ["bearer_pat", "pat-123"]);
});

test("7: switching from a stored PAT to Cloud asks for a new token instead of reusing the stored one", () => {
  const card = mountConfluence(confluence({ confluence_auth_mode: "bearer_pat" }, { confluence_token: true }));
  assert.match(card.input("confluence_token").props.placeholder, /stored — leave blank to keep/);
  card.type("confluence_token", "typed-pat");
  card.choose("confluence_auth_mode", "cloud");
  assert.equal(card.draft().confluence_token, "");
  assert.equal(card.input("confluence_token").props.value, "");
  assert.match(card.input("confluence_token").props.placeholder, /^Enter the api token$/i);
});
