// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// Starting a phased workflow from the chat (contract `phased_start.py`): the start card's view state is read from
// the session's proposal, and every answer (Start with its run location, Don't start, Other workflow) has one body.
import assert from "node:assert/strict";
import { test } from "node:test";

import { otherWorkflowChoices, proposalAnswerBody, proposalAnswerProblem } from "../../src/chat/run/workflowProposalAnswer.ts";
import { jiraProblemText, needsConfiguration, repositoryBlockedReason, runOnHelp, startBlockedReason, startButtonLabel, startedLinkLabel, workflowStartView } from "../../src/chat/run/workflowStartModel.ts";
import { buildWorkflowProposalDecision } from "../../src/chat/run/workflowDecisionSend.ts";
import { answerDetailText } from "../../src/chat/run/workflowProposalAnswer.ts";

const RUN_ON = {
  options: [
    { key: "auto", label: "Automatic", help: "Uses a free seat on your device first." },
    { key: "server", label: "Server" },
    { key: "dev-1", label: "lca-mac (/code/kitchen-helper, seat)", online: false },
  ],
  default: "auto",
};

function proposal(start, extra = {}) {
  return {
    proposalId: "p-1",
    status: "needs_confirmation",
    reasonCode: "explicit_phased_selection",
    workflowKey: "spec-writing",
    workflowTitle: "Spec writing",
    confidence: null,
    reason: "Chosen in the composer.",
    changeCapable: true,
    decision: null,
    phased: true,
    start,
    started: null,
    ...extra,
  };
}

const NEW_EPIC = {
  workflow_key: "spec-writing",
  workflow_title: "Spec writing",
  work_item: { mode: "new", type: "epic", type_label: "Epic", title: "Hello Kitchen", description: "Build 'Hello Kitchen'.", key: null, id: null },
  project_id: "ws-1",
  jira_project: "CHEF",
  run_on: RUN_ON,
  steps: [{ title: "Read the request" }, { title: "" }, { title: "Write the stories" }],
  summary: "Start Spec writing for a new Epic 'Hello Kitchen'",
  notes: ["The request names Jira project CHEF.", "  "],
};

test("a new Epic: summary, draft, Jira project, notes and steps without empty entries", () => {
  const view = workflowStartView(proposal(NEW_EPIC));
  assert.equal(view.summary, "Start Spec writing for a new Epic 'Hello Kitchen'");
  assert.deepEqual(
    { mode: view.item.mode, type: view.item.typeLabel, title: view.item.title, href: view.item.href, long: view.item.longDescription },
    { mode: "new", type: "Epic", title: "Hello Kitchen", href: null, long: false },
  );
  assert.equal(view.jiraProject, "CHEF");
  assert.deepEqual(view.notes, ["The request names Jira project CHEF."]);
  assert.deepEqual(view.steps, ["Read the request", "Write the stories"]);
  assert.deepEqual(view.outcome, { kind: "none" });
});

test("an existing item shows its key and links to it in the Work area", () => {
  const start = { ...NEW_EPIC, work_item: { mode: "existing", type: "story", type_label: "Story", title: "Login", description: "", key: "CHEF-12", id: "item-9" } };
  const item = workflowStartView(proposal(start)).item;
  assert.equal(item.key, "CHEF-12");
  assert.equal(item.href, "/chat?area=work&workspace_id=ws-1&work_item_id=item-9");
});

test("a long description starts folded", () => {
  const start = { ...NEW_EPIC, work_item: { ...NEW_EPIC.work_item, description: "x".repeat(400) } };
  assert.equal(workflowStartView(proposal(start)).item.longDescription, true);
});

test("Run on: the server's default is selected, offline options are marked and explained", () => {
  const { runOn } = workflowStartView(proposal(NEW_EPIC));
  assert.equal(runOn.selected, "auto");
  assert.deepEqual(runOn.options.map((option) => option.label), ["Automatic", "Server", "lca-mac (/code/kitchen-helper, seat) · offline"]);
  assert.equal(runOnHelp(runOn, "auto"), "Uses a free seat on your device first.");
  assert.equal(runOnHelp(runOn, "dev-1"), "This device is offline; the run waits for it.");
  assert.equal(runOnHelp(runOn, "server"), null);
});

