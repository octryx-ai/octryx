// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/seatUsageModel.test.mjs
// Operations › Costs › Seats by person: per person what the seat calls would cost via the API
// at list price, the API cost apart, the seat accounts, models, Workspaces and the last allowance. Names are invented.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import {
  accountTitle,
  allowanceStatus,
  allowanceText,
  clientLabel,
  isMissingRoute,
  limitHitsText,
  readSeatUsage,
  refusalText,
} from "../../src/admin/components/operations/seatUsageModel.ts";
import { byTestId, load, text } from "./workCodingSupport.mjs";

const { act } = TestRenderer;

const SEAT_USAGE = {
  window: { from: "2026-10-18T10:00:00+00:00", to: "2026-11-17T10:00:00+00:00", days: 30 },
  labels: { api_equivalent_usd: "would cost via API (list price)", unpriced_calls: "no list price (seat only)" },
  totals: { api_equivalent_usd: 73.44, api_cost_usd: 1.2, seat_calls: 420, unpriced_calls: 7 },
  people: [
    { user_id: "u-ana", username: "ana", api_equivalent_usd: 10, api_cost_usd: 0, seat_calls: 120, unpriced_calls: 7,
      seats: [{ seat: "9c1e0b7a2d", provider: "openai_codex_seat", label: "ChatGPT", api_equivalent_usd: 10, calls: 120, unpriced_calls: 7,
        models: [{ model: "gpt-6", api_equivalent_usd: 10, calls: 113, unpriced_calls: 0 },
          { model: "gpt-6-codex-preview", api_equivalent_usd: 0, calls: 7, unpriced_calls: 7 }] }],
      workspaces: [{ workspace_id: "ws-1", name: "Coffee", api_equivalent_usd: 10, api_cost_usd: 0 }],
      allowance: [], limit_hits: 0 },
    { user_id: "u-admin", username: "admin", api_equivalent_usd: 63.44, api_cost_usd: 1.2, seat_calls: 300, unpriced_calls: 0,
      seats: [{ seat: "3f9a8b2c1d", provider: "anthropic_seat", label: "Claude", api_equivalent_usd: 63.44, calls: 300, unpriced_calls: 0,
        models: [{ model: "claude-opus-5-5", api_equivalent_usd: 63.44, calls: 300, unpriced_calls: 0 }] }],
      workspaces: [{ workspace_id: null, name: "(none)", api_equivalent_usd: 0, api_cost_usd: 1.2 },
        { workspace_id: "ws-1", name: "Coffee", api_equivalent_usd: 63.44, api_cost_usd: 0 }],
      allowance: [{ client: "claude_code", five_hour_pct: 71.4, five_hour_resets_at: "2026-11-17T12:00:00+00:00", seven_day_pct: 22,
        seven_day_resets_at: "2026-11-20T00:00:00+00:00", status: "allowed_warning", updated_at: "2026-11-17T09:58:00+00:00" }],
      limit_hits: 2 },
  ],
};

test("people by seat equivalent, the API cost kept apart and never added", () => {
  const report = readSeatUsage(SEAT_USAGE);
  assert.deepEqual(report.people.map((p) => p.name), ["admin", "ana"]);
  const [admin, ana] = report.people;
  assert.deepEqual(admin.seat, { equivalentUsd: 63.44, unpricedCalls: 0 });
  assert.equal(admin.apiCostUsd, 1.2);
  assert.equal(report.totals.seat.equivalentUsd, 73.44);
  assert.equal(report.totals.apiCostUsd, 1.2);
  assert.ok(!JSON.stringify(report).includes("64.64") && !JSON.stringify(report).includes("74.64"), "no sum of both figures");
  assert.equal(report.labels.equivalent, "would cost via API (list price)");
  assert.equal(ana.seat.unpricedCalls, 7);
  assert.equal(admin.workspaces[0].name, "No Workspace", "no raw (none)");
  assert.equal(admin.accounts[0].models[0].name, "Claude Opus 5.5");
});

