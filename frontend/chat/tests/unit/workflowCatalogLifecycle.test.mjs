import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { scopedWorkflowOptions, useWorkflowCatalog } from "../../src/chat/useWorkflowCatalog.ts";
import { workflowOptionTitle } from "../../src/chat/composer/workflowClass.ts";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;
function setup() {
  const original = globalThis.fetch;
  const pending = []; let current; let renderer;
  globalThis.fetch = (url) => new Promise((resolve, reject) => pending.push({ url, resolve, reject }));
  function Probe({ scope }) { current = useWorkflowCatalog(scope); return null; }
  act(() => { renderer = TestRenderer.create(createElement(Probe, { scope: "a" })); });
  return { pending, get current() { return current; },
    scope(scope) { act(() => renderer.update(createElement(Probe, { scope }))); },
    async resolve(index, key) { await act(async () => pending[index].resolve({ ok: true, json: async () => ({
      workflows: [{ key }], workflow_proposal_enabled: true,
    }) })); },
    async reject(index) { await act(async () => pending[index].reject(new Error("Denied"))); },
    close() { act(() => renderer.unmount()); globalThis.fetch = original; },
  };
}
test("workflow catalog carries composer scope and Global uses only the global endpoint", async () => {
  const p = setup(); try {
    assert.equal(p.pending[0].url, "/chat/api/workflows?project_id=a");
    await p.resolve(0, "repository-questions");
    assert.equal(p.current.options[0].key, "repository-questions");
    p.scope(""); assert.equal(p.current.status, "loading"); assert.deepEqual(p.current.options, []);
    assert.equal(p.pending[1].url, "/chat/api/workflows");
    await p.resolve(1, "global"); assert.equal(p.current.workspaceId, "");
  } finally { p.close(); }
});
test("late results cannot reinstate another workspace's choices, including A to B to A", async () => {
  const p = setup(); try {
    await p.resolve(0, "old-a"); p.scope("b"); p.scope("a");
    assert.deepEqual(p.current.options, []);
    await p.resolve(1, "b"); assert.deepEqual(p.current.options, []);
    await p.resolve(2, "new-a"); assert.equal(p.current.options[0].key, "new-a");
  } finally { p.close(); }
});
test("an obsolete failure cannot erase the current scoped catalog", async () => {
  const p = setup(); try {
    p.scope("b"); await p.resolve(1, "b"); await p.reject(0);
    assert.equal(p.current.status, "ready"); assert.equal(p.current.options[0].key, "b");
  } finally { p.close(); }
});
test("current failures retain no old choices or proposal configuration", async () => {
  const p = setup(); try {
    await p.resolve(0, "a"); p.scope("b"); await p.reject(1);
    assert.equal(p.current.status, "error"); assert.deepEqual(p.current.options, []);
    assert.equal(p.current.proposalsEnabled, false);
  } finally { p.close(); }
});

test("workspace definitions override matching global keys with one option and foreign scopes are excluded", () => {
  const local = { key: "same", project_id: "a", title: "Local" };
  const global = { key: "same", project_id: null, title: "Global" };
  const foreign = { key: "private", project_id: "b" };
  for (const options of [[local, global, foreign], [global, local, foreign]]) {
    assert.deepEqual(scopedWorkflowOptions(options, "a"), [local]);
    assert.deepEqual(scopedWorkflowOptions(options, ""), [global]);
  }
});

test("Two workflows with the same title are told apart by their key; a unique title stays as it is", () => {
  const options = [{ key: "companion-fixture-a", title: "Companion acceptance fixture" },
    { key: "companion-fixture-b", title: "Companion acceptance fixture" }, { key: "diagnose", title: "Diagnose" }];
  assert.deepEqual(options.map((option) => workflowOptionTitle(option, options)), [
    "Companion acceptance fixture (companion-fixture-a)", "Companion acceptance fixture (companion-fixture-b)", "Diagnose"]);
});
