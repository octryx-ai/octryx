// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workJiraTaskList.test.mjs
//
// Jira Cloud ↔ integrated task list, frontend (F-1..F-5). F-1: the board has a column per workflow state
// (ready_for_development, development, …) plus one per state outside the vocabulary, so no item is hidden and every
// counter matches its cards. F-2: people by display name (id fallback), filters by id labelled with names, search by
// name. F-3: a transition is previewed, then applied in an explicit step whose confirmation lists exactly what is
// written to Jira; a 409 shows Jira's offered transitions; the audit timeline lists the state events. F-4: the
// request and comments are plain-text paragraphs (never HTML), sprint/board by name, the Workspace by name. F-5: the
// Workspace connectors say when the server does not list Jira/Confluence.
process.env.TZ = "Europe/Zurich";

import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { SHARED_WORK_STATES, workBoardColumns, workStateKey } from "../../src/chat/work/workBoardColumns.ts";
import { assigneeFilterOptions, assigneeLabel, personLabel, reporterLabel, watcherLabels } from "../../src/chat/work/workPeople.ts";
import { filterWorkItems, EMPTY_WORK_FILTERS } from "../../src/chat/work/workUtils.ts";
import {
  jiraEffectText,
  preselectedWorkflow,
  targetStates,
  transitionPlan,
  transitionRefusal,
  transitionResultText,
  workflowsForItem,
} from "../../src/chat/work/workTransitionModel.ts";
import {
  boardText,
  commentsView,
  sprintText,
  statusMappingText,
  textBlocks,
  workspaceName,
} from "../../src/chat/work/workItemDetailModel.ts";
import { globalConnectorStatus } from "../../src/admin/components/projectsTab/workspaceConnectorTableState.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
const json = (value) => JSON.parse(JSON.stringify(value));

const ACCOUNT = "5ab515fe4373ef2a697c2c9c";
const item = (overrides = {}) => ({
  id: "wi-4", project_id: "ws-1", source_type: "jira", source_instance: "octryx", source_key: "BRD-4",
  source_project_key: "BRD", title: "Payments API returns 503 under peak load", work_state: "ready_for_development",
  sync_state: "updated", source_status: "Zu erledigen", assignee: ACCOUNT, assignee_display: "Jane Doe",
  reporter: ACCOUNT, reporter_display: null, watchers: [ACCOUNT, "acc-2"], watchers_display: [{ id: ACCOUNT, display: "Jane Doe" }, { id: "acc-2", display: null }],
  labels: [], fix_versions: ["2026.11 BLUE-HERON"], ...overrides,
});
const WORKFLOW = {
  id: "wf-1", name: "Standard", project_id: "ws-1", is_default: true, is_active: true,
  states: SHARED_WORK_STATES.map((state) => ({ ...state })),
  mappings: { development: { source_status: "In Arbeit", sync_back: true, comment_template: "Started by PRJ" } },
  sync_policy: { sync_mode: "execute" },
};

// ---- F-1 ----------------------------------------------------------------------------------------

