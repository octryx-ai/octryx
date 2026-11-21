// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/connectorScopeCheck.test.mjs
//
// Connector UX (delivery 5): a connection test shows what the account can see. Each configured space is
// "visible" or "configured but not visible to this account" (the swapped-client case: a client that sees SPACE2
// configured for SPACE1), the visible list is bounded, a failed listing says so, and the card marks the tags.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import {
  configuredLines,
  missingFlags,
  scopeCheckOf,
  visibleText,
} from "../../src/admin/components/connectorTest/scopeCheckModel.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

const SWAPPED = {
  ok: true, scope_warning: true, summary: "Connected to Confluence. Not visible to this account: SPACE1.",
  warnings: ["Space SPACE1 is configured but not visible to this account."],
  scope_check: { label: "Spaces", noun: "space", configured: ["SPACE1"], visible: ["SPACE2"], visible_count: 1,
    visible_complete: true, missing: ["SPACE1"], error: null, http_status: null },
};

test("each configured key is visible or configured-but-not-visible; the visible list is bounded", () => {
  const check = scopeCheckOf(SWAPPED);
  assert.deepEqual(configuredLines(check), [
    { key: "SPACE1", visible: false, text: "Space SPACE1: configured but not visible to this account." }]);
  assert.equal(visibleText(check), "This account sees 1 space: SPACE2.");
  const many = scopeCheckOf({ scope_check: { ...SWAPPED.scope_check, configured: ["SPACE2"], missing: [],
    visible: ["A", "B"], visible_count: 640, visible_complete: false } });
  assert.deepEqual(configuredLines(many).map((line) => line.visible), [true]);
  assert.equal(visibleText(many),
    "This account sees 640 spaces: A, B, … (640 in total). The listing was cut; configured keys were checked one by one.");
  const failed = scopeCheckOf({ scope_check: { ...SWAPPED.scope_check, error: "visible_scopes_unavailable", http_status: 403 } });
  assert.equal(visibleText(failed), "The visible spaces could not be listed (visible_scopes_unavailable, HTTP 403).");
  assert.equal(scopeCheckOf({ ok: true, summary: "x" }), null, "an answer without a comparison");
  const none = scopeCheckOf({ scope_check: { ...SWAPPED.scope_check, visible: [], visible_count: 0 } });
  assert.equal(visibleText(none), "This account sees no spaces.");
  assert.deepEqual(missingFlags(scopeCheckOf(SWAPPED)), { SPACE1: "Configured but not visible to this account" });
  const unrestricted = scopeCheckOf({ scope_check: { ...SWAPPED.scope_check, label: "Projects", noun: "project", configured: null, missing: [] } });
  assert.deepEqual(configuredLines(unrestricted), []);
});

function load(relative) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, JSON, encodeURIComponent,
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

test("rendered: the card's test result warns per space and names what the account sees", () => {
  const { ConfiguredConnectorActions } = load("admin/components/connectorsTab/ConfiguredConnectorActions.tsx");
  let view;
  act(() => {
    view = TestRenderer.create(createElement(ConfiguredConnectorActions, {
      connector: { tool_name: "confluence", configured: true, supports_test: true }, testResult: SWAPPED,
      ctx: { connectorSaving: null, connectorTesting: null, handleTestConnector: () => {} }, onSave: () => {},
    }));
  });
  const result = view.root.find((node) => node.props["data-testid"] === "connector-test-result");
  assert.match(result.props.className, /connector-card__test-result--warn/, "works, but with a warning");
  assert.match(text(result), /⚠ Connected to Confluence\. Not visible to this account: SPACE1\./);
  assert.match(text(result), /Space SPACE1: configured but not visible to this account\./);
  assert.match(text(result), /This account sees 1 space: SPACE2\./);

  act(() => {
    view.update(createElement(ConfiguredConnectorActions, {
      connector: { tool_name: "confluence", configured: true, supports_test: true },
      testResult: { ...SWAPPED, scope_warning: undefined, summary: "Connected to Confluence.",
        scope_check: { ...SWAPPED.scope_check, configured: ["SPACE2"], missing: [] } },
      ctx: { connectorSaving: null, connectorTesting: null, handleTestConnector: () => {} }, onSave: () => {},
    }));
  });
  const ok = view.root.find((node) => node.props["data-testid"] === "connector-test-result");
  assert.match(ok.props.className, /--ok/);
  assert.match(text(ok), /Space SPACE2: visible to this account\./);
});

test("rendered: the Confluence card marks a configured space the account cannot see", () => {
  const { ConfluenceScopeFields } = load("admin/components/connectorsTab/ConfluenceScopeFields.tsx");
  let view;
  act(() => {
    view = TestRenderer.create(createElement(ConfluenceScopeFields, {
      toolName: "confluence", set: () => {}, flagged: missingFlags(scopeCheckOf(SWAPPED)),
      draft: { confluence_allowed_spaces: '[{"space_key": "SPACE1", "enabled": true}, {"space_key": "SPACE2", "enabled": true}]' },
    }));
  });
  const tags = view.root.findAll((node) => node.props["data-key"]);
  assert.deepEqual(tags.map((node) => [node.props["data-key"], node.props.className.includes("--flagged")]),
    [["SPACE1", true], ["SPACE2", false]]);
  assert.equal(tags[0].props.title, "Configured but not visible to this account");
});
