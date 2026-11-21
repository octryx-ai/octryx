// Agents & workflows → Overview → Effective setup (A1): parsing, budget, query and the part bodies.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as areas from "../../src/admin/config/adminPanelAreas.ts";
import {
  budgetShares,
  effectiveSetupSessionHref,
  readEffectiveSetup,
  readSessionFromSearch,
  setupQueryString,
} from "../../src/admin/components/agentsWorkflows/effectiveSetup/effectiveSetupModel.ts";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function load(path) {
  const exports = {};
  const source = fs.readFileSync(new URL(`../../src/admin/components/agentsWorkflows/${path}`, import.meta.url), "utf8");
  const compiled = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX },
  }).outputText;
  vm.runInNewContext(compiled, {
    exports,
    require: (name) => (name === "../awBadges" ? load("awBadges.tsx") : require(name)),
  });
  return exports;
}

const RAW = {
  runtime: "chat",
  summary: { capability: { class: "read_only", source: "explicit" }, workflow_key: "answer-from-docs", profile_status: "allowed" },
  parts: [
    { id: "system_texts", title: "System prompt texts", source: { label: "Prompt catalog", tab: "promptCatalog" },
      version: "3 keys · 1 overridden", enforced: "enforced", tokens: 1200, details: { keys: [] } },
    { id: "workflow", title: "Workflow", source: { label: "Workflows → answer-from-docs", tab: "workflowList" },
      version: "v4", enforced: "enforced", tokens: 40,
      details: { selected: true, capability_class: "read_only", when_to_use: "Answer from documents.",
        checks: [{ type: "tool_called", description: "The sources were searched" }],
        tool_policy: { allowlist: ["knowledge_search"] } } },
    { id: "unknown", title: "Other", source: {}, enforced: "nonsense", tokens: "x", details: null },
  ],
  budget: { total: 1240, limit: 8000, groups: [{ key: "platform_agent", label: "Platform + agent", tokens: 1200 }] },
  turn: { trace_id: "4f2c0000", created_at: "2026-10-08T10:00:00" },
  comparison: { matches: false, changed: 1, same: 9, keys: [{ key: "system.x", turn: "system.x@1", now: "system.x@2", state: "changed" }] },
};

test("the response is read into typed parts with a closed enforcement vocabulary", () => {
  const setup = readEffectiveSetup(RAW);
  assert.equal(setup.capabilityClass, "read_only");
  assert.deepEqual(setup.parts.map((part) => part.id), ["system_texts", "workflow", "unknown"]);
  assert.equal(setup.parts[1].sourceTab, "workflowList");
  assert.equal(setup.parts[2].enforced, "guidance", "an unknown value never reads as enforced");
  assert.equal(setup.parts[2].tokens, 0);
  assert.equal(setup.comparison.matches, false);
  assert.equal(setup.comparison.keys[0].state, "changed");
  assert.equal(setup.turn.traceId, "4f2c0000");
});

test("budget shares are percent of the turn budget and never exceed the bar", () => {
  const setup = readEffectiveSetup(RAW);
  assert.deepEqual(budgetShares(setup.budget).map((group) => group.percent), [15]);
  assert.equal(budgetShares({ total: 10, limit: 1, groups: [{ key: "a", label: "A", tokens: 10 }] })[0].percent, 100);
});

test("the query names only what was chosen and always the runtime", () => {
  assert.equal(
    setupQueryString({ projectId: "p", userId: "", agentId: "", workflowKey: "none", runtime: "octryx_claude" }),
    "project_id=p&workflow_key=none&runtime=octryx_claude",
  );
  assert.equal(readSessionFromSearch("?area=workflows&tab=effectiveSetup&session=s-1"), "s-1");
  assert.equal(effectiveSetupSessionHref("a b"), "/chat?area=workflows&tab=effectiveSetup&session=a%20b");
});

test("Effective setup left the navigation for Admin › Rules (E6); its links still open it in the Agents area", () => {
  const ref = areas.listAdminAreaTabRefs("workflows").find((tab) => tab.id === "effectiveSetup");
  assert.equal(ref.hidden, true);
  assert.equal(areas.resolveAdminAreaForTab("effectiveSetup"), "workflows");
});

test("the workflow part lists its evidence steps and tools", () => {
  const { SetupPartBody } = load("effectiveSetup/SetupPartBody.tsx");
  const part = readEffectiveSetup(RAW).parts[1];
  let renderer;
  act(() => {
    renderer = TestRenderer.create(createElement(SetupPartBody, { part }));
  });
  const textOf = (node) => (typeof node === "string" ? node : (node.children ?? []).map(textOf).join(""));
  const rendered = renderer.root.findAll(() => true).map((node) => textOf(node)).join(" ");
  assert.match(rendered, /Read-only/);
  assert.match(rendered, /knowledge_search/);
  assert.match(rendered, /Answer from documents\./);
});
