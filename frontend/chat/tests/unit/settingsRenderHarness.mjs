// Shared render harness for the Settings pages of the settings audit (S5+): transpiles a component with its relative
// imports into a VM with a stubbed fetch, window and document, renders it with react-test-renderer, and records calls.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url);
const ts = require("typescript");
export const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

export const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
export const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
export const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);

const windowStub = () => ({
  location: { origin: "http://localhost", search: "", href: "http://localhost/chat" },
  localStorage: { getItem: () => null, setItem: () => {} },
  history: { state: null, replaceState: () => {} },
  addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => {}, setTimeout: () => 0,
});
const documentStub = () => ({ activeElement: null, addEventListener: () => {}, removeEventListener: () => {}, querySelector: () => null });

export function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl, JSON,
      encodeURIComponent, FormData, setInterval, clearInterval, setTimeout, clearTimeout, Set, Map,
      window: windowStub(), document: documentStub(), ...extra,
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

/** A fetch stub: `answer(call)` returns `{status, body}`; every call is recorded with its parsed body. */
export function server(answer) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    const call = { url: String(url), method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null };
    calls.push(call);
    const { status, body } = answer(call);
    return { ok: status < 400, status, statusText: "", json: async () => body };
  };
  return { fetch, calls };
}

export const tick = (ms = 0) => act(async () => { await new Promise((resolve) => setTimeout(resolve, ms)); });
export const click = (view, id) => act(async () => { byTestId(view, id)[0].props.onClick(); });
export const change = (view, id, value) => act(async () => { byTestId(view, id)[0].props.onChange({ target: { value, checked: value } }); });

export async function render(relative, exportName, srv, props = {}) {
  const module = load(relative, { fetch: srv.fetch });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(module[exportName], props)); });
  await tick();
  return view;
}
