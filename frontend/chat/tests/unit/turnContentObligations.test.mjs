// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/turnContentObligations.test.mjs
//
// Content policy notices of `turn_execution_summary.v1`: closed parse (the backend set is read, never
// executed), the attention/error presentation of the mock, and that nothing shaped like the data is ever rendered.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  CONTENT_OBLIGATION_REASONS,
  parseTurnContentObligations,
  presentContentObligation,
} from "../../src/chat/run/turnContentObligations.ts";
import { parseTurnExecutionSummary } from "../../src/chat/run/turnExecutionSummaryParse.ts";
import { buildSummaryFixture } from "../e2e/turnExecutionSummaryFixtures.mjs";

const VALUE = "4000123412341234";
const NOTICES_SOURCE = readFileSync(
  new URL("../../../../backend/app/services/content_routing/notices.py", import.meta.url),
  "utf8",
);
const ROUTED = {
  source: "model", kind: "mask_reroute", reason: "content_obligation_applied", applied: true,
  found: { email: 1, phone: 1 }, masked: 2, policies: ["personal-data-approved-model"],
  decision_id: "7f21c0aa-1111-2222-3333-444455556666", model_from: "claude-sonnet-5", model_to: "company-model", tool: null,
};

test("the closed reasons match the backend notices", () => {
  const block = NOTICES_SOURCE.match(/REASONS = frozenset\(\{([\s\S]*?)\}\)/)[1];
  const backend = [...block.matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);
  assert.deepEqual([...backend, "content_obligation_applied"].sort(), [...CONTENT_OBLIGATION_REASONS].sort());
});

test("a masked and routed request reads like the mock, with the Why? link to its decision", () => {
  const summary = parseTurnExecutionSummary({
    ...buildSummaryFixture({ traceId: "t1", sessionId: "s1", reasonCode: "runtime_finished" }),
    content_obligations: [ROUTED],
  });
  const [notice] = summary.contentObligations;
  const view = presentContentObligation(notice);
  assert.equal(view.tone, "attention");
  assert.equal(view.head, "Sent to the approved model, personal data masked");
  assert.equal(view.code, "content_obligation_applied");
  assert.match(view.text, /policy personal-data-approved-model, 2 values were masked and this conversation now runs on company-model/);
  assert.deepEqual(view.fields, [
    { label: "Found", value: "email ×1 · phone ×1" },
    { label: "Model", value: "claude-sonnet-5 → company-model (until you start a new chat)" },
    { label: "Decision", value: ROUTED.decision_id },
  ]);
  assert.equal(view.whyHref, `/chat?area=operations&tab=observabilityDecisions&decision=${ROUTED.decision_id}`);
});

test("refusals are errors with their code; a masked tool result names the tool", () => {
  const [denied, unavailable, tool] = parseTurnContentObligations([
    { source: "model", kind: "block", reason: "content_policy_denied", found: { secrets: 2 }, policies: ["platform:secrets-never-leave"], decision_id: "pd-7f22a9" },
    { source: "model", kind: "block", reason: "content_route_unavailable", found: { email: 1 }, policies: ["personal-data"], model_to: "company-model" },
    { source: "tool_result", kind: "mask", reason: "content_obligation_applied", found: { email: 14 }, masked: 14, tool: "logs_tail" },
  ]);
  const deniedView = presentContentObligation(denied);
  assert.equal(deniedView.tone, "error");
  assert.equal(deniedView.code, "content_policy_denied");
  assert.equal(deniedView.head, "Not sent: the message contains a credential");
  assert.equal(presentContentObligation(unavailable).head, "Not sent: the approved model for personal data is not available");
  assert.equal(presentContentObligation(unavailable).whyHref, null);
  const toolView = presentContentObligation(tool);
  assert.equal(toolView.head, "Personal data masked in the logs_tail result");
  assert.deepEqual(toolView.fields, [{ label: "Found", value: "email ×14" }, { label: "Tool", value: "logs_tail" }]);
});

test("nothing shaped like the data survives the parse; unknown notices render nothing", () => {
  const parsed = parseTurnContentObligations([
    { ...ROUTED, found: { [VALUE]: 1, email: 1 }, policies: [VALUE, "ok-policy"], decision_id: VALUE, model_to: `value ${VALUE}`,
      tool: VALUE },
    { ...ROUTED, kind: "leak" },
    { ...ROUTED, reason: "free text" },
    "text",
  ]);
  assert.equal(parsed.length, 1);
  const rendered = JSON.stringify(presentContentObligation(parsed[0]));
  assert.ok(!rendered.includes(VALUE));
  assert.equal(parsed[0].decisionId, null);
  assert.deepEqual(parsed[0].policies, ["ok-policy"]);
  assert.deepEqual(parseTurnContentObligations(null), []);
});
