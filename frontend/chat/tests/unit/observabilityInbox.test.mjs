// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/observabilityInbox.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { listAdminAreaTabRefs } from "../../src/admin/config/adminPanelAreas.ts";
import { inboxHref, readInbox } from "../../src/chat/inbox/inboxModel.ts";
import { readDecisionParams } from "../../src/admin/components/observability/decisionsModel.ts";

test("the removed Approvals and Clarifications pages have no address", () => {
  const refs = listAdminAreaTabRefs("operations");
  for (const id of ["approvals", "clarifications"]) assert.equal(refs.find((item) => item.id === id), undefined);
});

test("an inbox item opens its owning screen", () => {
  assert.equal(inboxHref({ href: "/chat?session_id=s-1", label: "x" }), "/chat?session_id=s-1");
  assert.equal(inboxHref({ tab: "cedarPolicies", label: "x" }), "/chat?area=admin&tab=cedarPolicies");
  assert.equal(inboxHref({ tab: "skills", label: "x" }), "/chat?area=workflows&tab=skills");
});

test("a malformed answer is not shown as an empty inbox", () => {
  assert.equal(readInbox({ items: [] }), null);
  assert.deepEqual(readInbox({ waiting: [], requested_by_me: [], count: 0 }), { waiting: [], requested_by_me: [], count: 0 });
});

test("a Decisions address preselects its outcome filter", () => {
  assert.equal(readDecisionParams("?tab=observabilityDecisions&outcome=needs_approval").outcome, "needs_approval");
  assert.equal(readDecisionParams("?outcome=<x>").outcome, "");
});
