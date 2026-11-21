// Shared harness of the Cedar policy engine page tests: loads a TSX module in a VM context with stubbed
// globals (fetch, document), a request-recording stub server, and small query helpers for react-test-renderer.

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url);
const ts = require("typescript");
export const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const SRC = path.resolve(HERE, "../../src");
export const SCHEMA = fs.readFileSync(path.resolve(HERE, "../../../../backend/app/services/policy_engine/octryx.cedarschema"), "utf8");
export const CATALOG = JSON.parse(fs.readFileSync(path.resolve(HERE, "../../../../backend/app/services/policy_engine/policy_catalog.json"), "utf8"));
export const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
export const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
export const tick = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
export const click = (view, id, index = 0) => act(async () => { byTestId(view, id)[index].props.onClick(); });
export const change = (view, id, value, index = 0) => act(async () => { byTestId(view, id)[index].props.onChange({ target: { value, checked: value } }); });

export const FAKE_DOCUMENT = {
  activeElement: null,
  addEventListener() {},
  removeEventListener() {},
  documentElement: { getAttribute: () => "dark" },
};

export function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, JSON, Map, Set,
      encodeURIComponent, setTimeout, clearTimeout, document: FAKE_DOCUMENT, ...extra,
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
    const call = { url: String(url), method: init.method || "GET", body: init.body ? JSON.parse(init.body) : null, headers: init.headers || {} };
    calls.push(call);
    const { status, body } = answer(call);
    return { ok: status < 400, status, statusText: "", json: async () => body };
  };
  return { fetch, calls };
}

export const STATUS = (overrides = {}) => ({
  mode: "shadow", modes: ["off", "shadow", "enforce"],
  engine: { available: true, library: "cedarpy", schema_version: "2026-10-06.2" },
  custom: { version: 2, digest: "sha256:c", valid: true },
  baseline: { digest: "sha256:b", workspaces: 3, matrix_state: "default" },
  counters: { seat: { match: 4, mismatch: 0, custom_policy: 0, error: 0 }, gateway_tool_check: { match: 10, mismatch: 1, custom_policy: 2, error: 0 } },
  latency: { samples: 14, p50_ms: 0.2, p95_ms: 0.4 },
  decision_log: { pending: 0, dropped: 0, retention_days: 30 },
  enforce: { window_hours: 24, shadow_since: "2026-10-06T10:00:00", mismatches: 1, errors: 0, ready: false, reasons: ["window_not_elapsed", "mismatches_in_window"] },
  ...overrides,
});
