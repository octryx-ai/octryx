// Render harness for the admin render guards: transpiles a component with its relative imports into a VM (modules
// named in `stubs` are replaced by suffix), renders it with react-test-renderer and digests the rendered tree.
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url), ts = require("typescript");
export const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");

export const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));
export const byId = (root, id) => root.findAll((node) => node.props["data-testid"] === id && typeof node.type === "string");
export const labels = (root, className) => root.findAll((node) => node.props.className === className && typeof node.type === "string").map(text);
export const noop = () => {};
export const tick = (ms = 0) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });

/**
 * A digest of the whole rendered tree: element types, props (functions left out) and text. React's useId values count
 * up across every render of the process, so they are numbered in order of appearance instead.
 */
export function digest(view) {
  const ids = new Map();
  const json = JSON.stringify(view.toJSON()).replace(/:[rR][0-9a-zA-Z]*:/g, (id) => {
    if (!ids.has(id)) ids.set(id, `:id${ids.size}:`);
    return ids.get(id);
  });
  return crypto.createHash("sha256").update(json).digest("hex");
}

/** A fetch stub: `answer(call)` returns `{status, body}`; every call is recorded with its parsed body. */
export function server(answer) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const call = { url: String(url), method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null };
    calls.push(call);
    const { status, body } = answer(call);
    return { ok: status < 400, status, statusText: "", headers: { get: () => null }, json: async () => body, text: async () => JSON.stringify(body) };
  };
  return { fetch, calls };
}

const storage = () => ({ getItem: () => null, setItem: () => {}, removeItem: () => {} });
const windowStub = () => ({
  innerWidth: 1400, location: { search: "", pathname: "/chat", origin: "http://localhost", href: "http://localhost/chat", hash: "" },
  localStorage: storage(), sessionStorage: storage(), history: { state: null, replaceState() {}, pushState() {} },
  addEventListener() {}, removeEventListener() {}, dispatchEvent() {}, open() {}, confirm: () => true,
  setTimeout, clearTimeout, matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
  requestAnimationFrame: () => 0, cancelAnimationFrame() {},
});
const documentStub = () => ({
  addEventListener() {}, removeEventListener() {}, activeElement: null, getElementById: () => null, querySelector: () => null,
  body: {}, documentElement: { dataset: {} }, visibilityState: "visible",
});

function makeLoader(stubs, globals) {
  const cache = new Map();
  const sandbox = {
    JSON, Date, Math, Number, Object, Array, String, Boolean, Error, Promise, Set, Map, console, URL, RegExp, Intl,
    URLSearchParams, encodeURIComponent, decodeURIComponent, setTimeout, clearTimeout, setInterval, clearInterval,
    structuredClone, FormData, Blob, TextEncoder, crypto: globalThis.crypto,
    window: windowStub(), document: documentStub(), fetch: async () => { throw new Error("no fetch stub"); }, ...globals,
  };
  const load = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const module = { exports: {} };
    cache.set(file, module);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    vm.runInNewContext(output, { module, exports: module.exports, ...sandbox, require: (name) => resolve(name, path.dirname(file)) });
    return module.exports;
  };
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name === suffix || name.endsWith(suffix));
    if (stub) return stub[1];
    if (!name.startsWith(".")) return require(name);
    if (name.endsWith(".json")) return JSON.parse(fs.readFileSync(path.resolve(dir, name), "utf8"));
    const base = path.resolve(dir, name);
    const file = [".tsx", ".ts", "/index.ts", "/index.tsx"].map((ext) => base + ext).find((candidate) => fs.existsSync(candidate));
    return load(file);
  };
  return (relative) => load(path.join(SRC, relative));
}

/** Loads `relative` and returns its exports, with `stubs` and extra sandbox `globals`. */
export const loadModule = (relative, { stubs = {}, globals = {} } = {}) => makeLoader(stubs, globals)(relative);

const nodeMock = () => ({
  focus() {}, blur() {}, scrollIntoView() {}, contains: () => false, querySelector: () => null, querySelectorAll: () => [],
  addEventListener() {}, removeEventListener() {}, getBoundingClientRect: () => ({ width: 800, height: 600, top: 0, left: 0 }),
});

/** Renders `exportName` of `relative` with `props`, settles its effects and returns the test renderer. */
export async function mount(relative, exportName, props, options = {}) {
  const Component = loadModule(relative, options)[exportName];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(Component, props), { createNodeMock: nodeMock });
  });
  await tick();
  return view;
}
