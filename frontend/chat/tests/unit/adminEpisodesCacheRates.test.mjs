// The Workspace session-episode switches.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  EPISODE_POLICY_SWITCHES,
  episodePolicyPayload,
  episodePolicyView,
} from "../../src/admin/components/workspaceKnowledge/episodePolicy.ts";

const SETTINGS = {
  workspace_id: "ws-1",
  may_author: true,
  public_origin_configured: false,
  accept_session_episodes: false,
  future_switch: true,
};

test("known boolean keys are switches with their explanation; unknown keys are read-only rows", () => {
  const view = episodePolicyView(SETTINGS);
  assert.deepEqual(view.switches.map((row) => [row.key, row.value]), [["accept_session_episodes", false]]);
  assert.ok(view.switches[0].explanation.length > 0);
  assert.deepEqual(view.unknown, [{ key: "future_switch", value: true }]);
  assert.equal(view.mayAuthor, true);
  assert.equal(view.publicOriginConfigured, false);
  assert.ok(EPISODE_POLICY_SWITCHES.every((entry) => entry.key && entry.label && entry.explanation));
});

test("capture_platform_turns is a known switch, rendered after accept_session_episodes", () => {
  const view = episodePolicyView({ ...SETTINGS, capture_platform_turns: true });
  assert.deepEqual(
    view.switches.map((row) => [row.key, row.value]),
    [
      ["accept_session_episodes", false],
      ["capture_platform_turns", true],
    ],
  );
});

test("a known key the server does not return is not rendered", () => {
  const view = episodePolicyView({ workspace_id: "ws-1", may_author: false });
  assert.deepEqual(view.switches, []);
  assert.deepEqual(view.unknown, []);
});

test("saving a switch sends every policy value back, unknown keys included, never the envelope", () => {
  assert.deepEqual(episodePolicyPayload(SETTINGS, "accept_session_episodes", true), {
    accept_session_episodes: true,
    future_switch: true,
  });
});
