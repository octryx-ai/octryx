// Revoking a device sits in the row's ⋯ menu and is confirmed in the app. The
// dialog names the device, the reason field is labelled with a placeholder, the button says why it waits, and a
// message confirms the revoke afterwards. Real ActionMenu, ConfirmDialog and useConfirmAction; the API is a stub.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");
const text = (node) => (typeof node === "string" ? node : node.children.map(text).join(""));

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

const DEVICES = { items: [{ id: "dev_a", name: "Mac (Alex)", os: "macos", status: "active", owner_name: "Alex", connected: false, last_seen_at: null }] };

async function mount(revoke) {
  const calls = [];
  let listed = DEVICES;
  const api = {
    loadAdminDevices: async () => listed,
    adminRevokeDevice: async (id, reason) => {
      calls.push([id, reason]);
      await revoke();
      listed = { items: [{ ...DEVICES.items[0], status: "revoked" }] };
    },
    loadLoginValidity: async () => ({ validity: "90d" }),
    saveLoginValidity: async () => ({ validity: "90d" }),
  };
  const window = { innerWidth: 1400, addEventListener() {}, removeEventListener() {} };
  const document = { addEventListener() {}, removeEventListener() {} };
  const loadModule = makeLoader({ "/devicesApi": api }, { window, document, console, Error });
  const { AdminDevicesList } = loadModule("chat/devices/AdminDevicesList.tsx");
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AdminDevicesList), { createNodeMock: () => ({ focus() {} }) }); });
  return { view, calls };
}

const button = (view, label) => view.root.findAll((node) => node.type === "button" && text(node) === label)[0];
const openRevoke = (view) => {
  const more = view.root.findAll((node) => node.type === "button" && node.props["aria-label"] === "More actions for Mac (Alex)")[0];
  act(() => more.props.onClick({ currentTarget: { getBoundingClientRect: () => ({ bottom: 10, right: 100 }) } }));
  act(() => button(view, "Revoke…").props.onClick());
};

test("Revoke is in the ⋯ menu; the dialog names the device and labels its reason field", async () => {
  const { view, calls } = await mount(async () => {});
  assert.equal(button(view, "Revoke"), undefined, "no revoke button in the row");
  openRevoke(view);
  const dialog = view.root.find((node) => node.props.role === "alertdialog");
  assert.match(text(dialog), /^Revoke device Mac \(Alex\)\?/);
  const field = dialog.find((node) => node.type === "textarea");
  assert.equal(field.props.placeholder, "e.g. Laptop replaced");
  assert.match(text(dialog), /Reason for revoking \(required\)/);
  assert.match(text(dialog), /Enter reason for revoking to continue\./, "says why the button waits");
  assert.equal(button(view, "Revoke Mac (Alex)").props.disabled, true);
  act(() => field.props.onChange({ target: { value: "Laptop replaced" } }));
  assert.equal(button(view, "Revoke Mac (Alex)").props.disabled, false);
  await act(async () => { button(view, "Revoke Mac (Alex)").props.onClick(); });
  assert.deepEqual(calls, [["dev_a", "Laptop replaced"]]);
  assert.equal(view.root.findAll((node) => node.props.role === "alertdialog").length, 0);
  assert.match(text(view.root.find((node) => node.props["data-testid"] === "action-done")), /^Device Mac \(Alex\) revoked\./);
  act(() => view.unmount());
});

test("a refused revoke stays in the dialog with its reason", async () => {
  const { view } = await mount(async () => { throw new Error("no"); });
  openRevoke(view);
  const dialog = () => view.root.find((node) => node.props.role === "alertdialog");
  act(() => dialog().find((node) => node.type === "textarea").props.onChange({ target: { value: "Lost" } }));
  await act(async () => { button(view, "Revoke Mac (Alex)").props.onClick(); });
  assert.match(text(dialog()), /The device could not be revoked\./);
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "action-done").length, 0);
  act(() => view.unmount());
});