test("Run on: an earlier choice wins over the default; an unknown default falls back to the first option", () => {
  assert.equal(workflowStartView(proposal({ ...NEW_EPIC, run_on: { ...RUN_ON, chosen: "server" } })).runOn.selected, "server");
  assert.equal(workflowStartView(proposal({ ...NEW_EPIC, run_on: { ...RUN_ON, default: "gone" } })).runOn.selected, "auto");
});

test("started: a link to the run with the item key; an error keeps its reason", () => {
  const started = workflowStartView(proposal(NEW_EPIC, {
    decision: "apply",
    started: { run_id: "r-1", session_id: "s-2", href: "/chat?session_id=s-2", work_item_id: "i-1", work_item_key: "CHEF-14" },
  })).outcome;
  assert.deepEqual(started, { kind: "started", href: "/chat?session_id=s-2", runId: "r-1", itemId: "i-1", itemKey: "CHEF-14",
    itemHref: "/chat?area=work&workspace_id=ws-1&work_item_id=i-1", jiraKey: null, jiraProblem: null });
  assert.equal(startedLinkLabel(started), "Open the run · CHEF-14");
  assert.equal(startedLinkLabel({ ...started, itemKey: null }), "Open the run");
  assert.deepEqual(workflowStartView(proposal(NEW_EPIC, { started: { error: "No seat is free." } })).outcome,
    { kind: "error", reason: "No seat is free.", state: null, code: null, itemId: null, itemKey: null, itemHref: null,
      jiraKey: null, jiraProblem: null });
});

test("a chat without a Workspace: Start is blocked, and the typed refusal says what to configure", () => {
  const noWorkspace = workflowStartView(proposal({ ...NEW_EPIC, project_id: null }));
  assert.match(startBlockedReason(noWorkspace, ""), /needs a Workspace: choose a Workspace for this chat/);
  assert.equal(startBlockedReason(workflowStartView(proposal(NEW_EPIC)), "r-1"), null);
  const refused = workflowStartView(proposal({ ...NEW_EPIC, project_id: null }, { decision: "apply", started: {
    error: "A workflow run needs a Workspace. Choose a Workspace and start the run again.",
    state: "needs_configuration", reason: "workspace_required" } })).outcome;
  assert.equal(refused.kind, "error");
  assert.deepEqual([refused.state, refused.code], ["needs_configuration", "workspace_required"]);
  assert.equal(needsConfiguration(refused), true);
  // The Allow itself is refused typed (409): the card shows the server's sentence, not "no longer waiting".
  assert.equal(answerDetailText({ state: "needs_configuration", reason: "workspace_required", code: "workspace_required",
    message: "A workflow run needs a Workspace." }), "A workflow run needs a Workspace.");
  assert.equal(answerDetailText("plain"), "plain");
  assert.equal(answerDetailText({ code: "x" }), null);
  assert.equal(needsConfiguration(workflowStartView(proposal(NEW_EPIC, { started: { error: "No seat is free." } })).outcome),
    false);
});

test("started: an address outside the product is not followed", () => {
  for (const href of ["https://example.com/x", "//evil.example/x", "javascript:alert(1)"]) {
    assert.deepEqual(workflowStartView(proposal(NEW_EPIC, { started: { href } })).outcome, { kind: "none" });
  }
});

test("no start card for a proposal that is not phased or has no draft", () => {
  assert.equal(workflowStartView(proposal(NEW_EPIC, { phased: false })), null);
  assert.equal(workflowStartView(proposal(null)), null);
  assert.equal(workflowStartView(null), null);
});

test("answer bodies: Start carries run_on, Other carries workflow_key, Deny carries nothing else", () => {
  assert.deepEqual(proposalAnswerBody({ proposalId: "p-1", decision: "apply", runOn: "dev-1" }),
    { proposal_id: "p-1", decision: "apply", run_on: "dev-1" });
  assert.deepEqual(proposalAnswerBody({ proposalId: "p-1", decision: "apply" }), { proposal_id: "p-1", decision: "apply" });
  assert.equal(proposalAnswerBody({ proposalId: "p-1", decision: "always", runOn: "auto" }), null);
  assert.deepEqual(proposalAnswerBody({ proposalId: "p-1", decision: "skip", runOn: "auto", workflowKey: "x" }),
    { proposal_id: "p-1", decision: "skip" });
  assert.deepEqual(proposalAnswerBody({ proposalId: "p-1", decision: "other", workflowKey: "epic-delivery", runOn: "auto" }),
    { proposal_id: "p-1", decision: "other", workflow_key: "epic-delivery" });
  assert.equal(proposalAnswerBody({ proposalId: "p-1", decision: "other" }), null);
  assert.equal(proposalAnswerBody({ proposalId: "", decision: "apply" }), null);
  assert.equal(proposalAnswerBody({ proposalId: "p-1", decision: "maybe" }), null);
});

