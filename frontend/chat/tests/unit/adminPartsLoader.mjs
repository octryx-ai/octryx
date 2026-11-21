// Loader for the admin parts render guards: like the settings harness, but each file is transpiled by its own
// extension (so `.ts` generics stay generics) and the window stub also has timers and confirm.
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { SRC } from "./settingsRenderHarness.mjs";

const require = createRequire(import.meta.url);
const ts = require("typescript");

const windowStub = () => ({
  location: { origin: "http://localhost", search: "", href: "http://localhost/chat", assign: () => {} },
  localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} }, history: { state: null, replaceState: () => {} },
  addEventListener: () => {}, removeEventListener: () => {}, dispatchEvent: () => {}, setTimeout, setInterval: () => 0, clearInterval: () => {},
  confirm: () => true,
});

export function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl, JSON,
      encodeURIComponent, FormData, setInterval, clearInterval, setTimeout, clearTimeout, Set, Map,
      window: windowStub(), document: { addEventListener() {}, removeEventListener() {}, activeElement: null, querySelector: () => null }, ...extra,
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
