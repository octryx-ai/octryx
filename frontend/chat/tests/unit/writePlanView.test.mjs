// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/writePlanView.test.mjs
// A chat writes after one confirmation per request. The card reads the gate's
// "write_plan" preview into the scope chips, one row per write with every field in full, and the result line.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  WRITE_PLAN_NOTE,
  isWritePlanRefusal,
  toolWords,
  writePlanNotice,
  writePlanResult,
  writePlanView,
} from "../../src/chat/approval/writePlanView.ts";
import { foldToolSteps } from "../../src/chat/toolStepFoldModel.ts";

const LONG = "As a cook I see this week's meals.\n".repeat(30);

// The payload shape of contract §3 (changePreview.preview).
const PLAN = {
  kind: "write_plan",
  plan_id: "wp_1",
  amends: null,
  request: "Create the Kitchen helper v1 Epic with its three stories\nand a working branch",
  title: "Write plan: 3 writes",
  scope: [
    { kind: "jira_project", value: "CHEF", named_by: "scope" },
    { kind: "repository", value: "app", named_by: "scope" },
    { kind: "branch", value: "feature/kitchen-helper", named_by: "writes" },
    { kind: "jira_project", value: "chef", named_by: "writes" },
    { kind: "confluence_page", value: "Kitchen helper v1 overview", named_by: "writes" },
  ],
  writes: [
    { index: 0, tool: "create_jira_ticket", connector: "jira", connection: "Jira",
      fields: { project_key: "CHEF", issue_type: "Epic", summary: "Kitchen helper v1", labels: ["kitchen-helper", "v1"] }, why: "the Epic",
      title: "Create Epic Kitchen helper v1 in CHEF", details: ["issue type: Epic"] },
    { index: 1, tool: "create_jira_ticket", connector: "jira", connection: "Jira",
      fields: { project_key: "CHEF", issue_type: "Story", summary: "Weekly meal plan", description: LONG } },
    { index: 2, tool: "create_bitbucket_branch", connector: "bitbucket", connection: "Bitbucket Cloud",
      fields: { repo_slug: "app", branch_name: "feature/kitchen-helper" }, before: null, after: { branch: "feature/kitchen-helper" } },
  ],
  standing_rule: null,
};

test("a write plan reads as heading, the request in one line and the write count", () => {
  const view = writePlanView(PLAN);
  assert.equal(view.heading, "Confirm the write plan");
  assert.equal(view.request, "Create the Kitchen helper v1 Epic with its three stories and a working branch");
  assert.equal(view.countLabel, "3 writes");
  assert.equal(view.amendment, false);
  assert.equal(view.many, false);
});

test("the scope is labelled chips grouped by system, writes-named entries included, each value once", () => {
  const view = writePlanView(PLAN);
  assert.deepEqual(
    view.scope.map((group) => [group.label, group.chips.map((chip) => chip.text)]),
    [
      ["Code", ["Repository app", "Branch feature/kitchen-helper"]],
      ["Jira", ["Jira project CHEF"]],
      ["Confluence", ["Confluence page Kitchen helper v1 overview"]],
    ],
  );
});

test("each write reads as an action in words with its connection and why; every field in full", () => {
  const [epic, story, branch] = writePlanView(PLAN).writes;
  assert.equal(epic.action, "Create Epic Kitchen helper v1 in CHEF", "the tool's own title wins");
  assert.equal(epic.subject, "");
  assert.equal(epic.connection, "Jira");
  assert.equal(epic.why, "the Epic");
  assert.deepEqual(epic.details, ["issue type: Epic"]);
  assert.deepEqual(epic.fields.find((field) => field.key === "labels"), { key: "labels", label: "Labels", value: "kitchen-helper, v1" });
  assert.equal(story.action, "Create Jira ticket", "never raw snake_case");
  assert.equal(story.subject, "Weekly meal plan");
  assert.equal(story.fields.find((field) => field.key === "description").value, LONG, "never shortened");
  assert.equal(branch.action, "Create Bitbucket branch");
  assert.equal(branch.subject, "feature/kitchen-helper");
  assert.equal(branch.connection, "Bitbucket Cloud");
  assert.match(branch.after, /"branch": "feature\/kitchen-helper"/);
  assert.equal(branch.before, "");
});

