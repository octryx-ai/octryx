// A rejected lazy admin panel keeps the navigation and the other panels alive, shows a plain
// load-failure state with one explicit reload, and genuine render errors still reach the area
// boundary. Real React.lazy, real Suspense, real ChatErrorBoundary; no browser fault injection.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement, Suspense } from "react";
import TestRenderer from "react-test-renderer";
import * as panelLoad from "../../src/admin/components/adminPanelLoad.ts";
import * as staleBuild from "../../src/staleBuild.ts";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const text = (node) => (node === null ? "" : typeof node === "string" ? node : node.children.map(text).join(""));

function load(path, sandbox = {}) {
  const exports = {};
  const source = fs.readFileSync(new URL(`../../src/${path}`, import.meta.url), "utf8");
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
    exports,
    console,
    window: sandbox.window ?? { location: { reload() { throw new Error("reload must not run"); } } },
    require: (name) => (name.endsWith("/adminPanelLoad") ? panelLoad : name.endsWith("/staleBuild") ? staleBuild : require(name)),
  });
  return exports;
}

const { ChatErrorBoundary } = load("chat/ChatErrorBoundary.tsx");
const CHUNK_ERROR = "Failed to fetch dynamically imported module: https://host/assets/AdminRuntimesTab-Bx9.js";

// React logs every caught error; keep the output readable and count instead.
async function quietly(run) {
  const original = console.error;
  const logged = [];
  console.error = (...args) => logged.push(args);
  try {
    return await run(logged);
  } finally {
    console.error = original;
  }
}

const flush = () => act(async () => { for (let i = 0; i < 5; i += 1) await new Promise((resolve) => setTimeout(resolve, 0)); });

function area(Boundary, tab, panels, onReload) {
  return createElement(
    ChatErrorBoundary, { fallbackTitle: "This page could not be displayed" },
    createElement("nav", { "data-testid": "admin-nav" }, "Users · Runtimes · Agents"),
    createElement(Boundary, { key: tab, onReload },
      createElement(Suspense, { fallback: createElement("div", null, "Loading…") }, createElement(panels[tab]))),
  );
}

function panels() {
  const calls = { runtimes: 0, users: 0 };
  return {
    calls,
    map: {
      runtimes: panelLoad.lazyAdminPanel(() => { calls.runtimes += 1; return Promise.reject(new TypeError(CHUNK_ERROR)); }),
      users: panelLoad.lazyAdminPanel(() => { calls.users += 1; return Promise.resolve({ default: () => createElement("section", null, "User accounts") }); }),
    },
  };
}

test("a rejected panel import shows its own failure state and keeps the navigation", async () => {
  const { AdminPanelLoadBoundary } = load("admin/components/AdminPanelLoadBoundary.tsx");
  const reloads = [];
  const { map } = panels();
  await quietly(async () => {
    let view;
    act(() => { view = TestRenderer.create(area(AdminPanelLoadBoundary, "runtimes", map, () => reloads.push(1))); });
    await flush();
    const all = text(view.toJSON() ? view.root : null);
    assert.match(all, /Users · Runtimes · Agents/, "navigation stays mounted");
    assert.match(all, /This page could not finish loading/);
    assert.match(all, /This can happen after an update or a connection problem\. You can choose another page from the navigation or reload\./);
    assert.match(all, /may discard unsaved changes/);
    // The page claims no cause it cannot know and promises nothing about other pages.
    assert.doesNotMatch(all, /did not download|still work/);
    assert.doesNotMatch(all, /This page could not be displayed/, "the area boundary is not triggered");
    assert.doesNotMatch(all, /Failed to fetch|AdminRuntimesTab|https:/, "no raw error text in the page");
    assert.deepEqual(reloads, [], "nothing reloads on its own");
    const reload = view.root.findAllByType("button").find((button) => text(button) === "Reload page");
    act(() => reload.props.onClick());
    assert.deepEqual(reloads, [1], "reload runs only on the explicit action");
    act(() => view.unmount());
  });
});

test("without an override the action reloads the current page (URL, area, tab and workspace kept)", async () => {
  const reloads = [];
  const { AdminPanelLoadBoundary } = load("admin/components/AdminPanelLoadBoundary.tsx", { window: { location: { reload: () => reloads.push("reload") } } });
  const { map } = panels();
  await quietly(async () => {
    let view;
    act(() => { view = TestRenderer.create(area(AdminPanelLoadBoundary, "runtimes", map)); });
    await flush();
    assert.deepEqual(reloads, []);
    act(() => view.root.findAllByType("button").find((button) => text(button) === "Reload page").props.onClick());
    // location.reload() re-requests the same address; nothing rewrites it first.
    assert.deepEqual(reloads, ["reload"]);
    act(() => view.unmount());
  });
});

