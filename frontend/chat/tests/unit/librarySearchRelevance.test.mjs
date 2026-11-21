// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/librarySearchRelevance.test.mjs
//
// Library search relevance explanation. The search methods say what they do (hybrid is relevance-
// ranked when the reranker is available; keyword and meaning are not relevance-filtered). The reranker's state comes
// from this search's `mode_states.rerank` and the Knowledge settings read model, as "Relevance ranking active" or
// "Relevance ranking unavailable: <reason; who can fix it>". A reranked answer with scores shows its low-relevance tail
// under "Less relevant" (display only, nothing hidden); without scores nothing is invented. An empty answer says
// "No matching knowledge found" and implies nothing about truth. Every request is a stub.
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
  LESS_RELEVANT_SHARE,
  NO_MATCH_TEXT,
  SEARCH_MODES,
  lessRelevantStart,
  relevanceStatus,
  searchModeHint,
} from "../../src/admin/components/workspaceKnowledge/knowledgeSearchPresenter.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);

const settings = (reranker, classification = { effective: "internal", source: "instance_default" }) =>
  ({ workspace_id: "w1", data_classification: classification, reranker });

// ---- model --------------------------------------------------------------------------------------

test("the methods say what they do; the hint follows the method and the reranker", () => {
  assert.deepEqual(SEARCH_MODES.map((mode) => [mode.value, mode.label]), [
    ["hybrid", "Hybrid: keywords and meaning, relevance-ranked when the reranker is available"],
    ["lexical", "Keyword: the exact terms, not relevance-filtered"],
    ["vector", "Meaning: similar meaning, not relevance-filtered"],
  ]);
  assert.match(searchModeHint("lexical", true), /^Not relevance-filtered: results may be only loosely related/);
  assert.match(searchModeHint("vector", true), /^Not relevance-filtered/);
  assert.match(searchModeHint("hybrid", true), /^Ranked by relevance; passages the reranker judges irrelevant are left out\./);
  assert.match(searchModeHint("hybrid", false), /^Relevance ranking is unavailable, so results are ranked by keywords and meaning only/);
  assert.equal(searchModeHint("hybrid", null), "Ranked by relevance when the reranker is available.");
});

test("the reranker state: active, or unavailable with the plain reason and who can fix it; this search's state wins", () => {
  assert.deepEqual(relevanceStatus(settings({ state: "ok", hold_reason: null }), undefined),
    { active: true, text: "Relevance ranking active.", classification: "Data classification: internal (Instance default)." });
  const reasons = {
    reranker_not_configured: /no reranker is configured for this instance; an instance operator can set one up/,
    reranker_unknown: /the configured reranker is not known; an instance operator/,
    region_missing: /no AWS region is set for the reranker on this instance; an instance operator sets it/,
    runtime_missing: /this instance cannot reach the reranker; an instance operator completes its installation/,
    workspace_data_classification_missing: /this Workspace has no data classification; a Workspace admin sets it, or an instance operator sets an Instance default/,
    workspace_data_classification_unknown: /data classification is not recognised; a Workspace admin corrects it/,
  };
  for (const [hold, pattern] of Object.entries(reasons)) {
    const status = relevanceStatus(settings({ state: "needs_configuration", hold_reason: hold }), undefined);
    assert.equal(status.active, false, hold);
    assert.match(status.text, new RegExp(`^Relevance ranking unavailable: .*${pattern.source}[^;]*\\.$`), hold);
  }
  assert.match(relevanceStatus(settings({ state: "denied", hold_reason: "data_policy_class_insufficient" }), undefined).text,
    /more sensitive than the reranker may receive; only a Workspace admin changing the classification/);
  // This search's own state wins, and a settings reason explains it only for the same state.
  assert.equal(relevanceStatus(settings({ state: "needs_configuration", hold_reason: "region_missing" }), "ok").active, true);
  assert.match(relevanceStatus(settings({ state: "ok", hold_reason: null }), "needs_configuration").text,
    /^Relevance ranking unavailable: the reranker needs configuration; an instance operator or a Workspace admin can check/);
  assert.match(relevanceStatus(null, "denied").text, /data policy does not allow the reranker/);
  const mismatched = relevanceStatus(settings({ state: "needs_configuration", hold_reason: "region_missing" }), "denied").text;
  assert.match(mismatched, /data policy does not allow the reranker/, "another state's hold reason never explains this one");
  assert.doesNotMatch(mismatched, /region/);
  assert.equal(relevanceStatus(null, "denied").classification, null, "not reported: no classification line");
  assert.match(relevanceStatus(settings({ state: "needs_configuration", hold_reason: "brand_new" }), undefined).text, /the reranker needs configuration/);
  assert.match(relevanceStatus(null, "sleeping").text, /reranker state sleeping\.$/);
  assert.equal(relevanceStatus(null, undefined), null, "not reported: nothing claimed");
  assert.equal(relevanceStatus({}, undefined), null);
  assert.equal(relevanceStatus(settings({ state: "ok" }, { effective: null, source: "unset" }), undefined).classification,
    "Data classification: not set.");
  assert.equal(relevanceStatus(settings({ state: "ok" }, { effective: "confidential", source: "workspace" }), undefined).classification,
    "Data classification: confidential (set for this Workspace).");
});

