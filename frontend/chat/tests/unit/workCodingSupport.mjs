// Shared helpers for Work and Coding unit tests: load a .ts/.tsx module with stubbed
// globals (fetch), a request stub, and render-tree queries. Not a test file itself.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");

export const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
export const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
export const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
export const button = (view, label) =>
  view.root.findAll((node) => node.type === "button" && text(node).trim() === label)[0] ?? null;

export function load(relative, extra = {}) {
  const cache = new Map();
  const window = { location: { origin: "http://localhost", search: "" }, setTimeout: () => 0, localStorage: { getItem: () => null, setItem: () => {} },
    addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => true, history: { replaceState: () => {}, pushState: () => {} } };
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText.replaceAll("import.meta.url", JSON.stringify(pathToFileURL(file).href));
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Intl, Math, JSON, Promise,
      encodeURIComponent, AbortController, CustomEvent: class { constructor(type, init) { this.type = type; this.detail = init?.detail; } },
      document: { getElementById: () => null, addEventListener: () => {}, removeEventListener: () => {}, activeElement: null },
      window, ...extra,
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

export function server(answer) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null });
    const { status, body } = answer(String(url), init.method || "GET", init.body ? JSON.parse(init.body) : null);
    return { ok: status < 400, status, statusText: "", json: async () => body, text: async () => JSON.stringify(body) };
  };
  return { fetch, calls };
}
