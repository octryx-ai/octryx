// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workJiraLiveRetest.test.mjs
//
// Root live re-test, frontend L-f (screens 480–498): the confirmation's heading, what is written and the actions
// each sit on their own line; a refusal shows Jira's offered transitions once (as the parsed list, not again raw in the
// sentence) and leaves no confirmation to apply; the timeline and the "Work state" filter use human state labels and
// the timeline names the labels written (or that they failed); the board hides empty states (named, one click shows
// them) so the populated columns fit. Also the C-7 refusals workflow_inactive and scope_not_allowed.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { jiraEffectText, transitionRefusal, transitionResultText } from "../../src/chat/work/workTransitionModel.ts";
import { workStateFilterLabels, workStateLabel } from "../../src/chat/work/workBoardColumns.ts";
import { readJson } from "../../src/admin/utils/adminPanelHelpers.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);

const OFFERS_MESSAGE = "Mapped Jira transition 'Start QA sign-off' is not available from the issue's current status. "
  + "Jira offers: ['Zu erledigen -> Zu erledigen', 'In Bearbeitung -> In Bearbeitung', 'Erledigt -> Erledigt']";

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

// ---- refusals ------------------------------------------------------------------------------------

test("a refusal names the offers once: the sentence without the raw list, the list parsed", async () => {
  const refusal = transitionRefusal(new Error(OFFERS_MESSAGE));
  assert.equal(refusal.text, "Mapped Jira transition 'Start QA sign-off' is not available from the issue's current status.");
  assert.deepEqual([...refusal.offers], ["Zu erledigen -> Zu erledigen", "In Bearbeitung -> In Bearbeitung", "Erledigt -> Erledigt"]);
  const unreadable = "… Jira offers: ['broken";
  assert.deepEqual({ ...transitionRefusal(new Error(unreadable)) }, { text: unreadable, offers: null, stale: false },
    "an unreadable list keeps the server's whole text");
  const inactive = transitionRefusal(await refusalFrom(409, { code: "workflow_inactive", message: "Workflow is inactive" }));
  assert.match(inactive.text, /^This workflow is deactivated, so it cannot move items\./);
  assert.equal(inactive.stale, true, "the preview is discarded");
  const scope = transitionRefusal(await refusalFrom(409, { state: "refused", reason: "scope_not_allowed" }));
  assert.match(scope.text, /outside the Workspace's allowed Jira projects, so nothing was written to Jira\./);
});

test("results and the timeline say when labels could not be added", () => {
  const execution = { transition_name: "Start", resulting_status: "In Arbeit", comment_posted: false, labels_applied: [], labels_failed: true };
  assert.equal(transitionResultText("Development", { jira_sync_preview: { execution } }),
    "Moved to Development. Jira: transition “Start” → In Arbeit; no comment posted; the labels could not be added.");
  assert.equal(jiraEffectText({ dry_run: false, jira_sync_preview: { execution } }),
    "Jira: transition “Start” → In Arbeit, the labels could not be added.");
  assert.equal(jiraEffectText({ dry_run: false, jira_sync_preview: { execution: { ...execution, labels_failed: false, labels_applied: ["octryx"] } } }),
    "Jira: transition “Start” → In Arbeit, labels applied: octryx.");
});

// ---- labels --------------------------------------------------------------------------------------

const WORKFLOW = {
  id: "wf-1", name: "Standard", project_id: "ws-1", is_default: true, is_active: true,
  states: [{ key: "intake", label: "Inbox" }, { key: "qa_signoff", label: "QA sign-off" }, { key: "development", label: "Development" }],
  mappings: {}, sync_policy: { sync_mode: "execute" },
};

test("states read by their human label: the workflow's, else the shared vocabulary's, else the key in words", () => {
  assert.equal(workStateLabel("qa_signoff", [WORKFLOW]), "QA sign-off");
  assert.equal(workStateLabel("intake", [WORKFLOW]), "Inbox");
  assert.equal(workStateLabel("intake", [{ ...WORKFLOW, is_active: false }]), "Intake", "an inactive workflow does not name states");
  assert.equal(workStateLabel("ready_for_development"), "Ready for development");
  assert.equal(workStateLabel("in_progress"), "In progress");
  assert.equal(workStateLabel(null), "Intake");
  assert.deepEqual(workStateFilterLabels(["qa_signoff", "ready_for_development"], [WORKFLOW]),
    { qa_signoff: "QA sign-off", ready_for_development: "Ready for development" });
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

const ITEM = { id: "wi-6", project_id: "ws-1", source_type: "jira", source_key: "BRD-6", title: "x", work_state: "development", sync_state: "updated" };
const PREVIEW = {
  valid: true, workflow_id: "wf-1", work_item_id: "wi-6", source_key: "BRD-6", from_state: "development", to_state: "qa_signoff", reason: "",
  jira_sync_preview: { mode: "dry_run", will_mutate_jira: true, transition: "Start QA sign-off", target_status: null, effects_hash: "h",
    effects: [{ kind: "status", value: "Start QA sign-off", transition: "Start QA sign-off", target_status: null }] },
  conflict: { has_conflict: false },
};
const choose = (view, value) => act(() => view.root.find((node) => node.type === "select" && node.props["aria-label"] === "Target state").props.onChange({ target: { value } }));
const button = (view, label) => view.root.findAll((node) => node.type === "button" && text(node).trim() === label)[0] ?? null;

test("rendered: heading, what is written and actions are separate lines; a 409 shows the offers once and no confirmation", async () => {
  const fetch = async (url) => (String(url).endsWith("/dry-run-transition")
    ? { ok: true, status: 200, json: async () => ({ preview: PREVIEW, event: {} }) }
    : { ok: false, status: 409, statusText: "", json: async () => ({ detail: OFFERS_MESSAGE }) });
  const { WorkItemTransition } = load("chat/work/WorkItemTransition.tsx", { fetch });
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkItemTransition, { item: ITEM, workflows: [WORKFLOW] })); });
  choose(view, "qa_signoff");
  await act(async () => { button(view, "Preview").props.onClick(); });
  const confirmation = byTestId(view, "transition-confirmation")[0];
  assert.equal(confirmation.props.className, "work-transition__block");
  assert.deepEqual(confirmation.children.map((child) => child.type), ["p", "p", "ul", "div"],
    "heading, 'Written to Jira', the effects and the actions are block elements of their own");
  assert.equal(text(byTestId(view, "transition-heading")[0]), "Development → QA sign-off");
  await act(async () => { button(view, "Apply and write to Jira").props.onClick(); });
  const refusal = byTestId(view, "transition-refusal")[0];
  assert.equal(text(refusal).split("In Bearbeitung -> In Bearbeitung").length - 1, 1, "each offer appears once");
  assert.deepEqual(refusal.findAllByType("li").map(text), ["Zu erledigen -> Zu erledigen", "In Bearbeitung -> In Bearbeitung", "Erledigt -> Erledigt"]);
  assert.equal(byTestId(view, "transition-confirmation").length, 0, "the refused confirmation is gone");
  act(() => view.unmount());
});

