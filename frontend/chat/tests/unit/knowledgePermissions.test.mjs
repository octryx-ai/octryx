import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { useKnowledgePermissions } from "../../src/chat/knowledge/useKnowledgePermissions.ts";
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;
function setup() {
  const pending = []; let value; let renderer;
  const load = (workspace) => new Promise((resolve, reject) => pending.push({ workspace, resolve, reject }));
  function Probe({ workspace }) { value = useKnowledgePermissions(workspace, load); return null; }
  act(() => { renderer = TestRenderer.create(createElement(Probe, { workspace: "a" })); });
  return { pending, get value() { return value; },
    scope(workspace) { act(() => renderer.update(createElement(Probe, { workspace }))); },
    async resolve(index, permission) { await act(async () => pending[index].resolve({ may_author: permission })); },
    async reject(index) { await act(async () => pending[index].reject(new Error("Denied"))); },
    close() { act(() => renderer.unmount()); } };
}
test("knowledge authoring fails closed until the server confirms it", async () => {
  const p = setup(); try { assert.equal(p.value, false); await p.resolve(0, true); assert.equal(p.value, true); }
  finally { p.close(); }
});
test("old author rights cannot reappear after leaving and returning to a workspace", async () => {
  const p = setup(); try { await p.resolve(0, true); p.scope("b"); assert.equal(p.value, false);
    p.scope("a"); assert.equal(p.value, false); await p.resolve(1, true); assert.equal(p.value, false);
    await p.resolve(2, false); assert.equal(p.value, false); } finally { p.close(); }
});
test("missing permissions and rejected reads never enable mutation controls", async () => {
  const p = setup(); try { await p.resolve(0, undefined); assert.equal(p.value, false);
    p.scope("b"); await p.reject(1); assert.equal(p.value, false); } finally { p.close(); }
});
