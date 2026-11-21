import assert from "node:assert/strict";
import { test } from "node:test";
import { registerHooks } from "node:module";
import { readFileSync } from "node:fs";
import { transpileModule, ModuleKind, JsxEmit } from "typescript";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
const loader = registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith(".") && !/\.[a-z]+$/.test(specifier)) {
      try { return nextResolve(`${specifier}.tsx`, context); } catch { /* TS uses shared loader. */ }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.endsWith(".css")) return { format: "module", source: "", shortCircuit: true };
    if (url.endsWith(".tsx")) return { format: "module", shortCircuit: true, source: transpileModule(readFileSync(new URL(url), "utf8"), {
      compilerOptions: { module: ModuleKind.ESNext, jsx: JsxEmit.ReactJSX },
    }).outputText };
    return nextLoad(url, context);
  },
});
const { AnswerSourcesButton } = await import("../../src/chat/evidence/AnswerSourcesButton.tsx");
loader.deregister();
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;

test("source count updates when lazy Markdown arrives after the footer mounted", () => {
  const previous = globalThis.MutationObserver;
  const previousWindow = globalThis.window;
  let notify; let disconnected = false; let links = [];
  const body = {};
  const article = { querySelector: () => body, querySelectorAll: () => links };
  globalThis.window = { location: { origin: "http://localhost:8090" } };
  globalThis.MutationObserver = class {
    constructor(callback) { notify = callback; }
    observe(element) { assert.equal(element, body, "only the message body is observed"); }
    disconnect() { disconnected = true; }
  };
  let view;
  try {
    act(() => { view = TestRenderer.create(createElement(AnswerSourcesButton, { contentKey: "answer" }), {
      createNodeMock: (element) => element.type === "button" ? { closest: () => article } : {},
    }); });
    links = [{ getAttribute: () => "https://example.org/evidence", textContent: "Source", closest: () => ({ textContent: "Claim" }) }];
    act(() => notify([]));
    assert.match(JSON.stringify(view.toJSON()), /Sources · 1/);
    act(() => view.unmount());
    assert.equal(disconnected, true);
  } finally { globalThis.MutationObserver = previous; globalThis.window = previousWindow; }
});

test("a source marker [n] in the answer opens the Sources panel on that source", () => {
  const previous = globalThis.MutationObserver;
  const previousWindow = globalThis.window;
  const handlers = {};
  const body = { addEventListener: (type, handler) => { handlers[type] = handler; }, removeEventListener: () => {} };
  const marker = { getAttribute: () => "https://example.org/evidence", textContent: "[1]", closest: () => ({ textContent: "Claim" }) };
  const other = { getAttribute: () => "https://example.org/other", textContent: "Other page", closest: () => ({ textContent: "More" }) };
  const article = { querySelector: () => body, querySelectorAll: () => [marker, other] };
  globalThis.window = { location: { origin: "http://localhost:8090" } };
  globalThis.MutationObserver = class { observe() {} disconnect() {} };
  const dialog = { open: false, showModal() { this.open = true; }, close() {}, querySelector: () => ({ scrollIntoView() {} }) };
  let view;
  try {
    act(() => { view = TestRenderer.create(createElement(AnswerSourcesButton, { contentKey: "answer" }), {
      createNodeMock: (element) => element.type === "button" ? { closest: () => article } : element.type === "dialog" ? dialog : {},
    }); });
    let prevented = 0;
    act(() => handlers.click({ target: { closest: () => other }, preventDefault: () => { prevented++; } }));
    assert.equal(prevented, 0, "an ordinary link keeps opening in a new tab");
    assert.equal(dialog.open, false);
    act(() => handlers.click({ target: { closest: () => marker }, preventDefault: () => { prevented++; } }));
    assert.equal(prevented, 1);
    assert.equal(dialog.open, true, "the marker opens the Sources panel");
    const focused = view.root.findAll((node) => typeof node.props.className === "string" && node.props.className.includes("answer-sources__item--focused"));
    assert.equal(focused.length, 1);
    assert.equal(focused[0].findByType("a").props.href, "https://example.org/evidence");
    act(() => view.unmount());
  } finally { globalThis.MutationObserver = previous; globalThis.window = previousWindow; }
});
