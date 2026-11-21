// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workTransitionApply.test.mjs
//
// Frontend corrections from judge r7. The apply is bound to its preview: the preview's effects hash and workflow
// version (C-7) go back with the apply, and a 409 `preview_stale` asks for a new preview. The confirmation shows the
// target status (a transition name never poses as a status). Jira's offered transitions are read from the server's
// Python list even with apostrophes and mixed quotes. The audit timeline shows the labels applied and never shows a
// previous item's events. The preview and the apply send the item's last synced Jira update for the conflict guard.
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
  jiraEffectText,
  parseStringList,
  previewBinding,
  statusEffectText,
  transitionPlan,
  transitionRefusal,
} from "../../src/chat/work/workTransitionModel.ts";
import { readJson } from "../../src/admin/utils/adminPanelHelpers.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
const json = (value) => JSON.parse(JSON.stringify(value));

// ---- offers --------------------------------------------------------------------------------------

test("offered transitions are read from the server's Python list, apostrophes and escapes included; nothing else is guessed", () => {
  assert.deepEqual(parseStringList(`["Won't do -> Closed", 'Start -> In Progress']`), ["Won't do -> Closed", "Start -> In Progress"]);
  assert.deepEqual(parseStringList(`['It\\'s done -> Done', "Say \\"hi\\" -> Open"]`), ["It's done -> Done", 'Say "hi" -> Open']);
  assert.deepEqual(parseStringList("[]"), []);
  assert.deepEqual(parseStringList("[ 'a' ,'b' ]"), ["a", "b"]);
  for (const bad of ["['a', b]", "['a'", "'a'", "['a' 'b']", "['a' x 'b']", "[\"a', 'b']"]) assert.equal(parseStringList(bad), null, bad);
  const message = `Mapped Jira transition 'Done' is not available from the issue's current status. Jira offers: ["Won't do -> Closed", 'Start -> In Progress']`;
  // L-f: the offers are shown once, as the list; the sentence no longer repeats them raw.
  assert.deepEqual(json(transitionRefusal(new Error(message))), {
    text: "Mapped Jira transition 'Done' is not available from the issue's current status.",
    offers: ["Won't do -> Closed", "Start -> In Progress"], stale: false,
  });
  assert.equal(transitionRefusal(new Error("… Jira offers: ['broken")).offers, null, "an unreadable list keeps only the server's text");
  assert.deepEqual(transitionRefusal(new Error("… Jira offers: none")).offers, []);
});

// ---- target status -------------------------------------------------------------------------------

test("the confirmation names the target status; a transition is labelled as a transition", () => {
  assert.equal(statusEffectText({ value: "Start Progress" }, { target_status: "In Arbeit", transition: "Start Progress" }),
    "Status → In Arbeit (via the transition “Start Progress”)");
  assert.equal(statusEffectText({ value: "Start Progress" }, { transition: "Start Progress" }), "Transition “Start Progress” (Jira decides the resulting status)");
  assert.equal(statusEffectText({ value: "In Arbeit", target_status: "In Arbeit" }, {}), "Status → In Arbeit", "a C-7 effect may carry it itself");
  assert.equal(statusEffectText({ value: "Done" }, {}), "Status → Done");
  const plan = transitionPlan({ source_type: "jira", work_state: "intake" }, { sync_policy: { sync_mode: "execute" } },
    { jira_sync_preview: { will_mutate_jira: true, transition: "Start Progress", target_status: "In Arbeit", effects: [{ kind: "status", value: "Start Progress" }] } });
  assert.equal(plan.effects[0].text, "Status → In Arbeit (via the transition “Start Progress”)");
  const viaTransition = transitionPlan({ source_type: "jira", work_state: "intake" }, { sync_policy: { sync_mode: "execute" } },
    { jira_sync_preview: { will_mutate_jira: true, transition: "Start Progress", effects: [{ kind: "status", value: "Start Progress" }] } });
  assert.equal(viaTransition.effects[0].text, "Transition “Start Progress” (Jira decides the resulting status)");
});

