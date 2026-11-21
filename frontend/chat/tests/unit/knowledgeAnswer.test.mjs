// The short cited answer above the Knowledge Search hits. Pure answer handling plus the rendered
// answer through the transpile + vm harness (no browser; layout itself is unverified here).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as api from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeApi.ts";
import * as request from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeRequest.ts";
import * as presenter from "../../src/admin/components/workspaceKnowledge/knowledgeSearchPresenter.ts";
import * as searchFacets from "../../src/admin/components/workspaceKnowledge/search/searchFacets.ts";
import * as searchFamilies from "../../src/admin/components/workspaceKnowledge/search/searchFamilies.ts";
import * as snippet from "../../src/admin/components/workspaceKnowledge/search/snippet.ts";
import * as searchProgress from "../../src/admin/components/workspaceKnowledge/search/searchProgress.ts";
import * as askInChat from "../../src/admin/components/workspaceKnowledge/search/askInChat.ts";
import * as answerApi from "../../src/admin/components/workspaceKnowledge/search/answerApi.ts";
import * as dateTime from "../../src/admin/utils/dateTime.ts";
import * as SidePanel from "../../src/layout/SidePanel.ts";

const {
  ANSWER_PASSAGES, answerEvidenceKeys, answerMarkers, answerStateText, readKnowledgeAnswer,
} = answerApi;

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const src = fileURLToPath(new URL("../../src/", import.meta.url));

