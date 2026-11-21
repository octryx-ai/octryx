// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/automationPermissionMode.test.mjs
//
// Automation run-mode choice (Slice A, A4): the shipped run modes are read only; only active ones are offered, a
// stored key that no longer validates is reported without rewriting it, and every non-ready state blocks saving.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { permissionModeChoice } from "../../src/admin/components/automation/permissionModeCatalog.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const ADMIN = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src/admin");

// readJson is the only network seam: each call is recorded and answered by the test.
const requests = [];
function pendingRead(url) {
  let settle;
  const promise = new Promise((resolve, reject) => { settle = { resolve, reject }; });
  requests.push({ url, ...settle });
  return promise;
}

function makeLoader(stubs) {
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
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, { module, exports: module.exports, console, require: (name) => resolve(name, path.dirname(file)) });
    return module.exports;
  };
  return (relative) => load(path.join(ADMIN, relative));
}

const loadModule = makeLoader({ "/utils/adminPanelHelpers": { readJson: (url) => pendingRead(url) } });

const MODES = [
  { id: "1", key: "diagnosis", name: "Diagnosis", is_active: true, capability_type: "diagnosis" },
  { id: "2", key: "change", name: "Change", is_active: true, capability_type: "change" },
  { id: "3", key: "paused", name: "Paused", is_active: false, capability_type: "diagnosis" },
];

// ---- model -----------------------------------------------------------------------------------

test("model: only active modes are offered and every non-ready state blocks submission", () => {
  const ready = { status: "ready", modes: MODES };
  const cases = [
    [{ status: "loading", modes: [] }, "", "loading", /Loading run modes/],
    [{ status: "error", modes: [], error: "boom" }, "", "error", /could not be loaded: boom/],
    [{ status: "ready", modes: [MODES[2]] }, "", "empty", /No run mode is available/],
    [ready, "", "unchosen", /Choose the run mode/],
    [ready, "paused", "invalid_stored", /"paused" is inactive/],
    [ready, "retired_mode", "invalid_stored", /"retired_mode" no longer exists/],
  ];
  for (const [catalog, value, state, message] of cases) {
    const choice = permissionModeChoice(catalog, value);
    assert.equal(choice.state, state, `${state} for ${value}`);
    assert.match(choice.message, message);
    assert.equal(choice.canSubmit, false);
  }
  const choice = permissionModeChoice(ready, "change");
  assert.deepEqual([choice.state, choice.canSubmit, choice.message], ["ready", true, null]);
  assert.deepEqual(choice.options.map((mode) => mode.key), ["diagnosis", "change"]);
});

// The inbound webhook drawer with its permission-mode picker is gone; a webhook starts an Action,
// which carries the workflow (tests/unit/automationInboundWebhooks.test.mjs).

test("the webhook form state starts without a hidden default mode", () => {
  const { useAdminWebhookState } = loadModule("hooks/useAdminWebhookState.ts");
  let webhook;
  function Probe() {
    webhook = useAdminWebhookState();
    return null;
  }
  act(() => { TestRenderer.create(createElement(Probe)); });
  assert.equal(webhook.webhookFormAgentType, "");
});