// ---- binding and stale ---------------------------------------------------------------------------

test("the apply carries the preview's binding from the sync preview", () => {
  assert.deepEqual(json(previewBinding({ jira_sync_preview: { effects_hash: "h1", workflow_updated_at: "2026-10-05T10:00:00Z" } })),
    { effects_hash: "h1", workflow_updated_at: "2026-10-05T10:00:00Z" });
  assert.deepEqual(json(previewBinding({ jira_sync_preview: { effects_hash: "h2" } })), { effects_hash: "h2" });
  assert.deepEqual(json(previewBinding({ jira_sync_preview: {} })), {});
  assert.deepEqual(json(previewBinding(null)), {});
});

async function refusalFrom(status, detail) {
  const original = globalThis.fetch;
  globalThis.fetch = async () => ({ ok: false, status, statusText: "", json: async () => ({ detail }) });
  try {
    await readJson("/api/x", { method: "POST", body: "{}" });
  } catch (error) {
    return error;
  } finally { globalThis.fetch = original; }
  throw new Error("expected a refusal");
}

test("readJson keeps a refusal's fixed code; a stale preview is explained, not shown as the server's words", async () => {
  const coded = await refusalFrom(409, { code: "preview_stale", message: "Preview is stale" });
  assert.deepEqual([coded.status, coded.code, coded.message], [409, "preview_stale", "Preview is stale"]);
  assert.equal((await refusalFrom(409, { state: "refused", reason: "preview_stale" })).code, "preview_stale");
  assert.equal((await refusalFrom(409, { reason: "Not A Code!" })).code, null, "only a plain name is a code");
  assert.equal((await refusalFrom(409, "plain text")).code, null);
  const stale = transitionRefusal(coded);
  assert.equal(stale.stale, true);
  assert.match(stale.text, /changed after the preview, so nothing was applied\. Preview again/);
});

// ---- timeline ------------------------------------------------------------------------------------

test("the timeline names the labels applied", () => {
  const event = { id: "e", to_state: "development", dry_run: false, conflict: {},
    jira_sync_preview: { execution: { transition_name: "Start", resulting_status: "In Arbeit", comment_posted: true, labels_applied: ["octryx", "dev"] } } };
  assert.equal(jiraEffectText(event), "Jira: transition “Start” → In Arbeit, comment posted, labels applied: octryx, dev.");
  assert.equal(jiraEffectText({ ...event, jira_sync_preview: { execution: { transition_name: "Start", resulting_status: "X", labels_applied: [] } } }),
    "Jira: transition “Start” → X.");
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
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Intl, encodeURIComponent,
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

const WORKFLOW = {
  id: "wf-1", name: "Standard", project_id: "ws-1", is_default: true, is_active: true,
  states: [{ key: "intake", label: "Intake" }, { key: "development", label: "Development" }],
  mappings: {}, sync_policy: { sync_mode: "execute" },
};
const ITEM = { id: "wi-4", project_id: "ws-1", source_type: "jira", source_key: "BRD-4", title: "x", work_state: "intake", sync_state: "updated",
  last_source_updated_at: "2026-10-05T08:43:00+00:00" };
const PREVIEW = {
  valid: true, workflow_id: "wf-1", work_item_id: "wi-4", source_key: "BRD-4", from_state: "intake", to_state: "development", reason: "",
  jira_sync_preview: { mode: "dry_run", will_mutate_jira: true, transition: "Start Progress", target_status: "In Arbeit",
    effects: [{ kind: "status", value: "Start Progress" }], effects_hash: "sha256:abc", workflow_updated_at: "2026-10-05T09:00:00Z" },
  conflict: { has_conflict: false },
};

function server(applyAnswer) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ url: String(url), body });
    const answer = String(url).endsWith("/dry-run-transition") ? { status: 200, body: { preview: PREVIEW, event: {} } } : applyAnswer;
    return { ok: answer.status < 400, status: answer.status, statusText: "", json: async () => answer.body };
  };
  return { fetch, calls };
}
const choose = (view, value) => act(() => view.root.find((node) => node.type === "select" && node.props["aria-label"] === "Target state").props.onChange({ target: { value } }));
const button = (view, label) => view.root.findAll((node) => node.type === "button" && text(node).trim() === label)[0] ?? null;

