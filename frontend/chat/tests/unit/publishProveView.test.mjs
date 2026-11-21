import assert from "node:assert/strict";
import test from "node:test";
import { publishProvePayload, publishProveStatus } from "../../src/chat/workflowRun/publishProveView.ts";
import { payloadView } from "../../src/chat/workflowRun/workflowRunPayloadView.ts";
import { runActionRequest } from "../../src/chat/workflowRun/workflowRunRequests.ts";

test("functional acceptance shows observed build, blockers and late decision semantics", () => {
  const view = publishProvePayload("functional_acceptance", { statement: "I observed it on Test", build: {
    tested_sha: "exact-sha", ci_url: "https://ci.invalid/11", note: "Pre-merge build" },
    accept_blockers: ["environment missing"], pending_since: "2026-10-13", refresh_note: "Page is not edited" });
  assert.equal(view.heading, "Functional acceptance (a)");
  assert.deepEqual(view.blockers, ["environment missing"]);
  assert.ok(view.lines.includes("Page is not edited"));
  assert.ok(view.lines.includes("Observed tested commit: exact-sha"));
});

test("publication is its own exact-target card and storage is shown as inert text", () => {
  const view = payloadView({ kind: "awaiting_confirmation", subject: "publication", payload: {
    title: "Feature", body: "<p>Approved <script>evil()</script> text</p>",
    target: { instance: "https://site.invalid/wiki", connection_id: "bound", space_key: "DEMO", parent_id: "17" },
    acceptance_pending: true, acceptance_as_of: "2026-10-13T18:00:00Z", audience: { semantics: "workspace_readers" },
  } });
  assert.equal(view.heading, "Publication (b)");
  assert.equal(view.text.includes("<script>"), false);
  assert.ok(view.lines.includes("Connection: bound"));
  assert.ok(view.lines.includes("Acceptance pending as of 2026-10-13T18:00:00Z"));
});

test("deferred acceptance card and actions retain the exact current payload hash", () => {
  const waiting = { kind: "functional_acceptance", subject: "functional_acceptance", payload_hash: "sha256:current",
    payload: { statement: "Accept on Test" } };
  assert.equal(payloadView(waiting).heading, "Functional acceptance (a)");
  assert.equal(runActionRequest({ id: "run", waiting }, { key: "accept", label: "Accept" }).body.payload_hash,
    "sha256:current");
});

test("later acceptance never claims that the historic page was updated", () => {
  const lines = publishProveStatus({ publication: { page_id: "17", version: 1, published_at: "then",
    acceptance_as_published: "pending", acceptance_as_of: "then" }, acceptance: {
      state: "accepted", as_of: "later", late: true } });
  assert.ok(lines.includes("That page version records acceptance pending as of then."));
  assert.ok(lines.includes("Functional acceptance: accepted · later"));
  assert.ok(lines.includes("The later decision is recorded here; the published page was not edited."));
  assert.deepEqual(publishProveStatus(null), []);
});

test("the test-contract card also shows the documentation contract it hashes", () => {
  const view = payloadView({ kind: "awaiting_confirmation", subject: "test_contract", payload: {
    documentation_contract: { space_key: "DEMO", parent_page_id: "17", doc_owner: "owner", timing: "After merge",
      audience: { semantics: "workspace_readers" }, not_configured: [] },
  } });
  assert.ok(view.lines.includes("Documentation audience: workspace_readers"));
  assert.ok(view.lines.includes("Documentation owner: owner"));
});
