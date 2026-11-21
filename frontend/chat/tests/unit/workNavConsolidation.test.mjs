// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workNavConsolidation.test.mjs
//
// Work navigation: Work items with a Board | Table toggle, Plans with All plans |
// Waiting for review, Pull requests as the one PR source; the removed entries redirect to their new home; one plan
// status vocabulary. Requests are stubs; names invented.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { workLocation, workViewOf } from "../../src/chat/work/workNavRedirects.ts";
import { FINAL_PLAN_STATUSES, planStatusLabel } from "../../src/chat/work/planStatus.ts";
import { byTestId, load, server, text } from "./workCodingSupport.mjs";

const { WORK_NAV_ITEMS } = load("chat/work/WorkNav.tsx");

const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

test("one Work address per page: the written names reopen their page, unrecognized names open the home page", () => {
  assert.deepEqual(workLocation("?work_view=table"), { nav: "board", itemsMode: "table", plansTab: "all" });
  assert.deepEqual(workLocation("?work_view=reviews"), { nav: "changePlans", itemsMode: "board", plansTab: "review" });
  for (const former of ["?view=reviews", "?work_view=planReviews", "?work_view=syncSettings", "?work_view=items",
    "?work_view=engineeringProfiles", "?work_view=toString"]) {
    assert.deepEqual(workLocation(former), workLocation(""), former);
  }
  assert.equal(workLocation("?work_item_id=a&change_plan_id=b").nav, "changePlans");
  assert.equal(workLocation("").nav, "runs", "Work opens on Runs");
  assert.equal(workLocation("?work_view=board").nav, "board");
  for (const page of [{ nav: "intake", itemsMode: "board", plansTab: "all" }, { nav: "board", itemsMode: "table", plansTab: "all" },
    { nav: "changePlans", itemsMode: "board", plansTab: "review" }, { nav: "writeback", itemsMode: "board", plansTab: "all" }]) {
    assert.deepEqual(workLocation(`?work_view=${workViewOf(page)}`), page, "the written address reopens the same page");
  }
  const labels = WORK_NAV_ITEMS.map((item) => item.label);
  assert.ok(!labels.includes("Work Items") && !labels.includes("Plan reviews") && !labels.includes("PR Coordination"));
  assert.ok(!labels.includes("Repositories") && !labels.includes("Engineering Profiles") && !labels.includes("Sync Settings"));
  assert.ok(["Work items", "Plans", "Intake", "Jira write-back"].every((label) => labels.includes(label)));
  assert.ok(!labels.includes("Pull requests"), "a PR is seen on its run and its work item; there is no PR page");
});

test("one plan status vocabulary", () => {
  assert.equal(planStatusLabel("ready_for_review"), "Waiting for review");
  assert.ok(FINAL_PLAN_STATUSES.has("superseded") && !FINAL_PLAN_STATUSES.has("draft"));
});

test("rendered Plans: All plans and Waiting for review with counts, scoped to the Workspace", async () => {
  const srv = server(() => ({ status: 200, body: { items: [], next_cursor: null, status_counts: { approved: 2, ready_for_review: 1, draft: 1 } } }));
  const { WorkPlansPage } = load("chat/work/WorkPlansPage.tsx", { fetch: srv.fetch });
  const tabs = [];
  let view;
  await act(async () => { view = TestRenderer.create(createElement(WorkPlansPage, { tab: "all", onTab: (tab) => tabs.push(tab), projectId: "ws-1",
    reloadKey: 0, selectedPlanId: null, onOpenPlan: () => {}, onOpenApprovalRule: () => {} })); });
  const tabButtons = view.root.findAll((node) => node.props.role === "tab");
  assert.deepEqual(tabButtons.map((node) => text(node)), ["All plans4", "Waiting for review1"]);
  assert.ok(srv.calls.every((call) => call.url.includes("project_id=ws-1")));
  await act(async () => { tabButtons[1].props.onClick(); });
  assert.deepEqual(tabs, ["review"]);
  act(() => view.unmount());
});

test("rendered reviewer suggestions: a declared name stays named; selecting sends the user or the name", async () => {
  const payload = { work_item_id: "i1", source_key: "CLM-1", change_unit_count: 1, missing_setup: [], overrides: [], recommendations: [
    { user_id: "u1", display_name: "bob", primary_email: "bob@example.test", score: 45, available: true, teams: [], skills: [],
      approval_roles: ["member"], scm_username: "bob.scm", evidence: [{ kind: "default_reviewer", points: 40, reason: "Declared default reviewer bob.scm." }] },
    { user_id: null, display_name: "Claims backend team", score: 30, available: true, teams: [], skills: [], approval_roles: [], evidence: [] },
  ] };
  const srv = server((url, method) => ({ status: 200, body: method === "POST" ? { id: "o1" } : payload }));
  const { WorkReviewerRecommendations } = load("chat/work/WorkReviewerRecommendations.tsx", { fetch: srv.fetch });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(WorkReviewerRecommendations, { item: { id: "i1" } })); });
  assert.match(text(view.root), /Declared name, not a Workspace member/);
  await act(async () => { view.root.findAll((node) => node.type === "button" && text(node) === "Select reviewer")[1].props.onClick(); });
  const posted = srv.calls.find((call) => call.method === "POST").body;
  assert.equal(posted.selected_user_id, null);
  assert.equal(posted.selected_reviewer, "Claims backend team");
  act(() => view.unmount());
});
