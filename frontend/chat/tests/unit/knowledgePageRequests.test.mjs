// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgePageRequests.test.mjs
//
// Perf audit: Knowledge → Search fired 13 calls where 6 suffice (every call twice ~1 ms apart, bindings
// 4×). Two causes: the admin shell showed "Loading…" for a moment on every tab entry, even for a panel that loads its
// own data, which unmounted the panel that had just mounted and mounted it again; and the page and its status line
// each read the bindings. This test renders the real AdminPanelContent driven by the real tab loader (as
// useAdminPanelContainerEffects does) with a counting fetch. Set KNOWLEDGE_REQUESTS_SRC to another src/ to compare.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement, useEffect, useRef, useState } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = process.env.KNOWLEDGE_REQUESTS_SRC
  || path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");

function loader(extra) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, TypeError, Number, Object, Math,
      Promise, Intl, JSON, encodeURIComponent, decodeURIComponent, setInterval, clearInterval, setTimeout,
      clearTimeout, CustomEvent, Event, Set, Map, WeakMap, String, Array, Boolean, RegExp, Symbol, FormData,
      AbortController, queueMicrotask, structuredClone, Reflect,
      ...extra,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          for (const ext of [".tsx", ".ts", "/index.ts", "/index.tsx"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return (relative) => loadFile(path.join(SRC, relative));
}

const storage = () => {
  const values = new Map();
  return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key) };
};

function windowStub() {
  const listeners = new Map();
  return {
    location: { origin: "http://localhost", protocol: "http:", host: "localhost", pathname: "/chat",
      search: "?area=knowledge", href: "http://localhost/chat?area=knowledge" },
    history: { state: null, replaceState() {}, pushState() {} },
    localStorage: storage(), sessionStorage: storage(),
    matchMedia: () => ({ matches: false, addEventListener() {}, removeEventListener() {} }),
    addEventListener: (type, fn) => listeners.set(type, [...(listeners.get(type) ?? []), fn]),
    removeEventListener: (type, fn) => listeners.set(type, (listeners.get(type) ?? []).filter((item) => item !== fn)),
    dispatchEvent: (event) => { for (const fn of listeners.get(event.type) ?? []) fn(event); return true; },
    setTimeout, clearTimeout, setInterval, clearInterval,
    requestAnimationFrame: (fn) => setTimeout(fn, 0), cancelAnimationFrame: clearTimeout,
  };
}

const BODIES = [
  [/\/knowledge\/bindings$/, { may_author: true, bindings: [], source_options: [] }],
  [/\/knowledge\/sources$/, { sources: [], next_cursor: null, total: 0 }],
  [/\/knowledge\/connectors$/, { connectors: [] }],
  [/\/web-search\/sources$/, { mode: "open", sources: [] }],
  [/\/knowledge\/settings$/, {}],
];

function countingFetch() {
  const calls = [];
  const fetch = async (url) => {
    const target = String(url);
    calls.push(target);
    const body = BODIES.find(([pattern]) => pattern.test(target.replace(/\?.*$/, "")))?.[1];
    return { ok: Boolean(body), status: body ? 200 : 404, statusText: body ? "OK" : "Not Found",
      headers: { get: () => "application/json" }, json: async () => body ?? { detail: "Not Found" } };
  };
  return { calls, fetch };
}

const settle = async () => {
  for (let round = 0; round < 8; round += 1) await act(() => new Promise((resolve) => setTimeout(resolve, 0)));
};

const tally = (calls) => {
  const counts = {};
  for (const url of calls) {
    const key = url.replace(/^\/api\/v1\/workspaces\/[^/]+/, "").replace(/\?.*$/, "");
    counts[key] = (counts[key] ?? 0) + 1;
  }
  return counts;
};