test("F-1: one column per workflow state, then states outside the vocabulary; every item exactly once", () => {
  const items = [
    item({ id: "1", work_state: "ready_for_development" }), item({ id: "2", work_state: "development" }),
    item({ id: "3", work_state: "intake" }), item({ id: "4", work_state: "in_progress" }), item({ id: "5", work_state: "Ready For-Development" }),
    item({ id: "6", work_state: "" }),
  ];
  const custom = { ...WORKFLOW, id: "wf-2", is_default: false, states: [{ key: "triage", label: "Triage" }, { key: "intake", label: "Inbox" }] };
  const columns = workBoardColumns(items, [custom, WORKFLOW, { ...WORKFLOW, id: "off", is_active: false, states: [{ key: "hidden", label: "Hidden" }] }]);
  const keys = columns.map((column) => column.key);
  assert.deepEqual(keys.slice(0, 3), ["intake", "clarification", "ready_for_plan"], "the default workflow's states come first");
  assert.ok(keys.includes("triage") && !keys.includes("hidden"), "other active workflows add their states; inactive ones do not");
  assert.equal(columns.find((column) => column.key === "intake").label, "Intake", "the default workflow's label wins");
  assert.deepEqual(columns.at(-1), { key: "in_progress", label: "In progress", outsideVocabulary: true, items: [items[3]] },
    "a legacy state gets its own column, never re-mapped");
  assert.deepEqual(columns.find((column) => column.key === "ready_for_development").items.map((entry) => entry.id), ["1", "5"]);
  assert.deepEqual(columns.find((column) => column.key === "development").items.map((entry) => entry.id), ["2"]);
  assert.deepEqual(columns.find((column) => column.key === "intake").items.map((entry) => entry.id), ["3", "6"], "no state is intake");
  assert.equal(columns.reduce((sum, column) => sum + column.items.length, 0), items.length, "no item hidden, none twice");
  assert.deepEqual(workBoardColumns([], []).map((column) => column.key), SHARED_WORK_STATES.map((state) => state.key),
    "without workflows the shared vocabulary still shows every state");
  assert.equal(workStateKey(" Plan Review "), "plan_review");
});

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
      window: { location: { origin: "http://localhost" }, setTimeout: () => 0, confirm: () => true }, ...extra,
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

test("rendered F-1: every column's counter equals its cards, and the cards add up to the items", () => {
  const { WorkBoard } = load("chat/work/WorkAreaViews.tsx");
  const items = [item({ id: "1" }), item({ id: "2", work_state: "development" }), item({ id: "3", work_state: "done" }), item({ id: "4", work_state: "in_progress" })];
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkBoard, { items, syncConfigs: [], onOpenItem: () => {}, workflows: [WORKFLOW] })); });
  // Done is folded with its count visible; one click shows its cards.
  const toggle = view.root.findByProps({ "data-testid": "board-done-toggle" });
  assert.equal(text(toggle), "Show 1 done");
  act(() => toggle.props.onClick());
  const columns = view.root.findAll((node) => node.type === "section" && node.props.className === "work-board__column");
  let cards = 0;
  for (const column of columns) {
    const count = Number(text(column.findByType("strong")));
    const shown = column.findAll((node) => node.type === "button" && node.props.className === "work-card").length;
    assert.equal(count, shown, column.props["data-state"]);
    cards += shown;
  }
  assert.equal(cards, items.length);
  assert.equal(view.root.findByProps({ className: "work-board" }).props.style.gridTemplateColumns,
    `repeat(${columns.length}, minmax(13rem, 1fr))`, "all columns on one scrolling row, not wrapped under the first six");
  const state = (key) => columns.find((column) => column.props["data-state"] === key);
  assert.ok(state("ready_for_development") && state("development") && state("in_progress"));
  assert.match(text(state("ready_for_development")), /Ready for development1/);
  act(() => view.unmount());
});

// ---- F-2 ----------------------------------------------------------------------------------------

test("F-2: people by display name with the id as fallback; filters match ids, labelled and sorted by name", () => {
  assert.equal(personLabel(ACCOUNT, " Jane Doe "), "Jane Doe");
  assert.equal(personLabel(ACCOUNT, null), ACCOUNT);
  assert.equal(personLabel(null, null), "");
  assert.equal(assigneeLabel(item()), "Jane Doe");
  assert.equal(assigneeLabel(item({ assignee: null, assignee_display: null })), "Unassigned");
  assert.equal(reporterLabel(item()), ACCOUNT, "no display name: the id");
  assert.deepEqual(watcherLabels(item()), ["Jane Doe", "acc-2"]);
  assert.deepEqual(watcherLabels(item({ watchers_display: undefined })), [ACCOUNT, "acc-2"], "without display names: the ids");
  const options = assigneeFilterOptions([
    item({ id: "1", assignee: "acc-z", assignee_display: "Anna" }), item({ id: "2", assignee: ACCOUNT, assignee_display: null }),
    item({ id: "3", assignee: ACCOUNT, assignee_display: "Jane Doe" }), item({ id: "4", assignee: null }),
  ]);
  assert.deepEqual(json(options), { values: ["acc-z", ACCOUNT], labels: { "acc-z": "Anna", [ACCOUNT]: "Jane Doe" } });
  assert.equal(assigneeFilterOptions([item({ id: "1", assignee_display: "Jane Doe" }), item({ id: "2", assignee_display: null })]).labels[ACCOUNT],
    "Jane Doe", "a later item without a name never replaces a known name with the id");
  const items = [item({ id: "1" }), item({ id: "2", assignee: "acc-z", assignee_display: "Anna" })];
  assert.deepEqual(filterWorkItems(items, { ...EMPTY_WORK_FILTERS, assignees: [ACCOUNT] }).map((entry) => entry.id), ["1"], "filters keep the id");
  assert.deepEqual(filterWorkItems(items, { ...EMPTY_WORK_FILTERS, search: "anna" }).map((entry) => entry.id), ["2"], "search finds the name");
});

