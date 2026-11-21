import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function load(file, window) {
  const exports = {};
  const source = fs.readFileSync(new URL(`../../src/chat/${file}.ts`, import.meta.url), "utf8");
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, {
    exports, window, CustomEvent,
    require: (name) => name === "./artifactPreviewUtils"
      ? { resolveOfficeAction: async () => ({ text: "  Review the sample report  " }) }
      : name === "./artifactPreviewKind" ? load("artifactPreviewKind", window) : require(name),
  });
  return exports;
}

test("Office draft reaches the composer, persists, focuses and stops after cleanup", async () => {
  const events = [], values = [], storage = new Map();
  let focuses = 0;
  const target = new EventTarget();
  const window = {
    addEventListener: target.addEventListener.bind(target),
    removeEventListener: target.removeEventListener.bind(target),
    dispatchEvent: (event) => { events.push(event.type); return target.dispatchEvent(event); },
    localStorage: { setItem: (key, value) => storage.set(key, value) },
  };
  const { useComposerArtifactDraftListener } = load("useComposerArtifactDraftListener", window);
  const { draftOfficeAction } = load("artifactPreviewOfficeState", window);
  function Composer() {
    useComposerArtifactDraftListener({ composerDraftKey: "draft-demo", setComposerValue: (text) => values.push(text),
      textareaRef: { current: { focus: () => { focuses++; } } } });
    return null;
  }
  let view;
  act(() => { view = TestRenderer.create(createElement(Composer)); });
  const errors = [], busy = [];
  await act(async () => draftOfficeAction({ artifact: { path: "sample.docx" }, actionId: "review", actionMode: "prompt",
    setBusyActionId: (id) => busy.push(id), setActionsError: (error) => errors.push(error) }));
  assert.deepEqual(events, ["octryx:artifact-draft"]);
  assert.deepEqual(values, ["Review the sample report"]);
  assert.equal(storage.get("draft-demo"), values[0]);
  assert.equal(focuses, 1);
  assert.deepEqual(errors, [""]);
  assert.deepEqual(busy, ["review", null]);
  act(() => view.unmount());
  target.dispatchEvent(new CustomEvent("octryx:artifact-draft", { detail: "ignored after unmount" }));
  assert.equal(values.length, 1);
});