test("the proposal endpoint gets the built body", () => {
  assert.deepEqual(
    buildWorkflowProposalDecision("s 1", { decisionKey: "workflow_proposal", value: "other", label: "x", proposalId: "p-1", workflowKey: "bug-fix" }),
    { path: "/chat/api/sessions/s%201/workflow-proposal", body: { proposal_id: "p-1", decision: "other", workflow_key: "bug-fix" } },
  );
});

test("refusals in words: the server's sentence first, else 422 and 409 have their own", () => {
  assert.equal(proposalAnswerProblem(409, "Choose the repository the run works in (octryx/kitchen-helper, demo/shop)."),
    "Choose the repository the run works in (octryx/kitchen-helper, demo/shop).");
  assert.equal(proposalAnswerProblem(422, "Choose one of the repositories the card offers."), "Choose one of the repositories the card offers.");
  assert.match(proposalAnswerProblem(422), /not offered here/);
  assert.match(proposalAnswerProblem(409), /no longer waiting/);
  assert.match(proposalAnswerProblem(500), /could not be sent/);
});

const REPO_OPTIONS = [{ id: "r1", name: "octryx/kitchen-helper", ref: "bitbucket:octryx/kitchen-helper" }, { id: "r2", name: "demo/shop", ref: "github:demo/shop" }];

test("repository: a known one with its source in words; a missing one blocks Start until chosen; none needs nothing", () => {
  const known = workflowStartView(proposal({ ...NEW_EPIC, repository: { ref: "bitbucket:octryx/kitchen-helper", name: "octryx/kitchen-helper", id: "r1",
    source: "request", required: true, options: REPO_OPTIONS } })).repository;
  assert.deepEqual(known, { name: "octryx/kitchen-helper", id: "r1", sourceText: "named in your request",
    options: [{ id: "r1", name: "octryx/kitchen-helper" }, { id: "r2", name: "demo/shop" }] });
  assert.equal(repositoryBlockedReason(known, ""), null);
  const missing = workflowStartView(proposal({ ...NEW_EPIC, repository: { ref: null, name: null, id: null, source: null, required: true,
    options: REPO_OPTIONS } })).repository;
  assert.equal(missing.name, null);
  assert.equal(repositoryBlockedReason(missing, ""), "Choose the repository the run works in");
  assert.equal(repositoryBlockedReason(missing, "r2"), null);
  assert.match(repositoryBlockedReason({ ...missing, options: [] }, ""), /no repository a run can use/);
  assert.equal(workflowStartView(proposal({ ...NEW_EPIC, repository: null })).repository, null);
  assert.equal(repositoryBlockedReason(null, ""), null);
  for (const [source, words] of [["only_coding_repository", "the Workspace's only coding repository"], ["work_item", "from the Work item"], ["chosen", "chosen by you"]]) {
    assert.equal(workflowStartView(proposal({ ...NEW_EPIC, repository: { ref: "x:y/z", name: "y/z", id: null, source, options: [] } })).repository.sourceText, words);
  }
});

test("Start sends the chosen repository with apply; a partial start shows what exists and offers Start again", () => {
  assert.deepEqual(proposalAnswerBody({ proposalId: "p-1", decision: "apply", runOn: "auto", repository: "r2" }),
    { proposal_id: "p-1", decision: "apply", run_on: "auto", repository: "r2" });
  assert.deepEqual(proposalAnswerBody({ proposalId: "p-1", decision: "skip", repository: "r2" }), { proposal_id: "p-1", decision: "skip" });
  const partial = workflowStartView(proposal(NEW_EPIC, { decision: "apply", started: { jira: { key: "CHEF-9" }, work_item_id: "i-7",
    work_item_key: "OCX-40", error: "The run could not start: no seat. Press Start again to retry." } })).outcome;
  assert.deepEqual([partial.kind, partial.itemKey, partial.itemHref, partial.jiraKey],
    ["error", "OCX-40", "/chat?area=work&workspace_id=ws-1&work_item_id=i-7", "CHEF-9"]);
  assert.equal(startButtonLabel(partial), "Start again");
  assert.equal(startButtonLabel({ kind: "none" }), "Start");
});

