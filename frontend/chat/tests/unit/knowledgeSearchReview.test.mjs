// Knowledge → Search: one request per search, page families folded, labelled dates,
// excerpts with the question's words, citation markers as named buttons, timings per stage.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import { useKnowledgeSearch } from "../../src/admin/components/workspaceKnowledge/useKnowledgeSearch.ts";
import { hitNumbers, isDeprecatedTitle, pageKey, presentedEvidence, presentHits, titleStem } from "../../src/admin/components/workspaceKnowledge/search/searchFamilies.ts";
import { excerptFor, isHeadingOnly, markTerms, queryTerms } from "../../src/admin/components/workspaceKnowledge/search/snippet.ts";
import { applyFacets, hitDate, NO_FACETS } from "../../src/admin/components/workspaceKnowledge/search/searchFacets.ts";
import { searchTimingSummary, searchTimingText } from "../../src/admin/components/workspaceKnowledge/search/searchProgress.ts";
import { plainSentence, readKnowledgeAnswer } from "../../src/admin/components/workspaceKnowledge/search/answerApi.ts";

globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;
const require = createRequire(import.meta.url);
const ts = require("typescript");
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");

const hit = (key, title, extra = {}) => ({ evidence_key: key, source_id: `s-${key}`, text: `Passage ${key}.`, citation: "",
  source_title: title, source_url: null, products: [], version: null, section: null,
  origin: { kind: "confluence" }, container: "OPS", ...extra });

test("Versions of one page fold under the current one; deprecated titles rank below current ones", () => {
  assert.equal(titleStem("Acme Orders Service Catalog 2022/2023"), "acme orders service catalog");
  assert.equal(titleStem("Acme Orders Service Catalog 2025 (deprecated)"), "acme orders service catalog");
  assert.ok(isDeprecatedTitle("Offering 2021 (deprecated)") && !isDeprecatedTitle("Offering 2026"));
  const hits = [
    hit("a", "Acme Orders Service Catalog 2025 (deprecated)"),
    hit("b", "Onboarding of new customers"),
    hit("c", "Acme Orders Service Catalog 2026"),
    hit("d", "Acme Orders Service Catalog 2022/2023"),
    hit("e", "Acme Orders Service Catalog 2024", { container: "OTHER" }),
    hit("f", "2024"),
  ];
  const shown = presentHits(hits);
  assert.deepEqual(shown.map((entry) => [entry.number, entry.hit.evidence_key, entry.older.map((older) => older.evidence_key)]), [
    [1, "b", []], [2, "c", ["d", "a"]], [3, "e", []], [4, "f", []],
  ], "same family only within one space; a title that is only a year is never grouped; deprecated last");
  const numbers = hitNumbers(shown);
  assert.equal(numbers.get("a"), 2, "a folded version carries its family's number");
  // Two passages of one source are not versions of each other: they are one page.
  const same = presentHits([hit("x", "Guide 2026"), { ...hit("y", "Guide 2026"), source_id: "s-x" }]);
  assert.deepEqual(same.map((entry) => [entry.hit.evidence_key, entry.passages.map((p) => p.evidence_key), entry.older.length]),
    [["x", ["y"], 0]]);
});

test("the passages of one page are one hit at the best passage's rank, with its family and numbers", () => {
  const hits = [
    hit("a1", "Onboarding of new customers"),
    hit("b1", "Acme Orders Service Catalog 2022/2023"),
    hit("c1", "Release process"),
    { ...hit("a2", "Onboarding of new customers"), source_id: "s-a1" },
    { ...hit("b2", "Acme Orders Service Catalog 2022/2023"), source_id: "s-b1" },
    hit("d1", "Acme Orders Service Catalog 2021 (deprecated)"),
    { ...hit("d2", "Acme Orders Service Catalog 2021 (deprecated)"), source_id: "s-d1" },
    { ...hit("u1", "Link only"), source_id: null, origin: { kind: "confluence", url: "https://wiki/p/1" } },
    { ...hit("u2", "Link only"), source_id: null, origin: { kind: "confluence", url: "https://wiki/p/1" } },
    { ...hit("o1", "Other workspace copy"), source_id: "s-a1", workspace: "Team B" },
  ];
  const shown = presentHits(hits);
  assert.deepEqual(shown.map((entry) => [entry.number, entry.hit.evidence_key, entry.passages.map((p) => p.evidence_key),
    entry.older.map((p) => p.evidence_key), entry.hidden.map((p) => p.evidence_key)]), [
    [1, "a1", ["a2"], [], []],
    [2, "b1", ["b2"], ["d1"], ["d2"]],
    [3, "c1", [], [], []],
    [4, "u1", ["u2"], [], []],
    [5, "o1", [], [], []],
  ], "same source or link is one page; a further passage of an older version stays with it; another Workspace is another page");
  const numbers = hitNumbers(shown);
  assert.deepEqual(["a2", "b2", "d1", "d2", "u2"].map((key) => numbers.get(key)), [1, 2, 2, 2, 4],
    "a citation of a folded passage leads to the hit it sits under");
  assert.deepEqual(presentedEvidence(shown).map((entry) => entry.evidence_key).slice(0, 5), ["a1", "b1", "c1", "u1", "o1"],
    "the answer reads each page's best passage first");
  assert.equal(pageKey({ ...hit("n", "No id"), source_id: null, source_url: null, origin: null }), null);
});

