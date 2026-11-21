// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workTransitionPreview.test.mjs
//
// The transition preview reads `transition_available`,
// `offered_transitions` and `blocked_reason`: when the server says the apply would be refused, the confirmation says
// so (with Jira's offers), never "nothing is written", and offers no Apply. The workflow summary lists only states
// that write something or sync back (the server normalises mappings to one per state). Workflow mode and activation
// changes send the loaded `updated_at`; a 409 stale refusal reloads the list and closes the old confirmation.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { blockedText, offeredTransitions, transitionPlan } from "../../src/chat/work/workTransitionModel.ts";
import { isStaleRefusal, mappingSummary, workflowRefusalText } from "../../src/chat/work/workflowLifecycleModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
const json = (value) => JSON.parse(JSON.stringify(value));

const ITEM = { id: "wi-1", project_id: "ws-1", source_type: "jira", source_key: "BRD-1", title: "x", work_state: "intake", sync_state: "updated" };
const EXECUTE = { sync_policy: { sync_mode: "execute" } };

// ---- preview model ------------------------------------------------------------------------------

test("a preview the server marks as refused is blocked: no write claim, no 'nothing is written', Jira's offers listed", () => {
  const notOffered = transitionPlan(ITEM, EXECUTE, { jira_sync_preview: { sync_back: true, will_mutate_jira: false, transition_available: false,
    offered_transitions: [{ name: "Done", to: "Done" }, { name: "Start", to: "In Progress" }], effects: [], transition: "QA" } });
  assert.deepEqual(json(notOffered), {
    writesToJira: false, effects: [], localReason: null, conflict: null,
    blocked: "Jira does not offer the mapped transition “QA” from the issue's current status, so applying would be refused before anything is written.",
    offers: ["Done", "Start → In Progress"],
  });
  const scope = transitionPlan(ITEM, EXECUTE, { jira_sync_preview: { sync_back: true, will_mutate_jira: false, blocked_reason: "scope_not_allowed", effects: [], transition: "QA" } });
  assert.equal(scope.localReason, null);
  assert.match(scope.blocked, /^This item's Jira project is outside the Workspace's allowed Jira projects, so applying would be refused/);
  assert.match(blockedText({ blocked_reason: "issue_locked" }), /^Applying would be refused \(issue_locked\)/, "an unknown reason is still a refusal");
  assert.match(blockedText({ transition_available: false, target_status: "Done" }), /mapped transition “Done”/);
  assert.equal(blockedText({ transition_available: null }), null, "unknown is not refused: the preview stands as mapped");
  assert.equal(blockedText({ transition_available: true }), null);
  assert.equal(blockedText(undefined), null);
  const writes = transitionPlan(ITEM, EXECUTE, { jira_sync_preview: { sync_back: true, will_mutate_jira: true, transition_available: true,
    effects: [{ kind: "status", value: "Done", target_status: "Done" }] } });
  assert.deepEqual([writes.writesToJira, writes.blocked], [true, null]);
  assert.deepEqual(offeredTransitions({ offered_transitions: [{ name: "", to: "" }, { name: "Reopen", to: null }, { to: "Done" }] }), ["Reopen", "→ Done"]);
  assert.deepEqual(offeredTransitions({}), []);
});

// ---- workflow model -----------------------------------------------------------------------------

