// Shared by the automation page tests: transpiles a component from src/ in a VM with stubbed imports (CSS is
// ignored, `stubs` replace modules by path suffix), so a component renders without a bundler or a browser.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");

export const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

const fakeDocument = {
  getElementById: () => null,
  addEventListener: () => {},
  removeEventListener: () => {},
  activeElement: null,
};

export function makeLoader(stubs = {}) {
  const cache = new Map();
  const resolve = (name, dir) => {
    if (name.endsWith(".css")) return {};
    const stub = Object.entries(stubs).find(([suffix]) => name.endsWith(suffix));
    if (stub) return stub[1];
    if (name.startsWith(".")) {
      const base = path.resolve(dir, name);
      for (const ext of [".tsx", ".ts"]) if (fs.existsSync(base + ext)) return load(base + ext);
    }
    return require(name);
  };
  const load = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl,
      JSON, encodeURIComponent, setTimeout, clearTimeout, navigator: { clipboard: { writeText: async () => {} } },
      window: { location: { origin: "https://platform.invalid" } },
      document: fakeDocument, require: (name) => resolve(name, path.dirname(file)),
    });
    return module.exports;
  };
  return (relative) => load(path.join(SRC, relative));
}
