// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workSettingsWorkflows.test.mjs
//
// Work → Jira write-back (workflow management) and the intake run model (work-settings-workflows-ui). Workflows per
// Workspace with their mode (a warning badge when they execute in Jira), active state and mapping summary; activate,
// deactivate and the mode switch each ask first and list exactly what will (or will no longer) be written to Jira, and
// refusals keep the server's message. Each intake lists its last runs: time, trigger, outcome, counts, the failure code
// with Jira's message, and a refused scope explained. Every request is a stub.
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
  activationConfirmation,
  executeWrites,
  mappingSummary,
  mappingWrites,
  modeSwitchConfirmation,
  switchedPolicy,
  workflowGroups,
  workflowMode,
  workflowRefusalText,
} from "../../src/chat/work/workflowLifecycleModel.ts";
import { readRun, runAutomationText, runCountsText, runOutcome } from "../../src/chat/work/workIntakeRunsModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
const json = (value) => JSON.parse(JSON.stringify(value));

const EXECUTE = {
  id: "wf-x", name: "BRD execute", project_id: "ws-1", is_default: true, is_active: true,
  states: [{ key: "intake", label: "Intake" }, { key: "development", label: "Development" }, { key: "review", label: "Review" }, { key: "done", label: "Done" }],
  mappings: {
    development: { source_status: "In Arbeit", source_transition: "Start", comment_template: "Started by PRJ", sync_back: true },
    review: { source_transition: "Send to review", labels: ["octryx", "review"], sync_back: true },
    done: { source_status: "Erledigt", sync_back: false },
  },
  sync_policy: { sync_mode: "execute", conflict_policy: "require_review" },
};
const DRY = { ...EXECUTE, id: "wf-d", name: "Standard", project_id: null, is_default: false, sync_policy: { sync_mode: "dry_run_only" } };

// ---- workflow model -----------------------------------------------------------------------------

test("mode and mapping summary: what each mapped state writes, and which states sync back", () => {
  assert.equal(workflowMode(EXECUTE), "execute");
  assert.equal(workflowMode(DRY), "dry_run");
  assert.equal(workflowMode({ ...EXECUTE, sync_policy: {} }), "dry_run", "no mode is never execute");
  assert.equal(mappingWrites(EXECUTE.mappings.development), "status In Arbeit · via “Start” · comment “Started by PRJ”");
  assert.equal(mappingWrites(EXECUTE.mappings.review), "transition “Send to review” · labels octryx, review");
  assert.equal(mappingWrites({ sync_back: true }), "");
  assert.deepEqual(json(mappingSummary(EXECUTE)), [
    { state: "development", label: "Development", writes: "status In Arbeit · via “Start” · comment “Started by PRJ”",
      status: "In Arbeit", transition: "Start", extras: "comment “Started by PRJ”", syncBack: true },
    { state: "review", label: "Review", writes: "transition “Send to review” · labels octryx, review",
      status: "", transition: "Send to review", extras: "labels octryx, review", syncBack: true },
    { state: "done", label: "Done", writes: "status Erledigt", status: "Erledigt", transition: "", extras: "", syncBack: false },
  ]);
  assert.deepEqual(executeWrites(EXECUTE).map((row) => row.state), ["development", "review"], "only sync-back rows write");
  assert.deepEqual(executeWrites({ ...EXECUTE, mappings: { development: { sync_back: true } } }), [], "sync-back with nothing to write");
});

test("confirmations list exactly what will, or will no longer, be written to Jira", () => {
  const toExecute = modeSwitchConfirmation(DRY);
  assert.equal(toExecute.title, "Switch “Standard” to execute in Jira?");
  assert.deepEqual(toExecute.lines, [
    "Applying a transition will then write to Jira:",
    "Development: status In Arbeit · via “Start” · comment “Started by PRJ”",
    "Review: transition “Send to review” · labels octryx, review",
    "Each apply still needs its own preview and confirmation.",
  ]);
  assert.equal(toExecute.danger, true);
  assert.match(modeSwitchConfirmation({ ...DRY, mappings: {} }).lines[0], /^No state of this workflow syncs back to Jira yet/);
  const toDry = modeSwitchConfirmation(EXECUTE);
  assert.equal(toDry.title, "Switch “BRD execute” to dry-run only?");
  assert.match(toDry.lines[0], /^Jira will no longer be written by this workflow/);
  assert.equal(toDry.lines[1], "It stops writing: Development, Review.");
  const deactivate = activationConfirmation(EXECUTE);
  assert.equal(deactivate.title, "Deactivate “BRD execute”?");
  assert.deepEqual(deactivate.lines.slice(1), ["It executes in Jira, so Jira will no longer be written through it."]);
  assert.equal(activationConfirmation(DRY).lines.length, 1, "a dry-run workflow writes nothing to stop");
  assert.match(activationConfirmation({ ...EXECUTE, is_active: false }).lines[0], /applies write to Jira/);
  assert.deepEqual(switchedPolicy(EXECUTE), { sync_mode: "dry_run_only", conflict_policy: "require_review" },
    "every other policy key is kept");
  assert.equal(switchedPolicy(DRY).sync_mode, "execute");
});

