import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement, useState } from "react";
import TestRenderer from "react-test-renderer";
import { urlWithFlowId, urlWithoutFlowId, useFlowDeepLink } from "../../src/admin/components/flowBuilder/useFlowDeepLink.ts";
import { flowEditorHref } from "../../src/admin/editorLinks.ts";

const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

test("leaving the editor removes only flow_id from the URL", () => {
  const href = `https://octryx.example${flowEditorHref("7784cd96-1fa5-4bd5-8bfc-1b7f225a2d1d")}#canvas`;
  assert.equal(urlWithoutFlowId(href), "/chat?area=workflows&tab=workflowList&view=canvas#canvas");
  assert.equal(urlWithoutFlowId("https://octryx.example/chat?area=workflows&tab=workflowList"), null);
  assert.equal(urlWithoutFlowId("not a url"), null);
});

test("the open workflow is written to the URL once", () => {
  assert.equal(urlWithFlowId("https://octryx.example/chat?area=workflows&tab=workflowList#c", "f-1"), "/chat?area=workflows&tab=workflowList&flow_id=f-1#c");
  assert.equal(urlWithFlowId("https://octryx.example/chat?tab=workflowList&flow_id=f-1", "f-1"), null);
  assert.equal(urlWithFlowId("not a url", "f-1"), null);
});

function fakeWindow(href) {
  const win = { location: {}, history: { state: null } };
  const go = (next) => {
    const url = new URL(next, win.location.href || undefined);
    win.location.href = url.href;
    win.location.search = url.search;
  };
  win.history.replaceState = (state, _title, url) => { win.history.state = state; go(url); };
  go(href);
  return win;
}

// The same glue as AdminFlowBuilderTab: Open loads the workflow and shows the editor; Back shows the list.
function makeEditor(opened) {
  let api;
  function Editor() {
    const [openId, setOpenId] = useState(null);
    const open = async (flowId) => { opened.push(flowId); setOpenId(flowId); };
    useFlowDeepLink(open, openId);
    api = { open, back: () => setOpenId(null) };
    return createElement("p", null, openId ?? "list");
  }
  return { Editor, api: () => api };
}

test("a workflow opened from the list survives the admin loader's remount (the lost first Open click)", async () => {
  globalThis.window = fakeWindow("https://octryx.example/chat?area=workflows&tab=workflowList");
  const opened = [];
  const { Editor, api } = makeEditor(opened);
  let view;
  act(() => { view = TestRenderer.create(createElement(Editor)); });
  await act(async () => { await api().open("f-1"); });
  assert.equal(new URL(window.location.href).searchParams.get("flow_id"), "f-1");
  // AdminPanelContent replaces the panel with "Loading…" and mounts it again.
  act(() => view.unmount());
  await act(async () => { view = TestRenderer.create(createElement(Editor)); });
  assert.deepEqual(opened, ["f-1", "f-1"], "the remounted editor reopens the same workflow");
  assert.equal(view.toJSON().children[0], "f-1");
  act(() => api().back());
  assert.equal(window.location.href, "https://octryx.example/chat?area=workflows&tab=workflowList", "back to the list clears it");
  act(() => view.unmount());
  act(() => { view = TestRenderer.create(createElement(Editor)); });
  assert.equal(view.toJSON().children[0], "list", "a later mount shows the list");
  act(() => view.unmount());
  delete globalThis.window;
});
