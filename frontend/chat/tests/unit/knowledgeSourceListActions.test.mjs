// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgeSourceListActions.test.mjs
//
// Knowledge → Documents: title-first rows with an always-visible "View revisions", "Enable
// Knowledge" on a listing error, and "Remove document…" in the drawer for authors only, with an inline
// confirm. Every API call is a stub; nothing is removed or enabled for real.
import assert from "node:assert/strict";
import { test } from "node:test";
import { registerHooks } from "node:module";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { transpileModule, ModuleKind, JsxEmit } from "typescript";
import { workspaceKnowledgeApi } from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeApi.ts";

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
const { KnowledgeSourceInventory } = await import("../../src/chat/knowledge/KnowledgeSourceInventory.tsx");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;

const SOURCE = { source_id: "src-1", source_key: "spring-boot-4-0-configuration-changelog-3",
  display_title: "Spring Boot 4.0 Configuration Changelog", revision_count: 3, latest_revision_ordinal: 3 };
const DETAIL = { source_id: "src-1", display_title: SOURCE.display_title, revisions: [
  { revision_id: "r3", revision_ordinal: 3, media_type: "application/pdf", byte_size: 2048, span_count: 4, state: "projected", content_sha256: "x" },
] };

const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));
const buttons = (view, label) => view.root.findAll((node) => node.type === "button" && text(node) === label);

async function mount({ mayAuthor = true, listing = () => Promise.resolve({ sources: [SOURCE], projection_backlog: {}, next_cursor: null }), api = {} } = {}) {
  const original = { ...workspaceKnowledgeApi };
  const calls = { pages: 0, removed: [], enabled: [] };
  workspaceKnowledgeApi.sourcePage = (...args) => { calls.pages++; return listing(calls.pages, ...args); };
  workspaceKnowledgeApi.sourceDetail = () => Promise.resolve(DETAIL);
  workspaceKnowledgeApi.removeSource = (workspace, sourceId) => { calls.removed.push([workspace, sourceId]); return api.remove ? api.remove() : Promise.resolve({}); };
  workspaceKnowledgeApi.enable = (workspace) => { calls.enabled.push(workspace); return Promise.resolve({}); };
  let view;
  await act(async () => { view = TestRenderer.create(createElement(KnowledgeSourceInventory, { workspaceId: "ws-1", mayAuthor })); });
  await flush();
  return { view, calls, restore: () => { act(() => view.unmount()); Object.assign(workspaceKnowledgeApi, original); } };
}

const openDrawer = async (view) => {
  await act(async () => view.root.find((node) => node.type === "tr" && node.props["data-row-key"]).props.onClick());
  await flush();
  return view.root.find((node) => node.props.role === "dialog");
};

test("rows are title first: bold title, muted origin with the key in its title, one Revisions cell; the row opens", async () => {
  const { view, restore } = await mount();
  try {
    const rows = view.root.findAllByType("tr").slice(1);
    assert.equal(rows.length, 1);
    assert.equal(text(rows[0].findByType("strong")), SOURCE.display_title);
    // The second line says where it comes from; the internal key is only its tooltip.
    const key = rows[0].findByProps({ className: "knowledge-sources__key" });
    assert.equal(key.props.title, SOURCE.source_key);
    assert.equal(text(key), "Uploaded");
    const revisions = rows[0].findByProps({ "data-label": "Revisions" });
    assert.equal(text(revisions), "3 revisions · latest #3");
    assert.ok(rows[0].props.onClick, "the whole row opens the document");
    const headers = view.root.findAllByType("th").map(text);
    assert.deepEqual(headers, ["Title", "Revisions"]);
    const filter = view.root.findByProps({ role: "search" });
    const input = filter.findByType("input");
    assert.equal(filter.findByType("label").props.htmlFor, input.props.id);
    assert.equal(input.props.maxLength, 200);
  } finally { restore(); }
});