test("rendered: preview and apply send the conflict guard; the apply sends the binding; the target status is shown", async () => {
  const srv = server({ status: 200, body: { item_id: "wi-4", work_state: "development", event: {}, preview: { ...PREVIEW, jira_sync_preview: { ...PREVIEW.jira_sync_preview, execution: { transition_name: "Start Progress", resulting_status: "In Arbeit" } } } } });
  const { WorkItemTransition } = load("chat/work/WorkItemTransition.tsx", { fetch: srv.fetch });
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkItemTransition, { item: ITEM, workflows: [WORKFLOW] })); });
  choose(view, "development");
  await act(async () => { button(view, "Preview").props.onClick(); });
  assert.deepEqual(srv.calls[0].body, { work_item_id: "wi-4", to_state: "development", reason: "", source: "ui_preview", source_jira_updated_at: "2026-10-05T08:43:00+00:00" });
  assert.deepEqual(byTestId(view, "transition-effects")[0].findAllByType("li").map(text), ["Status → In Arbeit (via the transition “Start Progress”)"]);
  await act(async () => { button(view, "Apply and write to Jira").props.onClick(); });
  assert.deepEqual(srv.calls[1].body, {
    workflow_id: "wf-1", to_state: "development", reason: "", source: "ui_apply", source_jira_updated_at: "2026-10-05T08:43:00+00:00",
    effects_hash: "sha256:abc", workflow_updated_at: "2026-10-05T09:00:00Z",
  });
  act(() => view.unmount());
});

test("rendered: a 409 preview_stale discards the preview and asks for a new one", async () => {
  const srv = server({ status: 409, body: { detail: { code: "preview_stale", message: "Preview is stale" } } });
  const { WorkItemTransition } = load("chat/work/WorkItemTransition.tsx", { fetch: srv.fetch });
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkItemTransition, { item: { ...ITEM, last_source_updated_at: null }, workflows: [WORKFLOW] })); });
  choose(view, "development");
  await act(async () => { button(view, "Preview").props.onClick(); });
  assert.equal("source_jira_updated_at" in srv.calls[0].body, false, "no guard without a synced update time");
  await act(async () => { button(view, "Apply and write to Jira").props.onClick(); });
  assert.match(text(byTestId(view, "transition-refusal")[0]), /^Not applied: The workflow or what it writes to Jira changed after the preview/);
  assert.equal(byTestId(view, "transition-confirmation").length, 0, "the stale preview cannot be applied again");
  assert.equal(button(view, "Apply and write to Jira"), null);
  act(() => view.unmount());
});

test("rendered: the timeline never shows the previous item's events while the next item loads", async () => {
  let release;
  const fetch = async (url) => {
    if (String(url).includes("/wi-a/")) {
      return { ok: true, status: 200, json: async () => ({ items: [{ id: "a1", from_state: "intake", to_state: "development", dry_run: false, jira_sync_preview: {}, conflict: {} }] }) };
    }
    await new Promise((resolve) => { release = resolve; });
    return { ok: true, status: 200, json: async () => ({ items: [] }) };
  };
  const { WorkItemStateTimeline } = load("chat/work/WorkItemStateTimeline.tsx", { fetch });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(WorkItemStateTimeline, { workItemId: "wi-a" })); });
  assert.equal(byTestId(view, "state-timeline").length, 1);
  await act(async () => { view.update(createElement(WorkItemStateTimeline, { workItemId: "wi-b" })); });
  assert.equal(byTestId(view, "state-timeline").length, 0, "item A's events are gone");
  assert.match(text(view.root), /Loading the audit timeline/);
  await act(async () => { release(); });
  assert.match(text(view.root), /No state change recorded yet\./);
  act(() => view.unmount());
});
