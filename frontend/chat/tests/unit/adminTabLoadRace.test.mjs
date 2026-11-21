// Switching admin tabs while an earlier load still runs must not end the new tab's loading early.
// A previous tab's load that finishes first must not show an empty state for the active tab.
import assert from "node:assert/strict";
import { test } from "node:test";

import { runTabLoad } from "../../src/admin/hooks/useAdminTabLoader.ts";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
}

function harness() {
  const pending = new Map();
  const state = { loading: [], error: null, users: null, projects: null };
  const args = {
    readJson: (url) => {
      const next = deferred();
      pending.set(url, next);
      return next.promise;
    },
    setLoadingTab: (value) => state.loading.push(value),
    setTabError: (value) => { state.error = value; },
    setUsers: (value) => { state.users = value; },
    setAdminProjects: (value) => { state.projects = value; },
  };
  return { pending, state, args };
}

test("an earlier tab finishing first leaves the new tab loading", async () => {
  const { pending, state, args } = harness();
  const counter = { current: 0 };
  const users = runTabLoad(counter, "users", args);
  const projects = runTabLoad(counter, "projects", args);
  pending.get("/admin/chat/api/panel/users").resolve([{ id: "u1" }]);
  await users;
  assert.deepEqual(state.loading, [true, true], "still loading Workspaces");
  pending.get("/admin/chat/api/panel/projects").resolve([{ id: "p1" }]);
  await projects;
  assert.deepEqual(state.loading, [true, true, false]);
  assert.deepEqual(state.projects, [{ id: "p1" }]);
});

test("only the latest load reports its failure", async () => {
  const { pending, state, args } = harness();
  const counter = { current: 0 };
  const users = runTabLoad(counter, "users", args);
  const projects = runTabLoad(counter, "projects", args);
  pending.get("/admin/chat/api/panel/users").reject(new Error("old tab failed"));
  await users;
  assert.equal(state.error, null);
  pending.get("/admin/chat/api/panel/projects").reject(new Error("Workspaces could not be loaded"));
  await projects;
  assert.equal(state.error, "Workspaces could not be loaded");
  assert.equal(state.loading.at(-1), false);
});
