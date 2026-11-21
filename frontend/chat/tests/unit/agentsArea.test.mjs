// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/agentsArea.test.mjs
//
// The "Agents" main-menu area (root freeze 1). Every Workspace member gets the entry. "Connected clients" lists
// the Workspace's agent clients from GET /api/v1/agent-gateway/presence (contract item 5): user, client and profile,
// state, work item, branch, model and last seen, with 5h/7d allowance bars only when the server returned allowance
// (admins/owners, D2). It polls every 15 s while the page is visible. The views are chosen in the same collapsible
// second-level left menu as Work and Coding. "Message board" and "Claims and handoffs" are covered by
// agentBoard.test.mjs (freeze 2). The action-needed bell asks for browser-notification permission only on a
// click. Requests are stubs.
process.env.TZ = "Europe/Zurich";

import assert from "node:assert/strict";

import { formatDateTime } from "../../src/admin/utils/dateTime.ts";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import {
  allowanceBar,
  clientLabel,
  presenceErrorText,
  presenceSummary,
  readClient,
  readPresence,
  showsAllowance,
} from "../../src/chat/agents/agentPresenceModel.ts";
import {
  browserNotificationState,
  browserNotificationText,
  requestBrowserNotifications,
} from "../../src/chat/agents/browserNotifications.ts";
import { getWorkspaceDestinations } from "../../src/chat/workspaceDestinations.ts";
import { readFileSync } from "node:fs";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
// Connected clients is a design-system table: its rows, without the ⋯ menu cell.
const clientRowsOf = (view) => view.root.findAll((node) => node.type === "tr" && String(node.props.className || "").includes("ds-table__row"));
const rowText = (row) => row.findAll((node) => node.type === "td" && !String(node.props.className || "").includes("ds-table__menu-cell"))
  .map(text).join("");
const tabOf = (view, key) => view.root.find((node) => node.props.id === `agents-clients-tab-${key}`);
const json = (value) => JSON.parse(JSON.stringify(value));

const NOW = Date.parse("2026-10-05T12:00:00Z");
const MEMBER_ITEM = {
  id: "pe-anna", session_key_hash: "h-anna", sessions: 1, user: { id: "u1", display_name: "Anna" }, client: "octryx-claude", profile: "seat", state: "active",
  work_item: { id: "wi-6", key: "BRD-6", title: "Onboarding checklist" }, branch: "brd-6", model: "claude-sonnet-5",
  last_seen_at: "2026-10-05T11:58:00Z", allowance: null,
};
const ADMIN_ITEM = { ...MEMBER_ITEM, allowance: { five_hour_pct: 12.4, five_hour_resets_at: "2026-10-05T14:00:00Z",
  seven_day_pct: 95, seven_day_resets_at: "2026-10-09T08:00:00Z", status: "allowed_warning" } };

// ---- registration -------------------------------------------------------------------------------

test("every member gets the Agents entry, with its page help", () => {
  for (const [admin, work] of [[false, false], [false, true], [true, true]]) {
    assert.ok(getWorkspaceDestinations(admin, work).some((item) => item.area === "agents" && item.label === "Agents" && !item.adminTab));
  }
  assert.match(readFileSync(new URL("../../help/agents/index.md", import.meta.url), "utf8"), /^---\r?\ntitle: Agents\r?\n/);
});

// ---- model --------------------------------------------------------------------------------------

test("the presence listing is read strictly; members get no allowance, admins get it as sent", () => {
  assert.equal(readPresence({}), null);
  assert.equal(readPresence(null), null);
  assert.deepEqual(readPresence({ items: [{ user: {} }, null] }), [], "an entry without a stable id is left out");
  const member = readClient(MEMBER_ITEM);
  assert.deepEqual(json(member), { id: "pe-anna", sessions: 1, device: "", user: "Anna", userId: "u1", client: "octryx-claude", profile: "seat", state: "active",
    workItem: { id: "wi-6", key: "BRD-6", title: "Onboarding checklist" }, branch: "brd-6", model: "claude-sonnet-5",
    lastSeenAt: "2026-10-05T11:58:00Z", allowance: null, sensitive: null });
  assert.deepEqual(json(readClient(ADMIN_ITEM).allowance), { fiveHourPct: 12.4, fiveHourResetsAt: "2026-10-05T14:00:00Z",
    sevenDayPct: 95, sevenDayResetsAt: "2026-10-09T08:00:00Z", status: "allowed_warning" });
  assert.equal(readClient({ ...MEMBER_ITEM, state: "sleeping" }).state, "unknown");
  assert.equal(readClient({ ...MEMBER_ITEM, user: { id: "u9", display_name: "" } }).user, "u9");
  assert.equal(readClient({ ...MEMBER_ITEM, work_item: { id: "x" } }).workItem, null);
  assert.equal(readClient({ ...ADMIN_ITEM, allowance: { five_hour_pct: "12" } }).allowance.fiveHourPct, null, "only numbers");
  assert.equal(showsAllowance([member]), false);
  assert.equal(showsAllowance([member, readClient(ADMIN_ITEM)]), true);
  assert.equal(clientLabel(member), "octryx-claude · seat");
  assert.equal(clientLabel({ ...member, profile: "" }), "octryx-claude");
});

