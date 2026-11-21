import assert from "node:assert/strict";
import { test } from "node:test";
import { refusalFromBody } from "../../src/admin/components/governedWrite/governedRequest.ts";
import {
  workflowProposalPolicyPatch,
  workflowProposalPolicyState,
} from "../../src/admin/components/projectsTab/workflowProposalPolicy.ts";

test("server refusals keep their codes", () => {
  const refusal = refusalFromBody(409, {
    detail: {
      errors: [{ code: "governance_approval_required", message: "needs approval" }],
      warnings: [],
      governance_review: { approval_gate: { status: "pending", approval_id: "ap-1" } },
    },
  });
  assert.deepEqual(refusal.issues.map((issue) => issue.code), ["governance_approval_required"]);
  assert.deepEqual(refusalFromBody(400, { detail: "bad value" }).issues, [{ code: "http_400", message: "bad value" }]);
});

test("the proposal switch maps the stored section to explicit states and back", () => {
  assert.equal(workflowProposalPolicyState({}), "default");
  assert.equal(workflowProposalPolicyState({ workflow_proposal_policy: { enabled: true } }), "enabled");
  assert.equal(workflowProposalPolicyState({ workflow_proposal_policy: { enabled: false } }), "disabled");
  assert.deepEqual(workflowProposalPolicyPatch("default"), { workflow_proposal_policy: { enabled: null } });
  assert.deepEqual(workflowProposalPolicyPatch("disabled"), { workflow_proposal_policy: { enabled: false } });
});
