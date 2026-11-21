import assert from "node:assert/strict";
import test from "node:test";

import {
  ACCEPTED_LINE,
  acceptBody,
  decidedLine,
  decisionErrorText,
  findingLine,
  proposalsFor,
  proposalsLoadProblem,
  readProposals,
  ruleProblem,
  withDecided,
} from "../../src/admin/components/projectsTab/repositories/prReviewBotRulesModel.ts";

const RAW = {
  can_edit: true,
  proposals: [
    { id: "p2", state: "open", repository_id: "r1", file: "pay/bulk.py", rule: "Do not report in pay/bulk.py: retries (reason: idempotent)",
      reason: "idempotent", finding: { id: "f1", severity: "high", file: "pay/bulk.py", line: 42, fix: "add a guard" },
      proposed_by: "dana", pr_url: "https://github.com/acme/pay/pull/7", created_at: "2026-11-17T10:00:00Z" },
    { id: "p1", state: "accepted", repository_id: "r1", file: "a.py", rule: "x", finding: {}, pr_url: "javascript:alert(1)" },
    { id: "p3", state: "open", repository_id: "r2", rule: "y", finding: {} },
    { id: "p4", state: "weird", repository_id: "r1", rule: "z" },
    { state: "open", rule: "no id" },
  ],
};

test("proposals are read per repository; unknown states are decided, rows without id and unsafe PR links dropped", () => {
  const payload = readProposals(RAW);
  assert.equal(payload.canEdit, true);
  assert.equal(payload.proposals.length, 4);
  const mine = proposalsFor(payload.proposals, "r1");
  assert.deepEqual(mine.open.map((row) => row.id), ["p2"]);
  assert.deepEqual(mine.decided.map((row) => [row.id, row.state]), [["p1", "accepted"], ["p4", "rejected"]]);
  assert.equal(mine.decided[0].prUrl, "");
  assert.equal(readProposals({ proposals: "nope" }).canEdit, false);
});

test("accept sends the rule only when the admin changed more than whitespace", () => {
  const [proposal] = readProposals(RAW).proposals;
  assert.deepEqual(acceptBody(proposal, `  ${proposal.rule.replace(" ", "   ")}\n`), {});
  assert.deepEqual(acceptBody(proposal, "Do not report retries in pay/bulk.py"), { rule: "Do not report retries in pay/bulk.py" });
  assert.deepEqual(acceptBody(proposal, "   "), {});
});

test("the edited rule must have text and fit the server's 500 characters after folding whitespace", () => {
  assert.match(ruleProblem("  \n "), /needs some text/);
  assert.equal(ruleProblem(`${"a".repeat(250)}    ${"b".repeat(249)}`), null);
  assert.match(ruleProblem("a".repeat(501)), /at most 500.*501/);
});

test("finding and decided lines say where and what follows", () => {
  const [open, accepted] = readProposals(RAW).proposals;
  assert.equal(findingLine(open), "high · pay/bulk.py:42");
  assert.equal(findingLine(accepted), "a.py");
  assert.equal(decidedLine(accepted, () => "17 Nov 2026"), ACCEPTED_LINE);
  const rejected = { ...accepted, state: "rejected", decidedAt: "2026-11-17T11:00:00Z" };
  assert.match(decidedLine(rejected, () => "17 Nov 2026"), /Rejected on 17 Nov 2026/);
});

test("refusals are words, and a missing route shows nothing", () => {
  assert.match(decisionErrorText(403, { reason: "workspace_admin_required" }), /admins and owners/);
  assert.match(decisionErrorText(409, { reason: "proposal_decided" }), /already decided/);
  assert.match(decisionErrorText(409, { reason: "invalid_rules" }), /3000/);
  assert.match(decisionErrorText(409, { reason: "invalid_layout" }), /code style refused.*invalid_layout/);
  assert.match(decisionErrorText(0, null), /did not reach/);
  assert.equal(proposalsLoadProblem(404, { detail: "Not Found" }), null);
  assert.match(proposalsLoadProblem(500, { reason: "boom" }), /could not be loaded/);
});

test("a decision replaces only its own row", () => {
  const rows = readProposals(RAW).proposals;
  const next = withDecided(rows, { ...rows[0], state: "accepted" });
  assert.equal(next[0].state, "accepted");
  assert.equal(next[1], rows[1]);
});