test("allowance bars: only for a sent percentage, clamped, toned at 80 and 100, with the reset in local time", () => {
  assert.equal(allowanceBar("5h", null, null, NOW), null);
  assert.deepEqual(json(allowanceBar("7d", 95, null, NOW)), { label: "7d", pct: 95, width: 95, tone: "attention", resets: null });
  assert.equal(allowanceBar("7d", 79.9, null, NOW).tone, "active");
  assert.equal(allowanceBar("7d", 120, null, NOW).width, 100);
  assert.equal(allowanceBar("7d", 100, null, NOW).tone, "danger");
  assert.equal(allowanceBar("7d", -5, null, NOW).width, 0);
  assert.equal(allowanceBar("5h", 12, "2026-10-05T14:00:00Z", NOW).resets, `resets ${formatDateTime("2026-10-05T14:00:00Z")}`);
  assert.equal(allowanceBar("5h", 12, "2026-10-05T11:00:00Z", NOW).resets, "resets now");
  const clients = readPresence({ items: [MEMBER_ITEM, { ...MEMBER_ITEM, id: "pe-2", session_key_hash: "h-2", state: "limit_reached" }] });
  assert.equal(presenceSummary(clients), "2 connected · 1 working now · 1 at their allowance limit");
  assert.equal(presenceSummary([]), "No agent client is connected to this Workspace.");
  assert.equal(presenceErrorText(Object.assign(new Error("Forbidden"), { status: 403 })).kind, "forbidden");
  assert.equal(presenceErrorText(Object.assign(new Error("Not Found"), { status: 404 })).text, "Only members of this Workspace can see its agents.");
  assert.equal(presenceErrorText(Object.assign(new Error("boom"), { status: 500 })).text, "The agent clients could not be loaded: boom.");
});

test("browser notifications: permission is asked only through the explicit request", async () => {
  let asked = 0;
  const api = { permission: "default", requestPermission: async () => { asked += 1; return "granted"; } };
  assert.equal(browserNotificationState(api), "default");
  assert.equal(asked, 0, "reading the state never asks");
  assert.equal(await requestBrowserNotifications(api), "granted");
  assert.equal(asked, 1);
  assert.equal(browserNotificationState(null), "unsupported");
  assert.equal(await requestBrowserNotifications(null), "unsupported");
  assert.equal(browserNotificationState({ ...api, permission: "denied" }), "denied");
  assert.match(browserNotificationText("denied"), /blocked for this site/);
});

test("browser notifications (C5): a rejected permission request ends in a neutral, retryable state", async () => {
  const api = { permission: "default", requestPermission: () => Promise.reject(new Error("SecurityError")) };
  assert.equal(await requestBrowserNotifications(api), "failed");
  assert.equal(browserNotificationText("failed"), "The browser did not complete the notification request. Nothing was changed; you can try again.");
});

// ---- rendered -----------------------------------------------------------------------------------

function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl,
      encodeURIComponent, FormData, setInterval, clearInterval, setTimeout, CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
      ...extra,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return loadFile(path.join(SRC, relative));
}

const windowStub = (storage = new Map()) => ({
  location: { origin: "http://localhost", search: "", href: "http://localhost/chat?area=agents" },
  localStorage: { getItem: (key) => storage.get(key) ?? null, setItem: (key, value) => { storage.set(key, String(value)); } },
  history: { state: null, replaceState: () => {} },
  addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => {}, setTimeout: () => 0,
});