test("workflows are grouped per Workspace by name, the Workspace-independent ones last", () => {
  const groups = workflowGroups([DRY, EXECUTE, { ...DRY, id: "wf-b", project_id: "ws-0" }], [{ id: "ws-1", name: "BRD team" }, { id: "ws-0", name: "Alpha" }]);
  assert.deepEqual(groups.map((group) => [group.title, group.workflows.map((entry) => entry.id)]),
    [["Alpha", ["wf-b"]], ["BRD team", ["wf-x"]], ["All Workspaces", ["wf-d"]]]);
  assert.equal(workflowGroups([{ ...DRY, project_id: "ws-9" }], [])[0].title, "ws-9");
  assert.equal(workflowRefusalText(Object.assign(new Error("Forbidden"), { status: 403 })), "You may not change this Workspace's workflows (Workspace admin or owner needed).");
  assert.equal(workflowRefusalText(Object.assign(new Error("Unknown workflow state in mappings: qa"), { status: 422 })), "Not saved: Unknown workflow state in mappings: qa");
});

// ---- intake runs model --------------------------------------------------------------------------

const config = (overrides = {}) => ({
  id: "cfg-1", name: "BRD intake", source_type: "jira", source_instance: "octryx", filters: {}, field_mapping: {}, sync_options: {},
  is_active: true, last_sync_at: "2026-10-05T10:00:00Z", last_sync_status: "completed",
  last_sync_summary: { imported: 2, updated: 1, unchanged: 4, total_source: 9, total_after_filter: 7 }, ...overrides,
});

test("runs: one run read strictly from a serialized sync run, with its trigger", () => {
  assert.equal(readRun({ id: "r1" }), null, "a run needs an id and a status");
  assert.deepEqual(json(readRun({ id: "r1", status: "completed", mode: "dry_run", trigger: "scheduled", completed_at: "2026-10-05T11:00:00Z", summary: {} })),
    { id: "r1", at: "2026-10-05T11:00:00Z", trigger: "scheduled", mode: "preview", status: "completed", summary: {}, error: null });
  assert.equal(readRun({ id: "r1", status: "completed", mode: "sync" }, "manual").trigger, "manual");
  assert.equal(readRun({ id: "r1", status: "completed", trigger: "cron" }).trigger, "trigger not reported");
});

test("outcome: counts, a refused scope explained, the failure code with Jira's message, a blocked JQL", () => {
  assert.equal(runCountsText(config().last_sync_summary), "2 imported · 1 updated · 4 unchanged",
    "a limited or paged run is never called filtered out");
  assert.equal(runCountsText({ imported: 50, unchanged: 0, total_source: 120, total_after_filter: 50, pending_next_run: 70,
    more_pending: true, source: { returned: 50, requested_limit: 50 } }), "50 imported · 0 unchanged · 70 pending next run");
  assert.equal(runCountsText({ imported: 3, more_pending: true, total_after_filter: 3, source: { returned: 5 } }),
    "3 imported · more pending next run · 2 left out by the intake's filters");
  assert.equal(runAutomationText({ automation: { labels: ["PRJ"], matching: 4, mode: "direct" } }), "4 with label PRJ – agent may start");
  assert.equal(runAutomationText({ imported: 1 }), "", "older runs without the count show nothing");
  assert.equal(runCountsText({ imported: 0 }), "0 imported");
  assert.equal(runCountsText({}), "");
  const run = (status, summary, error = null) => ({ id: "r", at: null, trigger: "manual", mode: "sync", status, summary, error });
  const refused = runOutcome(run("failed", { code: "scope_not_allowed", reason: "scope_not_allowed", projects: ["BRD"] }));
  assert.equal(refused.label, "refused");
  assert.match(refused.detail, /^The intake's Jira projects \(BRD\) are outside this Workspace's allowed Jira projects, so nothing was fetched\./);
  assert.deepEqual(json(runOutcome(run("failed", { code: "jql_invalid", message: "Error in the JQL Query: 'ORDER' is a reserved word." }))),
    { label: "failed", tone: "danger", detail: "jql_invalid: Error in the JQL Query: 'ORDER' is a reserved word." });
  assert.equal(runOutcome(run("failed", {}, "jira_sync_failed")).detail, "jira_sync_failed");
  assert.match(runOutcome(run("blocked", { blocked: true, block_reason: "jql_unbalanced" })).detail, /unbalanced parentheses or quotes, so it was not sent/);
  assert.equal(runOutcome(run("blocked", { blocked: true, block_reason: "Jira connector is not configured." })).detail, "Jira connector is not configured.");
  assert.deepEqual(json(runOutcome(run("completed", { filtered_outside_allowlist: true }))),
    { label: "completed", tone: "active", detail: "Issues outside the Workspace's allowed Jira projects were left out." });
  assert.equal(runOutcome(run("completed", {})).detail, null);
  assert.equal(runOutcome({ ...run("failed", { code: "scope_not_allowed", projects: ["OPS"] }), mode: "last run" }).label, "refused",
    "the stored last run's summary carries the same facts");
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
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Intl, encodeURIComponent, AbortController,
      window: { location: { origin: "http://localhost" }, setTimeout: () => 0 }, ...extra,
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

function server(answer) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null });
    const { status, body } = answer(String(url), init.method || "GET");
    return { ok: status < 400, status, statusText: "", json: async () => body };
  };
  return { fetch, calls };
}
const button = (view, label) => view.root.findAll((node) => node.type === "button" && text(node).trim() === label)[0] ?? null;