test("the 'Less relevant' tail: only for a reranked answer whose passages all carry scores; nothing is dropped", () => {
  const hits = (...scores) => scores.map((relevance) => ({ relevance }));
  assert.equal(LESS_RELEVANT_SHARE, 0.5);
  assert.equal(lessRelevantStart(hits(0.9, 0.8, 0.3, 0.12), "ok"), 2);
  assert.equal(lessRelevantStart(hits(0.4, 0.1), "ok"), 1);
  assert.equal(lessRelevantStart(hits(0.9, 0.3, 0.8), "ok"), null, "a high score after a low one: no trailing tail");
  assert.equal(lessRelevantStart(hits(0.9, 0.85, 0.5), "ok"), null, "none below half the best");
  assert.equal(lessRelevantStart(hits(0.9, 0.45), "ok"), null, "exactly half is not below");
  assert.equal(lessRelevantStart(hits(0.9, 0.2), "needs_configuration"), null, "not reranked: no relevance judgement");
  assert.equal(lessRelevantStart(hits(0.9, 0.2), undefined), null);
  assert.equal(lessRelevantStart([{ relevance: 0.9 }, { relevance: null }], "ok"), null, "a missing score: nothing invented");
  assert.equal(lessRelevantStart(hits(0.9), "ok"), null);
  assert.equal(lessRelevantStart(hits(-0.1, -0.2), "ok"), null, "never a tail that starts at the best passage");
  assert.match(NO_MATCH_TEXT, /^No matching knowledge found\. Try another wording or other terms\. .*does not confirm or refute anything\.$/);
});

// ---- rendered -----------------------------------------------------------------------------------

function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    assert.ok(fs.readdirSync(path.dirname(file)).includes(path.basename(file)), `no file with this exact case: ${file}`);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl, encodeURIComponent, FormData,
      window: { location: { origin: "http://localhost" }, setTimeout: () => 0 }, ...extra,
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

const hit = (key, relevance) => ({
  evidence_key: key, text: `Passage ${key}.`, citation: `Doc ${key}, rev 1`, source_title: `Doc ${key}`, source_url: null,
  products: [], version: null, kind: null, pages: null, section: null, found_by: [], relevance, similarity: null,
});

test("rendered results: a reranked answer shows its tail under 'Less relevant' with every passage; scores only when sent", () => {
  const { KnowledgeSearchResults } = load("admin/components/workspaceKnowledge/KnowledgeSearchResults.tsx");
  const outcome = (result) => ({ busy: false, error: null, query: "probe", result });
  let view;
  act(() => { view = TestRenderer.create(createElement(KnowledgeSearchResults, { workspaceId: "w1",
    search: outcome({ evidence: [hit("a", 0.91), hit("b", 0.8), hit("c", 0.21), hit("d", 0.12)], mode_states: { rerank: "ok" } }) })); });
  const lists = view.root.findAllByType("ol");
  assert.equal(lists.length, 2);
  assert.deepEqual(lists.map((list) => list.findAll((n) => n.type === "h3" && /^\d/.test(text(n))).map(text)), [["1Doc a", "2Doc b"], ["3Doc c", "4Doc d"]],
    "numbering continues into the tail");
  const tail = byTestId(view, "search-less-relevant")[0];
  assert.equal(text(tail.findByProps({ className: "knowledge-search__tail-head" })), "Less relevant");
  // The ranking is the order; no score is shown.
  assert.doesNotMatch(text(view.root), /Relevance \d/);

  act(() => view.update(createElement(KnowledgeSearchResults, { workspaceId: "w1",
    search: outcome({ evidence: [hit("a", null), hit("b", null)], mode_states: { rerank: "needs_configuration" } }) })));
  assert.equal(view.root.findAllByType("ol").length, 1);
  assert.equal(byTestId(view, "search-less-relevant").length, 0);
  assert.doesNotMatch(text(view.root), /Relevance \d/, "no score when the server sent none");

  act(() => view.update(createElement(KnowledgeSearchResults, { workspaceId: "w1", search: outcome({ evidence: [], mode_states: {} }) })));
  assert.equal(text(view.root.findByProps({ className: "knowledge-search__empty" })), NO_MATCH_TEXT);
  act(() => view.unmount());
});

