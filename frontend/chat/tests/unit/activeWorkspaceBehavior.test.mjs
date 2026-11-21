// Behaviour of the shared active workspace (judge findings J-A-001/003)
// and of the sign-in restriction save (J-A-002), exercised as user transitions.
import assert from "node:assert/strict";
import { test, beforeEach } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;

function installWindow(href) {
  const target = new EventTarget();
  const store = new Map();
  const win = Object.assign(target, {
    location: new URL(href),
    history: {
      state: null,
      replaceState(_state, _title, next) { win.location = new URL(next); },
      pushState(_state, _title, next) { win.location = new URL(next); },
    },
    localStorage: {
      getItem: (key) => (store.has(key) ? store.get(key) : null),
      setItem: (key, value) => store.set(key, String(value)),
      removeItem: (key) => store.delete(key),
    },
  });
  Object.defineProperty(win.location, "search", { get() { return new URL(win.location.href).search; } });
  globalThis.window = win;
  return win;
}

const { useActiveWorkspace } = await import("../../src/chat/useActiveWorkspace.ts");
const { setActiveWorkspaceUser, hrefWithWorkspace } = await import("../../src/chat/activeWorkspace.ts");
const { saveSignInRestriction } = await import("../../src/admin/components/usersTab/signInRestriction.ts");
const PROJECTS = [{ id: "workspace-a" }, { id: "workspace-b" }];

function mount(fallbackId, projects = PROJECTS) {
  let current;
  function Probe() { current = useActiveWorkspace(projects, fallbackId); return null; }
  let renderer;
  act(() => { renderer = TestRenderer.create(createElement(Probe)); });
  return {
    get id() { return current[0]; },
    choose(next) { act(() => current[1](next)); },
    unmount() { act(() => renderer.unmount()); },
  };
}

beforeEach(() => { setActiveWorkspaceUser("user-1"); });

test("an explicit clear stays empty instead of falling back to the chat workspace (J-A-001)", () => {
  installWindow("http://localhost:8090/chat?area=knowledge");
  const view = mount("workspace-a");
  assert.equal(view.id, "workspace-a");
  view.choose("workspace-b");
  assert.equal(view.id, "workspace-b");
  view.choose("");
  assert.equal(view.id, "");
  view.unmount();
  const again = mount("workspace-a");
  assert.equal(again.id, "", "the cleared choice survives an area change");
  again.unmount();
});

test("a later explicit choice beats the URL workspace after an area remount and reload (J-A-003)", () => {
  const win = installWindow("http://localhost:8090/chat?area=knowledge&workspace_id=workspace-a");
  const view = mount(null);
  assert.equal(view.id, "workspace-a");
  view.choose("workspace-b");
  view.unmount();
  assert.equal(new URL(win.location.href).searchParams.get("workspace_id"), "workspace-b");
  assert.equal(mount(null).id, "workspace-b", "remount");
  installWindow(win.location.href);
  assert.equal(mount(null).id, "workspace-b", "reload keeps the choice in the URL");
});

test("back/forward restores the workspace of that history entry", () => {
  const win = installWindow("http://localhost:8090/chat?area=knowledge&workspace_id=workspace-b");
  const view = mount(null);
  win.location = new URL("http://localhost:8090/chat?area=knowledge&workspace_id=workspace-a");
  act(() => { win.dispatchEvent(new Event("popstate")); });
  assert.equal(view.id, "workspace-a");
  view.unmount();
});

test("preferences are per user, so a shared browser does not reopen another user's workspace", () => {
  const win = installWindow("http://localhost:8090/chat?area=knowledge");
  const first = mount(null);
  first.choose("workspace-b");
  first.unmount();
  // The next user signs in on a fresh /chat URL in the same browser storage.
  win.location = new URL("http://localhost:8090/chat?area=knowledge");
  setActiveWorkspaceUser("user-2");
  assert.equal(mount(null).id, "");
});

test("a failed SSO save response never claims that nothing changed (J-A-002)", async () => {
  const committedThenLost = async (url, init) => {
    if (init?.method === "PUT") throw new Error("connection reset after commit");
    return { auth_oidc_only: true };
  };
  assert.deepEqual(await saveSignInRestriction(committedThenLost, true), { state: "unconfirmed", effective: true });
  const unreachable = async () => { throw new Error("offline"); };
  assert.deepEqual(await saveSignInRestriction(unreachable, true), { state: "unknown" });
  let body;
  const ok = async (url, init) => { body = init?.body; return { auth_oidc_only: false }; };
  assert.deepEqual(await saveSignInRestriction(ok, false), { state: "saved", effective: false });
  assert.deepEqual(JSON.parse(body), { auth_oidc_only: false }, "only the sign-in key is written");
});

const { useChatWorkspaceSync } = await import("../../src/chat/useActiveWorkspace.ts");

function mountChatSync(initialProject, hasSession = false, allowGlobal = true, projects = PROJECTS) {
  let setProject;
  let selected = initialProject;
  function Probe({ project }) {
    useChatWorkspaceSync("user-1", project, (next) => { selected = next; }, projects, hasSession, allowGlobal);
    return null;
  }
  let renderer;
  act(() => { renderer = TestRenderer.create(createElement(Probe, { project: initialProject })); });
  setProject = (next) => act(() => renderer.update(createElement(Probe, { project: next })));
  return { setProject, get selected() { return selected; }, unmount: () => act(() => renderer.unmount()) };
}

test("an explicit Global choice in a new chat is kept, not reopened from storage or URL (J-A-004)", () => {
  const win = installWindow("http://localhost:8090/chat?workspace_id=workspace-a");
  const chat = mountChatSync("workspace-a");
  chat.setProject("");
  assert.equal(new URL(win.location.href).searchParams.has("workspace_id"), false);
  chat.unmount();
  assert.equal(mount("workspace-a").id, "", "the next area does not reopen workspace-a");
});

