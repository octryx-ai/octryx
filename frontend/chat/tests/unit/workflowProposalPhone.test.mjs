// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workflowProposalPhone.test.mjs
//
// The phone shows a chat's held workflow proposal like the web: the start card for a phased workflow, the
// plain prompt for any other pending one, nothing once nothing waits; it keeps reading the chat's state while the
// proposal is open or a confirmed start has no run link yet.
import assert from "node:assert/strict";
import { test } from "node:test";

import { phoneProposal, proposalStillOpen } from "../../src/mobile/workflowProposalPhone.ts";

const START = {
  workflow_key: "spec-writing", workflow_title: "Spec writing", project_id: "ws-1", jira_project: null, notes: [],
  work_item: { mode: "new", type: "epic", type_label: "Epic", title: "Hello Kitchen", description: "", key: null, id: null },
  run_on: { options: [{ key: "auto", label: "Automatic" }], default: "auto" }, steps: [{ title: "Write" }],
  summary: "Start Spec writing for a new Epic 'Hello Kitchen'",
};
const proposal = (extra = {}) => ({
  proposalId: "p-1", status: "needs_confirmation", reasonCode: null, workflowKey: "release-notes",
  workflowTitle: "Release notes", confidence: null, reason: "The question asks for release changes.", changeCapable: true,
  decision: null, phased: false, start: null, started: null, ...extra,
});

test("a plain pending proposal: Allow once and Deny", () => {
  const card = phoneProposal(proposal());
  assert.equal(card.kind, "plain");
  assert.equal(card.title, "Release notes");
  assert.equal(card.reason, "The question asks for release changes.");
  assert.deepEqual(card.answers.map((answer) => answer.value), ["apply", "skip"]);
});

test("a phased proposal shows the start card with its reason in words; one without a draft waits for the next poll", () => {
  const card = phoneProposal(proposal({ phased: true, reasonCode: "explicit_phased_selection", workflowKey: "spec-writing", start: START }));
  assert.equal(card.kind, "start");
  assert.equal(card.view.summary, "Start Spec writing for a new Epic 'Hello Kitchen'");
  assert.match(card.reason, /Chosen in the composer/);
  assert.equal(phoneProposal(proposal({ phased: true, start: null })), null);
});

test("nothing shows for an offered or missing proposal", () => {
  for (const status of ["offered", "none", "disabled"]) assert.equal(phoneProposal(proposal({ status })), null);
  assert.equal(phoneProposal(null), null);
  assert.equal(phoneProposal(proposal({ proposalId: null })), null);
});

test("the chat keeps reading its state while the proposal is open or a start has no run link yet", () => {
  const phased = (extra) => phoneProposal(proposal({ phased: true, workflowKey: "spec-writing", start: START, ...extra }));
  assert.equal(proposalStillOpen(phoneProposal(proposal())), true);
  assert.equal(proposalStillOpen(phoneProposal(proposal({ decision: "skip" }))), false);
  assert.equal(proposalStillOpen(phased({ decision: "apply" })), true, "started, link not there yet");
  assert.equal(proposalStillOpen(phased({ decision: "apply", started: { work_item_id: "i-1", work_item_key: "OCX-40" } })), true,
    "the item exists, the run not yet");
  assert.equal(proposalStillOpen(phased({ decision: "apply", started: { href: "/chat?session_id=s", run_id: "r-1" } })), false);
  assert.equal(proposalStillOpen(phased({ decision: "apply", started: { error: "No seat" } })), false);
  assert.equal(proposalStillOpen(null), false);
});