test("rendered clients: a member's list has no allowance column; an admin's shows the bars as sent; empty says so", () => {
  const { AgentsConnectedClients } = load("chat/agents/AgentsConnectedClients.tsx", { window: windowStub() });
  let view;
  act(() => { view = TestRenderer.create(createElement(AgentsConnectedClients, { clients: readPresence({ items: [MEMBER_ITEM] }), now: NOW })); });
  const headers = () => view.root.findAllByType("th").map(text);
  assert.deepEqual(headers(), ["User", "Client", "State", "Work item", "Branch", "Model", "Sensitive data", "Last seen"]);
  assert.match(rowText(clientRowsOf(view)[0]), /^Annaoctryx-claude · seatactiveBRD-6Onboarding checklistbrd-6claude-sonnet-5—.+ ago$/);
  act(() => view.update(createElement(AgentsConnectedClients, { clients: readPresence({ items: [ADMIN_ITEM] }), now: NOW })));
  assert.equal(headers().at(-1), "Allowance");
  const bars = byTestId(view, "agents-allowance-bar");
  assert.deepEqual(bars.map((bar) => text(bar.findByProps({ className: "agents-allowance__label" }))), ["5h 12%", "7d 95%"]);
  assert.equal(bars[1].findByProps({ role: "meter" }).props["aria-valuenow"], 95);
  act(() => view.update(createElement(AgentsConnectedClients, { clients: [], now: NOW })));
  assert.match(text(byTestId(view, "agents-clients-empty")[0]), /^No agent client is connected to this Workspace\.Start a session with octryx-claude/);
  act(() => view.unmount());
});

test("sensitive data: badge and routed model from names and counts only; anything else is dropped", () => {
  const { AgentsConnectedClients } = load("chat/agents/AgentsConnectedClients.tsx", { window: windowStub() });
  const sensitive = { categories: ["pii"], detectors: { email: 15, phone: 4, "4000123412341234": 1 },
    since: "2026-10-05T10:42:00Z", policy_id: "pii-masked", route_to: "company-model" };
  const client = readClient({ ...MEMBER_ITEM, sensitive });
  assert.deepEqual(json(client.sensitive.detectors), [["email", 15], ["phone", 4]]);
  assert.equal(readClient({ ...MEMBER_ITEM, sensitive: { categories: [], route_to: "" } }).sensitive, null);
  let view;
  act(() => { view = TestRenderer.create(createElement(AgentsConnectedClients, { clients: [client], now: NOW })); });
  const [badge] = byTestId(view, "agents-sensitive")[0].findAllByType("span");
  assert.equal(text(badge), "PII · governed until /clear");
  assert.equal(badge.props.className, "work-badge work-badge--running");
  assert.match(badge.props.title, /^email ×15, phone ×4 since \d{1,2}:\d{2}( [AP]M)? · policy pii-masked$/);
  assert.match(rowText(clientRowsOf(view)[0]), /claude-sonnet-5 → company-model/);
  assert.ok(!JSON.stringify(view.toJSON()).includes("4000123412341234"));
  act(() => view.unmount());
});

// A document with visibility and its `visibilitychange` listeners (C5).
const documentStub = (visibilityState = "visible") => {
  const listeners = new Set();
  return {
    visibilityState, listeners,
    addEventListener: (type, listener) => { if (type === "visibilitychange") listeners.add(listener); },
    removeEventListener: (type, listener) => { if (type === "visibilitychange") listeners.delete(listener); },
    show(state) { this.visibilityState = state; for (const listener of listeners) listener(); },
  };
};

function server(answer) {
  const calls = [];
  const fetch = async (url) => {
    calls.push(String(url));
    const { status, body } = answer(String(url));
    return { ok: status < 400, status, statusText: "", json: async () => body };
  };
  return { fetch, calls };
}
const tick = (ms = 0) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