test("The date is labelled; the source's own change date wins over the date it was received", () => {
  assert.deepEqual(hitDate({ changed_at: "2026-10-07T10:00:00" }), { value: "2026-10-07T10:00:00", label: "received" });
  assert.deepEqual(hitDate({ changed_at: "2026-10-07T10:00:00+00:00", origin: { kind: "confluence", source_changed_at: "2024-03-12T08:00:00+00:00" } }),
    { value: "2024-03-12T08:00:00+00:00", label: "changed" }, "the backend sends it inside origin");
  assert.deepEqual(hitDate({ changed_at: "2026-10-07T10:00:00+00:00", origin: { kind: "upload", source_changed_at: null } }),
    { value: "2026-10-07T10:00:00+00:00", label: "received" }, "null keeps received");
  assert.deepEqual(hitDate({ changed_at: "2026-10-07T10:00:00", source_changed_at: "2024-03-12T08:00:00" }),
    { value: "2024-03-12T08:00:00", label: "changed" });
  assert.equal(hitDate({}), null);
  const now = Date.parse("2026-10-08T00:00:00Z");
  const old = { ...hit("o", "Old"), changed_at: "2026-10-07T00:00:00Z", source_changed_at: "2024-03-12T00:00:00Z" };
  assert.deepEqual(applyFacets([old], { ...NO_FACETS, within: "30d" }, now), [], "the time filter reads the change date");
});

test("The excerpt starts where the question's words are, under their heading, and marks them", () => {
  assert.deepEqual(queryTerms("How do I rotate the database credentials?"), ["rotate", "database", "credentials"]);
  const passage = [
    "## Onboarding of new customers", "", "Deliveries are planned per quarter. ".repeat(6), "",
    "## Operations", "", "Rotate the database credentials every 90 days with the vault job.", "", "More text. ".repeat(20),
  ].join("\n");
  const excerpt = excerptFor(passage, queryTerms("rotate database credentials"));
  assert.match(excerpt, /^…\n## Operations\n\nRotate the database credentials/);
  assert.ok(excerpt.length <= 300);
  // Without a match: the body after the headings, not the headings alone.
  assert.match(excerptFor(passage, ["nothing"]), /^## Onboarding of new customers\n\nDeliveries/);
  assert.equal(excerptFor("Short.", ["x"]), "Short.");
  assert.ok(isHeadingOnly("## A\n\n### B") && !isHeadingOnly("## A\nText"));
  assert.deepEqual(markTerms("Rotate the database", ["database", "rotate"]),
    [{ text: "Rotate", marked: true }, { text: " the ", marked: false }, { text: "database", marked: true }]);
});

test("Passage numbers the model wrote into a sentence leave the text; citations stay in cites", () => {
  assert.equal(plainSentence("PostgreSQL 16 is required [1][2]."), "PostgreSQL 16 is required.");
  assert.equal(plainSentence("See [1, 3] for details."), "See for details.");
  const answer = readKnowledgeAnswer({ state: "ok", sentences: [{ text: "It is 16 [1].", cites: ["k1"] }] });
  assert.equal(answer.sentences[0].text, "It is 16.");
});

test("The timings read the route's nested form, and the embedding and the index query are named apart", () => {
  assert.equal(
    searchTimingText({ total: 15399, index: "postgres", stages: { lexical: 1738, embed: 9063, vector_query: 2990, vector: 12055, rerank: 700 } }),
    "Found in 15 s (keywords 1.7 s · reading the question 9.1 s · meaning 3.0 s · ranking 0.7 s)",
  );
  assert.equal(searchTimingSummary({ total: 3443, stages: { lexical: 2462 } }), "Found in 3.4 s", "the page shows only the total");
  assert.equal(searchTimingSummary(null), "");
  assert.equal(searchTimingText({ total: 3200, lexical: 200, vector: 800, rerank: 2100 }),
    "Found in 3.2 s (keywords 0.2 s · meaning 0.8 s · ranking 2.1 s)");
});

function probe(options) {
  const pending = [];
  let current;
  const search = (workspace, body) => new Promise((resolve, reject) => { pending.push({ body, resolve, reject }); });
  function Probe() { current = useKnowledgeSearch("w1", search, options); return null; }
  let renderer;
  act(() => { renderer = TestRenderer.create(createElement(Probe)); });
  return {
    pending,
    get current() { return current; },
    submit(body) { act(() => { void current.submit(body); }); },
    async settle(index, value, failed = false) {
      await act(async () => { if (failed) pending[index].reject(new Error(value)); else pending[index].resolve(value); });
    },
    close() { act(() => renderer.unmount()); },
  };
}

// One search is one request: no second, lexical-only POST …/search in parallel.
test("a hybrid search sends one request; its result or its error is shown", async () => {
  const view = probe();
  try {
    view.submit({ query_text: " rotate credentials ", mode: "hybrid" });
    await act(async () => { await Promise.resolve(); });
    assert.equal(view.pending.length, 1, "one POST …/search per submit");
    assert.deepEqual(view.pending[0].body, { query_text: "rotate credentials", mode: "hybrid" });
    assert.equal(view.current.busy, true);
    await view.settle(0, { evidence: [{ evidence_key: "k" }, { evidence_key: "v" }] });
    assert.equal(view.current.busy, false);
    assert.equal(view.current.result.evidence.length, 2);

    view.submit({ query_text: "second", mode: "hybrid" });
    await act(async () => { await Promise.resolve(); });
    assert.equal(view.pending.length, 2);
    await view.settle(1, "Storage unavailable", true);
    assert.equal(view.current.error, "Storage unavailable");
    assert.equal(view.current.result, null);
  } finally { view.close(); }
});

test("A late answer of an earlier query never replaces the current one", async () => {
  const view = probe();
  try {
    view.submit({ query_text: "x", mode: "hybrid" });
    view.submit({ query_text: "y", mode: "lexical" });
    await act(async () => { await Promise.resolve(); });
    assert.equal(view.pending.length, 2);
    await view.settle(1, { evidence: [{ evidence_key: "y" }] });
    await view.settle(0, { evidence: [{ evidence_key: "late" }] });
    assert.equal(view.current.query, "y");
    assert.deepEqual(view.current.result, { evidence: [{ evidence_key: "y" }] });
  } finally { view.close(); }
});

function loadPanel(fetch) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true, target: ts.ScriptTarget.ES2020 },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl,
      encodeURIComponent, FormData, fetch, setTimeout, clearTimeout,
      window: { location: { origin: "http://localhost", search: "", href: "http://localhost/chat" }, setTimeout: () => 0 },
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
  return loadFile(path.join(SRC, "admin/components/workspaceKnowledge/KnowledgeSearchPanel.tsx"));
}

