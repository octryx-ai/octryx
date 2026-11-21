// E6 Admin › Platform: Version and Devices are built only on existing endpoints (GET /api/v1/health,
// GET /octryx-claude/version, GET /api/v1/admin/devices); Storage and Logs have no endpoint of their own, so they
// are no entries. Devices moved out of Agents › Connected clients, which links there for platform admins.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import { ADMIN_AREA_CONFIGS, resolveAdminAreaTab } from "../../src/admin/config/adminPanelAreas.ts";
import { ADMIN_PAGE_PURPOSE } from "../../src/admin/config/pagePurpose.ts";
import {
  clientDetails,
  forwardedTrustLabel,
  attentionText,
  readClientVersion,
  readPlatformVersion,
  securityLabel,
  serverStateLabel,
} from "../../src/admin/components/platform/platformVersionModel.ts";
import { adminDeviceState, readAdminDevices } from "../../src/chat/devices/adminDevicesModel.ts";
import { ADMIN_ENTRIES } from "../../src/admin/config/adminEntries.ts";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));

function makeLoader(stubs, sandbox) {
  const cache = new Map();
  const load = (file) => {
    if (cache.has(file)) return cache.get(file);
    const exports = {};
    cache.set(file, exports);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    vm.runInNewContext(output, { exports, ...sandbox, require: (name) => resolve(name, path.dirname(file)) });
    return exports;
  };
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name.endsWith(suffix));
    if (stub) return stub[1];
    if (!name.startsWith(".")) return require(name);
    const base = path.resolve(dir, name);
    const file = [".tsx", ".ts"].map((ext) => base + ext).find((candidate) => fs.existsSync(candidate));
    return load(file);
  };
  return (relative) => load(path.join(SRC, relative));
}

const sandbox = () => ({
  window: { innerWidth: 1400, addEventListener() {}, removeEventListener() {} },
  document: { addEventListener() {}, removeEventListener() {}, activeElement: null },
  console, Error, Promise, Set, Map,
});

const HEALTH = {
  status: "degraded", version: "2.4.0",
  summary: { status: "degraded", error_components: [], degraded_components: ["retention_worker"], unknown_components: ["analytics_worker"] },
  checks: {},
  configuration: { security_defaults: { status: "secure", runtime_profile: "kubernetes", production_like: true, debug: false,
    force_secure_auth_cookies: true, forwarded_header_trust: "allowlist" } },
};
const CLIENT = { client: "octryx-claude", version: "0.9.3", sha256: "abcdef0123456789ffff", requires_python: ">=3.11" };
const DEVICES = { items: [
  { id: "dev_a", name: "Mac (Alex)", os: "macos", status: "active", owner_name: "alex", connected: true, running_jobs: 1,
    max_parallel_jobs: 2, client_version: "0.9.3", service_kind: "launchd", profiles: ["seat"], folder_count: 2,
    created_at: "2026-11-01T08:00:00+00:00", last_seen_at: "2026-11-06T10:00:00+00:00", revoked_at: null },
  { id: "dev_b", name: "Old laptop", os: "linux", status: "revoked", owner_name: "anna", connected: false,
    last_seen_at: null, revoked_at: "2026-11-05T21:47:35+00:00" },
] };

test("Platform lists Version and Devices first; Storage and Logs are no entries without an endpoint", () => {
  const platform = ADMIN_ENTRIES.find((entry) => entry.label === "Platform");
  const labels = platform.views.map((view) => view.label);
  assert.deepEqual(labels.slice(0, 2), ["Version", "Devices"]);
  assert.ok(!labels.includes("Storage") && !labels.includes("Logs"));
  for (const tab of ["platformVersion", "platformDevices"]) {
    assert.equal(resolveAdminAreaTab("admin", tab), tab);
    assert.ok(ADMIN_PAGE_PURPOSE[tab], `${tab} has one purpose sentence`);
  }
});

test("the version model reads health and client, names what needs attention, colour only for exceptions", () => {
  const version = readPlatformVersion(HEALTH);
  assert.equal(version.server.version, "2.4.0");
  assert.deepEqual(version.server.attention, ["analytics_worker", "retention_worker"]);
  assert.equal(attentionText(version.server.attention), "2 components need attention.");
  assert.equal(attentionText([]), "");
  assert.deepEqual(serverStateLabel("ok"), { label: "Running", tone: "neutral" });
  assert.equal(serverStateLabel("error").tone, "problem");
  assert.deepEqual(securityLabel("secure"), { label: "Secure defaults", tone: "neutral" });
  assert.equal(securityLabel("local_only_defaults").tone, "attention");
  assert.equal(readPlatformVersion({ status: "ok" }).security, null, "an anonymous health body carries no configuration");
  assert.deepEqual(readClientVersion(CLIENT), { version: "0.9.3", requiresPython: ">=3.11", sha256: "abcdef0123456789ffff" });
  assert.equal(readClientVersion({ state: "denied" }), null);
});

