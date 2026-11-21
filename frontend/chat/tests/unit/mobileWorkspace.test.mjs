// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/mobileWorkspace.test.mjs
//
// The phone's Workspace choice: a stale or foreign choice falls back to all Workspaces, things without a
// Workspace stay visible under every choice, and blocked browser storage never breaks the app.
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ALL_WORKSPACES,
  inWorkspace,
  newChatWorkspace,
  readWorkspaceChoice,
  resolveWorkspace,
  storeWorkspaceChoice,
  usageWorkspace,
  workspaceName,
} from "../../src/mobile/mobileWorkspace.ts";

const WORKSPACES = [
  { id: "shop", name: "Demo Shop" },
  { id: "mine", name: "Private", private: true, isDefault: true },
];

function memoryStore() {
  const values = new Map();
  return {
    getItem: (key) => (values.has(key) ? values.get(key) : null),
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  };
}

test("a choice that is no longer one of the person's Workspaces shows all of them", () => {
  assert.equal(resolveWorkspace("shop", WORKSPACES), "shop");
  assert.equal(resolveWorkspace("removed-or-foreign", WORKSPACES), ALL_WORKSPACES);
  assert.equal(resolveWorkspace("shop", []), ALL_WORKSPACES);
  assert.equal(workspaceName("removed-or-foreign", WORKSPACES), "All workspaces");
});

test("the filter keeps only the chosen Workspace, and things without one under every choice", () => {
  assert.equal(inWorkspace("shop", "shop"), true);
  assert.equal(inWorkspace("mine", "shop"), false);
  assert.equal(inWorkspace("", "shop"), true);
  assert.equal(inWorkspace(null, "shop"), true);
  assert.equal(inWorkspace("mine", ALL_WORKSPACES), true);
});

test("the choice survives in the phone's storage and blocked storage falls back to all Workspaces", () => {
  const store = memoryStore();
  storeWorkspaceChoice(store, "shop");
  assert.equal(readWorkspaceChoice(store), "shop");
  storeWorkspaceChoice(store, ALL_WORKSPACES);
  assert.equal(readWorkspaceChoice(store), ALL_WORKSPACES);
  const blocked = {
    getItem: () => {
      throw new Error("SecurityError");
    },
    setItem: () => {
      throw new Error("QuotaExceededError");
    },
    removeItem: () => undefined,
  };
  assert.equal(readWorkspaceChoice(blocked), ALL_WORKSPACES);
  assert.doesNotThrow(() => storeWorkspaceChoice(blocked, "shop"));
  assert.equal(readWorkspaceChoice(null), ALL_WORKSPACES);
});

test("a new chat starts in the chosen Workspace, else the default; usage follows the choice", () => {
  assert.equal(newChatWorkspace("shop", WORKSPACES), "shop");
  assert.equal(newChatWorkspace(ALL_WORKSPACES, WORKSPACES), "mine");
  assert.equal(newChatWorkspace("gone", WORKSPACES), "mine");
  assert.equal(usageWorkspace("shop", WORKSPACES, "mine"), "shop");
  assert.equal(usageWorkspace(ALL_WORKSPACES, WORKSPACES, "shop"), "shop");
  assert.equal(usageWorkspace(ALL_WORKSPACES, WORKSPACES), "mine");
});
