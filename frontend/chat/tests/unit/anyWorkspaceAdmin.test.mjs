import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { TestRenderer, act, flush, loader, windowStub } from "./adminFlowRenderHarness.mjs";

function harness(answers) {
  const calls = [];
  const fetch = (url) => {
    calls.push(url);
    const next = answers.shift();
    return next instanceof Error ? Promise.reject(next) : Promise.resolve({ ok: next });
  };
  const load = loader({ window: windowStub(), fetch });
  const { useAnyWorkspaceAdmin } = load("admin/components/operations/useWorkspaceAdmin.ts");
  const Probe = ({ enabled, userId }) => String(useAnyWorkspaceAdmin(false, enabled, userId));
  return { calls, Probe };
}

test("a failed eligibility request is asked again when the area reopens", async () => {
  const { calls, Probe } = harness([new Error("offline"), true]);
  let view;
  await act(async () => { view = TestRenderer.create(createElement(Probe, { enabled: true, userId: "u-1" })); });
  await flush();
  assert.equal(view.toJSON(), "false");

  await act(async () => { view.update(createElement(Probe, { enabled: false, userId: "u-1" })); });
  await act(async () => { view.update(createElement(Probe, { enabled: true, userId: "u-1" })); });
  await flush();
  assert.equal(view.toJSON(), "true");
  assert.equal(calls.length, 2);
});

test("another signed-in user is asked anew and an older answer is dropped", async () => {
  let release;
  const slow = new Promise((resolve) => { release = resolve; });
  const calls = [];
  const fetch = () => { calls.push(1); return calls.length === 1 ? slow : Promise.resolve({ ok: false }); };
  const load = loader({ window: windowStub(), fetch });
  const { useAnyWorkspaceAdmin } = load("admin/components/operations/useWorkspaceAdmin.ts");
  const Probe = ({ userId }) => String(useAnyWorkspaceAdmin(false, true, userId));
  let view;
  await act(async () => { view = TestRenderer.create(createElement(Probe, { userId: "admin-of-other" })); });
  await act(async () => { view.update(createElement(Probe, { userId: "plain-member" })); });
  await flush();
  await act(async () => { release({ ok: true }); });
  await flush();
  assert.equal(view.toJSON(), "false");
  assert.equal(calls.length, 2);
});
