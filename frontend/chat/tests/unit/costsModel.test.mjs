// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/costsModel.test.mjs
// Operations › Costs: cost and outcome per group, a total, links per row.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  costCell,
  deliveredText,
  mainSessionOf,
  periodText,
  perDeliveredText,
  readCosts,
  rowLink,
  workflowWords,
} from "../../src/admin/components/operations/costsModel.ts";

const PAYLOAD = {
  window: { from: "2026-10-14T00:00:00+00:00", to: "2026-11-13T00:00:00+00:00", days: 30 },
  group: "workflow",
  totals: { runs: 7, delivered: 3, pull_requests: 2, cost_usd: 14.2, cost_per_delivered_usd: 4.733333 },
  groups: [
    { key: "spec-writing", label: "spec-writing", runs: 2, delivered: 0, pull_requests: 0, cost_usd: 1.3, cost_per_delivered_usd: null },
    { key: "team-delivery", label: "team-delivery", runs: 4, delivered: 3, pull_requests: 2, cost_usd: 12.9, cost_per_delivered_usd: 4.3 },
    { key: "-", label: "(none)", runs: 1, delivered: 0, pull_requests: 0, cost_usd: 0, cost_per_delivered_usd: null },
  ],
};

test("rows by cost, workflow keys in words, the total kept apart", () => {
  const report = readCosts(PAYLOAD, "workflow");
  assert.deepEqual(report.rows.map((row) => row.label), ["Team delivery", "Spec writing", "No workflow"]);
  assert.equal(report.days, 30);
  assert.deepEqual([report.totals.label, report.totals.runs, report.totals.costUsd], ["Total", 7, 14.2]);
  assert.equal(workflowWords("epic_delivery"), "Epic delivery");
});

test("cost per delivered run is a dash without a delivery, never 0 or infinity", () => {
  const [team, spec, none] = readCosts(PAYLOAD, "workflow").rows;
  assert.equal(perDeliveredText(team), "$4.30");
  assert.equal(perDeliveredText(spec), "—");
  assert.equal(perDeliveredText({ delivered: 0, costPerDeliveredUsd: 0 }), "—", "a server 0 with nothing delivered");
  assert.equal(costCell(none.costUsd), "$0.00");
  assert.equal(deliveredText(team), "3 of 4");
});

test("a run row opens the run's chat, a work item row the work item; no id, no link", () => {
  assert.deepEqual(rowLink("run", { key: "r1" }), { kind: "run", runId: "r1" });
  assert.deepEqual(rowLink("work_item", { key: "wi-7" }, "ws1"), { kind: "href", href: "/chat?area=work&work_item_id=wi-7&workspace_id=ws1" });
  assert.equal(rowLink("work_item", { key: "" }), null);
  assert.equal(rowLink("person", { key: "u1" }), null);
  assert.equal(mainSessionOf({ run: { sessions: [{ session_id: "c", role: "child" }, { session_id: "m", role: "main" }] } }), "m");
  assert.equal(mainSessionOf({ run: {} }), "");
});

test("the API cost and the seat's API equivalent are two columns, never one sum", () => {
  const report = readCosts({
    window: { days: 7 }, group: "person",
    totals: { runs: 2, delivered: 1, pull_requests: 1, cost_usd: 0.5, cost_per_delivered_usd: 0.5,
      seat_api_equivalent_usd: 10.25, seat_unpriced_calls: 3 },
    groups: [
      { key: "u1", label: "ana", runs: 1, delivered: 1, pull_requests: 1, cost_usd: 0, cost_per_delivered_usd: 0,
        seat_api_equivalent_usd: 10.25, seat_unpriced_calls: 3 },
      { key: "u2", label: "ben", runs: 1, delivered: 0, pull_requests: 0, cost_usd: 0.5, cost_per_delivered_usd: null },
    ],
  }, "person");
  const ana = report.rows.find((row) => row.label === "ana");
  assert.equal(ana.costUsd, 0, "a seat run costs the platform nothing");
  assert.deepEqual(ana.seat, { equivalentUsd: 10.25, unpricedCalls: 3 });
  assert.deepEqual(report.rows.find((row) => row.label === "ben").seat, { equivalentUsd: 0, unpricedCalls: 0 });
  assert.equal(report.totals.costUsd, 0.5);
  assert.deepEqual(report.totals.seat, { equivalentUsd: 10.25, unpricedCalls: 3 });
  assert.match(periodText(report), /sorted by API cost/);
  assert.match(periodText(report), /would cost via the API at list price, apart from the API cost/);
});
