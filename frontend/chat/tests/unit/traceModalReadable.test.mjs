// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/traceModalReadable.test.mjs
// The execution trace closes on Escape, its close button sits beside the title, and the execution profile shows
// readable labels on top; the raw codes (runtime_finished, direct_chat_safe, chat_default, execution_profile.v1,
// allowed) only under "Technical details".
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import { parseTurnExecutionSummary } from "../../src/chat/run/turnExecutionSummaryParse.ts";
import { TURN_RUN_END_REASONS } from "../../src/chat/run/turnRunIdentityParse.ts";
import { presentEndReasonLabel, readableCode } from "../../src/chat/run/turnRunIdentityPresentation.ts";
import { buildSummaryFixture, profileSection } from "../e2e/turnExecutionSummaryFixtures.mjs";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : Array.isArray(node) ? node.map(text).join("")
  : (node?.children || []).map(text).join(""));

function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, Error, Intl, Number, ...extra,
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

const RUN_ID = "0f8fad5b-d9cb-469f-a165-70867728950e";
const ATTEMPT_ID = "7c9e6679-7425-40de-944b-e07fc1f90ae7";

function summary() {
  return parseTurnExecutionSummary(buildSummaryFixture({
    traceId: "t", sessionId: "s", reasonCode: "runtime_finished",
    profile: profileSection({ profileId: "direct_chat_safe", status: "allowed", decisionSource: "direct_chat_safe",
      executionStrategy: "direct",
      capability: { class: "read_only", source: "chat_default", enforced: true, escalated: false, agent_type_ignored: false } }),
    runIdentity: { kind: "product_run", product_run_id: RUN_ID, run_state: "finished_unverified",
      attempt: { id: ATTEMPT_ID, number: 1, state: "finished_unverified", end_reason: "runtime_finished" } },
  }));
}

test("every end reason has a readable label; unknown values stay neutral", () => {
  for (const reason of TURN_RUN_END_REASONS) {
    const label = presentEndReasonLabel(reason);
    assert.ok(label && !label.includes("_"), reason);
  }
  assert.equal(presentEndReasonLabel("runtime_finished"), "Reply delivered");
  assert.equal(presentEndReasonLabel({ unrecognized: true, value: "x" }), "Unrecognized");
  assert.equal(presentEndReasonLabel(null), null);
  assert.equal(readableCode("direct_chat_safe"), "Direct chat safe");
  assert.equal(readableCode("allowed"), "Allowed");
  assert.equal(readableCode(""), null);
});

test("the execution profile shows readable labels and keeps raw codes under Technical details", () => {
  const { TurnExecutionDetailsSection } = load("chat/run/TurnExecutionDetailsSection.tsx", { navigator: {}, window: {} });
  const parsed = summary();
  assert.ok(parsed, "fixture parses");
  let view;
  act(() => {
    view = TestRenderer.create(createElement(TurnExecutionDetailsSection, { load: { status: "ready", summary: parsed } }));
  });
  const all = text(view.toJSON());
  const hiddenText = text(view.root.findByProps({ className: "turn-exec-details__technical" }).findAllByType("dd")
    .map((node) => node.props.children));
  const shown = all.replace(/Technical details[\s\S]*$/, "");
  for (const rawValue of ["runtime_finished", "direct_chat_safe", "chat_default", "execution_profile.v1"]) {
    assert.doesNotMatch(shown, new RegExp(rawValue.replace(".", "\\.")), `${rawValue} is not shown on top`);
  }
  assert.match(shown, /Direct chat safe/);
  assert.match(shown, /Reply delivered/);
  assert.match(all, /Technical details/);
  for (const rawValue of ["direct_chat_safe", "chat_default", "execution_profile.v1", "allowed", "runtime_finished"]) {
    assert.match(hiddenText, new RegExp(rawValue.replace(".", "\\.")), `${rawValue} stays under Technical details`);
  }
});

test("Escape closes the execution trace; the close button sits beside the title", () => {
  const listeners = new Map();
  const document = {
    addEventListener: (type, fn) => listeners.set(type, fn),
    removeEventListener: (type, fn) => { if (listeners.get(type) === fn) listeners.delete(type); },
  };
  const { TurnTraceModal } = load("chat/traceTurnTraceModal.tsx", { document, navigator: {}, window: {} });
  let closed = 0;
  let view;
  act(() => {
    view = TestRenderer.create(createElement(TurnTraceModal, { trace: { model: "m", usage: {} }, open: true, onClose: () => { closed += 1; } }));
  });
  const handler = listeners.get("keydown");
  assert.ok(handler, "a keydown listener is registered while open");
  handler({ key: "Enter", defaultPrevented: false, preventDefault() {} });
  assert.equal(closed, 0);
  handler({ key: "Escape", defaultPrevented: false, preventDefault() {} });
  assert.equal(closed, 1);
  act(() => { view.update(createElement(TurnTraceModal, { trace: { model: "m", usage: {} }, open: false, onClose() {} })); });
  assert.equal(listeners.has("keydown"), false, "the listener goes away when closed");

  const css = fs.readFileSync(path.join(SRC, "styles/chat/admin-policy-modals/modal-frame.css"), "utf8");
  const header = css.match(/^\.admin-modal \.admin-panel__header \{[^}]*\}/m);
  assert.ok(header);
  assert.match(header[0], /display: flex;/);
  assert.match(header[0], /justify-content: space-between;/);
});

test("Escape closes the execution trace drawer, also after a click inside; a modal over it closes first", () => {
  const listeners = new Map();
  let overlay = null;
  const document = {
    activeElement: null,
    addEventListener: (type, fn) => listeners.set(type, fn),
    removeEventListener: (type, fn) => { if (listeners.get(type) === fn) listeners.delete(type); },
    querySelector: () => overlay,
  };
  const { TraceDrawer } = load("chat/traceDrawer.tsx", { document, navigator: {}, window: {} });
  let closed = 0;
  const props = (open) => ({ open, events: [], onClose: () => { closed += 1; } });
  let view;
  act(() => { view = TestRenderer.create(createElement(TraceDrawer, props(false))); });
  assert.equal(listeners.has("keydown"), false, "no listener while the drawer is parked");
  act(() => { view.update(createElement(TraceDrawer, props(true))); });
  const handler = listeners.get("keydown");
  assert.ok(handler, "a document listener: Escape works wherever the focus is");
  overlay = { role: "dialog" };
  handler({ key: "Escape", defaultPrevented: false, preventDefault() {} });
  assert.equal(closed, 0, "the modal over the trace takes the Escape");
  overlay = null;
  handler({ key: "Escape", defaultPrevented: false, preventDefault() {} });
  assert.equal(closed, 1);
  act(() => { view.update(createElement(TraceDrawer, props(false))); });
  assert.equal(listeners.has("keydown"), false, "the listener goes away when closed");
  act(() => view.unmount());
});