test("the mapping summary skips the server's empty per-state mappings; a 409 stale is explained", () => {
  const empty = { source_status: null, source_transition: null, comment_template: "", labels: [], sync_back: false };
  const rows = mappingSummary({ states: [{ key: "intake", label: "Intake" }, { key: "review", label: "Review" }, { key: "done", label: "Done" }],
    mappings: { intake: empty, review: { ...empty, sync_back: true }, done: { ...empty, source_status: "Done" } } });
  assert.deepEqual(rows.map((row) => [row.state, row.writes, row.syncBack]), [["review", "nothing", true], ["done", "status Done", false]]);
  const stale = Object.assign(new Error("Workflow changed"), { status: 409, code: "workflow_stale" });
  assert.equal(isStaleRefusal(stale), true);
  assert.equal(isStaleRefusal(Object.assign(new Error("x"), { status: 409, code: null })), true, "a 409 without a code is a version conflict");
  assert.equal(isStaleRefusal(Object.assign(new Error("x"), { status: 409, code: "workflow_inactive" })), false);
  assert.equal(isStaleRefusal(Object.assign(new Error("x"), { status: 422, code: "workflow_stale" })), false);
  assert.match(workflowRefusalText(stale), /^Not saved: this workflow was changed after this page loaded it\. The list was reloaded/);
  assert.equal(workflowRefusalText(Object.assign(new Error("Workflow is inactive"), { status: 409, code: "workflow_inactive" })), "Not saved: Workflow is inactive");
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
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl, encodeURIComponent, FormData,
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

const WORKFLOW = {
  id: "wf-1", name: "BRD execute", project_id: "ws-1", is_default: true, is_active: true, updated_at: "2026-10-05T12:00:00+00:00",
  states: [{ key: "intake", label: "Intake" }, { key: "qa", label: "QA sign-off" }],
  mappings: { qa: { source_transition: "QA", sync_back: true } }, sync_policy: { sync_mode: "execute" },
};

test("rendered: a blocked preview shows why and Jira's offers, and offers no Apply", async () => {
  const preview = { valid: true, workflow_id: "wf-1", work_item_id: "wi-1", source_key: "BRD-1", from_state: "intake", to_state: "qa", reason: "",
    jira_sync_preview: { mode: "dry_run", sync_back: true, will_mutate_jira: false, transition_available: false, transition: "QA",
      offered_transitions: [{ name: "Done", to: "Erledigt" }], effects: [] }, conflict: { has_conflict: false } };
  const srv = server(() => ({ status: 200, body: { preview, event: {} } }));
  const { WorkItemTransition } = load("chat/work/WorkItemTransition.tsx", { fetch: srv.fetch });
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkItemTransition, { item: ITEM, workflows: [WORKFLOW] })); });
  act(() => view.root.find((node) => node.type === "select" && node.props["aria-label"] === "Target state").props.onChange({ target: { value: "qa" } }));
  await act(async () => { button(view, "Preview").props.onClick(); });
  const blocked = byTestId(view, "transition-blocked")[0];
  assert.match(text(blocked), /^Jira does not offer the mapped transition “QA”/);
  assert.deepEqual(blocked.findAllByType("li").map(text), ["Done → Erledigt"]);
  assert.equal(byTestId(view, "transition-local").length, 0, "never 'nothing is written' when the apply would be refused");
  const apply = view.root.findAll((node) => node.type === "button" && /^Apply/.test(text(node)))[0];
  assert.equal(apply.props.disabled, true);
  act(() => view.unmount());
});

test("rendered: workflow changes send the loaded updated_at; a 409 stale reloads and closes the confirmation", async () => {
  let stale = false;
  const srv = server(() => (stale
    ? { status: 409, body: { detail: { code: "workflow_stale", message: "Workflow changed" } } }
    : { status: 200, body: { ...WORKFLOW, sync_policy: { sync_mode: "dry_run_only" } } }));
  const { WorkWorkflowList } = load("chat/work/WorkWorkflowList.tsx", { fetch: srv.fetch });
  const reloads = [];
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkWorkflowList, { workflows: [WORKFLOW], onChanged: () => reloads.push(1) })); });
  await act(async () => { button(view, "Switch to dry-run only…").props.onClick(); });
  await act(async () => { button(view, "Switch to dry-run only").props.onClick(); });
  assert.equal(srv.calls[0].body.updated_at, "2026-10-05T12:00:00+00:00");
  await act(async () => { button(view, "Deactivate…").props.onClick(); });
  stale = true;
  await act(async () => { button(view, "Deactivate").props.onClick(); });
  assert.deepEqual([srv.calls[1].url, srv.calls[1].body], ["/api/v1/secure-work/workflows/wf-1/deactivate", { updated_at: "2026-10-05T12:00:00+00:00" }]);
  assert.match(text(byTestId(view, "workflow-message")[0]), /^Not saved: this workflow was changed after this page loaded it/);
  assert.equal(byTestId(view, "workflow-confirmation").length, 0, "the confirmation of the old version is closed");
  assert.equal(reloads.length, 2, "reloaded after the success and after the stale refusal");
  act(() => view.unmount());
});
