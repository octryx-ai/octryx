// One loading state. A skeleton of the coming content instead of "Loading…", and after ten seconds a
// plain message with "Try again". The old ad-hoc loading texts may only go down.
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
const text = (node) => (node === null ? "" : typeof node === "string" ? node : node.children.map(text).join(""));

function load(windowStub) {
  const exports = {};
  const source = fs.readFileSync(new URL("../../src/layout/LoadingState.ts", import.meta.url), "utf8");
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
    exports, setTimeout: windowStub.setTimeout, clearTimeout: windowStub.clearTimeout, globalThis: { location: windowStub.location }, require: (name) => (name.endsWith(".css") ? {} : require(name)),
  });
  return exports;
}

function clock() {
  const timers = [];
  return {
    timers,
    window: { setTimeout: (fn, ms) => { timers.push({ fn, ms }); return timers.length; }, clearTimeout: () => {}, location: { reload: () => { throw new Error("reload must not run"); } } },
  };
}

test("a skeleton with a screen-reader label first, then after ten seconds a message with Try again", () => {
  const time = clock();
  const { LoadingState } = load(time.window);
  const retried = [];
  let view;
  act(() => { view = TestRenderer.create(createElement(LoadingState, { label: "work items", rows: 3, onRetry: () => retried.push(1) })); });
  const busy = view.root.findByProps({ "data-testid": "loading-state" });
  assert.equal(busy.props["aria-busy"], "true");
  assert.equal(text(busy), "Loading work items…");
  assert.equal(busy.findAll((node) => node.props.className === "loading-state__block").length, 3);
  assert.equal(time.timers[0].ms, 10000);
  act(() => time.timers[0].fn());
  const slow = view.root.findByProps({ "data-testid": "loading-slow" });
  assert.equal(text(slow), "Work items are taking longer than usual.Try again");
  act(() => slow.findByType("button").props.onClick());
  assert.deepEqual(retried, [1]);
  act(() => view.unmount());
});

test("singular labels read 'is'", () => {
  const time = clock();
  const { LoadingState } = load(time.window);
  let view;
  act(() => { view = TestRenderer.create(createElement(LoadingState, { label: "the delivery pipeline" })); });
  act(() => time.timers[0].fn());
  assert.match(text(view.root), /^The delivery pipeline is taking longer than usual\./);
  act(() => view.unmount());
});

test("the old loading texts may only go down", () => {
  const root = new URL("../../src/", import.meta.url).pathname;
  let count = 0;
  const walk = (dir) => {
    for (const name of fs.readdirSync(dir)) {
      const file = path.join(dir, name);
      if (fs.statSync(file).isDirectory()) walk(file);
      else if (/\.tsx?$/.test(name)) count += (fs.readFileSync(file, "utf8").match(/className="(admin-panel|work-area)__loading"/g) ?? []).length;
    }
  };
  walk(root);
  // Remaining: ProvidersList uses the class for an empty state; ModelCatalogSyncDrawer shows a progress message.
  assert.ok(count <= 2, `${count} ad-hoc loading texts; use <LoadingState>`);
});
