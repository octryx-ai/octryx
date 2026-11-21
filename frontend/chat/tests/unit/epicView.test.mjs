// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/epicView.test.mjs
//
// Work › Epics (Alex OK on the mock "Work: epic, stories, tasks"): the epic's counts, then each story (work
// item with the epic's key in `epic_key`) with its task bar, status, pull request and cost; open, its tasks. Names and
// numbers are invented.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import {
  chooseEpic,
  decisionRun,
  epicsOf,
  epicSummary,
  initiallyOpen,
  progressShares,
  runsByItem,
  storiesOf,
  storyCost,
  storyProgress,
  storyPullRequest,
  storySeat,
  storyStatus,
} from "../../src/chat/work/epicViewModel.ts";
import { costText } from "../../src/chat/work/workRunsModel.ts";
import { workLocation, workViewOf } from "../../src/chat/work/workNavRedirects.ts";
import { workAreaGroup, workAreaLabel } from "../../src/chat/work/workAreaMenu.ts";
import { byTestId, load, server, text } from "./workCodingSupport.mjs";

const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const item = (id, key, extra = {}) => ({ id, source_key: key, title: `Title ${key}`, source_type: "platform",
  source_instance: "octryx", issue_type: "story", ...extra });
const task = (id, status, extra = {}) => ({ id, text: `Task ${id}`, proof: `tests/test_${id}.py::test_x`, done: null, status, ...extra });
const run = (id, workItemId, status, extra = {}) => ({ id, title: id, workflow_key: "epic-delivery", workflow_kind: "phased",
  status, waiting_kind: null, pause_reason: null, outcome: null, updated_at: null, work_item_id: workItemId, ...extra });

const ITEMS = [
  item("e1", "OCX-1", { issue_type: "Epic", title: "benchmark run web v1" }),
  item("s10", "OCX-10", { epic_key: "OCX-1" }),
  item("s2", "OCX-2", { epic_key: "OCX-1" }),
  item("s3", "OCX-3", { epic_key: "OCX-9" }),
  item("e9", "OCX-9", { issue_type: "epic" }),
];

test("epics and their stories come from issue_type and epic_key; stories by key", () => {
  assert.deepEqual(epicsOf(ITEMS).map((entry) => entry.source_key), ["OCX-1", "OCX-9"]);
  assert.deepEqual(storiesOf(ITEMS, "OCX-1").map((entry) => entry.source_key), ["OCX-2", "OCX-10"]);
  assert.deepEqual(storiesOf(ITEMS, ""), []);
  assert.equal(chooseEpic(epicsOf(ITEMS), "OCX-9").id, "e9");
  assert.equal(chooseEpic(epicsOf(ITEMS), "OCX-404").id, "e1", "an unknown address falls back to the first epic");
  assert.equal(chooseEpic([], null), null);
  const byItem = runsByItem([run("a", "s2", "running"), run("b", null, "running"), run("c", "s2", "completed")]);
  assert.deepEqual(byItem.get("s2").map((entry) => entry.id), ["a", "c"]);
  assert.equal(byItem.size, 1);
});

test("a story reads like the mock: progress, bar, status, pull request, cost", () => {
  const tasks = [task("T1", "verified"), task("T2", "verified"), task("T3", "done"), task("T4", "done"),
    task("T5", "changes", { note: "Review: wrong list." }), task("T6", "in_progress"), task("T7", "open")];
  assert.equal(storyProgress(tasks), "4/7 done · 2 verified · 1 changes · 1 in progress");
  assert.deepEqual(progressShares(tasks), { done: 57, changes: 14 });
  assert.equal(storyProgress([task("T1", "open"), task("T2", "open")]), "2 tasks · nothing built yet");
  assert.equal(storyProgress([]), "No task list yet");
  assert.deepEqual(progressShares([]), { done: 0, changes: 0 });

  const waiting = run("w", "s2", "waiting", { session_id: "sess-1", cost: 1.2,
    pull_request: { id: 1471, url: "https://scm.test/pr/1471" } });
  const older = run("o", "s2", "completed", { cost: 1.1 });
  const story = { item: ITEMS[2], tasks, runs: [waiting, older] };
  assert.deepEqual(storyStatus(story), { label: "Needs you", tone: "attention" });
  assert.deepEqual(storyPullRequest(story.runs), { label: "PR #1471", url: "https://scm.test/pr/1471" });
  assert.equal(costText(storyCost(story.runs)), "$2.30");
  assert.equal(decisionRun(story.runs).id, "w");

  assert.equal(storyStatus({ ...story, runs: [run("r", "s2", "running")] }).label, "Building");
  assert.equal(storyStatus({ ...story, runs: [run("r", "s2", "completed", { pull_request: { id: 9, url: "u" } })] }).label, "Shipped");
  assert.equal(storyStatus({ ...story, item: { ...story.item, work_state: "done" }, runs: [] }).label, "Shipped");
  assert.equal(storyStatus({ ...story, runs: [run("r", "s2", "failed")] }).label, "Failed");
  assert.equal(storyStatus({ ...story, runs: [] }).label, "Ready to build");
  assert.equal(storyStatus({ ...story, tasks: [], runs: [] }).label, "Draft");
  assert.equal(storyPullRequest([]), null);
  const linkless = [{ ...run("r", "s2", "completed"), pull_request: { id: 41, url: "", state: "open" } }];
  assert.deepEqual(storyPullRequest(linkless), { label: "PR #41", url: null });
  assert.equal(storyStatus({ ...story, runs: linkless }).label, "Shipped");
  assert.equal(costText(storyCost([])), "–");
});

