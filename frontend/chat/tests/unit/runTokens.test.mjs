// The run's Tokens view: bars per phase in the server's category order, consumers with their size and
// repetition, the estimate said in plain words, hints as the server wrote them.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import * as model from "../../src/chat/workflowRun/runTokensModel.ts";
import {
  BASIS_TEXT,
  consumerText,
  phaseBars,
  phaseFacts,
  tokenCount,
  tokenProfilePath,
} from "../../src/chat/workflowRun/runTokensModel.ts";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const require = createRequire(import.meta.url);
const ts = require("typescript");

function loadView() {
  const exports = {};
  const source = fs.readFileSync(new URL("../../src/chat/workflowRun/RunTokens.tsx", import.meta.url), "utf8");
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const mocks = {
    "./runTokensModel": model,
    "./useRunResource": { useRunResource: (path) => { requested.push(path); return path ? loaded.profile : null; } },
    "./runTokens.css": {},
    "../../layout/SidePanel": {
      SidePanel: ({ title, subtitle, children }) => createElement("section", { "data-title": title, "data-subtitle": subtitle }, children),
    },
  };
  vm.runInNewContext(output, { exports, require: (spec) => mocks[spec] ?? require(spec) });
  return exports;
}
const requested = [];
const loaded = { profile: null };
const { RunTokensBody, RunTokensPanel } = loadView();

const CATEGORIES = [
  { key: "system_and_tools", label: "System prompt and tool definitions" },
  { key: "tool_results", label: "Tool results" },
  { key: "history", label: "Conversation history" },
  { key: "output", label: "Output" },
];

function phase(name, categories, extra = {}) {
  return { phase: name, turns: 2, calls: 10, basis: "measured", categories, by_tool: {},
    cache: { read: 900, write: 90, uncached: 10, output: 5 }, ...extra };
}

const PROFILE = {
  run_id: "r1",
  basis: "estimated",
  categories: CATEGORIES,
  totals: { read: 20_170_883, write: 1_516_526, uncached: 724, output: 114_600, input: 21_688_133 },
  phases: [
    phase("Reproduce", { system_and_tools: 1_000, tool_results: 3_000, history: 0, output: 0 }, { basis: "estimated" }),
    phase("Minimal fix", { system_and_tools: 1_000, tool_results: 1_000, history: 0, output: 0 }),
  ],
  consumers: [{ tool: "mcp__octryx__workflow_run_status", label: "workflow_run_status {}", count: 38, max_kb: 4,
    total_kb: 149, tokens: 228_228, estimated: true, at_least: true, phase: "Reproduce" }],
  hints: [{ rule: "contract_reread", text: "The run contract was read 38× (149 KB in all).", tokens: 228_228,
    phase: "", estimated: true }],
};

test("bars keep the server's category order, drop empty ones and compare between phases", () => {
  const [first, second] = phaseBars(PROFILE);
  assert.deepEqual(first.segments.map((segment) => [segment.key, segment.share]), [["system_and_tools", 0.25], ["tool_results", 0.75]]);
  assert.equal(first.width, 1);
  assert.equal(second.width, 0.5);
});

test("numbers and facts read at a glance; an estimate says so", () => {
  assert.deepEqual([tokenCount(724), tokenCount(1_516), tokenCount(114_600), tokenCount(21_688_133)], ["724", "1.5k", "115k", "22M"]);
  assert.equal(consumerText(PROFILE.consumers[0]), "≥4 KB × 38 · 228k tokens (estimate)");
  assert.equal(phaseFacts(PROFILE.phases[0]), "2 turns · 90% from the cache · estimate");
  assert.equal(phaseFacts(PROFILE.phases[1]), "2 turns · 10 calls · 90% from the cache");
  assert.equal(tokenProfilePath("a b"), "/api/v1/workflow-runs/a%20b/token-profile");
});

test("the view shows the basis, a bar per phase, the consumers and the server's hints", () => {
  let view;
  TestRenderer.act(() => { view = TestRenderer.create(createElement(RunTokensBody, { profile: PROFILE })); });
  const byTestId = (id) => view.root.find((node) => node.props["data-testid"] === id);
  const text = (node) => [].concat(node.children).map((child) => (typeof child === "string" ? child : text(child))).join("");
  assert.match(text(byTestId("run-tokens-basis")), new RegExp(BASIS_TEXT.estimated.slice(0, 20)));
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "run-tokens-phase").length, 2);
  assert.match(text(byTestId("run-tokens-consumers")), /workflow_run_status \{\}≥4 KB × 38/);
  assert.equal(byTestId("run-tokens-hints").findAll((node) => node.props["data-rule"] === "contract_reread").length, 1);
  TestRenderer.act(() => { view.update(createElement(RunTokensBody, { profile: { ...PROFILE, phases: [] } })); });
  assert.equal(view.root.findAll((node) => node.props.className === "ds-empty").length, 1);
});

test("Work › Runs: the side panel reads the run's profile by its id, for readers who cannot open the run's chat", () => {
  loaded.profile = PROFILE;
  let view;
  TestRenderer.act(() => { view = TestRenderer.create(createElement(RunTokensPanel, { runId: "r 1", title: "OCX-72", onClose: () => {} })); });
  assert.equal(requested.at(-1), "/api/v1/workflow-runs/r%201/token-profile");
  const panel = view.root.find((node) => node.props["data-title"] === "Tokens");
  assert.equal(panel.props["data-subtitle"], "OCX-72");
  assert.equal(view.root.findAll((node) => node.props["data-rule"] === "contract_reread").length, 1);
});