function load(file, modules) {
  const exports = {};
  const output = ts.transpileModule(fs.readFileSync(path.join(src, file), "utf8"),
    { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  vm.runInNewContext(output, { exports, require(name) {
    if (!name.startsWith(".")) return require(name);
    if (name.endsWith(".css")) return {};
    const base = path.basename(name);
    if (modules[base]) return modules[base];
    const target = path.join(path.dirname(file), `${name}.tsx`);
    if (fs.existsSync(path.join(src, target))) return load(target, modules);
    throw new Error(`unexpected import ${name} from ${file}`);
  } });
  return exports;
}

const text = (node) => node.children.map((child) => (typeof child === "string" ? child : text(child))).join("");
const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

test("the answer rests on at most ten top hits, in ranked order without repeats", () => {
  const hits = ["a", "b", "a", ...Array.from({ length: 12 }, (_, i) => `k${i}`)].map((evidence_key) => ({ evidence_key }));
  const keys = answerEvidenceKeys(hits);
  assert.equal(keys.length, ANSWER_PASSAGES);
  assert.deepEqual(keys.slice(0, 3), ["a", "b", "k0"]);
});

test("the server's answer is checked; an ok without a cited sentence is no answer", () => {
  assert.deepEqual(readKnowledgeAnswer({ state: "ok", sentences: [{ text: " Ships in March. ", cites: ["a", "b"] }] }),
    { state: "ok", sentences: [{ text: "Ships in March.", cites: ["a", "b"] }], cited_keys: ["a", "b"] });
  assert.equal(readKnowledgeAnswer({ state: "ok", sentences: [{ text: "Uncited.", cites: [] }] }).state, "no_answer");
  assert.equal(readKnowledgeAnswer({ state: "denied", sentences: [{ text: "x", cites: ["a"] }] }).sentences.length, 0);
  assert.equal(readKnowledgeAnswer({ state: "strange" }).state, "unavailable");
  assert.equal(readKnowledgeAnswer(null).state, "unavailable");
});

test("every state without an answer is one plain sentence", () => {
  assert.equal(answerStateText("no_answer"), "No answer from these passages.");
  for (const state of ["needs_configuration", "denied", "unavailable"]) {
    const sentence = answerStateText(state);
    assert.ok(sentence.endsWith("."), state);
    assert.equal(sentence.split(". ").length <= 2, true, state);
  }
  assert.equal(answerStateText("ok"), "");
});

test("markers carry the hit numbers on the page; a hit hidden by filters has none", () => {
  assert.deepEqual(answerMarkers(["b", "z"], new Map([["a", 1], ["b", 2]])), [{ key: "b", number: 2 }, { key: "z", number: null }]);
});

test("the answer progress names its stage", () => {
  assert.equal(searchProgress.answerProgressText(0), "Writing a short answer…");
  assert.equal(searchProgress.answerProgressText(3), "Writing a short answer · 3 s");
});

function renderAnswer(loadAnswer, extra = {}) {
  const { KnowledgeAnswer } = load("admin/components/workspaceKnowledge/search/KnowledgeAnswer.tsx", { answerApi, searchProgress });
  const opened = [];
  const asked = [];
  const props = { workspaceId: "w1", query: "When does 4.1 ship?", evidenceKeys: ["a", "b"],
    numberOf: new Map([["a", 1], ["b", 2]]), onOpen: (key) => opened.push(key), onAskInChat: () => asked.push(true),
    loadAnswer, ...extra };
  let view;
  act(() => { view = TestRenderer.create(createElement(KnowledgeAnswer, props)); });
  return { view, opened, asked };
}

test("while the answer is written the progress says so; then the sentence with markers that open the preview", async () => {
  const calls = [];
  let resolve;
  const { view, opened, asked } = renderAnswer((...args) => { calls.push(args); return new Promise((done) => { resolve = done; }); });
  await flush();
  assert.match(text(view.root.findByProps({ role: "status" })), /^Writing a short answer/);
  assert.equal(view.root.findAllByProps({ "data-testid": "answer-progress" }).length, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(calls)), [["w1", "When does 4.1 ship?", ["a", "b"]]]);
  await act(async () => { resolve({ state: "ok", sentences: [{ text: "4.1 ships in March.", cites: ["b", "a"] }], cited_keys: ["b", "a"] }); });
  const cites = view.root.findAllByProps({ "data-testid": "answer-cite" }).filter((node) => node.type === "button");
  assert.deepEqual(cites.map(text), ["[2]", "[1]"]);
  assert.equal(text(view.root.findByProps({ className: "knowledge-search__answer-text" })), "4.1 ships in March.[2][1]");
  act(() => cites[0].props.onClick());
  assert.deepEqual(opened, ["b"]);
  act(() => view.root.findByProps({ "data-testid": "ask-in-chat" }).props.onClick());
  assert.equal(asked.length, 1);
  act(() => view.unmount());
});

test("no answer, a denied model and a failed request each show one sentence and keep Ask in chat", async () => {
  const cases = [
    [async () => ({ state: "no_answer", sentences: [], cited_keys: [] }), "No answer from these passages."],
    [async () => ({ state: "denied", sentences: [], cited_keys: [] }), answerStateText("denied")],
    [async () => { throw new Error("boom"); }, answerStateText("unavailable")],
  ];
  for (const [loadAnswer, expected] of cases) {
    const { view } = renderAnswer(loadAnswer);
    await flush();
    assert.equal(text(view.root.findByProps({ "data-testid": "answer-state" })), expected);
    assert.equal(view.root.findAllByProps({ "data-testid": "answer-cite" }).length, 0);
    assert.equal(view.root.findAllByProps({ "data-testid": "ask-in-chat" }).filter((n) => n.type === "button").length, 1);
    act(() => view.unmount());
  }
});

test("without a question or hits nothing is asked", async () => {
  const calls = [];
  const { view } = renderAnswer(async (...args) => { calls.push(args); return { state: "ok", sentences: [], cited_keys: [] }; },
    { evidenceKeys: [] });
  await flush();
  assert.equal(calls.length, 0);
  assert.equal(view.root.findAllByProps({ "data-testid": "search-answer" }).length, 0);
  act(() => view.unmount());
});

const hit = (key, extra = {}) => ({ evidence_key: key, text: `Passage ${key}.`, citation: "", source_title: `Doc ${key}`,
  source_url: null, products: [], version: null, section: null, ...extra });

test("on the page the answer stands above the hits, asks with the top hits' keys and a marker opens that hit", async () => {
  const calls = [];
  const stubAnswerApi = { ...answerApi, requestKnowledgeAnswer: async (...args) => {
    calls.push(JSON.parse(JSON.stringify(args)));
    return { state: "ok", sentences: [{ text: "Doc b says so.", cites: ["b"] }], cited_keys: ["b"] };
  } };
  const modules = { workspaceKnowledgeApi: api, workspaceKnowledgeRequest: request, knowledgeSearchPresenter: presenter, searchFacets, searchFamilies, snippet, searchProgress,
    askInChat, answerApi: stubAnswerApi, dateTime, SidePanel };
  const { KnowledgeSearchResults } = load("admin/components/workspaceKnowledge/KnowledgeSearchResults.tsx", modules);
  const search = { busy: false, error: null, query: "Who says so?", result: { evidence: [hit("a"), hit("b")] } };
  let view;
  act(() => { view = TestRenderer.create(createElement(KnowledgeSearchResults, { workspaceId: "w1", search })); });
  await flush();
  assert.deepEqual(calls, [["w1", "Who says so?", ["a", "b"]]]);
  const results = view.root.findByProps({ className: "knowledge-search__results" });
  // The first thing in the results column is the answer, then the hit groups.
  assert.equal(results.children[0].findAllByProps({ "data-testid": "search-answer" }).length, 1);
  assert.equal(results.children[0].findAllByProps({ "data-testid": "search-groups" }).length, 0);
  const cite = view.root.findAllByProps({ "data-testid": "answer-cite" }).find((node) => node.type === "button");
  assert.equal(text(cite), "[2]");
  // The marker is a button named after its source.
  assert.equal(cite.props["aria-label"], "Source 2: Doc b");
  act(() => cite.props.onClick());
  const preview = view.root.findByProps({ "data-testid": "search-preview" });
  assert.equal(text(preview.findByType("h2")), "Doc b", "the cited hit opens in the side panel");
  // Ask in chat sits with the answer, once on the page.
  assert.equal(view.root.findAllByProps({ "data-testid": "ask-in-chat" }).filter((n) => n.type === "button").length, 1);
  act(() => view.unmount());
});
