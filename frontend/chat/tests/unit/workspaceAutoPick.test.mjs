// Fresh-install review (UX review): the app picks the default or the only Workspace by itself while nothing is chosen,
// and every page without an active Workspace offers the choice inline instead of a bare sentence.
import assert from "node:assert/strict";
import { test, beforeEach } from "node:test";
import fs from "node:fs";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;

function installWindow(href) {
  const target = new EventTarget();
  const store = new Map();
  const win = Object.assign(target, {
    location: new URL(href),
    history: { state: null, replaceState(_s, _t, next) { win.location = new URL(next); }, pushState(_s, _t, next) { win.location = new URL(next); } },
    localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), setItem: (k, v) => store.set(k, String(v)), removeItem: (k) => store.delete(k) },
  });
  globalThis.window = win;
  return win;
}

const { useActiveWorkspace, automaticWorkspaceIdOf } = await import("../../src/chat/useActiveWorkspace.ts");
const { setActiveWorkspaceUser, storeWorkspacePreference } = await import("../../src/chat/activeWorkspace.ts");
const { ChooseWorkspaceLine } = await import("../../src/chat/workspace/ChooseWorkspaceLine.ts");

function mount(projects, fallbackId) {
  let current;
  function Probe() { current = useActiveWorkspace(projects, fallbackId); return null; }
  let renderer;
  act(() => { renderer = TestRenderer.create(createElement(Probe)); });
  return { get id() { return current[0]; }, unmount() { act(() => renderer.unmount()); } };
}

beforeEach(() => { setActiveWorkspaceUser("user-1"); });

test("the default, else the only Workspace is picked by itself; several without a default are not guessed", () => {
  assert.equal(automaticWorkspaceIdOf([{ id: "a" }]), "a");
  assert.equal(automaticWorkspaceIdOf([{ id: "a" }, { id: "b", is_default: true }]), "b");
  assert.equal(automaticWorkspaceIdOf([{ id: "a" }, { id: "b", isDefault: true }]), "b");
  assert.equal(automaticWorkspaceIdOf([{ id: "a" }, { id: "b" }]), "");
  assert.equal(automaticWorkspaceIdOf([]), "");

  installWindow("http://localhost/chat?area=knowledge");
  const only = mount([{ id: "demo" }]);
  assert.equal(only.id, "demo", "a fresh install with one Workspace needs no choice");
  only.unmount();
  const withDefault = mount([{ id: "a" }, { id: "b", is_default: true }]);
  assert.equal(withDefault.id, "b");
  withDefault.unmount();
  const several = mount([{ id: "a" }, { id: "b" }]);
  assert.equal(several.id, "");
  several.unmount();
});

test("an explicit choice, an explicit no-workspace and a URL workspace_id win over the automatic pick", () => {
  installWindow("http://localhost/chat?area=knowledge");
  storeWorkspacePreference("a");
  const chosen = mount([{ id: "a" }, { id: "b", is_default: true }]);
  assert.equal(chosen.id, "a");
  chosen.unmount();

  installWindow("http://localhost/chat?area=knowledge");
  storeWorkspacePreference("");
  const none = mount([{ id: "demo" }]);
  assert.equal(none.id, "", "an explicit no-workspace choice is kept");
  none.unmount();

  setActiveWorkspaceUser("user-2");
  installWindow("http://localhost/chat?area=knowledge&workspace_id=a");
  const fromUrl = mount([{ id: "a" }, { id: "b", is_default: true }]);
  assert.equal(fromUrl.id, "a");
  fromUrl.unmount();

  setActiveWorkspaceUser("user-3");
  installWindow("http://localhost/chat?area=knowledge");
  const unknownFallback = mount([{ id: "a" }, { id: "b", is_default: true }], "gone");
  assert.equal(unknownFallback.id, "b", "an unknown chat workspace falls through to the default");
  unknownFallback.unmount();
});

test("the inline choice lists the Workspaces and sets the one global context", () => {
  setActiveWorkspaceUser("user-4");
  const win = installWindow("http://localhost/chat?area=knowledge");
  const events = [];
  win.addEventListener("octryx-active-workspace-change", (event) => events.push(event.detail));
  let renderer;
  act(() => {
    renderer = TestRenderer.create(createElement(ChooseWorkspaceLine, {
      projects: [{ id: "a", name: "Alpha" }, { id: "b", name: "Beta" }], purpose: "to search its knowledge",
    }));
  });
  const text = JSON.stringify(renderer.toJSON());
  assert.match(text, /Choose a workspace/);
  assert.match(text, /to search its knowledge/);
  const select = renderer.root.findByProps({ "data-testid": "choose-workspace-select" });
  assert.deepEqual(select.findAllByType("option").map((o) => o.props.value), ["", "a", "b"]);
  act(() => select.props.onChange({ target: { value: "b" } }));
  assert.deepEqual(events, ["b"]);
  assert.match(win.location.href, /workspace_id=b/);
  act(() => renderer.unmount());

  act(() => { renderer = TestRenderer.create(createElement(ChooseWorkspaceLine, { projects: [] })); });
  assert.match(JSON.stringify(renderer.toJSON()), /No workspaces available/);
  act(() => renderer.unmount());
});

test("no page keeps a bare 'Select a workspace' sentence; the rail switch carries a visible word", () => {
  for (const file of ["src/chat/knowledge/KnowledgeAreaWorkspace.tsx", "src/chat/agents/AgentsAreaWorkspace.tsx",
    "src/chat/work/WorkAreaWorkspace.tsx", "src/chat/coding/CodingWorkspaceEntry.tsx"]) {
    const source = fs.readFileSync(new URL(`../../${file}`, import.meta.url), "utf8");
    assert.doesNotMatch(source, /Select a [Ww]orkspace to/, file);
    assert.match(source, /ChooseWorkspaceLine/, file);
  }
  const rail = fs.readFileSync(new URL("../../src/chat/workspace/GlobalWorkspaceSwitch.tsx", import.meta.url), "utf8");
  assert.match(rail, /global-workspace__caption[^>]*>Workspace</);
});