test("switching to an existing Global session does not rewrite the workspace choice", () => {
  installWindow("http://localhost:8090/chat");
  const chat = mountChatSync("workspace-b", true);
  chat.setProject("workspace-b");
  chat.setProject("");
  chat.unmount();
  assert.equal(mount(null).id, "workspace-b");
});

test("back to an entry without workspace_id equals reloading that entry", () => {
  const win = installWindow("http://localhost:8090/chat?area=knowledge");
  const view = mount(null);
  view.choose("workspace-b");
  win.location = new URL("http://localhost:8090/chat?area=knowledge&workspace_id=workspace-a");
  act(() => { win.dispatchEvent(new Event("popstate")); });
  assert.equal(view.id, "workspace-a");
  win.location = new URL("http://localhost:8090/chat?area=knowledge");
  act(() => { win.dispatchEvent(new Event("popstate")); });
  const reloaded = mount(null).id;
  assert.equal(view.id, reloaded, "same result as a fresh load of the entry");
  view.unmount();
});

test("after an unknown save outcome the page does not claim the effective setting (J-A-002)", async () => {
  const { signInEffectiveLabel } = await import("../../src/admin/components/usersTab/signInRestriction.ts");
  const unknown = signInEffectiveLabel("unknown", false);
  assert.equal(unknown.known, false);
  assert.match(unknown.text, /^Unknown — last confirmed/);
  assert.deepEqual(signInEffectiveLabel("unconfirmed", true), { known: true, text: "SSO only — password login is refused" });
});


test("explicit Global survives new-chat bootstrap for an authorized admin (J-A-004)", async () => {
  installWindow("http://localhost:8090/chat");
  const { storeWorkspacePreference } = await import("../../src/chat/activeWorkspace.ts");
  storeWorkspacePreference("");
  const chat = mountChatSync("workspace-a");
  assert.equal(chat.selected, "", "bootstrap must not reopen the former workspace");
  chat.unmount();
});

test("stored Global cannot override a member's required workspace", async () => {
  installWindow("http://localhost:8090/chat");
  const { storeWorkspacePreference } = await import("../../src/chat/activeWorkspace.ts");
  storeWorkspacePreference("");
  const chat = mountChatSync("workspace-a", false, false);
  assert.equal(chat.selected, "workspace-a");
  chat.unmount();
});

test("stored Global never changes an existing session scope", async () => {
  installWindow("http://localhost:8090/chat");
  const { storeWorkspacePreference } = await import("../../src/chat/activeWorkspace.ts");
  storeWorkspacePreference("");
  const chat = mountChatSync("workspace-b", true);
  assert.equal(chat.selected, "workspace-b");
  chat.unmount();
});

// The chat's projects (and every area's) are the active Workspaces only; "archived" is the Workspace of the admin's
// latest chat session, archived since. The Instance's default is "acme-orders" (review: "Work · Acme Orders" in the
// header while the address carried the archived Workspace's id).
const ACTIVE_ONLY = [{ id: "default" }, { id: "acme-orders", isDefault: true }];
const addressed = (win) => new URL(win.location.href).searchParams.get("workspace_id");

test("an archived Workspace of the latest chat never becomes the active one: header, address and API agree", () => {
  const win = installWindow("http://localhost:8090/chat?area=work");
  const chat = mountChatSync("archived", true, true, ACTIVE_ONLY);
  assert.equal(addressed(win), null, "the archived id is never written to the address");
  const view = mount("archived", ACTIVE_ONLY);
  assert.equal(view.id, "acme-orders", "the Instance's default, as the global switch shows");
  view.unmount();
  installWindow(win.location.href);
  assert.equal(mount("archived", ACTIVE_ONLY).id, "acme-orders", "a reload keeps it");
  chat.unmount();
});

test("an address or stored choice naming an archived Workspace is replaced by the default", async () => {
  const win = installWindow("http://localhost:8090/chat?area=work&workspace_id=archived&work_item_id=wi-1");
  const chat = mountChatSync("archived", true, true, ACTIVE_ONLY);
  assert.equal(addressed(win), "acme-orders");
  assert.equal(new URL(win.location.href).searchParams.get("work_item_id"), "wi-1", "the rest of the address stays");
  assert.equal(mount(null, ACTIVE_ONLY).id, "acme-orders");
  chat.unmount();

  const { storeWorkspacePreference } = await import("../../src/chat/activeWorkspace.ts");
  const stored = installWindow("http://localhost:8090/chat?area=work");
  storeWorkspacePreference("archived");
  const again = mountChatSync("archived", true, true, ACTIVE_ONLY);
  assert.equal(addressed(stored), "acme-orders");
  again.unmount();
});

test("an archived Workspace with no default to fall back to leaves no choice behind", () => {
  const win = installWindow("http://localhost:8090/chat?area=work&workspace_id=archived");
  const chat = mountChatSync("archived", true, true, PROJECTS);
  assert.equal(addressed(win), null);
  assert.equal(mount(null).id, "", "nothing guessed among several Workspaces");
  chat.unmount();
});

test("opening an old chat of an archived Workspace never moves the other areas there", () => {
  const win = installWindow("http://localhost:8090/chat?area=work");
  const chat = mountChatSync("acme-orders", false, true, ACTIVE_ONLY);
  assert.equal(addressed(win), "acme-orders");
  chat.setProject("archived");
  assert.equal(addressed(win), "acme-orders");
  assert.equal(mount(null, ACTIVE_ONLY).id, "acme-orders");
  chat.unmount();
});