test("rendered F-2: card and table show the name", () => {
  const { WorkBoard, WorkTable } = load("chat/work/WorkAreaViews.tsx");
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkTable, { items: [item()], syncConfigs: [], onOpenItem: () => {} })); });
  assert.match(text(view.root), /Jane Doe/);
  assert.doesNotMatch(text(view.root), new RegExp(ACCOUNT));
  act(() => view.update(createElement(WorkBoard, { items: [item()], syncConfigs: [], onOpenItem: () => {}, workflows: [] })));
  assert.match(text(view.root), /Jane Doe/);
  act(() => view.unmount());
});

// ---- F-3 model ----------------------------------------------------------------------------------

const preview = (sync, conflict = { has_conflict: false }) => ({
  valid: true, workflow_id: "wf-1", work_item_id: "wi-4", source_key: "BRD-4", from_state: "ready_for_development",
  to_state: "development", reason: "", jira_sync_preview: { mode: "dry_run", will_mutate_jira: false, ...sync }, conflict,
});

test("F-3: workflow choice, target states, and exactly what an apply writes to Jira", () => {
  const global = { ...WORKFLOW, id: "wf-g", project_id: null, is_default: true };
  const other = { ...WORKFLOW, id: "wf-o", project_id: "ws-9" };
  assert.deepEqual(workflowsForItem(item(), [global, other, WORKFLOW, { ...WORKFLOW, id: "off", is_active: false }]).map((entry) => entry.id), ["wf-g", "wf-1"]);
  assert.equal(preselectedWorkflow(item(), [global, WORKFLOW]).id, "wf-1", "the Workspace's own workflow first");
  assert.equal(preselectedWorkflow(item({ project_id: "ws-x" }), [global]).id, "wf-g");
  assert.equal(preselectedWorkflow(item(), []), null);
  assert.equal(targetStates(item(), WORKFLOW).some((state) => state.key === "ready_for_development"), false, "not the current state");
  assert.equal(targetStates(item(), null).length, 0);

  const written = transitionPlan(item(), WORKFLOW, preview({ will_mutate_jira: true,
    effects: [{ kind: "status", value: "In Arbeit" }, { kind: "comment", value: "Started by PRJ" }, { kind: "labels", value: ["octryx", "dev"] }] }));
  assert.deepEqual(json(written), { writesToJira: true, localReason: null, conflict: null, blocked: null, offers: [], effects: [
    { kind: "status", text: "Status → In Arbeit" }, { kind: "comment", text: "Comment: Started by PRJ" }, { kind: "labels", text: "Labels: octryx, dev" },
  ] });
  const dryOnly = transitionPlan(item(), { ...WORKFLOW, sync_policy: { sync_mode: "dry_run_only" } },
    preview({ will_mutate_jira: false, effects: [{ kind: "status", value: "In Arbeit" }] }));
  assert.equal(dryOnly.writesToJira, false);
  assert.deepEqual(json(dryOnly.effects), [], "nothing listed as written when nothing is");
  assert.match(dryOnly.localReason, /dry-run mode only/);
  assert.match(transitionPlan(item(), WORKFLOW, preview({ effects: [] , sync_back: false })).localReason, /no Jira sync-back/);
  assert.match(transitionPlan(item({ source_type: "platform" }), WORKFLOW, preview({ effects: [] })).localReason, /not from Jira/);
  // The server's `will_mutate_jira` decides; nothing is inferred from the mapping.
  assert.equal(transitionPlan(item(), WORKFLOW, preview({ sync_back: true, target_status: "In Arbeit", effects: [] })).writesToJira, false,
    "nothing to write");
  assert.match(transitionPlan(item(), WORKFLOW, preview({ effects: [] }, { has_conflict: true, reason: "updated in Jira" })).conflict,
    /^Jira changed after this item was last synced \(updated in Jira\): run the intake sync first/);
});