// Review (search width): the results use the full width; the preview opens only for a chosen hit, as a side
// panel over them, and the filters fold away.
test("no preview until a hit is chosen; it opens as a side panel; the filters fold away", () => {
  const wide = { location: { origin: "http://localhost" }, setTimeout: () => 0, matchMedia: () => ({ matches: true }) };
  const { KnowledgeSearchResults } = load("admin/components/workspaceKnowledge/KnowledgeSearchResults.tsx", { window: wide });
  const search = { busy: false, error: null, query: "probe", result: { evidence: [hit("a", null), hit("b", null)], mode_states: {} } };
  let view;
  act(() => { view = TestRenderer.create(createElement(KnowledgeSearchResults, { workspaceId: "w1", search })); });
  const preview = () => byTestId(view, "search-preview");
  assert.equal(preview().length, 0, "nothing beside the results until a hit is chosen");
  act(() => view.root.findAll((n) => n.type === "button" && text(n) === "Preview")[1].props.onClick());
  assert.equal(preview().length, 1);
  assert.equal(preview()[0].props.role, "dialog", "the design system's side panel");
  assert.equal(text(preview()[0].findByType("h2")), "Doc b");
  act(() => byTestId(view, "search-preview-close")[0].props.onClick());
  assert.equal(preview().length, 0);
  const layout = () => view.root.find((n) => typeof n.props.className === "string" && n.props.className.startsWith("knowledge-search__layout"));
  assert.equal(byTestId(view, "search-filters").length, 1);
  const toggle = byTestId(view, "search-filters-toggle")[0];
  assert.equal(text(toggle), "Hide filters");
  act(() => toggle.props.onClick());
  assert.equal(byTestId(view, "search-filters").length, 0);
  assert.match(layout().props.className, /knowledge-search__layout--wide/, "the results take the whole width");
  assert.equal(text(byTestId(view, "search-filters-toggle")[0]), "Filters");
  act(() => view.unmount());
});

function server({ settings: settingsAnswer, search }) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method || "GET" });
    const answer = String(url).endsWith("/settings") ? settingsAnswer : search;
    return { ok: answer.status < 400, status: answer.status, statusText: "", json: async () => answer.body };
  };
  return { fetch, calls };
}

async function mountPanel(srv, isAdmin = true) {
  const { KnowledgeSearchPanel } = load("admin/components/workspaceKnowledge/KnowledgeSearchPanel.tsx", { fetch: srv.fetch });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(KnowledgeSearchPanel, { workspaceId: "w1", showOverview: false, isAdmin })); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  return view;
}

test("rendered panel: the settings say why relevance ranking is unavailable before a search; a reranked search says active", async () => {
  const srv = server({
    settings: { status: 200, body: settings({ state: "needs_configuration", hold_reason: "workspace_data_classification_missing" }, { effective: null, source: "unset" }) },
    search: { status: 200, body: { evidence: [hit("a", 0.9)], mode_states: { lexical: "ok", vector: "ok", rerank: "ok" } } },
  });
  const view = await mountPanel(srv);
  const status = byTestId(view, "relevance-status")[0];
  assert.equal(status.props["data-active"], false);
  assert.equal(status.props.className, "knowledge-search__hint", "a quiet note, not a warning");
  assert.equal(text(status), "Relevance ranking unavailable: this Workspace has no data classification; a Workspace admin sets it, or an instance operator sets an Instance default.");
  // The classification is detail: it lives in Options.
  assert.match(text(byTestId(view, "relevance-detail")[0]), /Data classification: not set\.$/);
  assert.match(text(byTestId(view, "search-mode-hint")[0]), /^Relevance ranking is unavailable/);
  assert.deepEqual(view.root.findByType("select").findAllByType("option").map(text), SEARCH_MODES.map((mode) => mode.label));
  act(() => view.root.findByType("select").props.onChange({ target: { value: "vector" } }));
  assert.match(text(byTestId(view, "search-mode-hint")[0]), /^Not relevance-filtered/);

  act(() => view.root.findByProps({ type: "text" }).props.onChange({ target: { value: "probe" } }));
  await act(async () => { await view.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  // An active ranking is not worth a line under the field; Options still states it.
  assert.equal(byTestId(view, "relevance-status").length, 0, "this search was reranked");
  assert.match(text(byTestId(view, "relevance-detail")[0]), /^Relevance ranking active\./);
  assert.deepEqual(srv.calls.map((call) => [call.url, call.method]), [
    ["/api/v1/workspaces/w1/knowledge/settings", "GET"], ["/api/v1/workspaces/w1/knowledge/search", "POST"],
  ]);
  act(() => view.unmount());
});

test("rendered panel: without the settings read model nothing is claimed before a search", async () => {
  const srv = server({ settings: { status: 404, body: { detail: "Not Found" } }, search: { status: 200, body: { evidence: [] } } });
  const view = await mountPanel(srv);
  assert.equal(byTestId(view, "relevance-status").length, 0);
  assert.equal(text(byTestId(view, "search-mode-hint")[0]), "Ranked by relevance when the reranker is available.");
  act(() => view.unmount());
});

test("rendered panel: a member does not see the ranking note; Options still states it", async () => {
  const srv = server({
    settings: { status: 200, body: settings({ state: "needs_configuration", hold_reason: "workspace_data_classification_missing" }, { effective: null, source: "unset" }) },
    search: { status: 200, body: { evidence: [] } },
  });
  const view = await mountPanel(srv, false);
  assert.equal(byTestId(view, "relevance-status").length, 0);
  assert.match(text(byTestId(view, "relevance-detail")[0]), /^Relevance ranking unavailable/);
  act(() => view.unmount());
});