test("rendered area: loads the Workspace's clients, polls while visible, pauses while hidden", async () => {
  const srv = server(() => ({ status: 200, body: { items: [MEMBER_ITEM] } }));
  const document = documentStub();
  const { AgentsAreaWorkspace } = load("chat/agents/AgentsAreaWorkspace.tsx", { fetch: srv.fetch, window: windowStub(), document });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsAreaWorkspace, {
    projects: [{ id: "ws-1", name: "BRD team" }], fallbackWorkspaceId: "ws-1", pollMs: 25 })); });
  try {
  await tick();
  assert.ok(srv.calls[0].endsWith("/api/v1/agent-gateway/presence?project_id=ws-1"), srv.calls[0]);
  assert.equal(clientRowsOf(view).length, 1);
  // Wait for two more polls rather than a fixed time: on a loaded machine 70 ms of timers can take far longer.
  for (let waited = 0; srv.calls.length < 3 && waited < 5000; waited += 25) await tick(25);
  assert.ok(srv.calls.length >= 3, `polled (${srv.calls.length})`);
  document.visibilityState = "hidden";
  const before = srv.calls.length;
  await tick(70);
  assert.equal(srv.calls.length, before, "no polling while the page is hidden");
  // The board and the claims left the menu; their deep links still open them (test below).
  assert.equal(byTestId(view, "agents-placeholder").length, 0, "no placeholder is left");
  } finally { act(() => view.unmount()); }
});

test("rendered area: a refusal is explained, never shown as an empty list", async () => {
  const srv = server(() => ({ status: 403, body: { detail: "Forbidden" } }));
  const { AgentsAreaWorkspace } = load("chat/agents/AgentsAreaWorkspace.tsx", { fetch: srv.fetch, window: windowStub(), document: documentStub() });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsAreaWorkspace, {
    projects: [{ id: "ws-1", name: "BRD team" }], fallbackWorkspaceId: "ws-1", pollMs: 10_000 })); });
  await tick();
  assert.equal(text(byTestId(view, "agents-clients-error")[0]), "Only members of this Workspace can see its agents.");
  assert.equal(byTestId(view, "agents-clients-empty").length, 0);
  act(() => view.unmount());
});

test("rendered area (C5): back on the tab the list refreshes at once; hiding it does not load; unmount unsubscribes", async () => {
  const srv = server(() => ({ status: 200, body: { items: [MEMBER_ITEM] } }));
  const document = documentStub();
  const { AgentsAreaWorkspace } = load("chat/agents/AgentsAreaWorkspace.tsx", { fetch: srv.fetch, window: windowStub(), document });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsAreaWorkspace, {
    projects: [{ id: "ws-1", name: "BRD team" }], fallbackWorkspaceId: "ws-1", pollMs: 10_000 })); });
  try {
    await tick();
    assert.equal(srv.calls.length, 1);
    await act(async () => { document.show("hidden"); });
    await tick();
    assert.equal(srv.calls.length, 1, "hiding the tab loads nothing");
    await act(async () => { document.show("visible"); });
    await tick();
    assert.equal(srv.calls.length, 2, "refreshed without waiting for the 10 s poll");
    assert.ok(srv.calls[1].endsWith("/api/v1/agent-gateway/presence?project_id=ws-1"));
  } finally { act(() => view.unmount()); }
  assert.equal(document.listeners.size, 0, "the listener is removed with the page");
});

// ---- second-level menu --------------------------------------------------------------------------

const navState = (view) => {
  const nav = view.root.find((node) => node.type === "nav" && node.props["aria-label"] === "Agents navigation");
  return {
    sections: nav.findAll((node) => node.props.className === "work-area__nav-section").map(text),
    entries: nav.findAll((node) => node.type === "button").map((node) => text(node)),
    active: nav.findAll((node) => node.type === "button" && /\bis-active\b/.test(node.props.className)).map((node) => text(node)),
    current: nav.findAll((node) => node.type === "button" && node.props["aria-current"] === "page").map((node) => text(node)),
  };
};
const header = (view) => ({
  eyebrow: text(byTestId(view, "agents-eyebrow")[0]),
  title: text(view.root.find((node) => node.type === "h1")),
});