test("F-3: a 409 refusal lists Jira's offers; results and timeline entries say what Jira got", () => {
  const offered = transitionRefusal(new Error("Mapped Jira transition 'In Arbeit' is not available from the issue's current status. Jira offers: ['Start -> In Progress', 'Done -> Fertig']"));
  assert.deepEqual(json(offered.offers), ["Start -> In Progress", "Done -> Fertig"]);
  assert.match(offered.text, /^Mapped Jira transition 'In Arbeit' is not available/);
  assert.deepEqual(json(transitionRefusal(new Error("… Jira offers: none")).offers), []);
  assert.deepEqual(json(transitionRefusal(new Error("Workflow requests a Jira transition but the project has no Jira credentials configured"))),
    { text: "Workflow requests a Jira transition but the project has no Jira credentials configured", offers: null, stale: false });
  assert.equal(transitionRefusal("x").text, "The transition was not applied.");

  assert.equal(transitionResultText("Development", preview({ execution: { executed: true, transition_name: "Start", resulting_status: "In Arbeit", comment_posted: true, labels_applied: ["octryx"] } })),
    "Moved to Development. Jira: transition “Start” → In Arbeit; comment posted; labels applied: octryx.");
  assert.equal(transitionResultText("Development", preview({})), "Moved to Development. Nothing was written to Jira.");
  assert.equal(transitionResultText("Review", preview({ execution: { mode: "comment_only" } })), "Moved to Review. Jira: comment posted, status unchanged.");
  const event = (overrides) => ({ id: "e", to_state: "development", dry_run: false, jira_sync_preview: {}, conflict: {}, ...overrides });
  assert.equal(jiraEffectText(event({ dry_run: true })), "Jira: nothing written (preview).");
  assert.equal(jiraEffectText(event({ jira_sync_preview: { execution: { transition_name: "Start", resulting_status: "In Arbeit", comment_posted: true } } })),
    "Jira: transition “Start” → In Arbeit, comment posted.");
  assert.equal(jiraEffectText(event({})), "Jira: nothing written.");
});

// ---- F-3 rendered -------------------------------------------------------------------------------

function server(routes) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : null;
    calls.push({ url: String(url), method: init.method || "GET", body });
    const answer = routes(String(url), init.method || "GET", body);
    return { ok: answer.status < 400, status: answer.status, statusText: "", json: async () => answer.body };
  };
  return { fetch, calls };
}
const button = (view, label) => view.root.find((node) => node.type === "button" && text(node).trim() === label);
const choose = (view, label, value) => act(() => view.root.find((node) => node.type === "select" && node.props["aria-label"] === label).props.onChange({ target: { value } }));

