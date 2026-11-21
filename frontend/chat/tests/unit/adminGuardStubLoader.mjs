// Shared helpers of the admin render guards (adminRenderGuards*): a loader that replaces chosen imports by stub
// components (rendered as "stub:<Name>" host nodes, so a guard can read the props a parent passes), and a readJson
// stub that answers by URL.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { createElement } from "react";
import { SRC } from "./settingsRenderHarness.mjs";

const require = createRequire(import.meta.url);
const ts = require("typescript");

// A stub renders its children, and a `footer` prop inside a "stub:footer" node.
const stubModule = () => new Proxy({}, {
  get: (_, name) => (name === "__esModule" ? true : (props) => createElement(`stub:${String(name)}`, props, props.children,
    props.footer ? createElement("stub:footer", null, props.footer) : null)),
});

/**
 * Loads `relative` like adminPartsLoader, but every import whose specifier ends with one of `stubs` is a stub module
 * and one ending with a key of `mocks` is that value.
 */
export function loadStubbed(relative, stubs, extra = {}, mocks = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, JSON, Set, Map,
      encodeURIComponent, setTimeout, clearTimeout, window: { location: { search: "" }, setTimeout, clearTimeout },
      document: { addEventListener() {}, removeEventListener() {}, activeElement: null, querySelector: () => null }, ...extra,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        const mocked = Object.keys(mocks).find((suffix) => name.endsWith(suffix));
        if (mocked) return mocks[mocked];
        if (stubs.some((suffix) => name.endsWith(suffix))) return stubModule();
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

/** The stub nodes of one stubbed component. */
export const stubs = (view, name) => view.root.findAll((node) => node.type === `stub:${name}`);

/** A readJson stub: `routes` maps a URL prefix to the answer (a value or a function of the init); calls are recorded. */
export function jsonRoutes(routes) {
  const calls = [];
  const readJson = async (url, init = {}) => {
    calls.push({ url, method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null });
    const key = Object.keys(routes).filter((prefix) => url.startsWith(prefix)).sort((a, b) => b.length - a.length)[0];
    if (key === undefined) throw new Error(`no route for ${url}`);
    const answer = routes[key];
    return typeof answer === "function" ? answer(init) : answer;
  };
  return { readJson, calls };
}