test("rendered: the timeline shows human state labels", async () => {
  const fetch = async () => ({ ok: true, status: 200, json: async () => ({ items: [
    { id: "e1", from_state: "development", to_state: "qa_signoff", dry_run: false, jira_sync_preview: {}, conflict: {}, created_at: "2026-10-05T10:00:00Z" },
  ] }) });
  const { WorkItemStateTimeline } = load("chat/work/WorkItemStateTimeline.tsx", { fetch });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(WorkItemStateTimeline, { workItemId: "wi-6", workflows: [WORKFLOW] })); });
  assert.match(text(byTestId(view, "state-timeline")[0]), /^Development → QA sign-off · applied/);
  act(() => view.unmount());
});

test("rendered board: empty states are hidden and named; one click shows every state; counters match cards", () => {
  const { WorkBoard } = load("chat/work/WorkAreaViews.tsx");
  const items = [
    { ...ITEM, id: "1", work_state: "development" }, { ...ITEM, id: "2", work_state: "development" },
    { ...ITEM, id: "3", work_state: "done" }, { ...ITEM, id: "4", work_state: "in_progress" },
  ];
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkBoard, { items, syncConfigs: [], onOpenItem: () => {}, workflows: [WORKFLOW] })); });
  const sections = () => view.root.findAll((node) => node.type === "section" && node.props.className === "work-board__column");
  assert.deepEqual(sections().map((section) => section.props["data-state"]), ["development", "done", "in_progress"]);
  assert.equal(view.root.findByProps({ className: "work-board" }).props.style.gridTemplateColumns, "repeat(3, minmax(13rem, 1fr))");
  const note = byTestId(view, "board-empty-states")[0];
  assert.match(text(note), /^13 empty columns hidden\.Show all columns$/);
  act(() => note.findByType("button").props.onClick());
  assert.equal(sections().length, 16, "every state again: 3 workflow + 12 more shared + 1 legacy");
  assert.match(text(byTestId(view, "board-empty-states")[0]), /^Showing all 16 columns\.Hide empty columns$/);
  act(() => byTestId(view, "board-done-toggle")[0].props.onClick());
  for (const section of sections()) {
    assert.equal(Number(text(section.findByType("strong"))), section.findAll((node) => node.props.className === "work-card").length);
  }
  act(() => view.unmount());
});