test("Agents menu: the Work/Coding second-level menu, grouped, one active entry, the header follows it; no tab buttons", async () => {
  const srv = server((url) => (url.includes("/agent-board/") ? { status: 200, body: { items: [], next_cursor: null } } : { status: 200, body: { items: [] } }));
  const { AgentsAreaWorkspace } = load("chat/agents/AgentsAreaWorkspace.tsx", { fetch: srv.fetch, window: windowStub(), document: documentStub() });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsAreaWorkspace, {
    projects: [{ id: "ws-1", name: "BRD team" }], fallbackWorkspaceId: "ws-1", pollMs: 10_000, boardPollMs: 10_000,
    isPlatformAdmin: true })); });
  try {
    await tick();
    assert.equal(view.root.findAll((node) => node.props.role === "tab" || node.props.role === "tablist").length, 0, "no tabs");
    assert.equal(view.root.findAll((node) => node.type === "main")[0].props.className.split(" ").includes("work-area"), true);
    // One Agents area; E6 took the board, claims and the Workspace rules pages out of the menu (they
    // still open by link, see below). The builder pages open in the admin shell.
    assert.deepEqual(navState(view), {
      sections: ["Clients", "Build", "Governance", "Reference"],
      entries: ["Connected clients", "Install octryx-claude", "Agents", "Workflows", "Skills", "Seats & data classification", "Policy", "Tools"],
      active: ["Connected clients"], current: ["Connected clients"],
    });
    assert.deepEqual(header(view), { eyebrow: "Agents · Clients", title: "Connected clients" });
    assert.equal(view.root.findAll((node) => node.props.className === "page-header__actions")[0]
      .findAll((node) => node.type === "select").length, 0, "no page Workspace selector: the one global switch");
    const subtitles = [];
    for (const [key, label, section] of [
      ["install", "Install octryx-claude", "Clients"],
      ["clients", "Connected clients", "Clients"],
      ["classification", "Seats & data classification", "Governance"],
      ["policy", "Policy", "Governance"],
    ]) {
      await act(async () => { byTestId(view, `agents-nav-${key}`)[0].props.onClick(); });
      await tick();
      const state = navState(view);
      assert.deepEqual([state.active, state.current], [[label], [label]], key);
      assert.deepEqual(header(view), { eyebrow: `Agents · ${section}`, title: label });
      subtitles.push(text(byTestId(view, "agents-page-subtitle")[0]));
    }
    // Each page has its own one-line subtitle (not one sentence repeated on every page).
    assert.equal(new Set(subtitles).size, 4, subtitles.join(" | "));
    assert.equal(byTestId(view, "agents-nav-board").length + byTestId(view, "agents-nav-claims").length, 0, "out of the menu");
  } finally { act(() => view.unmount()); }
});

test("Agents menu: the collapse button folds the menu, says so, and is remembered", async () => {
  const storage = new Map();
  const srv = server(() => ({ status: 200, body: { items: [] } }));
  const { AgentsAreaWorkspace } = load("chat/agents/AgentsAreaWorkspace.tsx", { fetch: srv.fetch, window: windowStub(storage), document: documentStub() });
  const render = async () => {
    let view;
    await act(async () => { view = TestRenderer.create(createElement(AgentsAreaWorkspace, {
      projects: [{ id: "ws-1", name: "BRD team" }], fallbackWorkspaceId: "ws-1", pollMs: 10_000 })); });
    return view;
  };
  const main = (view) => view.root.find((node) => node.type === "main");
  const collapse = (view) => view.root.find((node) => node.type === "button" && node.props.className === "work-area__collapse");
  let view = await render();
  try {
    assert.equal(main(view).props.className.includes("work-area--sidebar-collapsed"), false);
    assert.equal(collapse(view).props["aria-label"], "Collapse Agents navigation");
    await act(async () => { collapse(view).props.onClick(); });
    assert.equal(main(view).props.className.includes("work-area--sidebar-collapsed"), true);
    assert.equal(collapse(view).props["aria-label"], "Expand Agents navigation");
    assert.equal(storage.get("octryx.agents.sidebarCollapsed"), "true");
  } finally { act(() => view.unmount()); }
  view = await render();
  try {
    assert.equal(main(view).props.className.includes("work-area--sidebar-collapsed"), true, "remembered");
  } finally { act(() => view.unmount()); }
});

test("Agents: bell and notification deep links still open the board and the claims, outside the menu (E6)", async () => {
  for (const [query, label] of [
    ["?area=agents&workspace_id=ws-1&board_message_id=m2", "Message board"],
    ["?area=agents&workspace_id=ws-1&claim_id=c1", "Claims and handoffs"],
  ]) {
    const srv = server(() => ({ status: 200, body: { items: [], next_cursor: null, root: null } }));
    const win = windowStub();
    win.location.search = query;
    const { AgentsAreaWorkspace } = load("chat/agents/AgentsAreaWorkspace.tsx", { fetch: srv.fetch, window: win, document: documentStub() });
    let view;
    await act(async () => { view = TestRenderer.create(createElement(AgentsAreaWorkspace, {
      projects: [{ id: "ws-1", name: "BRD team" }], fallbackWorkspaceId: "ws-1", pollMs: 10_000, boardPollMs: 10_000 })); });
    try {
      await tick();
      assert.deepEqual(navState(view).active, [], query);
      assert.deepEqual(header(view), { eyebrow: "Agents", title: label });
    } finally { act(() => view.unmount()); }
  }
});