test("rendered F-3: preview, then an explicit apply that lists what is written to Jira; a stale preview is never applied", async () => {
  const effects = [{ kind: "status", value: "In Arbeit" }, { kind: "comment", value: "Started by PRJ" }];
  const srv = server((url, method, body) => {
    if (url.endsWith("/dry-run-transition")) return { status: 200, body: { preview: preview({ will_mutate_jira: true, effects }), event: {} } };
    if (url.endsWith("/transition")) {
      return { status: 200, body: { item_id: "wi-4", work_state: body.to_state, event: {},
        preview: preview({ will_mutate_jira: true, effects, execution: { transition_name: "Start", resulting_status: "In Arbeit", comment_posted: true } }) } };
    }
    return { status: 404, body: {} };
  });
  const { WorkItemTransition } = load("chat/work/WorkItemTransition.tsx", { fetch: srv.fetch });
  const applied = [];
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkItemTransition, { item: item(), workflows: [WORKFLOW], onApplied: () => applied.push(1) })); });
  assert.equal(button(view, "Preview").props.disabled, true, "a target state first");
  choose(view, "Target state", "development");
  await act(async () => { button(view, "Preview").props.onClick(); });
  assert.deepEqual(byTestId(view, "transition-effects")[0].findAllByType("li").map(text), ["Status → In Arbeit", "Comment: Started by PRJ"]);
  assert.match(text(byTestId(view, "transition-confirmation")[0]), /^Ready for development → Development/);
  assert.equal(srv.calls.filter((call) => call.url.endsWith("/transition")).length, 0, "the preview applies nothing");

  choose(view, "Target state", "review");
  assert.equal(byTestId(view, "transition-confirmation").length, 0, "a changed choice discards the preview");
  choose(view, "Target state", "development");
  await act(async () => { button(view, "Preview").props.onClick(); });
  await act(async () => { button(view, "Apply and write to Jira").props.onClick(); });
  const apply = srv.calls.find((call) => call.url.endsWith("/work-items/wi-4/transition"));
  assert.deepEqual(apply.body, { workflow_id: "wf-1", to_state: "development", reason: "", source: "ui_apply" });
  assert.equal(text(byTestId(view, "transition-result")[0]), "Moved to Development. Jira: transition “Start” → In Arbeit; comment posted.");
  assert.equal(applied.length, 1);
  act(() => view.unmount());
});

test("rendered F-3: a 409 shows Jira's offers; a conflict blocks the apply; a local transition says so", async () => {
  const refusal = "Mapped Jira transition 'In Arbeit' is not available from the issue's current status. Jira offers: ['Start -> In Progress']";
  let conflict = false;
  let local = false;
  const srv = server((url) => {
    if (url.endsWith("/dry-run-transition")) {
      return { status: 200, body: { preview: preview(local ? { will_mutate_jira: false, effects: [], sync_back: false } : { will_mutate_jira: true, effects: [{ kind: "status", value: "In Arbeit" }] },
        conflict ? { has_conflict: true, reason: null } : { has_conflict: false }), event: {} } };
    }
    return { status: 409, body: { detail: refusal } };
  });
  const { WorkItemTransition } = load("chat/work/WorkItemTransition.tsx", { fetch: srv.fetch });
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkItemTransition, { item: item(), workflows: [WORKFLOW] })); });
  choose(view, "Target state", "development");
  await act(async () => { button(view, "Preview").props.onClick(); });
  await act(async () => { button(view, "Apply and write to Jira").props.onClick(); });
  const shown = byTestId(view, "transition-refusal")[0];
  assert.match(text(shown), /^Not applied: Mapped Jira transition 'In Arbeit' is not available/);
  assert.deepEqual(shown.findAllByType("li").map(text), ["Start -> In Progress"]);

  conflict = true;
  choose(view, "Target state", "review");
  await act(async () => { button(view, "Preview").props.onClick(); });
  assert.equal(button(view, "Apply and write to Jira").props.disabled, true);
  conflict = false;
  local = true;
  choose(view, "Target state", "done");
  await act(async () => { button(view, "Preview").props.onClick(); });
  assert.match(text(byTestId(view, "transition-local")[0]), /no Jira sync-back/);
  assert.equal(button(view, "Apply in Octryx").props.disabled, false);
  act(() => view.unmount());
});

