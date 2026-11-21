// Render guard for the app shell: loading and error states, the Spec Studio render, and the page each area shows with
// the props it gets stay the same when the shell is split into smaller parts. Every child is stubbed by module name.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { load, noop, render } from "./renderGuardHarness.mjs";

// A stub that shows its name, its plain props and the viewer it gets; children render inside it.
const probe = (name) => (props) => createElement("div", {
  "data-testid": name,
  "data-props": JSON.stringify(Object.fromEntries(Object.entries(props)
    .filter(([key, value]) => key === "viewer" || ["string", "number", "boolean"].includes(typeof value)).sort())),
}, props.children ?? null);
const pass = (props) => props.children;

function loadShell(windowStub, helpOpen) {
  const names = ["BootstrapUnavailable", "AdminAreaWorkspace", "AreaRail", "CompactAreaMenu", "AgentsAreaWorkspace", "PageHelpDrawer",
    "AppContainerOverlays", "CodingWorkspaceEntry", "WorkAreaWorkspace", "SpecStudioPage", "SpecStudioRender",
    "PersonalSettingsWorkspace", "SetupGuidePage", "AdminReturnFrame", "ChatAppArea"];
  const stubs = Object.fromEntries(names.map((name) => [name, { [name]: probe(name) }]));
  return load("chat/AppContainerView.tsx", {
    ...stubs,
    CompanionHost: { CompanionHost: pass },
    usePageHelp: { usePageHelp: () => [helpOpen, noop], useHelpPage: (area) => `help:${area}` },
    adminReturn: { currentAdminReturn: () => null },
    specStudioAddress: { specStudioAddress: (search) => (search.includes("studio") ? { runId: "r1", render: search.includes("render") } : null) },
  }, { window: windowStub }).AppContainerView;
}

const chatState = (roles) => ({ currentUser: { id: "u1", username: "ann", roles }, projects: [{ id: "p1" }], selectedProjectId: "p1" });
const baseProps = {
  loading: false, error: null, activeBranding: { app_name: "Octryx Chat" }, adminPanelInitialTab: "users", currentUserName: "Ann",
  currentUserEmail: "ann@example.test", profileDropdownOpen: false, chatTheme: "dark", traceOpen: false, composerDisabled: false,
  setActiveArea: noop, openSettingsTab: noop, handleThreadSelect: noop, setProfileDropdownOpen: noop, setChatTheme: noop,
  setTraceOpen: noop, setPreviewArtifact: noop, loadState: async () => {}, extra: "chat-only",
};
const shape = (view) => {
  const out = [];
  const walk = (node) => {
    if (!node || typeof node === "string") return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    out.push(node.props["data-testid"] ? `${node.props["data-testid"]} ${node.props["data-props"]}` : `${node.type}.${node.props.className ?? ""}`);
    walk(node.children);
  };
  walk(view.toJSON());
  return out;
};

test("the shell shows loading, the bootstrap error and the bare Spec Studio render", async () => {
  const windowStub = { location: { search: "" }, history: { length: 1, back: noop } };
  const Shell = loadShell(windowStub, false);
  assert.deepEqual(shape(await render(Shell, { ...baseProps, chatState: null, loading: true, activeArea: "chat" })),
    ["div.chat-loading", "div.chat-loading__orb", "div."]);
  assert.deepEqual(shape(await render(Shell, { ...baseProps, chatState: null, error: "Down", activeArea: "chat" })),
    ['BootstrapUnavailable {"message":"Down"}']);
  windowStub.location.search = "?area=work&studio=1&render=1";
  assert.deepEqual(shape(await render(Shell, { ...baseProps, chatState: chatState(["admin"]), activeArea: "work" })),
    ["SpecStudioRender {}"]);
});

test("each area shows its page next to the menu, the rail and the overlays", async () => {
  const windowStub = { location: { search: "" }, history: { length: 1, back: noop } };
  const expected = {
    chat: ['ChatAppArea {"activeArea":"chat","adminPanelInitialTab":"users","chatTheme":"dark","composerDisabled":false,"currentUserEmail":"ann@example.test","currentUserName":"Ann","extra":"chat-only","loading":false,"profileDropdownOpen":false,"traceOpen":false}'],
    work: ["AdminReturnFrame {}", 'WorkAreaWorkspace {"canManageWork":true,"initialWorkspaceId":"p1","viewer":{"id":"u1","name":"Ann","role":"admin"}}'],
    agents: ['AgentsAreaWorkspace {"fallbackWorkspaceId":"p1","isPlatformAdmin":true}'],
    personal: ['PersonalSettingsWorkspace {"fallbackWorkspaceId":"p1"}'],
    help: ['SetupGuidePage {"fallbackWorkspaceId":"p1","isAdmin":true,"userId":"u1"}'],
    coding: ["AdminReturnFrame {}", 'CodingWorkspaceEntry {"canManageWork":true,"initialWorkspaceId":"p1","isPlatformAdmin":true}'],
    admin: ['AdminAreaWorkspace {"adminPanelInitialTab":"users","area":"admin","currentUserId":"u1","isAdmin":true}'],
  };
  for (const [area, page] of Object.entries(expected)) {
    const lines = shape(await render(loadShell(windowStub, true), { ...baseProps, chatState: chatState(["admin"]), activeArea: area }));
    assert.deepEqual(lines, [
      "div.app-shell app-shell--help-open",
      'CompactAreaMenu {"activeArea":"' + area + '","canManageWork":true,"canReadWork":true,"fallbackWorkspaceId":"p1","isAdmin":true}',
      'AreaRail {"activeArea":"' + area + '","brandFallbackLabel":"OC","chatTheme":"dark","currentUserCanReadWork":true,"currentUserEmail":"ann@example.test","currentUserId":"u1","currentUserIsAdmin":true,"currentUserName":"Ann","fallbackWorkspaceId":"p1","profileDropdownOpen":false}',
      ...page,
      'AppContainerOverlays {"canInspectSetup":true,"composerDisabled":false,"traceOpen":false}',
      'PageHelpDrawer {"area":"' + area + '","page":"help:' + area + '"}',
    ], area);
  }
  windowStub.location.search = "?area=work&studio=1";
  const studio = shape(await render(loadShell(windowStub, false), { ...baseProps, chatState: chatState(["member"]), activeArea: "work" }));
  assert.deepEqual(studio.slice(3), ['SpecStudioPage {"runId":"r1"}', 'AppContainerOverlays {"canInspectSetup":false,"composerDisabled":false,"traceOpen":false}']);
  assert.equal(studio[0], "div.app-shell");
  const member = shape(await render(loadShell({ location: { search: "" } }, false), { ...baseProps, chatState: chatState(["member"]), activeArea: "operations" }));
  assert.match(member[3], /^ChatAppArea .*"activeArea":"operations"/);
});