test("an amendment shows only the new writes and keeps the confirmed ones apart", () => {
  const view = writePlanView({
    ...PLAN, amends: "wp_1", writes: [PLAN.writes[0]],
    confirmed_writes: [{ tool: "create_bitbucket_branch", connection: "Bitbucket Cloud", fields: { branch_name: "feature/kitchen-helper" } }],
  });
  assert.equal(view.heading, "Confirm a change to the plan");
  assert.equal(view.countLabel, "1 write");
  assert.equal(view.confirmed.length, 1);
  assert.equal(view.confirmed[0].action, "Create Bitbucket branch");
  assert.equal(writePlanView(PLAN).confirmed.length, 0, "a first plan has no confirmed part");
});

test("from 4 writes on, rows start collapsed so Approve stays reachable", () => {
  const writes = (n) => Array.from({ length: n }, (_, index) => ({ ...PLAN.writes[1], index }));
  assert.equal(writePlanView({ ...PLAN, writes: writes(3) }).many, false);
  assert.equal(writePlanView({ ...PLAN, writes: writes(4) }).many, true);
});

test("other approvals keep their own card", () => {
  assert.equal(writePlanView({ kind: "tool_execution", connection: "Jira", details: [] }), null);
  assert.equal(writePlanView(null), null);
});

test("decided plans are one calm line naming the decider; a pending one has none", () => {
  const view = writePlanView(PLAN);
  const me = { approvedBy: "u-me", currentUserId: "u-me" };
  const anna = { approvedBy: "u-anna", approvedByName: "Anna Keller", currentUserId: "u-me" };
  assert.equal(writePlanResult("pending", view, me), null);
  assert.equal(writePlanResult("approved", view, me).label, "Plan confirmed by you · 3 writes");
  assert.equal(writePlanResult("approved", view, anna).label, "Plan confirmed by Anna Keller · 3 writes");
  assert.equal(writePlanResult("approved", view, { approvedBy: "u-anna", currentUserId: "u-me" }).label,
    "Plan confirmed by another person · 3 writes", "never a raw user id");
  assert.equal(writePlanResult("approved", view, { approvedBy: "u-me" }).label,
    "Plan confirmed by another person · 3 writes", "not 'you' without knowing the viewer");
  assert.equal(writePlanResult("approved", view).label, "Plan confirmed · 3 writes");
  assert.equal(writePlanResult("approved", { amendment: true, count: 1 }, me).label, "Change confirmed by you · 1 write");
  assert.equal(writePlanResult("rejected", view, me).label, "Rejected by you");
  assert.equal(writePlanResult("rejected", view, anna).label, "Rejected by Anna Keller");
  assert.equal(writePlanResult("rejected", view).label, "Rejected");
  assert.equal(writePlanResult("approved", view).tone, "neutral");
  assert.match(WRITE_PLAN_NOTE, /without asking again/);
});

test("the session's confirmed plan is a quiet notice with count and scope", () => {
  assert.equal(writePlanNotice(null), null);
  assert.equal(
    writePlanNotice({ planId: "wp_1", writes: [{}, {}, {}, {}], scope: PLAN.scope }),
    "Write plan confirmed · 4 writes · scope Repository app, Branch feature/kitchen-helper, Jira project CHEF +1",
  );
});

test("tool names read as words with product names spelled right", () => {
  assert.equal(toolWords("create_github_pull_request"), "Create GitHub pull request");
  assert.equal(toolWords("ask_reporter_via_teams"), "Ask reporter via Teams");
});

test("the gate's write-plan refusals are one quiet line in the tool fold, never a failure", () => {
  const refusal = (id, code) => ({ id, toolName: "create_jira_ticket", status: "error", parameters: {}, durationMs: 5,
    result: { error: "Propose the plan first", code, next_tool: "propose_write_plan" } });
  assert.equal(isWritePlanRefusal(refusal("a", "write_plan_required").result), true);
  assert.equal(isWritePlanRefusal({ detail: { code: "write_plan_amendment_required" } }), true);
  assert.equal(isWritePlanRefusal({ code: "role_tool_not_granted" }), false);
  const fold = foldToolSteps([refusal("a", "write_plan_required"), refusal("b", "write_plan_required"),
    refusal("c", "write_plan_amendment_required")]);
  assert.equal(fold.failures.length, 1);
  assert.equal(fold.failures[0].text, "Preparing the write plan");
  assert.equal(fold.failures[0].blocked, true);
});