test("rendered F-3: the audit timeline lists applied and previewed state events", async () => {
  const srv = server(() => ({ status: 200, body: { items: [
    { id: "e2", from_state: "ready_for_development", to_state: "development", dry_run: false, reason: "go", created_at: "2026-10-05T10:00:00Z",
      jira_sync_preview: { execution: { transition_name: "Start", resulting_status: "In Arbeit", comment_posted: false } }, conflict: {} },
    { id: "e1", from_state: "ready_for_development", to_state: "development", dry_run: true, created_at: "2026-10-05T09:59:00Z", jira_sync_preview: {}, conflict: {} },
  ] } }));
  const { WorkItemStateTimeline } = load("chat/work/WorkItemStateTimeline.tsx", { fetch: srv.fetch });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(WorkItemStateTimeline, { workItemId: "wi-4", reloadKey: 0 })); });
  const entries = byTestId(view, "state-timeline")[0].findAllByType("li").map(text);
  // L-f: states by their human label (shared vocabulary without workflows).
  assert.match(entries[0], /^Ready for development → Development · applied · .*12:00.*Reason: goJira: transition “Start” → In Arbeit\.$/);
  assert.match(entries[1], /preview \(dry run\).*Jira: nothing written \(preview\)\.$/);
  await act(async () => { view.update(createElement(WorkItemStateTimeline, { workItemId: "wi-4", reloadKey: 1 })); });
  assert.equal(srv.calls.length, 2, "reloads after an apply");
  act(() => view.unmount());
});

// ---- F-4 ----------------------------------------------------------------------------------------

test("F-4: plain-text paragraphs and lists, sprint/board/Workspace by name, mapping source, comments", () => {
  assert.deepEqual(json(textBlocks("First line\nsecond line\n\n- one\n- two\n\n<b>bold</b>")), [
    { kind: "paragraph", lines: ["First line", "second line"] },
    { kind: "list", items: ["one", "two"] },
    { kind: "paragraph", lines: ["<b>bold</b>"] },
  ]);
  assert.deepEqual(textBlocks("  "), []);
  assert.equal(sprintText({}), "-", "an empty object is none");
  assert.equal(sprintText(null), "-");
  assert.equal(sprintText({ id: 5, name: "BRD Sprint 1", state: "active", goal: "x" }), "BRD Sprint 1 (active)");
  assert.equal(sprintText({ id: 7 }), "7");
  assert.equal(boardText({}), "-");
  assert.equal(boardText({ id: 1, name: "BRD board" }), "BRD board");
  assert.equal(workspaceName("ws-1", [{ id: "ws-1", name: "Confluence Cloud Acceptance" }]), "Confluence Cloud Acceptance");
  assert.equal(workspaceName("ws-9", []), "ws-9");
  assert.equal(workspaceName(null, []), "No Workspace");
  assert.match(statusMappingText(item({ status_mapping: { source: "status_category", category: "indeterminate" } })), /status category “indeterminate”/);
  assert.match(statusMappingText(item({ status_mapping: { source: "unmapped" } })), /stays in Intake/);
  assert.equal(statusMappingText(item()), null, "not reported");
  assert.deepEqual(json(commentsView(item())), { state: "not_reported" });
  assert.deepEqual(json(commentsView(item({ comments: [{ id: "1" }], comments_total: 3 }))), { state: "listed", comments: [{ id: "1" }], older: 2 });
});

