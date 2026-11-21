// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/startupRequests.test.mjs
//
// Perf audit login: HTML → bundle → bootstrap → a second wave of 7 calls that all waited for the
// bootstrap. Two of them need nothing from it: the attention list and the admin's setup status (its Workspace is
// the stored choice). They now start with the bundle, in parallel with the bootstrap, and the first reader takes
// the answer instead of asking again.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");

function loader(extra) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true, target: ts.ScriptTarget.ES2020 },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl,
      JSON, encodeURIComponent, setInterval, clearInterval, setTimeout, clearTimeout, CustomEvent, Set, Map, String,
      Array, Boolean, RegExp, Symbol, FormData,
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
  return (relative) => loadFile(path.join(SRC, relative));
}

const ATTENTION = { items: [], running: [], count: 0, cursor: null, quiet: { active: false, until: null } };
const SETUP = { steps: [{ key: "provider", status: "done" }], workspace: { id: "w1", name: "Acme Orders" } };

function harness({ pathname = "/chat", stored = {} } = {}) {
  const calls = [];
  const values = new Map(Object.entries(stored));
  const localStorage = {
    getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key),
  };
  const window = {
    location: { pathname, search: "", href: `http://localhost${pathname}`, origin: "http://localhost" },
    localStorage, addEventListener() {}, removeEventListener() {},
  };
  const fetch = async (url) => {
    calls.push(String(url).replace("http://localhost", ""));
    const body = String(url).startsWith("/api/v1/attention") ? ATTENTION : SETUP;
    return { ok: true, status: 200, statusText: "OK", headers: { get: () => "application/json" }, json: async () => body,
      text: async () => JSON.stringify(body) };
  };
  const load = loader({ fetch, window, localStorage });
  return { calls, values, load };
}

test("the attention list and an admin's setup status start with the bundle; the first readers take them", async () => {
  const { calls, load } = harness({ stored: { "octryx-setup-progress-viewer": "u1", "octryx-active-workspace:u1": "w1" } });
  load("chat/startupRequests.ts").startStartupRequests();
  assert.deepEqual(calls, ["/api/v1/attention", "/api/v1/admin/setup/onboarding?workspace_id=w1"],
    "both requested before any bootstrap answer");
  const { loadAttention } = load("chat/companion/companionApi.ts");
  const { loadSetupStatus } = load("chat/setup/setupGuideApi.ts");
  const attention = await loadAttention();
  const setup = await loadSetupStatus("w1");
  assert.equal(attention.count, 0);
  assert.equal(setup.workspace?.id ?? "w1", "w1");
  assert.equal(calls.length, 2, "the shell's first reads asked nothing again");
  await loadAttention();
  assert.equal(calls.length, 3, "the next poll reads anew");
});

test("without a remembered admin only the attention list starts early; outside the chat app nothing does", async () => {
  const plain = harness();
  plain.load("chat/startupRequests.ts").startStartupRequests();
  assert.deepEqual(plain.calls, ["/api/v1/attention"]);
  const elsewhere = harness({ pathname: "/admin/tools" });
  elsewhere.load("chat/startupRequests.ts").startStartupRequests();
  assert.deepEqual(elsewhere.calls, []);
});

test("an early answer for another Workspace is not used, and an old one is read again", async () => {
  const { calls, load } = harness({ stored: { "octryx-setup-progress-viewer": "u1", "octryx-active-workspace:u1": "w1" } });
  load("chat/startupRequests.ts").startStartupRequests();
  await load("chat/setup/setupGuideApi.ts").loadSetupStatus("w2");
  assert.deepEqual(calls.slice(2), ["/api/v1/admin/setup/onboarding?workspace_id=w2"]);
  const { prefetch, takePrefetched } = load("chat/startupPrefetch.ts");
  const realNow = Date.now;
  prefetch("/x", async () => 1);
  try {
    Date.now = () => realNow() + 60_000;
    assert.equal(takePrefetched("/x"), null);
  } finally {
    Date.now = realNow;
  }
});

test("the setup progress remembers an admin viewer for the next start and forgets a non-admin", async () => {
  const { values, load } = harness();
  const { useSetupProgress } = load("chat/setup/useSetupProgress.ts");
  function Probe({ admin }) { useSetupProgress(admin, "u1", null); return null; }
  let view;
  await act(async () => { view = TestRenderer.create(createElement(Probe, { admin: true })); });
  assert.equal(values.get("octryx-setup-progress-viewer"), "u1");
  await act(async () => { view.update(createElement(Probe, { admin: false })); });
  assert.equal(values.has("octryx-setup-progress-viewer"), false);
  act(() => view.unmount());
});

test("the setup progress counts the Workspace the page shows and reads again when it changes", async () => {
  const { calls, load } = harness();
  const { useSetupProgress } = load("chat/setup/useSetupProgress.ts");
  function Probe({ workspace }) { useSetupProgress(true, "u1", workspace); return null; }
  let view;
  await act(async () => { view = TestRenderer.create(createElement(Probe, { workspace: "w1" })); });
  await act(async () => { view.update(createElement(Probe, { workspace: "w2" })); });
  const reads = calls.filter((call) => String(call).includes("/admin/setup/onboarding"));
  assert.deepEqual(reads.slice(-2), ["/api/v1/admin/setup/onboarding?workspace_id=w1",
    "/api/v1/admin/setup/onboarding?workspace_id=w2"]);
  act(() => view.unmount());
});
