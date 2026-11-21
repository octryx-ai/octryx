// Out-of-order page responses never mix two queries (judge J-C-002).
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { useSourcePages } from "../../src/chat/knowledge/useSourcePages.ts";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;
const page = (ids, next = null) => ({ sources: ids.map((id) => ({ source_id: id, source_key: id, display_title: id, revision_count: 1, latest_revision_ordinal: 1 })), projection_backlog: {}, next_cursor: next });

function setup() {
  const pending = [];
  const request = (workspaceId, params) => new Promise((resolve, reject) => pending.push({ workspaceId, params, resolve, reject }));
  let current;
  function Probe({ workspace, query, refresh }) {
    current = useSourcePages(workspace, query, refresh, request, 50);
    return null;
  }
  let renderer;
  act(() => { renderer = TestRenderer.create(createElement(Probe, { workspace: "w1", query: "", refresh: 0 })); });
  return {
    pending,
    get state() { return current; },
    rerender(props) { act(() => renderer.update(createElement(Probe, { workspace: "w1", query: "", refresh: 0, ...props }))); },
    async resolve(index, value) { await act(async () => { pending[index].resolve(value); }); },
    async loadMore() { let done; act(() => { done = current.loadMore(); }); return done; },
  };
}

test("a late Load more of the previous query is not appended to a new search", async () => {
  const probe = setup();
  await probe.resolve(0, page(["old-first"], "old-next"));
  const more = probe.loadMore();
  assert.equal(probe.pending[1].params.cursor, "old-next");
  probe.rerender({ query: "new" });
  await probe.resolve(2, page(["new-hit"], null));
  await probe.resolve(1, page(["old-stale"], "old-third"));
  await act(async () => { await more; });
  assert.deepEqual(probe.state.loaded.map((s) => s.source_id), ["new-hit"]);
  assert.equal(probe.state.hasMore, false);
  assert.equal(probe.state.loadingMore, false);
});

test("a late first page of an old workspace or refresh is ignored", async () => {
  const probe = setup();
  probe.rerender({ workspace: "w2" });
  await probe.resolve(1, page(["w2-doc"]));
  await probe.resolve(0, page(["w1-doc"], "w1-next"));
  assert.deepEqual(probe.state.loaded.map((s) => s.source_id), ["w2-doc"]);
  probe.rerender({ workspace: "w2", refresh: 1 });
  assert.deepEqual(probe.state.loaded, [], "refresh clears before the new page arrives");
  await probe.resolve(2, page(["w2-doc", "w2-new"]));
  assert.equal(probe.state.loaded.length, 2);
});