test("rendered Search page: one POST …/search per submit, and the answer is asked as soon as it is in", async () => {
  const calls = [];
  let releaseSearch;
  const searchDone = new Promise((resolve) => { releaseSearch = resolve; });
  const reply = (body) => ({ ok: true, status: 200, statusText: "OK", json: async () => body });
  const fetch = async (url, init = {}) => {
    const call = `${init.method || "GET"} ${String(url).replace("/api/v1/workspaces/w1/knowledge", "")}`;
    calls.push(call);
    if (call === "POST /search") {
      await searchDone;
      return reply({ evidence: [hit("a", "Doc a"), hit("b", "Doc b")], mode_states: { lexical: "ok", vector: "ok" } });
    }
    if (call === "POST /answer") return reply({ state: "ok", text: "Answer.", cites: ["a"] });
    return reply({});
  };
  const { KnowledgeSearchPanel } = loadPanel(fetch);
  const tick = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(KnowledgeSearchPanel, { workspaceId: "w1", showOverview: false })); });
  await tick();
  try {
    act(() => view.root.findByProps({ type: "text" }).props.onChange({ target: { value: "rotate credentials" } }));
    await act(async () => { view.root.findByType("form").props.onSubmit({ preventDefault() {} }); });
    await tick();
    assert.deepEqual(calls.filter((call) => call.startsWith("POST")), ["POST /search"], "one search, the answer waits for it");
    releaseSearch();
    await tick();
    await tick();
    assert.deepEqual(calls.filter((call) => call.startsWith("POST")), ["POST /search", "POST /answer"]);
  } finally { act(() => view.unmount()); }
});

test("A term marked inside a word adds no space to it", () => {
  const css = fs.readFileSync(path.resolve(path.dirname(fileURLToPath(import.meta.url)),
    "../../src/admin/components/workspaceKnowledge/knowledge-search.css"), "utf8");
  const rule = css.match(/^\.knowledge-search__term \{[^}]*\}/m);
  assert.ok(rule);
  assert.match(rule[0], /padding: 0;/);
  assert.doesNotMatch(rule[0], /margin|letter-spacing/);
});
