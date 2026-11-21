import assert from "node:assert/strict";
import { test } from "node:test";
import { partitionThreadGroups } from "../../src/chat/threadGroupPartition.ts";

test("threads of workspaces the chat cannot select move into one section, nothing is dropped", () => {
  const groups = [
    { projectId: "", sessions: [1, 2] },
    { projectId: "active-a", sessions: [1] },
    { projectId: "other-x", sessions: [1, 2, 3], totalThreadCount: 7 },
    { projectId: "other-y", sessions: [1] },
  ];
  const result = partitionThreadGroups(groups, new Set(["active-a"]));
  assert.deepEqual(result.active.map((g) => g.projectId), ["", "active-a"]);
  assert.deepEqual(result.other.map((g) => g.projectId), ["other-x", "other-y"]);
  assert.equal(result.otherThreadCount, 8);
  assert.equal(result.active.length + result.other.length, groups.length);
});

test("before the selectable workspaces are known nothing moves (no flicker)", () => {
  const groups = [{ projectId: "a", sessions: [1] }, { projectId: "b", sessions: [1] }];
  const result = partitionThreadGroups(groups, new Set());
  assert.equal(result.active.length, 2);
  assert.equal(result.other.length, 0);
});
