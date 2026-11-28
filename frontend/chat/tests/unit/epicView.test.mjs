// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/epicView.test.mjs
//
// Work › Epics: the selected Epic's lanes come from the backend (`/work-items/{id}/progress`); the page only maps and
// renders them. Names and numbers are invented.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import {
  barSegments,
  chooseEpic,
  epicProgressPath,
  epicsOf,
  needsYouText,
  readEpicProgress,
  reasonText,
  tasksDoneText,
} from "../../src/chat/work/epicViewModel.ts";
import { workLocation, workViewOf } from "../../src/chat/work/workNavRedirects.ts";
import { workAreaGroup, workAreaLabel } from "../../src/chat/work/workAreaMenu.ts";
import { byTestId, load, server, text } from "./workCodingSupport.mjs";

const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const item = (id, key, extra = {}) => ({ id, source_key: key, title: `Title ${key}`, source_type: "platform",
  source_instance: "octryx", issue_type: "story", ...extra });
const row = (id, key, lane, extra = {}) => ({ id, key, title: `Title ${key}`, issue_type: "Story", url: "", work_state: "development",
  source_status: "", lane, reason: "", checks: null, needs_you: false, run: null, pull_request: null, ...extra });

const ITEMS = [
  item("e1", "OCX-1", { issue_type: "Epic", title: "benchmark run web v1" }),
  item("s2", "OCX-2", { epic_key: "OCX-1" }),
  item("e9", "OCX-9", { issue_type: "epic" }),
];

const PAYLOAD = {
  epic: { id: "e1", key: "OCX-1", title: "benchmark run web v1", url: "https://jira.test/OCX-1", work_state: "development", source_status: "" },
  summary: { done: 1, in_review: 1, in_progress: 1, open: 1, total: 4, needs_you: 1 },
  stories: [
    row("s5", "OCX-5", "done", { reason: "merged", tasks: [], tasks_done: 0 }),
    row("s10", "OCX-10", "open", { reason: "ready_for_development", tasks: [], tasks_done: 0 }),
    row("s2", "OCX-2", "in_review", { reason: "pull request open", checks: "failed",
      pull_request: { url: "https://scm.test/pr/1471", status: "open" },
      tasks: [row("t2", "OCX-21", "open", { issue_type: "Sub-task" }), row("t1", "OCX-20", "done", { issue_type: "Sub-task", reason: "done" })],
      tasks_done: 1 }),
    row("s3", "OCX-3", "in_progress", { reason: "Implement", needs_you: true, checks: "running",
      run: { id: "r3", status: "waiting", phase: "Implement" }, tasks: [], tasks_done: 0 }),
  ],
};

test("epics come from issue_type; the selection falls back to the first epic", () => {
  assert.deepEqual(epicsOf(ITEMS).map((entry) => entry.source_key), ["OCX-1", "OCX-9"]);
  assert.equal(chooseEpic(epicsOf(ITEMS), "OCX-9").id, "e9");
  assert.equal(chooseEpic(epicsOf(ITEMS), "OCX-404").id, "e1");
  assert.equal(chooseEpic([], null), null);
  assert.equal(epicProgressPath("e 1"), "/api/v1/secure-work/work-items/e%201/progress");
});

test("endpoint rows map to view rows: needs-you first, then review, progress, open, done last", () => {
  const progress = readEpicProgress(PAYLOAD);
  assert.deepEqual(progress.stories.map((story) => story.key), ["OCX-3", "OCX-2", "OCX-10", "OCX-5"]);
  const review = progress.stories[1];
  assert.deepEqual({ lane: review.lane, checks: review.checks, pr: review.pullRequest, done: tasksDoneText(review) },
    { lane: "in_review", checks: "failed", pr: { url: "https://scm.test/pr/1471", status: "open" }, done: "1/2 tasks done" });
  assert.deepEqual(review.tasks.map((task) => task.key), ["OCX-21", "OCX-20"]);
  assert.equal(progress.stories[0].runPhase, "Implement");
  assert.equal(progress.stories[0].needsYou, true);
  assert.equal(tasksDoneText(progress.stories[3]), "");
  assert.equal(reasonText("ready_for_development"), "Ready for development");
  assert.equal(reasonText(""), "");
});