test("the epic header counts shipped stories, done tasks, changes, decisions and cost; the waiting story opens", () => {
  const stories = [
    { item: ITEMS[2], tasks: [task("T1", "verified"), task("T2", "changes")], runs: [run("w", "s2", "waiting", { cost: 0.5 })] },
    { item: ITEMS[1], tasks: [task("T1", "done")], runs: [run("c", "s10", "completed", { cost: 1, pull_request: { id: 2, url: "u" } })] },
    { item: item("s4", "OCX-4"), tasks: [], runs: [] },
  ];
  assert.deepEqual(epicSummary(stories), { stories: 3, shipped: 1, tasks: 3, tasksDone: 2, tasksWithChanges: 1, decisions: 1, cost: 1.5,
    seat: { equivalentUsd: 0, unpricedCalls: 0 } });
  assert.equal(initiallyOpen(stories), "s2");
  assert.equal(initiallyOpen([stories[1]]), null);
});

test("Epics is a Work page in Deliver with its own address", () => {
  assert.equal(workLocation("?work_view=epics").nav, "epics");
  assert.equal(workViewOf({ nav: "epics", itemsMode: "board", plansTab: "all" }), "epics");
  assert.equal(workAreaLabel("work", "epics"), "Epics");
  assert.equal(workAreaGroup("work", "epics"), "Deliver");
});

test("a story and the epic sum the seat's API equivalent apart from the API cost", () => {
  const seatRun = run("a", "s2", "completed", { cost: 0, seat_api_equivalent: 10.25, seat_unpriced_calls: 2 });
  const apiRun = run("b", "s2", "completed", { cost: 1.5, seat_api_equivalent: 0.5, seat_unpriced_calls: 1 });
  assert.equal(storyCost([seatRun, apiRun]), 1.5, "the API cost holds no seat figure");
  assert.deepEqual(storySeat([seatRun, apiRun]), { equivalentUsd: 10.75, unpricedCalls: 3 });
  const summary = epicSummary([{ item: ITEMS[2], tasks: [], runs: [seatRun, apiRun] }]);
  assert.equal(summary.cost, 1.5);
  assert.deepEqual(summary.seat, { equivalentUsd: 10.75, unpricedCalls: 3 });
});

test("rendered: header counts, one row per story, tasks inside, story detail on request", async () => {
  const details = {
    s2: { ...ITEMS[2], task_list: [task("T1", "verified"), task("T2", "changes", { note: "Review: T2 reads the global list." })] },
    s10: { ...ITEMS[1], task_list: [task("T1", "open")] },
  };
  const srv = server((url) => {
    if (url.includes("/api/v1/workflow-runs")) {
      return { status: 200, body: { runs: [run("w", "s2", "waiting", { session_id: "sess-1", cost: 2.3,
        seat_api_equivalent: 10, seat_unpriced_calls: 3, pull_request: { id: 1471, url: "https://scm.test/pr/1471" } })] } };
    }
    const id = decodeURIComponent(url.split("/").pop());
    return { status: 200, body: details[id] };
  });
  const { WorkEpicsPage } = load("chat/work/WorkEpicsPage.tsx", { fetch: srv.fetch, performance });
  const opened = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(WorkEpicsPage, { items: ITEMS, projectId: "ws-1", reloadKey: 0,
      onOpenItem: (entry) => opened.push(entry.id) }));
  });
  assert.ok(srv.calls.some((call) => call.url.endsWith("/api/v1/workflow-runs?view=work&project_id=ws-1")));
  assert.ok(srv.calls.some((call) => call.url.endsWith("/work-items/s2")) && srv.calls.some((call) => call.url.endsWith("/work-items/s10")));
  assert.ok(!srv.calls.some((call) => call.url.endsWith("/work-items/s3")), "a story of another epic is not read");

  const page = text(view.root);
  assert.match(page, /OCX-1 · benchmark run web v1/);
  const counts = text(byTestId(view, "work-epics-counts")[0]);
  for (const part of ["0 of 2 stories shipped", "1 of 3 tasks done", "1 task with changes", "1 decision waiting for you", "$2.30 API cost",
    "$10.00 seat: would cost via API (list price)", "3 seat calls: no list price (seat only)"]) {
    assert.ok(counts.includes(part), part);
  }
  assert.ok(!counts.includes("$12.30"), "the API cost and the seat equivalent are never added together");
  const rows = byTestId(view, "work-epics-story");
  assert.deepEqual(rows.map((row) => text(row).split(" · ")[0]), ["OCX-2", "OCX-10"]);
  assert.equal(rows[0].props.open, true, "the story that needs a person is open");
  const first = text(rows[0]);
  for (const part of ["1/2 done · 1 verified · 1 changes", "Needs you", "PR #1471", "$2.30", "Seat $10.00 (list price)", "Changes requested",
    "Review: T2 reads the global list.", "Open decision"]) {
    assert.ok(first.includes(part), part);
  }
  assert.match(text(rows[1]), /1 task · nothing built yet/);
  assert.match(text(rows[1]), /Ready to build/);
  const openStory = rows[1].findAll((node) => node.type === "button" && text(node) === "Open the story")[0];
  act(() => openStory.props.onClick());
  assert.deepEqual(opened, ["s10"]);
  act(() => view.unmount());
});

test("rendered: no epic says so", async () => {
  const { WorkEpicsPage } = load("chat/work/WorkEpicsPage.tsx", { fetch: server(() => ({ status: 200, body: { runs: [] } })).fetch });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(WorkEpicsPage, { items: [ITEMS[1]], onOpenItem: () => {} })); });
  assert.match(text(byTestId(view, "work-epics-empty")[0]), /No epics yet/);
  act(() => view.unmount());
});
