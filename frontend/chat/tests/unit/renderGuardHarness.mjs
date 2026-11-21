// Shared harness for render guard tests: loads a source file through the TypeScript transpiler with relative imports
// resolved to stubs (by module file name) or to the real .tsx/.ts file, and renders with react-test-renderer.
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
const SRC = fileURLToPath(new URL("../../src/", import.meta.url));

export const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));
export const noop = () => {};
export const box = (testid) => (props) => createElement("div", { "data-testid": testid }, props.children ?? null);
export const icon = (props) => createElement("i", { "data-icon": props.name ?? "" });
export const flush = () => act(async () => { for (let i = 0; i < 5; i += 1) await Promise.resolve(); });

export function load(relative, stubs = {}, globals = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Intl, Promise,
      Math, JSON, Array, String, Boolean, Set, Map, RegExp, encodeURIComponent, setTimeout, clearTimeout,
      window: { localStorage: { getItem: () => null, setItem() {} }, setTimeout, clearTimeout, open() {} },
      document: { hidden: false, addEventListener() {}, removeEventListener() {} },
      ...globals,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (name.startsWith(".")) {
          const base = path.resolve(path.dirname(file), name);
          if (stubs[path.basename(base)]) return stubs[path.basename(base)];
          for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return loadFile(base + ext);
          if (fs.existsSync(path.join(base, "index.ts"))) return loadFile(path.join(base, "index.ts"));
        }
        return require(name);
      },
    });
    return module.exports;
  };
  return loadFile(path.join(SRC, relative));
}

export async function render(component, props) {
  let view;
  await act(async () => { view = TestRenderer.create(createElement(component, props)); });
  await flush();
  return view;
}