test("rendered Version: parts table, the attention line links Operations › Health, security facts", async () => {
  const opened = [];
  const load = makeLoader({
    "/platformApi": { loadPlatformHealth: async () => HEALTH, loadClientVersion: async () => CLIENT },
    "/adminNavigation": { useAdminNavigation: () => ({ openAdminTab: (tab) => opened.push(tab) }) },
  }, sandbox());
  const { PlatformVersionPage } = load("admin/components/platform/PlatformVersionPage.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(PlatformVersionPage)); });
  await act(async () => {});
  const table = view.root.find((node) => node.props["data-testid"] === "platform-version-table");
  assert.match(text(table), /Octryx server2\.4\.0Needs attention/);
  // The requirement and checksum in words, in a column with a header.
  assert.match(text(table), /octryx-claude client0\.9\.3AvailablePython 3\.11 or newer · checksum abcdef012345/);
  assert.ok(table.findAll((node) => node.type === "th").some((node) => text(node) === "Details"));
  const attention = view.root.find((node) => node.props["data-testid"] === "platform-version-attention");
  assert.match(text(attention), /^2 components need attention\./);
  act(() => attention.findByType("button").props.onClick());
  assert.deepEqual(opened, ["observabilityHealth"]);
  const security = view.root.find((node) => node.props["data-testid"] === "platform-version-security");
  assert.match(text(security), /Secure defaults/);
  assert.match(text(security), /kubernetes · production-like/);
  assert.doesNotMatch(text(security), /allowlist|_/, "no raw setting values");
  act(() => view.unmount());
});

test("rendered Version: an unreadable health says so with Try again", async () => {
  const load = makeLoader({
    "/platformApi": { loadPlatformHealth: async () => { throw new Error("401"); }, loadClientVersion: async () => CLIENT },
    "/adminNavigation": { useAdminNavigation: () => ({ openAdminTab() {} }) },
  }, sandbox());
  const { PlatformVersionPage } = load("admin/components/platform/PlatformVersionPage.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(PlatformVersionPage)); });
  await act(async () => {});
  const error = view.root.find((node) => node.props["data-testid"] === "platform-version-error");
  assert.match(text(error), /^The version of this installation could not be read\.Try again$/);
  act(() => view.unmount());
});

test("the devices model reads every field and gives one state word per device", () => {
  const [mac, old] = readAdminDevices(DEVICES);
  assert.equal(mac.clientVersion, "0.9.3");
  assert.equal(mac.folderCount, 2);
  assert.deepEqual(adminDeviceState(mac), { label: "Working", tone: "info" });
  assert.deepEqual(adminDeviceState(old), { label: "Revoked", tone: "neutral" });
  assert.deepEqual(adminDeviceState({ ...mac, connected: false }), { label: "Offline", tone: "neutral" });
  assert.deepEqual(adminDeviceState({ ...mac, paused: true }), { label: "Paused", tone: "attention" });
  assert.deepEqual(readAdminDevices({ items: "x" }), []);
});

test("rendered Devices: a full-width table, a row opens its facts in the side panel, no folders shown", async () => {
  const load = makeLoader({ "/devicesApi": { loadAdminDevices: async () => DEVICES, adminRevokeDevice: async () => {}, loadLoginValidity: async () => ({ validity: "90d" }), saveLoginValidity: async () => ({ validity: "1d" }) } }, sandbox());
  const { AdminDevicesList } = load("chat/devices/AdminDevicesList.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AdminDevicesList), { createNodeMock: () => ({ focus() {} }) }); });
  await act(async () => {});
  const table = view.root.find((node) => node.props["data-testid"] === "admin-devices-table");
  const rows = table.findAll((node) => node.type === "tr");
  assert.equal(rows.length, 3, "header and two devices");
  assert.match(text(rows[1]), /Mac \(Alex\)alexmacOS|Mac \(Alex\)alex/);
  assert.match(text(rows[1]), /Working/);
  assert.match(text(rows[2]), /Revoked/);
  assert.equal(rows[2].findAll((node) => node.props["aria-label"] === "More actions for Old laptop").length, 0, "no revoke for a revoked device");
  await act(async () => { rows[1].props.onClick({ target: rows[1], currentTarget: rows[1] }); });
  const panel = view.root.find((node) => node.props["data-testid"] === "admin-device-panel");
  const facts = panel.find((node) => node.props["data-testid"] === "admin-device-facts");
  assert.match(text(facts), /Owneralex/);
  assert.match(text(facts), /Jobs1 of 2/);
  assert.doesNotMatch(text(panel), /folders?:\s*\//i, "no folder paths (D12)");
  act(() => view.unmount());
});

test("rendered Devices: nothing connected is one line", async () => {
  const load = makeLoader({ "/devicesApi": { loadAdminDevices: async () => ({ items: [] }), adminRevokeDevice: async () => {}, loadLoginValidity: async () => ({ validity: "90d" }), saveLoginValidity: async () => ({ validity: "1d" }) } }, sandbox());
  const { AdminDevicesList } = load("chat/devices/AdminDevicesList.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AdminDevicesList)); });
  await act(async () => {});
  assert.match(text(view.root.find((node) => node.props["data-testid"] === "empty-line")), /^No device is connected yet\./);
  act(() => view.unmount());
});

test("Agents › Connected clients no longer lists every person's devices; it links Admin › Platform › Devices", () => {
  const source = fs.readFileSync(path.join(SRC, "chat/agents/AgentsAreaWorkspace.tsx"), "utf8");
  assert.doesNotMatch(source, /AdminDevicesList/);
  assert.match(source, /adminLink\("platformDevices"\)/);
});

test("setting values and the client checksum read in words", () => {
  assert.equal(forwardedTrustLabel("explicit_allowlist"), "Only from the listed proxies");
  assert.equal(forwardedTrustLabel("disabled"), "Not trusted");
  assert.equal(forwardedTrustLabel("—"), "—");
  assert.equal(clientDetails({ requiresPython: ">=3.11", sha256: "2262fe507ed8ffff" }), "Python 3.11 or newer · checksum 2262fe507ed8");
  assert.equal(clientDetails({ requiresPython: "~=3.12", sha256: "" }), "Python ~=3.12");
  assert.equal(clientDetails({ requiresPython: "—", sha256: "" }), "");
});