test("rendered: an execute workflow is flagged; the mode switch asks first and keeps the other policy keys", async () => {
  const srv = server((url) => ({ status: 200, body: { ...EXECUTE, sync_policy: { ...EXECUTE.sync_policy, sync_mode: "dry_run_only" } } }));
  const { WorkWorkflowList } = load("chat/work/WorkWorkflowList.tsx", { fetch: srv.fetch });
  const changed = [];
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkWorkflowList, { workflows: [EXECUTE, DRY], projects: [{ id: "ws-1", name: "BRD team" }], onChanged: () => changed.push(1) })); });
  const cards = byTestId(view, "workflow-card");
  const mode = cards[0].find((node) => node.props["data-testid"] === "workflow-mode");
  assert.deepEqual([text(mode), mode.props.className], ["Executes in the source", "work-badge work-badge--attention"]);
  assert.equal(cards[0].findAll((node) => node.props["data-testid"] === "workflow-execute-warning").length, 1);
  assert.equal(cards[1].findAll((node) => node.props["data-testid"] === "workflow-execute-warning").length, 0);
  assert.equal(text(cards[1].find((node) => node.props["data-testid"] === "workflow-mode")), "Dry-run only");
  assert.deepEqual(cards[0].findByType("thead").findAllByType("th").map(text),
    ["Octryx state", "Status in the source", "Transition used to write back", "Also writes", "Writes back"], "the same words for every source");
  assert.deepEqual(cards[0].findByType("tbody").findAllByType("tr").map(text),
    ["DevelopmentIn ArbeitStartcomment “Started by PRJ”yes", "Review–Send to reviewlabels octryx, reviewyes", "DoneErledigt––no"]);

  await act(async () => { cards[0].find((node) => node.type === "button" && text(node) === "Switch to dry-run only…").props.onClick(); });
  assert.equal(srv.calls.length, 0, "nothing is sent before the confirmation");
  const confirmation = byTestId(view, "workflow-confirmation")[0];
  assert.match(text(confirmation), /Switch “BRD execute” to dry-run only\?Jira will no longer be written/);
  await act(async () => { button(view, "Switch to dry-run only").props.onClick(); });
  assert.deepEqual(srv.calls, [{ url: "/api/v1/secure-work/workflows/wf-x", method: "PUT",
    body: { sync_policy: { sync_mode: "dry_run_only", conflict_policy: "require_review" } } }]);
  assert.equal(changed.length, 1);
  assert.equal(text(byTestId(view, "workflow-message")[0]), "“BRD execute” now: Dry-run only.");
  assert.equal(byTestId(view, "workflow-confirmation").length, 0);
  act(() => view.unmount());
});

test("rendered: deactivating asks first and says Jira is no longer written; a refusal keeps the server's message", async () => {
  let refuse = false;
  const srv = server(() => (refuse
    ? { status: 422, body: { detail: { code: "workflow_state_unknown", message: "Unknown workflow state in mappings: qa", states: ["intake"] } } }
    : { status: 200, body: { ...EXECUTE, is_active: false } }));
  const { WorkWorkflowList } = load("chat/work/WorkWorkflowList.tsx", { fetch: srv.fetch });
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkWorkflowList, { workflows: [EXECUTE], onChanged: () => {} })); });
  await act(async () => { button(view, "Deactivate…").props.onClick(); });
  assert.match(text(byTestId(view, "workflow-confirmation")[0]), /It executes in Jira, so Jira will no longer be written through it\./);
  await act(async () => { button(view, "Cancel").props.onClick(); });
  assert.equal(byTestId(view, "workflow-confirmation").length, 0);
  assert.equal(srv.calls.length, 0, "cancel sends nothing");
  await act(async () => { button(view, "Deactivate…").props.onClick(); });
  await act(async () => { button(view, "Deactivate").props.onClick(); });
  assert.deepEqual(srv.calls.map((call) => [call.url, call.method]), [["/api/v1/secure-work/workflows/wf-x/deactivate", "POST"]]);
  assert.equal(text(byTestId(view, "workflow-message")[0]), "“BRD execute” is now inactive.");

  refuse = true;
  await act(async () => { button(view, "Switch to dry-run only…").props.onClick(); });
  await act(async () => { button(view, "Switch to dry-run only").props.onClick(); });
  const message = byTestId(view, "workflow-message")[0];
  assert.deepEqual([text(message), message.props.role], ["Not saved: Unknown workflow state in mappings: qa", "alert"]);
  assert.equal(byTestId(view, "workflow-confirmation").length, 1, "a refused change keeps its confirmation open");
  act(() => view.unmount());
});