test("other panels still open, and revisiting the failed one stays truthful without a fake retry", async () => {
  const { AdminPanelLoadBoundary } = load("admin/components/AdminPanelLoadBoundary.tsx");
  const { map, calls } = panels();
  await quietly(async () => {
    let view;
    act(() => { view = TestRenderer.create(area(AdminPanelLoadBoundary, "runtimes", map, () => {})); });
    await flush();
    assert.match(text(view.root), /This page could not finish loading/);
    act(() => view.update(area(AdminPanelLoadBoundary, "users", map, () => {})));
    await flush();
    assert.match(text(view.root), /User accounts/, "another panel opens");
    assert.doesNotMatch(text(view.root), /could not finish loading/);
    assert.match(text(view.root), /Users · Runtimes · Agents/);
    act(() => view.update(area(AdminPanelLoadBoundary, "runtimes", map, () => {})));
    await flush();
    assert.match(text(view.root), /This page could not finish loading/, "the failed panel still says so");
    assert.equal(calls.runtimes, 1, "the cached rejection is not retried behind the user's back");
    act(() => view.unmount());
  });
});

test("a module that throws while it evaluates gets the same cause-neutral state", async () => {
  const { AdminPanelLoadBoundary } = load("admin/components/AdminPanelLoadBoundary.tsx");
  // import() rejects with the module's own error when its top-level code throws.
  const faulty = panelLoad.lazyAdminPanel(() => Promise.reject(new ReferenceError("settingsTable is not defined")));
  await quietly(async () => {
    let view;
    act(() => { view = TestRenderer.create(area(AdminPanelLoadBoundary, "faulty", { faulty }, () => {})); });
    await flush();
    const all = text(view.root);
    assert.match(all, /This page could not finish loading/);
    assert.doesNotMatch(all, /settingsTable|did not download|connection problem caused/);
    assert.match(all, /Users · Runtimes · Agents/);
    act(() => view.unmount());
  });
});

test("a genuine render error still reaches the area boundary", async () => {
  const { AdminPanelLoadBoundary } = load("admin/components/AdminPanelLoadBoundary.tsx");
  const broken = panelLoad.lazyAdminPanel(() => Promise.resolve({ default: () => { throw new Error("render bug"); } }));
  await quietly(async (logged) => {
    let view;
    act(() => { view = TestRenderer.create(area(AdminPanelLoadBoundary, "broken", { broken }, () => {})); });
    await flush();
    const all = text(view.root);
    assert.match(all, /This page could not be displayed/, "the existing area boundary handles it");
    assert.doesNotMatch(all, /This page could not finish loading/, "a render bug is not dressed up as a download failure");
    assert.ok(logged.some((args) => args.some((arg) => arg?.message === "render bug")), "the render error is reported, not swallowed");
    act(() => view.unmount());
  });
});

test("only an import rejection is marked; the original error keeps its identity", async () => {
  const failure = new TypeError(CHUNK_ERROR);
  const reason = await panelLoad.markImportFailure(() => Promise.reject(failure))().catch((error) => error);
  assert.equal(reason, failure);
  assert.equal(panelLoad.isAdminPanelLoadFailure(reason), true);
  assert.equal(reason.message, CHUNK_ERROR);
  const frozen = Object.freeze(new Error("frozen"));
  const wrapped = await panelLoad.markImportFailure(() => Promise.reject(frozen))().catch((error) => error);
  assert.equal(panelLoad.isAdminPanelLoadFailure(wrapped), true);
  assert.equal(wrapped.cause, frozen);
  assert.equal(panelLoad.isAdminPanelLoadFailure(new Error("render bug")), false);
  assert.equal(panelLoad.isAdminPanelLoadFailure(null), false);
  // A successful import passes through untouched.
  const ok = { default: () => null };
  assert.equal(await panelLoad.markImportFailure(() => Promise.resolve(ok))(), ok);
});

test("every admin panel is loaded through the marked loader and wrapped in its own boundary", () => {
  const source = ["AdminPanelContent.tsx", "adminPanelLazyPages.ts"]
    .map((file) => fs.readFileSync(new URL(`../../src/admin/components/${file}`, import.meta.url), "utf8")).join("\n");
  assert.equal((source.match(/\blazy\(/g) ?? []).length, 0, "no bare React.lazy left");
  assert.ok((source.match(/= lazyAdminPanel\(/g) ?? []).length >= 39);
  assert.match(source, /<AdminPanelLoadBoundary key=\{tab\}>\s*<Suspense/);
});