test("Other workflow: the catalog without the current one and 'No workflow', searchable", () => {
  const catalog = [
    { key: "spec-writing", title: "Spec writing", description: "Epic to stories" },
    { key: "epic-delivery", title: "Story / epic delivery", description: "Build one story" },
    { key: "bug-fix", title: "Bug fix", description: "Reproduce and fix" },
    { key: "none", title: "No workflow", description: "", selection: "no_workflow" },
    { key: "bug-fix", title: "Bug fix (Workspace)", description: "" },
  ];
  assert.deepEqual(otherWorkflowChoices(catalog, "spec-writing").map((choice) => choice.key), ["epic-delivery", "bug-fix"]);
  assert.deepEqual(otherWorkflowChoices(catalog, "spec-writing", "REPRO").map((choice) => choice.key), ["bug-fix"]);
  assert.deepEqual(otherWorkflowChoices(catalog, "spec-writing", "nothing"), []);
});

test("the composer chip of a held phased start says it waits for Start, not 'Suggested'", async () => {
  const { automaticWorkflowChip, proposalReasonText } = await import("../../src/chat/composer/automaticWorkflow.ts");
  assert.equal(automaticWorkflowChip({ proposal: proposal(NEW_EPIC) }).label, "Spec writing · waits for Start");
  assert.equal(automaticWorkflowChip({ proposal: proposal(null, { phased: false }) }).label, "Suggested: Spec writing");
  for (const code of ["explicit_phased_selection", "workflow_run_required", "user_chose_other"]) assert.ok(proposalReasonText(code));
  assert.equal(proposalReasonText("low_confidence"), null);
});

test("Jira: the planned issue is its own line; after the start its key, or a calm note when it was refused", () => {
  const start = { ...NEW_EPIC, jira: { project_key: "CHEF", issue_type: "Epic", summary: "Hello Kitchen", source: "request", label: "+ Jira MM: Epic 'Hello Kitchen'" } };
  assert.equal(workflowStartView(proposal(start)).jiraLabel, "+ Jira MM: Epic 'Hello Kitchen'");
  assert.equal(workflowStartView(proposal(NEW_EPIC)).jiraLabel, null);
  const href = "/chat?session_id=s-2";
  const ok = workflowStartView(proposal(start, { started: { href, work_item_key: "OCX-31", jira: { key: "CHEF-7", id: "1", project_key: "CHEF", issue_type: "Epic" } } })).outcome;
  assert.deepEqual([ok.jiraKey, ok.jiraProblem], ["CHEF-7", null]);
  // Preview: the item made from the Jira issue carries its key, so the card said "New Epic ".
  const same = workflowStartView(proposal(start, { started: { href, work_item_key: "CHEF-17", jira: { key: "CHEF-17", id: "2", project_key: "CHEF", issue_type: "Epic" } } })).outcome;
  assert.deepEqual([same.itemKey, same.jiraKey], ["CHEF-17", null]);
  const refused = workflowStartView(proposal(start, { started: { href, work_item_key: "OCX-31", jira: { error: "No Jira connection" } } })).outcome;
  assert.deepEqual([refused.kind, refused.jiraKey, refused.jiraProblem], ["started", null, "No Jira connection"]);
  assert.equal(jiraProblemText("No Jira connection"), "Jira issue could not be created: No Jira connection – the run started with a platform item.");
});

test("the held turn's 'started' state reads calmly as 'Workflow run started'", async () => {
  const { TURN_EXECUTION_STATES } = await import("../../src/chat/run/turnExecutionSummary.types.ts");
  const { presentTurnExecutionState } = await import("../../src/chat/run/turnExecutionSummaryPresentation.ts");
  assert.ok(TURN_EXECUTION_STATES.includes("started"));
  assert.deepEqual(
    { ...presentTurnExecutionState("started") },
    { tone: "neutral", label: "Workflow run started", description: "The workflow run started for its Work item; it continues in its own chat." },
  );
});
