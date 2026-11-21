// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/confirmDialogTyping.test.mjs
//
// ConfirmDialog focuses once when it opens: a focus effect that re-ran on every render (useConfirmAction passes a new
// onCancel each time) would move the focus from the reason field back to the dialog after each keystroke, so only
// the first character would reach the field. These tests count the focus calls while a reason is typed character by
// character, and check the full reason reaches the action.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement, useEffect } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(new URL(import.meta.url).pathname), "../../src");
const text = (node) => (typeof node === "string" ? node : node.children.map(text).join(""));
const REASON = "UX acceptance: emergency stop test on fixture run";

function load(relative, sandbox) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file);
    const exports = {};
    cache.set(file, exports);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    vm.runInNewContext(output, {
      exports, ...sandbox,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (!name.startsWith(".")) return require(name);
        const base = path.resolve(path.dirname(file), name);
        return loadFile([".tsx", ".ts"].map((ext) => base + ext).find((candidate) => fs.existsSync(candidate)));
      },
    });
    return exports;
  };
  return loadFile(path.join(SRC, relative));
}

function documentStub() {
  const listeners = new Set();
  return {
    listeners,
    addEventListener: (_type, listener) => listeners.add(listener),
    removeEventListener: (_type, listener) => listeners.delete(listener),
    key: (key) => { for (const listener of [...listeners]) listener({ key, defaultPrevented: false, preventDefault() {} }); },
  };
}

test("a reason typed character by character keeps the focus and reaches the action in full", async () => {
  const document = documentStub();
  const { useConfirmAction } = load("admin/components/confirm/useConfirmAction.tsx", { document, console, Error, Promise });
  const runs = [];
  let focusCalls = 0;
  function Host() {
    const { ask, dialog, notice } = useConfirmAction();
    useEffect(() => {
      ask({
        title: 'Emergency stop of the run "BRD-11"?', confirmLabel: "Emergency stop", tone: "danger",
        field: { label: "Reason", placeholder: "e.g. The run writes to the wrong system", required: true },
        run: async (reason) => { runs.push(reason); }, done: 'Run "BRD-11" stopped.',
      });
    }, []);
    return createElement("div", null, dialog, notice);
  }
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(Host), { createNodeMock: () => ({ focus() { focusCalls += 1; } }) });
  });
  assert.equal(focusCalls, 1, "the dialog takes the focus once when it opens");
  for (let length = 1; length <= REASON.length; length += 1) {
    await act(async () => view.root.find((node) => node.type === "textarea").props.onChange({ target: { value: REASON.slice(0, length) } }));
  }
  assert.equal(focusCalls, 1, "typing never moves the focus away from the reason field");
  assert.equal(view.root.find((node) => node.type === "textarea").props.value, REASON);
  const confirm = view.root.find((node) => node.props.role === "alertdialog").findAll((node) => node.type === "button")
    .find((button) => text(button) === "Emergency stop");
  await act(async () => confirm.props.onClick());
  assert.deepEqual(runs, [REASON], "the whole reason is sent, not its first character");
});

test("Escape still cancels with the latest handler after re-renders", async () => {
  const document = documentStub();
  const { ConfirmDialog } = load("admin/components/confirm/ConfirmDialog.tsx", { document, console });
  const cancelled = [];
  let focusCalls = 0;
  const dialog = (round) => createElement(ConfirmDialog, {
    title: "Abort?", confirmLabel: "Abort run", onConfirm() {}, onCancel: () => cancelled.push(round),
  });
  let view;
  await act(async () => { view = TestRenderer.create(dialog(1), { createNodeMock: () => ({ focus() { focusCalls += 1; } }) }); });
  await act(async () => view.update(dialog(2)));
  await act(async () => view.update(dialog(3)));
  assert.equal(focusCalls, 1);
  assert.equal(document.listeners.size, 1, "one Escape listener, not one per render");
  await act(async () => document.key("Escape"));
  assert.deepEqual(cancelled, [3], "the newest onCancel runs");
  await act(async () => view.unmount());
  assert.equal(document.listeners.size, 0);
});