test("Connected clients: one row per person and device, active now by default; All adds the stopped ones", async () => {
  const { AgentsConnectedClients } = load("chat/agents/AgentsConnectedClients.tsx");
  const person = (id, name, state) => readClient({ ...MEMBER_ITEM, id: `pe-${id}`, session_key_hash: `s-${id}`,
    user: { id, display_name: name }, state });
  const clients = [
    person("u-a", "Anna", "active"), person("u-b", "Ben", "idle"), person("u-c", "Cleo", "stopped"), person("u-d", "Dan", "stopped"),
  ];
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsConnectedClients, { clients })); });
  assert.equal(clientRowsOf(view).length, 2);
  assert.equal(text(tabOf(view, "active")), "Active now2");
  assert.equal(text(tabOf(view, "all")), "All4");
  await act(async () => { tabOf(view, "all").props.onClick(); });
  assert.equal(clientRowsOf(view).length, 4);
  await act(async () => { tabOf(view, "active").props.onClick(); });
  assert.equal(clientRowsOf(view).length, 2);

  const onlyStopped = [readClient({ ...MEMBER_ITEM, state: "stopped" })];
  await act(async () => { view = TestRenderer.create(createElement(AgentsConnectedClients, { clients: onlyStopped })); });
  assert.equal(clientRowsOf(view).length, 0);
  assert.equal(byTestId(view, "agents-clients-none-active").length, 1);
  await act(async () => { tabOf(view, "all").props.onClick(); });
  assert.equal(clientRowsOf(view).length, 1);
});

test("Connected clients: a person's device is removed from the ⋯ menu after a confirmation naming both", async () => {
  const document = { addEventListener: () => {}, removeEventListener: () => {}, activeElement: null };
  const { AgentsConnectedClients } = load("chat/agents/AgentsConnectedClients.tsx",
    { window: { ...windowStub(), innerWidth: 1200 }, document });
  const entry = readClient({ ...MEMBER_ITEM, id: "pe-1", sessions: 3, device: { name: "MacBook" } });
  assert.equal(entry.id, "pe-1");
  assert.equal(entry.sessions, 3);
  const removed = [];
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsConnectedClients, {
    clients: [entry], onRemove: async (client) => { removed.push(client.id); } })); });
  assert.match(rowText(clientRowsOf(view)[0]), /MacBook · octryx-claude · seat/);
  const menu = view.root.find((node) => node.type === "button" && String(node.props["aria-label"] || "").includes("Anna on MacBook"));
  await act(async () => { menu.props.onClick({ currentTarget: { getBoundingClientRect: () => ({ bottom: 0, right: 0 }) } }); });
  const remove = view.root.find((node) => node.type === "button" && text(node) === "Remove…");
  await act(async () => { remove.props.onClick(); });
  assert.ok(text(view.root).includes("Remove Anna on MacBook?"));
  const confirm = view.root.find((node) => node.type === "button" && text(node) === "Remove Anna on MacBook");
  await act(async () => { confirm.props.onClick(); });
  assert.deepEqual(removed, ["pe-1"]);
  // An entry without an id is not listed.
  assert.equal(readClient({ ...MEMBER_ITEM, id: "" }), null);
});

test("Agents menu of a member: only the pages a member opens, no builder", async () => {
  const srv = server(() => ({ status: 200, body: { items: [] } }));
  const { AgentsAreaWorkspace } = load("chat/agents/AgentsAreaWorkspace.tsx", { fetch: srv.fetch, window: windowStub(), document: documentStub() });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AgentsAreaWorkspace, {
    projects: [{ id: "ws-1", name: "BRD team" }], fallbackWorkspaceId: "ws-1", pollMs: 10_000, boardPollMs: 10_000 })); });
  try {
    await tick();
    assert.deepEqual(navState(view).entries, ["Connected clients", "Install octryx-claude", "Seats & data classification", "Policy"]);
  } finally {
    await act(async () => { view.unmount(); });
  }
});
