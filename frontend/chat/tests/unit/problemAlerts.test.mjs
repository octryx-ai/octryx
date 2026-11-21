// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/problemAlerts.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  personalChannelOn,
  personalProblemSubscription,
  problemSubscriptionRequest,
  readSubscriptions,
  workspaceAlertState,
  workspaceProblemSubscriptions,
} from "../../src/chat/notifications/problemAlertsModel.ts";

const sub = (over) => ({
  id: "s1", user_id: "u1", project_id: null, event_type: "problem.raised", channel_type: "email",
  channel_config_id: null, target: "a@example.com", template_id: null, is_active: true, created_at: null, ...over,
});

test("the API list is read defensively; rows without id or channel are dropped", () => {
  const rows = readSubscriptions([sub({}), { id: "x" }, null, sub({ id: "s2", is_active: undefined })]);
  assert.deepEqual(rows.map((row) => row.id), ["s1", "s2"]);
  assert.equal(rows[1].is_active, true);
  assert.deepEqual(readSubscriptions({ detail: "x" }), []);
});

test("a person's channel: the active problem subscription wins; other events and Workspace rows do not count", () => {
  const rows = [
    sub({ id: "old", is_active: false }),
    sub({ id: "live" }),
    sub({ id: "other", event_type: "approval.requested" }),
    sub({ id: "ws", user_id: null, project_id: "w1" }),
  ];
  assert.equal(personalProblemSubscription(rows, "email").id, "live");
  assert.equal(personalProblemSubscription([rows[0]], "email").id, "old");
  assert.equal(personalProblemSubscription(rows, "slack"), null);
});

test("a personal channel is its own switch: on while its problem subscription is active", () => {
  assert.equal(personalChannelOn(null), false);
  assert.equal(personalChannelOn(sub({ is_active: false })), false);
  assert.equal(personalChannelOn(sub({})), true);
});

test("the request keeps the fields the form does not show and always names problem.raised", () => {
  const base = sub({ template_id: "t1", user_id: "u1" });
  const body = problemSubscriptionRequest(
    { channel: "slack", target: "  C0123  ", projectId: "w1", channelConfigId: 4, active: false }, base);
  assert.deepEqual(body, { user_id: "u1", project_id: "w1", event_type: "problem.raised", channel_type: "slack",
    channel_config_id: 4, target: "C0123", template_id: "t1", is_active: false });
});

test("Workspace alerts: no person, problem.raised only, sorted by Workspace then channel order", () => {
  const names = { w1: "Payments", w2: "Demo Shop" };
  const rows = workspaceProblemSubscriptions([
    sub({ id: "mine" }),
    sub({ id: "a", user_id: null, project_id: "w1", channel_type: "teams" }),
    sub({ id: "b", user_id: null, project_id: "w1", channel_type: "email" }),
    sub({ id: "c", user_id: null, project_id: "w2", channel_type: "slack" }),
    sub({ id: "d", user_id: null, project_id: "w2", event_type: "*" }),
  ], (id) => names[id]);
  assert.deepEqual(rows.map((row) => row.id), ["c", "b", "a"]);
});

test("a Workspace alert needs an enabled connection of its kind (the chosen one when set)", () => {
  const connections = [{ id: 1, plugin_id: "msteams", enabled: true }, { id: 2, plugin_id: "slack", enabled: false }];
  assert.equal(workspaceAlertState(sub({ is_active: false }), connections), "Off");
  assert.equal(workspaceAlertState(sub({ channel_type: "teams" }), connections), "Active");
  assert.equal(workspaceAlertState(sub({ channel_type: "teams", channel_config_id: 9 }), connections), "Needs configuration");
  assert.equal(workspaceAlertState(sub({ channel_type: "slack" }), connections), "Needs configuration");
  assert.equal(workspaceAlertState(sub({}), connections), "Needs configuration");
});
