// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/chatMessageHeaderDensity.test.mjs
//
// Message header density: the density fix is CSS-only (message-stream-layout.css) and its
// layout effect is verified in a real browser by root, not here. These tests pin the render
// boundaries the fix relies on: closed Thinking/Performance panels are truly empty wrappers (so the
// `:empty` rule collapses only them), and every header control stays rendered, labelled and operable.
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

const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");

function load(relative) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    // Exact file-name case, so a wrong-case path also fails on case-insensitive hosts (as on Linux).
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console,
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

test("closed panels render empty wrappers; open or unavailable ones keep their content", () => {
  const { MessageThinkingPanel, MessagePerformancePanel } = load("chat/messageBubblePanels.tsx");
  const json = (element) => {
    let view;
    act(() => { view = TestRenderer.create(element); });
    return view.toJSON();
  };
  const toggle = async () => {};
  const closedThinking = json(createElement(MessageThinkingPanel, { isUser: false, hasTurnTrace: true, thinkingOpen: false, thinkingText: "x", thinkingUnavailable: false, onToggleThinking: toggle }));
  assert.deepEqual([closedThinking.props.className, closedThinking.children], ["message-thinking-panel", null]);
  const unavailable = json(createElement(MessageThinkingPanel, { isUser: false, hasTurnTrace: true, thinkingOpen: true, thinkingText: "", thinkingUnavailable: true, onToggleThinking: toggle }));
  assert.equal(unavailable.children.length, 1, "the unavailable notice is a child, so :empty does not hide it");
  const closedPerformance = json(createElement(MessagePerformancePanel, { isUser: false, performanceOpen: false, performance: { hasPerformance: false, summary: [] }, performanceUnavailable: false }));
  assert.deepEqual([closedPerformance.props.className, closedPerformance.children], ["message-performance-panel", null]);
});

test("the header side keeps timestamp and message actions; diagnostics live in the message menu", () => {
  const { MessageBubbleHeader } = load("chat/MessageBubbleHeader.tsx");
  const props = {
    isUser: false, title: "bedrock", roleLabel: "Bedrock / model", timestamp: "12:37 PM",
    headerActions: createElement("button", { type: "button", "aria-label": "Copy message" }),
  };
  let view;
  act(() => { view = TestRenderer.create(createElement(MessageBubbleHeader, props)); });
  const side = view.root.findByProps({ className: "message-row__header-side" });
  assert.equal(text(side.findByProps({ className: "message-row__timestamp" })), "12:37 PM");
  assert.equal(side.findAllByProps({ role: "group" }).length, 0, "Think, Perf and Trace moved into the ⋯ menu");
  assert.equal(side.findAllByProps({ "aria-label": "Copy message" }).length, 1);
});
