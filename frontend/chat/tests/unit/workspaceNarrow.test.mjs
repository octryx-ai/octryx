// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workspaceNarrow.test.mjs
//
// Workspace › Connections › narrow (UX audit Welle 2): a connection is defined once globally; a workspace
// only narrows it. The page offers exactly the global spaces, stores only what differs, and never a wider value.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  changeText,
  deviationOf,
  draftOf,
  draftProblem,
  fieldState,
  levelOptions,
} from "../../src/admin/components/projectsTab/workspaceNarrowModel.ts";

const base = {
  knowledge: { enabled: true, scope: { spaces: ["RIVER", "SHOP", "PRJ", "DOCS", "ARCH"] }, schedule: "daily" },
  agent_tools: { level: "write" },
};
const connection = { id: "c1", name: "Confluence", type: "confluence", state: "ok", base, effective: base, deviation: null, can_edit: true };

test("the draft starts from what applies; unchanged means nothing to store", () => {
  const draft = draftOf(connection);
  assert.deepEqual(draft.knowledge.items, ["RIVER", "SHOP", "PRJ", "DOCS", "ARCH"]);
  assert.equal(draft.level, "write");
  assert.equal(deviationOf(base, draft), null);
  assert.equal(changeText(null), "Inherited from global");
});

test("only the narrowed fields are stored", () => {
  const draft = { knowledge: { enabled: true, items: ["RIVER", "SHOP"] }, level: "read" };
  const deviation = deviationOf(base, draft);
  assert.deepEqual(deviation, { knowledge: { scope: { spaces: ["RIVER", "SHOP"] } }, agent_tools: { level: "read" } });
  assert.equal(changeText(deviation), "2 changes from global");
  assert.equal(fieldState(deviation, "knowledge", "scope"), "Narrowed");
  assert.equal(fieldState(deviation, "knowledge", "enabled"), "Inherited");
  assert.deepEqual(deviationOf(base, { knowledge: { enabled: false, items: [] } }), { knowledge: { enabled: false } });
});

test("levels go only down to off, and an empty scope on an active use is named", () => {
  assert.deepEqual(levelOptions("write"), ["off", "read", "write"]);
  assert.deepEqual(levelOptions("read"), ["off", "read"]);
  assert.deepEqual(levelOptions("off"), ["off"]);
  assert.match(draftProblem({ knowledge: { enabled: true, items: [] } }, base), /at least one/);
  // No global scope to pick from (Bitbucket): nothing to complain about.
  assert.equal(draftProblem({ knowledge: { enabled: true, items: [] } }, { knowledge: { enabled: true, scope: null } }), null);
  assert.equal(draftProblem({ knowledge: { enabled: false, items: [] } }), null);
});
