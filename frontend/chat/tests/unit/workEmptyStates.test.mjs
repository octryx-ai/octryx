import assert from "node:assert/strict";
import { test } from "node:test";
import { workEmptyStateFor } from "../../src/chat/work/workEmptyStates.ts";

test("without Jira every work list leads to connecting Jira and creating an intake", () => {
  const content = workEmptyStateFor("board", false, false);
  assert.deepEqual(content.actions.map((entry) => entry.action), ["connectJira", "openSyncSettings"]);
});

test("a filtered work item list says so; plan views have their own empty states (workPlanViews.test.mjs)", () => {
  assert.match(workEmptyStateFor("items", true, true).title, /filters/);
});
