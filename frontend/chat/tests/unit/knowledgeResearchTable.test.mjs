// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgeResearchTable.test.mjs
//
// Knowledge → Research websites: website-first rows without buttons; a row opens the website in a
// side panel with Approve, Block and Remove; Add website is a side panel; the provider check/diagnostics sit in a
// collapsed "Search provider" section and the explanations live in the page help. Every API call is a stub.
import assert from "node:assert/strict";
import { test } from "node:test";
import { registerHooks } from "node:module";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { transpileModule, ModuleKind, JsxEmit } from "typescript";
import { webSearchApi } from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeApi.ts";
import { providerSummary, researchActions, researchSourceRow } from "../../src/chat/knowledge/researchSourceRows.ts";

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith(".") && !/\.[a-z]+$/.test(specifier)) {
      try { return nextResolve(`${specifier}.tsx`, context); } catch { /* Shared TS hook handles pure modules. */ }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.endsWith(".css")) return { format: "module", source: "", shortCircuit: true };
    if (url.endsWith(".tsx")) return { format: "module", shortCircuit: true, source: transpileModule(readFileSync(new URL(url), "utf8"), {
      compilerOptions: { module: ModuleKind.ESNext, jsx: JsxEmit.ReactJSX },
    }).outputText };
    return nextLoad(url, context);
  },
});
const { KnowledgeResearchSourcesPanel } = await import("../../src/chat/knowledge/KnowledgeResearchSourcesPanel.tsx");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;

const source = (id, state, extra = {}) => ({
  id, scope: "workspace", pattern: `${id}.example.org`, products: [], state, origin: "agent",
  reason: "", evidence_url: null, decided_at: null, created_at: null, ...extra,
});
const SOURCES = [
  source("docs", "proposed", { reason: "Official Spring Boot reference documentation with the 4.0 migration guide.",
    evidence_url: "https://docs.example.org/guide", products: ["spring-boot", "spring-framework"] }),
  source("blog", "trusted", { origin: "admin" }),
  source("spam", "blocked"),
  source("shared", "proposed", { scope: "platform" }),
];
const OVERVIEW = {
  mode: "open", blocklist_version: "2026-09", may_edit_platform: false, sources: SOURCES,
  provider: { name: "tavily", state: "ok", quarantine_reason: null, data_policy_class: "internal" },
};
const context = { mayAuthor: true, mayEditPlatform: false, origin: "http://localhost" };
const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));

test("a row puts the website first and keeps the full reason for the clamped cell", () => {
  const row = researchSourceRow(SOURCES[0], context);
  assert.equal(row.pattern, "docs.example.org");
  assert.equal(row.reasonTitle, SOURCES[0].reason);
  assert.equal(row.evidenceUrl, "https://docs.example.org/guide");
  assert.equal(row.stateLabel, "Awaiting review");
  assert.deepEqual(row.meta, [
    { label: "Applies to", value: "This workspace" },
    { label: "Products", value: "spring-boot, spring-framework" },
    { label: "Proposed by", value: "Research agent" },
  ]);
  const empty = researchSourceRow(SOURCES[1], context);
  assert.equal(empty.reason, "No reason recorded.");
  assert.equal(empty.reasonTitle, undefined);
  assert.equal(empty.meta[1].value, "All");
  assert.equal(empty.meta[2].value, "Administrator");
});

test("the actions: Approve unless approved, Block unless blocked, always Remove", () => {
  assert.deepEqual(researchActions(SOURCES[0]).map((action) => action.label), ["Approve", "Block", "Remove"]);
  assert.deepEqual(researchActions(SOURCES[1]).map((action) => action.label), ["Block", "Remove"]);
  assert.deepEqual(researchActions(SOURCES[2]).map((action) => action.label), ["Approve", "Remove"]);
  const platform = researchSourceRow(SOURCES[3], context);
  assert.deepEqual(platform.actions, []);
  assert.equal(platform.readOnlyNote, "Platform admin only");
  assert.equal(researchSourceRow(SOURCES[0], { ...context, mayAuthor: false }).readOnlyNote, "View only");
});

test("the provider summary carries the status", () => {
  assert.equal(providerSummary(OVERVIEW.provider).text, "Search provider: Tavily · Working");
  assert.equal(providerSummary(OVERVIEW.provider).attention, false);
  const paused = providerSummary({ ...OVERVIEW.provider, state: "unavailable" });
  assert.equal(paused.text, "Search provider: Tavily · Unavailable");
  assert.equal(paused.attention, true);
  const missing = providerSummary({ name: null, state: "needs_configuration", quarantine_reason: null, data_policy_class: null });
  assert.equal(missing.text, "Search provider: not configured");
  assert.equal(providerSummary({ ...OVERVIEW.provider, state: "rate_limited" }).stateLabel, "Rate limited");
});

