import assert from "node:assert/strict";
import { test } from "node:test";
import { reviewSummaryFromAuditReport } from "../../src/chat/coding/codingReviewSummary.ts";

// Actual coding_audit.py BLOCKING_GATE_STATUSES includes "missing": this boolean concerns
// audit/PR readiness, not the narrower current-negative-review flag of the list summary.
for (const plan of [null, { id: "plan-4", version: 4 }]) {
  test(`real audit missing verdict remains known, with plan=${Boolean(plan)}`, () => {
    const report = { quality_gates: [{
      key: "reviewer_approval", status: "missing", blocking: true,
      reason: "No current review decision is recorded.",
      evidence: plan ? { plan_id: plan.id, plan_version: plan.version } : {},
    }] };
    const parsed = reviewSummaryFromAuditReport(report, plan);
    assert.equal(parsed.status, "missing", "Known absence of a decision must not become a load failure");
  });
}

import { codingSessionsNote } from "../../src/chat/coding/codingQueuePresenter.ts";

test("blocked overview discloses unavailable reviews instead of an unqualified zero", () => {
  const note = codingSessionsNote([{ state: "planned", phase: "planning", review: { status: "unavailable", cause: "refresh_failed" } }]);
  assert.match(note, /unavailable|unknown|incomplete/i, "A zero Blocked count alone hides the failed review refresh");
});