async function renderTab(tab) {
  const { calls, fetch } = countingFetch();
  const window = windowStub();
  const load = loader({ fetch, window, document: { title: "", addEventListener() {}, removeEventListener() {} },
    localStorage: window.localStorage, sessionStorage: window.sessionStorage, location: window.location,
    history: window.history });
  const { AdminPanelContent } = load("admin/components/AdminPanelContent.tsx");
  const { runTabLoad } = load("admin/hooks/useAdminTabLoader.ts");
  const projects = [{ id: "w1", name: "Acme Orders", is_active: true }];
  const readJson = async (url) => { throw new Error(`unexpected shell read ${url}`); };
  let loadingRenders = 0;
  // The container's tab entry (useAdminPanelContainerEffects): one tab load per tab, then the content.
  function Shell() {
    const [loadingTab, setLoadingTab] = useState(false);
    const [tabError, setTabError] = useState(null);
    const counter = useRef(0);
    useEffect(() => { void runTabLoad(counter, tab, { readJson, setLoadingTab, setTabError }); }, []);
    if (loadingTab) loadingRenders += 1;
    return createElement(AdminPanelContent, { loadingTab, tabError, tab, projects, readJson, isAdmin: true });
  }
  // The page's code is already loaded, as on every visit after the first (React.lazy resolved): render once to
  // load it, then measure a fresh visit.
  for (const measured of [false, true]) {
    calls.length = 0;
    loadingRenders = 0;
    let view;
    await act(async () => { view = TestRenderer.create(createElement(Shell)); });
    await settle();
    view.unmount();
    if (measured) break;
  }
  return { calls, counts: tally(calls), loadingRenders };
}

test("Knowledge → Search reads each fact once: 5 workspace calls, bindings shared by the page and its status line", async () => {
  const { calls, counts, loadingRenders } = await renderTab("knowledgeLibrary");
  assert.deepEqual(counts, {
    "/knowledge/bindings": 1, "/knowledge/sources": 1, "/knowledge/connectors": 1, "/web-search/sources": 1,
    "/knowledge/settings": 1,
  }, `calls: ${calls.join(", ")}`);
  assert.equal(loadingRenders, 0, "the shell never replaces a self-loading panel with Loading…");
});

test("Knowledge → Documents reads the bindings and the first source page once each", async () => {
  const { calls, counts } = await renderTab("knowledgeSources");
  assert.deepEqual(counts, { "/knowledge/bindings": 1, "/knowledge/sources": 1 }, `calls: ${calls.join(", ")}`);
});

test("a tab whose data the shell loads still shows Loading… until that data is there", async () => {
  const { runTabLoad } = await import("../../src/admin/hooks/useAdminTabLoader.ts");
  const loading = [];
  let resolve;
  const users = runTabLoad({ current: 0 }, "users", {
    readJson: () => new Promise((ok) => { resolve = ok; }), setLoadingTab: (value) => loading.push(value),
    setTabError() {}, setUsers() {},
  });
  assert.deepEqual(loading, [true]);
  resolve([]);
  await users;
  assert.deepEqual(loading, [true, false]);
  const knowledge = [];
  await runTabLoad({ current: 0 }, "knowledgeLibrary", { setLoadingTab: (value) => knowledge.push(value), setTabError() {} });
  assert.deepEqual(knowledge, [false], "a self-loading panel only ends an earlier tab's loading");
});

test("two simultaneous bindings reads of one workspace share one request; a later visit reads again", async () => {
  const { calls, fetch } = countingFetch();
  const load = loader({ fetch });
  const { sharedBindingsRead } = load("chat/knowledge/useKnowledgePermissions.ts");
  const [first, second] = await Promise.all([sharedBindingsRead("w1"), sharedBindingsRead("w1")]);
  assert.equal(first, second);
  assert.equal(calls.length, 1);
  await sharedBindingsRead("w1");
  assert.equal(calls.length, 2, "no stale permission after the read finished");
  await Promise.all([sharedBindingsRead("w1"), sharedBindingsRead("w2")]);
  assert.equal(calls.length, 4, "other workspaces read their own");
});
