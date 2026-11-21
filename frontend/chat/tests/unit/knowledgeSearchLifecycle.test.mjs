import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { useKnowledgeSearch } from "../../src/admin/components/workspaceKnowledge/useKnowledgeSearch.ts";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;
const result = (name) => ({ evidence: [{ evidence_key: name }] });

function setup(workspaceId = "workspace-a") {
  const pending = [];
  let current;
  const search = (workspace, body) => new Promise((resolve, reject) => {
    pending.push({ workspace, body, resolve, reject });
  });
  function Probe({ workspace }) {
    current = useKnowledgeSearch(workspace, search);
    return null;
  }
  let renderer;
  act(() => { renderer = TestRenderer.create(createElement(Probe, { workspace: workspaceId })); });
  return {
    pending,
    get current() { return current; },
    submit(query) { act(() => { void current.submit({ query_text: query, mode: "hybrid" }); }); },
    scope(workspace) { act(() => { renderer.update(createElement(Probe, { workspace })); }); },
    async resolve(index, value) { await act(async () => { pending[index].resolve(value); }); },
    async reject(index, message) { await act(async () => { pending[index].reject(new Error(message)); }); },
    close() { act(() => renderer.unmount()); },
  };
}

test("a failed replacement search cannot display the previous successful evidence", async () => {
  const probe = setup();
  try {
    probe.submit(" first query ");
    assert.equal(probe.pending[0].workspace, "workspace-a");
    assert.equal(probe.pending[0].body.query_text, "first query");
    await probe.resolve(0, result("first"));
    assert.deepEqual(probe.current.result, result("first"));
    probe.submit("second query");
    assert.equal(probe.current.result, null);
    assert.equal(probe.current.busy, true);
    await probe.reject(1, "Storage unavailable");
    assert.equal(probe.current.result, null);
    assert.equal(probe.current.error, "Storage unavailable");
    assert.equal(probe.current.busy, false);
  } finally { probe.close(); }
});

test("a late response cannot overwrite the newer successful request", async () => {
  const probe = setup();
  try {
    probe.submit("older"); probe.submit("newer");
    await probe.resolve(1, result("newer"));
    await probe.resolve(0, result("older"));
    assert.equal(probe.current.query, "newer");
    assert.deepEqual(probe.current.result, result("newer"));
  } finally { probe.close(); }
});

test("a late error cannot finish or fail the current pending search", async () => {
  const probe = setup();
  try {
    probe.submit("older"); probe.submit("newer");
    await probe.reject(0, "Old failure");
    assert.equal(probe.current.busy, true);
    assert.equal(probe.current.error, null);
    await probe.resolve(1, { evidence: [] });
    assert.deepEqual(probe.current.result, { evidence: [] });
    assert.equal(probe.current.busy, false);
  } finally { probe.close(); }
});

test("scope changes discard completed results even when returning to the original workspace", async () => {
  const probe = setup();
  try {
    probe.submit("private evidence");
    await probe.resolve(0, result("workspace-a-evidence"));
    probe.scope("workspace-b");
    assert.equal(probe.current.result, null);
    probe.scope("workspace-a");
    assert.equal(probe.current.result, null);
  } finally { probe.close(); }
});

test("a request abandoned by a workspace change cannot leak into another scope", async () => {
  const probe = setup();
  try {
    probe.submit("pending in a"); probe.scope("workspace-b");
    probe.submit("pending in b");
    assert.equal(probe.pending[1].workspace, "workspace-b");
    await probe.resolve(0, result("workspace-a-evidence"));
    assert.equal(probe.current.result, null);
    assert.equal(probe.current.busy, true);
    await probe.resolve(1, result("workspace-b-evidence"));
    assert.deepEqual(probe.current.result, result("workspace-b-evidence"));
  } finally { probe.close(); }
});

test("missing scope and empty queries do not trigger a request", () => {
  const probe = setup("");
  try {
    probe.submit("hello"); probe.scope("workspace-a"); probe.submit("  ");
    assert.equal(probe.pending.length, 0);
    assert.equal(probe.current.result, null);
  } finally { probe.close(); }
});

test("a refusal keeps the Knowledge state the server named, and a new search clears it", async () => {
  const probe = setup();
  try {
    probe.submit("rollback");
    await act(async () => {
      probe.pending[0].reject(Object.assign(new Error("Workspace knowledge storage is not configured."),
        { status: 503, state: "needs_configuration" }));
    });
    assert.equal(probe.current.errorState, "needs_configuration");
    probe.submit("rollback again");
    assert.equal(probe.current.errorState, null);
    await probe.reject(1, "Plain failure");
    assert.equal(probe.current.error, "Plain failure");
    assert.equal(probe.current.errorState, null);
  } finally { probe.close(); }
});