test("junk answers map to an honest empty progress; unknown lanes and checks are not invented", () => {
  const empty = readEpicProgress(null);
  assert.deepEqual(empty.stories, []);
  assert.deepEqual(empty.summary, { done: 0, in_review: 0, in_progress: 0, open: 0, total: 0, needsYou: 0 });
  const odd = readEpicProgress({ stories: [{ id: "x", key: "K-1", lane: "weird", checks: "purple" }] });
  assert.equal(odd.stories[0].lane, "open");
  assert.equal(odd.stories[0].checks, null);
  assert.deepEqual(odd.stories[0].tasks, []);
});

test("the bar has four segments in lane order with shares of the total; needs-you reads as a count", () => {
  const summary = { done: 6, in_review: 2, in_progress: 3, open: 3, total: 14, needsYou: 2 };
  assert.deepEqual(barSegments(summary).map((s) => [s.label, s.count, s.share]),
    [["Done", 6, 42.9], ["In review", 2, 14.3], ["In progress", 3, 21.4], ["Open", 3, 21.4]]);
  assert.deepEqual(barSegments({ ...summary, done: 0, in_review: 0, in_progress: 0, open: 0, total: 0 }).map((s) => s.share), [0, 0, 0, 0]);
  assert.equal(needsYouText(summary), "2 need you");
  assert.equal(needsYouText({ ...summary, needsYou: 1 }), "1 needs you");
  assert.equal(needsYouText({ ...summary, needsYou: 0 }), "");
});

test("Epics is a Work page in Deliver with its own address", () => {
  assert.equal(workLocation("?work_view=epics").nav, "epics");
  assert.equal(workViewOf({ nav: "epics", itemsMode: "board", plansTab: "all" }), "epics");
  assert.equal(workAreaLabel("work", "epics"), "Epics");
  assert.equal(workAreaGroup("work", "epics"), "Deliver");
});

test("rendered: the bar counts, stories by lane with chip, reason, checks, PR and indented tasks", async () => {
  const srv = server(() => ({ status: 200, body: PAYLOAD }));
  const { WorkEpicsPage } = load("chat/work/WorkEpicsPage.tsx", { fetch: srv.fetch, performance });
  const opened = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(WorkEpicsPage, { items: ITEMS, projectId: "ws-1", reloadKey: 0,
      onOpenItem: (entry) => opened.push(entry.id) }));
  });
  assert.deepEqual(srv.calls.map((call) => call.url), ["/api/v1/secure-work/work-items/e1/progress"], "one read, no run list");

  assert.match(text(view.root), /OCX-1 · benchmark run web v1/);
  const counts = text(byTestId(view, "work-epics-counts")[0]);
  for (const part of ["1 Done", "1 In review", "1 In progress", "1 Open", "4 stories", "1 needs you"]) assert.ok(counts.includes(part), part);
  const stories = byTestId(view, "work-epics-story");
  assert.deepEqual(stories.map((story) => story.props["data-lane"]), ["in_progress", "in_review", "open", "done"]);
  const review = text(stories[1]);
  for (const part of ["OCX-2 · Title OCX-2", "In review", "Checks failed", "Pull request (open)", "1/2 tasks done"]) {
    assert.ok(review.includes(part), part);
  }
  assert.equal(review.split("Pull request").length - 1, 1, "the open pull request is named once");
  assert.equal(stories[1].findAll((node) => node.props["data-testid"] === "work-epics-task").length, 2);
  assert.match(text(stories[0]), /Needs you.*Checks running.*Implement/);
  assert.match(text(stories[2]), /Ready for development/);

  const open = (story) => story.findAll((node) => node.type === "button")[0];
  await act(async () => open(stories[1]).props.onClick());
  assert.deepEqual(opened, ["s2"]);
  act(() => view.unmount());
});

test("rendered: a failed read says so and offers a retry, never derived data", async () => {
  const srv = server(() => ({ status: 500, body: { detail: "progress unavailable" } }));
  const { WorkEpicsPage } = load("chat/work/WorkEpicsPage.tsx", { fetch: srv.fetch, performance });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(WorkEpicsPage, { items: ITEMS, onOpenItem: () => {} })); });
  assert.match(text(view.root), /progress unavailable/);
  assert.equal(byTestId(view, "work-epics-story").length, 0);
  assert.equal(byTestId(view, "work-epics-counts").length, 0);
  act(() => view.unmount());
});

test("rendered: no epic says so", async () => {
  const { WorkEpicsPage } = load("chat/work/WorkEpicsPage.tsx", { fetch: server(() => ({ status: 200, body: {} })).fetch });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(WorkEpicsPage, { items: [ITEMS[1]], onOpenItem: () => {} })); });
  assert.match(text(byTestId(view, "work-epics-empty")[0]), /No epics yet/);
  act(() => view.unmount());
});