test("rendered F-4: request and comments render as text (no HTML), people and Workspace by name, safe comment links", () => {
  const { WorkItemJiraSource } = load("chat/work/WorkItemJiraSource.tsx");
  const shown = item({
    description: "During the peak the API returned 503.\nRoot cause: pool capped.\n\n* raise the pool\n* enable the breaker\n\n<script>alert(1)</script>",
    sprint: { id: 5, name: "BRD Sprint 1", state: "active", goal: "Stabilise payments" }, board: { id: 1, name: "BRD board" },
    comments: [
      { id: "c1", author: ACCOUNT, author_display: "Jane Doe", created: "2026-10-05T08:43:00+00:00", body: "Looking at it.", url: "https://your-site.atlassian.net/browse/BRD-4?focusedCommentId=c1" },
      { id: "c2", author: "acc-2", author_display: null, created: "2026-10-05T09:00:00Z", body: "Second", url: "javascript:alert(1)" },
    ],
    comments_total: 2,
  });
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkItemJiraSource, { item: shown, projects: [{ id: "ws-1", name: "Confluence Cloud Acceptance" }], acceptanceCriteria: "-" })); });
  const request = byTestId(view, "work-request-text")[0];
  assert.equal(request.findAllByType("p").length, 2);
  assert.equal(request.findAllByType("p")[0].findAllByType("br").length, 1, "a line break inside a paragraph is kept");
  assert.deepEqual(request.findByType("ul").findAllByType("li").map(text), ["raise the pool", "enable the breaker"]);
  assert.match(text(request), /<script>alert\(1\)<\/script>/, "markup stays text");
  assert.equal(view.root.findAll((node) => node.props.dangerouslySetInnerHTML).length, 0);
  assert.equal(view.root.findAll((node) => node.type === "script").length, 0);
  const all = text(view.root);
  for (const expected of [/WorkspaceConfluence Cloud Acceptance/, /AssigneeJane Doe/, new RegExp(`Reporter${ACCOUNT}`), /SprintBRD Sprint 1 \(active\) · goal: Stabilise payments/, /BoardBRD board/]) {
    assert.match(all, expected);
  }
  const comments = byTestId(view, "work-comments")[0].findAllByType("li");
  assert.match(text(comments[0]), /^Jane Doe · .*10:43.* · Open in JiraLooking at it\.$/);
  assert.equal(comments[0].findByType("a").props.href, "https://your-site.atlassian.net/browse/BRD-4?focusedCommentId=c1");
  assert.equal(comments[1].findAllByType("a").length, 0, "an unsafe link is not rendered");
  assert.match(text(comments[1]), /^acc-2 · /);
  act(() => view.unmount());
});

// ---- F-5 ----------------------------------------------------------------------------------------

test("F-5: a product without a global entry points to its own connection", () => {
  assert.equal(globalConnectorStatus({ global_configured: false, global_active: false }, true),
    "not configured · this Workspace can use its own connection");
  assert.equal(globalConnectorStatus({ global_configured: false, global_active: false }, false), "not configured");
  assert.equal(globalConnectorStatus({ global_configured: true, global_active: false }, true), "configured but inactive");
});

test("rendered F-5: a listed Jira card without any entry is offered", async () => {
  const { ProjectConnectorSettingsSection } = load("admin/components/projectsTab/ProjectConnectorSettingsSection.tsx");
  const { AdminNavigationContext } = load("admin/adminNavigation.ts");
  const access = (connector_name, label) => ({
    connector_name, label, description: "", limit_fields: [], global_configured: false, global_active: false,
    project_enabled: false, project_configured: false, project_limits: {}, inherited_limits: {}, effective_limits: {}, inherits_global_limits: true,
  });
  const mount = async (connectors) => {
    const readJson = async (url) => (url.endsWith("/connection")
      ? { source: "global", fields: {}, secret_status: {}, global: { configured: false, active: false }, health: null }
      : { project_id: "ws-1", connectors });
    let view;
    await act(async () => {
      view = TestRenderer.create(createElement(AdminNavigationContext.Provider, { value: { openAdminTab: () => {} } },
        createElement(ProjectConnectorSettingsSection, { ctx: { configuringProjectQuality: { id: "ws-1" }, readJson } })));
    });
    return view;
  };
  const listed = await mount([access("confluence", "Confluence"), access("jira", "Jira")]);
  // One table row per connector; the platform state in a word, its sentence as the tooltip.
  const jira = byTestId(listed, "connector-platform-state-jira")[0];
  assert.equal(text(jira), "Not set up");
  assert.equal(jira.props.title, "Platform connector: not configured · this Workspace can use its own connection");
  // Each connector's own-connection form is reachable in its side panel.
  for (const name of ["confluence", "jira"]) {
    const row = listed.root.find((node) => node.type === "tr" && node.props["data-row-key"] === name);
    await act(async () => { row.props.onClick(); });
    assert.equal(byTestId(listed, "workspace-connection").length, 1, `${name}: the own-connection form is in its panel`);
  }
  act(() => listed.unmount());
});
