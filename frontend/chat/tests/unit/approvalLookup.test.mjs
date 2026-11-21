// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/approvalLookup.test.mjs"
import assert from "node:assert/strict";
import { test } from "node:test";

import { approvalLookupUrl, lookupApproval } from "../../src/admin/components/governedWrite/approvalLookup.ts";

function respond(status, body) {
  return async (url) => {
    respond.calls.push(url);
    return new Response(body === undefined ? null : JSON.stringify(body), { status });
  };
}
respond.calls = [];

test("approvals are looked up by id; 404 means unknown or not visible", async () => {
  respond.calls = [];
  assert.equal(approvalLookupUrl(" appr/1 "), "/api/v1/approvals/appr%2F1");

  const found = await lookupApproval("appr-1", respond(200, { id: "appr-1", status: "approved", kind: "governance" }));
  assert.equal(found.status, "found");
  assert.equal(found.approval.status, "approved");
  assert.deepEqual(await lookupApproval("appr-2", respond(404, { detail: "Approval not found" })), { status: "not_found" });
  assert.deepEqual(await lookupApproval("appr-3", respond(500, {})), { status: "error", httpStatus: 500 });
  assert.deepEqual(respond.calls, ["/api/v1/approvals/appr-1", "/api/v1/approvals/appr-2", "/api/v1/approvals/appr-3"]);
  assert.ok(!respond.calls.some((url) => url.includes("?status=")));
});