test("a failing listing offers Enable Knowledge, which enables and reloads", async () => {
  const listing = (page) => (page === 1 ? Promise.reject(new Error("Knowledge is not enabled for this workspace."))
    : Promise.resolve({ sources: [SOURCE], projection_backlog: {}, next_cursor: null }));
  const { view, calls, restore } = await mount({ listing });
  try {
    assert.match(text(view.root.find((node) => node.props.role === "alert")), /not enabled/);
    const enable = buttons(view, "Enable Knowledge for this workspace");
    assert.equal(enable.length, 1);
    await act(async () => enable[0].props.onClick());
    await flush();
    assert.deepEqual(calls.enabled, ["ws-1"]);
    assert.equal(calls.pages, 2);
    assert.equal(view.root.findAll((node) => node.props.role === "alert").length, 0);
    assert.equal(view.root.findAllByType("tr").length, 2);
  } finally { restore(); }
});

test("readers see no Remove in the document drawer", async () => {
  const { view, restore } = await mount({ mayAuthor: false });
  try {
    const dialog = await openDrawer(view);
    assert.equal(dialog.findAll((node) => node.type === "button" && text(node).startsWith("Remove")).length, 0);
  } finally { restore(); }
});

test("authors confirm inline with the truthful consequences; Cancel keeps everything", async () => {
  const { view, calls, restore } = await mount();
  try {
    let dialog = await openDrawer(view);
    await act(async () => buttons(view, "Remove document…")[0].props.onClick());
    const confirm = view.root.find((node) => node.props.role === "group");
    assert.equal(text(confirm.findByProps({ className: "knowledge-sources__confirm-question" })), `Remove “${SOURCE.display_title}”?`);
    assert.deepEqual(confirm.findAllByType("li").map(text), [
      "The document leaves this workspace's searchable knowledge.",
      "Its history stays in the evidence ledger.",
      "Uploading the same file again brings it back.",
    ]);
    await act(async () => buttons(view, "Cancel")[0].props.onClick());
    dialog = view.root.find((node) => node.props.role === "dialog");
    assert.ok(dialog);
    assert.equal(buttons(view, "Remove document…").length, 1);
    assert.deepEqual(calls.removed, []);
  } finally { restore(); }
});

test("a confirmed removal shows busy, closes the drawer and reloads the list", async () => {
  let finish;
  const { view, calls, restore } = await mount({ api: { remove: () => new Promise((resolve) => { finish = resolve; }) } });
  try {
    await openDrawer(view);
    await act(async () => buttons(view, "Remove document…")[0].props.onClick());
    await act(async () => buttons(view, "Remove document")[0].props.onClick());
    assert.deepEqual(calls.removed, [["ws-1", "src-1"]]);
    assert.equal(buttons(view, "Removing…")[0].props.disabled, true);
    assert.equal(buttons(view, "Cancel")[0].props.disabled, true);
    await act(async () => finish({ projection: "retiring" }));
    await flush();
    assert.equal(view.root.findAll((node) => node.props.role === "dialog").length, 0);
    assert.equal(calls.pages, 2);
    assert.ok(view.root.findAll((node) => node.props.role === "status").some((node) => /was removed from this workspace/.test(text(node))));
  } finally { restore(); }
});

test("a refused removal (403) is shown inline and the drawer stays open", async () => {
  const { view, calls, restore } = await mount({ api: { remove: () => Promise.reject(new Error("Workspace author role required.")) } });
  try {
    await openDrawer(view);
    await act(async () => buttons(view, "Remove document…")[0].props.onClick());
    await act(async () => buttons(view, "Remove document")[0].props.onClick());
    await flush();
    const dialog = view.root.find((node) => node.props.role === "dialog");
    assert.equal(text(dialog.find((node) => node.props.role === "alert")), "Workspace author role required.");
    assert.equal(buttons(view, "Remove document")[0].props.disabled, false);
    assert.equal(calls.pages, 1);
  } finally { restore(); }
});

test("narrow lists stack each document instead of scrolling", () => {
  const css = readFileSync(new URL("../../src/chat/knowledge/knowledge-contribution.css", import.meta.url), "utf8");
  assert.match(css, /\.knowledge-sources__list \{ container:knowledge-sources \/ inline-size;/);
  assert.match(css, /@container knowledge-sources \(max-width: 40rem\)/);
  assert.match(css, /\.knowledge-sources__table \{ table-layout:fixed; \}/);
  assert.doesNotMatch(css.replace(/\/\*[\s\S]*?\*\//g, ""), /#[0-9a-fA-F]{3,8}\b|rgba?\(/, "tokens only");
});