test("a model without a list price has calls but no amount", () => {
  const [, ana] = readSeatUsage(SEAT_USAGE).people;
  const unpriced = ana.accounts[0].models.find((m) => m.model === "gpt-6-codex-preview");
  assert.deepEqual(unpriced.seat, { equivalentUsd: 0, unpricedCalls: 7 });
  assert.equal(unpriced.calls, 7);
  assert.equal(accountTitle(ana.accounts[0]), "ChatGPT · 9c1e0b7a2d");
});

test("the allowance is information in words", () => {
  const [admin] = readSeatUsage(SEAT_USAGE).people;
  assert.equal(admin.allowance[0].label, "Claude Code");
  assert.equal(allowanceText(admin.allowance[0]), "5 hours 71 % · 7 days 22 %");
  assert.equal(allowanceText({ fiveHourPct: null, sevenDayPct: null }), "No allowance reported");
  assert.deepEqual(allowanceStatus("allowed_warning"), { label: "Near the limit", tone: "attention" });
  assert.deepEqual(allowanceStatus("rejected"), { label: "Limit reached", tone: "attention" });
  assert.equal(allowanceStatus("allowed").tone, "neutral");
  assert.equal(clientLabel("codex"), "Codex");
  assert.equal(clientLabel("some_client"), "Some client");
  assert.equal(limitHitsText(2), "2 limit hits");
  assert.equal(limitHitsText(0), "No limit hit");
});

test("a missing route hides the view; refusals are words", () => {
  assert.equal(isMissingRoute({ status: 404, code: "", message: "Not Found" }), true);
  assert.equal(isMissingRoute({ status: 404, code: "workspace_not_found", message: "This Workspace does not exist" }), false);
  assert.equal(isMissingRoute({ status: 403, code: "admin_required", message: "x" }), false);
  assert.equal(refusalText({ status: 403, code: "admin_required", message: "Only platform or Workspace admins can see problems." }),
    "Only platform and Workspace admins can see seat usage.");
  assert.equal(refusalText({ status: 404, code: "workspace_not_found", message: "" }),
    "This Workspace does not exist, or you are not a member of it.");
  assert.equal(refusalText({ status: 422, code: "invalid_filter", message: "days must be between 1 and 366." }),
    "days must be between 1 and 366.");
});

test("rendered: one row per person plus a total per column, the detail panel per person", async () => {
  const { SeatUsageView } = load("admin/components/operations/SeatUsageView.tsx");
  const state = { report: readSeatUsage(SEAT_USAGE), error: "", missing: false, reload: () => {} };
  let view;
  await act(async () => { view = TestRenderer.create(createElement(SeatUsageView, { state })); });
  const table = text(byTestId(view, "seat-usage-table")[0]);
  for (const part of ["Seat: would cost via API (list price)", "API cost", "No list price (seat only)", "Limit hits",
    "$63.44", "$10.00", "$73.44", "$1.20", "420"]) {
    assert.ok(table.includes(part), part);
  }
  assert.ok(!table.includes("$64.64") && !table.includes("$74.64"), "the two figures are never added");
  const rows = view.root.findAll((node) => node.type === "tr" && typeof node.props.onClick === "function");
  await act(async () => { rows[1].props.onClick({ target: rows[1], currentTarget: rows[1] }); });
  const panel = text(byTestId(view, "seat-person-panel")[0]);
  for (const part of ["ana", "Last 30 days", "$10.00", "No list price (seat only)", "7 calls", "ChatGPT · 9c1e0b7a2d",
    "no list price (seat only) · 7 calls", "Coffee", "No allowance reported for this person."]) {
    assert.ok(panel.includes(part), part);
  }
});

test("a person is named by display_name, the username only when the server sends none", () => {
  const people = readSeatUsage({ people: [
    { user_id: "u-bot", username: "review-bot-ccdafffd", display_name: "Octryx review bot", api_equivalent_usd: 0.01 },
    { user_id: "u-old", username: "ana", api_equivalent_usd: 1 },
  ] }).people;
  assert.deepEqual(people.map((person) => person.name).sort(), ["Octryx review bot", "ana"]);
});