async function mount() {
  const original = { ...webSearchApi };
  const originalWindow = globalThis.window;
  globalThis.window = { location: { origin: "http://localhost" } };
  const calls = [];
  webSearchApi.overview = () => Promise.resolve(OVERVIEW);
  webSearchApi.decide = (...args) => { calls.push(["decide", ...args]); return Promise.resolve(OVERVIEW); };
  webSearchApi.remove = (...args) => { calls.push(["remove", ...args]); return Promise.resolve(OVERVIEW); };
  webSearchApi.canary = (...args) => { calls.push(["canary", ...args]); return Promise.resolve({ provider: "tavily", healthy: true, reason: "" }); };
  let view;
  await act(async () => { view = TestRenderer.create(createElement(KnowledgeResearchSourcesPanel, { workspaceId: "ws-1", mayAuthor: true })); });
  return { view, calls, restore: () => { act(() => view.unmount()); Object.assign(webSearchApi, original); globalThis.window = originalWindow; } };
}

test("rows carry no buttons; a row opens the website in a side panel whose actions call the same API", async () => {
  const { view, calls, restore } = await mount();
  try {
    assert.deepEqual(view.root.findAllByType("th").map(text), ["Website", "Decision", "Applies to", "Proposed by"]);
    const rows = () => view.root.findAllByType("tr").slice(1);
    assert.equal(rows().length, 4);
    for (const row of rows()) assert.equal(row.findAllByType("button").length, 0, "no buttons inside a row");
    const reason = rows()[0].findByProps({ className: "knowledge-research__reason" });
    assert.equal(reason.props.title, SOURCES[0].reason);
    const panelButtons = () => view.root.findAll((node) => node.type === "button" && /^research-website-(trusted|blocked|remove)$/.test(node.props["data-testid"] ?? ""));
    await act(async () => rows()[0].props.onClick());
    const panel = view.root.findByProps({ "data-testid": "research-website-panel" });
    assert.match(text(panel), /docs\.example\.org/);
    assert.match(text(panel), /Where research found it/);
    assert.deepEqual(panelButtons().map(text), ["Block", "Remove", "Approve"], "the bright action is last");
    const approve = panelButtons().find((node) => text(node) === "Approve");
    assert.equal(approve.props["aria-label"], "Approve docs.example.org");
    await act(async () => approve.props.onClick());
    await act(async () => panelButtons().find((node) => text(node) === "Block").props.onClick());
    await act(async () => rows()[1].props.onClick());
    await act(async () => panelButtons().find((node) => text(node) === "Remove").props.onClick());
    assert.deepEqual(calls, [
      ["decide", "ws-1", "docs", "trusted"], ["decide", "ws-1", "docs", "blocked"], ["remove", "ws-1", "blog"],
    ]);
    assert.equal(view.root.findAll((node) => node.props["data-testid"] === "research-website-panel").length, 0, "Remove closes the panel");
    await act(async () => rows()[3].props.onClick());
    assert.equal(panelButtons().length, 0);
    assert.match(text(view.root.findByProps({ "data-testid": "research-website-readonly" })), /Platform admin only/);
  } finally { restore(); }
});

test("the page explains nothing: mode, provider check and diagnostics stay; the explanations are in the help", async () => {
  const { view, calls, restore } = await mount();
  try {
    assert.equal(view.root.findAll((node) => node.type === "input" && node.props.type === "radio").length, 2);
    assert.ok(view.root.findByProps({ role: "radiogroup" }));
    const details = view.root.findByType("details");
    assert.notEqual(details.props.open, true);
    assert.equal(text(details.findByType("summary")), "Search provider: Tavily · Working");
    const policy = view.root.findByProps({ className: "knowledge-research__policy" });
    const outside = policy.children.filter((node) => node.type !== "details").map(text).join(" ");
    assert.doesNotMatch(outside, /chat web search may use|platform blocklist|Check provider/);
    const check = details.findAll((node) => node.type === "button" && text(node) === "Check provider");
    assert.equal(check.length, 1);
    assert.doesNotMatch(text(details), /one fixed test query/);
    assert.match(text(details), /up to Internal\./);
    assert.match(text(details), /Platform blocklist: 2026-09/);
    const help = readFileSync(new URL("../../help/knowledge/knowledgeResearch.md", import.meta.url), "utf8");
    for (const kept of [/platform blocklist/i, /one fixed test query/, /does not validate every claim/, /block always wins/i]) assert.match(help, kept);
    await act(async () => check[0].props.onClick());
    assert.deepEqual(calls[0], ["canary", "ws-1"]);
    assert.ok(view.root.findAll((node) => node.props.role === "status").some((node) => /Provider check passed \(tavily\)/.test(text(node))));
    const show = view.root.findByType("select");
    assert.equal(show.findAllByType("option").length, 4);
  } finally { restore(); }
});

test("Add website is a side panel with labelled fields and Cancel + the decision at the bottom", async () => {
  const { view, restore } = await mount();
  try {
    await act(async () => view.root.findByProps({ "data-testid": "research-add-website" }).props.onClick());
    const panel = view.root.findByProps({ "data-testid": "research-add-panel" });
    const labels = panel.findAll((node) => node.type === "label" && node.props.className === "admin-panel__field").map((node) => text(node.findAllByType("span")[0]));
    assert.deepEqual(labels.slice(0, 1), ["Website"]);
    assert.ok(labels.includes("Reason (optional)"));
    const footer = panel.findByType("footer").findAllByType("button").map(text);
    assert.deepEqual(footer, ["Cancel", "Approve website"]);
  } finally { restore(); }
});

