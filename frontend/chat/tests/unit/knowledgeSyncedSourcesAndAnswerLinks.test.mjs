// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgeSyncedSourcesAndAnswerLinks.test.mjs
//
// Frontend corrections L5 and L6. Documents: a synced source (origin type "connector") links to its page
// at the source, says when it was removed at the source, and never offers "upload again"; an upload and an older
// server without `origin` stay. Chat: links in the answer text open in a new tab like the Sources
// drawer; an intermediate tool step followed by the turn's answer shows no "Sources · none cited" chip. Every API
// call is a stub.
import assert from "node:assert/strict";
import { test } from "node:test";
import { registerHooks } from "node:module";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { transpileModule, ModuleKind, JsxEmit } from "typescript";
import { workspaceKnowledgeApi } from "../../src/admin/components/workspaceKnowledge/workspaceKnowledgeApi.ts";
import {
  removalConsequences,
  removedSourceNote,
  safeSourceUrl,
  syncedOriginOf,
} from "../../src/chat/knowledge/syncedSourceModel.ts";
import { intermediateToolMessageIds } from "../../src/chat/evidence/intermediateToolMessages.ts";

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
const { MarkdownRenderer } = await import("../../src/chat/MarkdownRenderer.tsx");
const { AnswerSourcesButton } = await import("../../src/chat/evidence/AnswerSourcesButton.tsx");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;

const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));
const allText = (view) => text(view.root);

const PAGE = "https://acme.atlassian.net/wiki/spaces/DEMO/pages/100003/Freshness+Probe";
const synced = (overrides = {}) => ({ type: "connector", connector_kind: "confluence", connector_key: "demo", url: PAGE, removed_at_source: false, ...overrides });
const SOURCE = { source_id: "src-1", source_key: "confluence.demo.100003", display_title: "Freshness Probe",
  revision_count: 2, latest_revision_ordinal: 2 };
const tombstoned = (origin) => ({ source_id: "src-1", display_title: "Freshness Probe", ...(origin ? { origin } : {}), revisions: [
  { revision_id: "r2", revision_ordinal: 2, media_type: "text/html", byte_size: 2048, span_count: 4, state: "tombstoned", content_sha256: "x" },
] });

// ---- L5 model ------------------------------------------------------------------------------------

test("Only an explicit connector origin is synced; its link must be http(s)", () => {
  assert.equal(syncedOriginOf(SOURCE), null, "no origin: shown as an upload, never guessed from the source key");
  assert.equal(syncedOriginOf({ origin: { type: "upload" } }), null);
  assert.deepEqual(syncedOriginOf({ origin: synced() }), { sourceName: "Confluence", noun: "page", url: PAGE, removedAtSource: false });
  assert.equal(syncedOriginOf({ origin: synced({ removed_at_source: "yes" }) }).removedAtSource, false, "only true is true");
  for (const url of ["javascript:alert(1)", "data:text/html,x", "/wiki/x", "ftp://host/x", 42, null]) {
    assert.equal(safeSourceUrl(url), null, String(url));
    assert.equal(syncedOriginOf({ origin: synced({ url }) }).url, null);
  }
  assert.match(removedSourceNote(null), /Uploading the same file again brings it back\./);
  assert.equal(removedSourceNote(syncedOriginOf({ origin: synced({ removed_at_source: true }) })),
    "This page was deleted or moved out of the synced scope in Confluence, so it was removed from search.");
  assert.doesNotMatch(removedSourceNote(syncedOriginOf({ origin: synced() })), /Upload/);
  assert.ok(removalConsequences(null).some((line) => line.startsWith("Uploading")));
  assert.ok(!removalConsequences(syncedOriginOf({ origin: synced() })).some((line) => line.startsWith("Uploading")));
});

// ---- L5 rendered ---------------------------------------------------------------------------------

async function mountDocuments({ source, detail }) {
  const original = { ...workspaceKnowledgeApi };
  workspaceKnowledgeApi.sourcePage = () => Promise.resolve({ sources: [source], projection_backlog: {}, next_cursor: null });
  workspaceKnowledgeApi.sourceDetail = () => Promise.resolve(detail);
  let view;
  await act(async () => { view = TestRenderer.create(createElement(KnowledgeSourceInventory, { workspaceId: "ws-1", mayAuthor: true })); });
  await flush();
  return { view, restore: () => { act(() => view.unmount()); Object.assign(workspaceKnowledgeApi, original); } };
}

const openDrawer = async (view) => {
  await act(async () => view.root.find((node) => node.type === "tr" && node.props["data-row-key"]).props.onClick());
  await flush();
  return view.root.find((node) => node.props.role === "dialog");
};

test("rendered L5: a synced row opens here, offers Open in Confluence only in its menu, says removed at source", async () => {
  const origin = synced({ removed_at_source: true });
  const { view, restore } = await mountDocuments({ source: { ...SOURCE, origin }, detail: tombstoned(origin) });
  try {
    const title = view.root.findByType("strong");
    assert.equal(title.findAll((node) => node.type === "a").length, 0, "the title never leaves the app");
    assert.equal(text(title), "Freshness Probe");
    assert.equal(view.root.findAll((node) => node.type === "button" && node.props["aria-label"] === "More actions for Freshness Probe").length, 1,
      "the source page is an explicit action in the row menu");
    assert.equal(view.root.findAll((node) => node.props["data-testid"] === "source-removed-at-source").length, 1);
    const drawer = await openDrawer(view);
    assert.equal(text(drawer.find((node) => node.props["data-testid"] === "source-drawer-removed")),
      "This page was deleted or moved out of the synced scope in Confluence, so it was removed from search.");
    assert.equal(drawer.find((node) => node.props["data-testid"] === "source-drawer-origin-link").props.href, PAGE);
    assert.doesNotMatch(allText(view), /Upload|uploaded/);
  } finally { restore(); }
});

test("rendered L5: an upload (or a source without origin) keeps its title text and the upload-again note", async () => {
  const { view, restore } = await mountDocuments({ source: SOURCE, detail: tombstoned(null) });
  try {
    assert.equal(view.root.findByType("strong").findAll((node) => node.type === "a").length, 0);
    assert.equal(view.root.findAll((node) => node.props["data-testid"] === "source-removed-at-source").length, 0);
    const drawer = await openDrawer(view);
    assert.equal(text(drawer.find((node) => node.props["data-testid"] === "source-drawer-removed")),
      "This document was removed from search. Uploading the same file again brings it back.");
  } finally { restore(); }
});

// ---- L6 ------------------------------------------------------------------------------------------

test("Answer-text links open in a new tab; an in-page anchor stays", async () => {
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(MarkdownRenderer, { theme: "light",
      content: `See [Freshness Probe](${PAGE}) and [below](#notes).` }));
  });
  const links = view.root.findAllByType("a");
  assert.deepEqual(links.map((link) => [link.props.href, link.props.target ?? null, link.props.rel ?? null]), [
    [PAGE, "_blank", "noopener noreferrer"],
    ["#notes", null, null],
  ]);
  act(() => view.unmount());
});

test("A tool step followed by the turn's answer is intermediate; the answer and a lone tool answer are not", () => {
  const message = (id, role, tools = 0) => ({ kind: "message", message: { id, role, toolEvents: Array.from({ length: tools }, () => ({})) } });
  const ids = intermediateToolMessageIds([
    message("u1", "user"),
    message("a1", "assistant", 1), // "I am now gathering the missing evidence…"
    { kind: "approval" },
    message("a2", "assistant"), // the answer
    message("u2", "user"),
    message("a3", "assistant", 2), // tools and the answer in one message
    message("u3", "user"),
    message("a4", "assistant"), // no tools, followed by another message
    message("a5", "assistant", 1),
  ]);
  assert.deepEqual([...ids], ["a1"]);
});

test("rendered L6: the quiet chip hides 'none cited' on a tool step, the answer keeps it", async () => {
  globalThis.window = { location: { origin: "http://localhost" } };
  const render = async (props) => {
    let view;
    await act(async () => { view = TestRenderer.create(createElement(AnswerSourcesButton, { contentKey: "x", ...props })); });
    const buttonLabels = view.root.findAll((node) => node.type === "button" && /^Sources/.test(text(node))).map(text);
    const quiet = view.root.findAll((node) => node.props["data-testid"] === "answer-sources-quiet").length;
    act(() => view.unmount());
    return { buttonLabels, quiet };
  };
  assert.deepEqual(await render({}), { buttonLabels: ["Sources · none cited"], quiet: 0 });
  assert.deepEqual(await render({ quietWhenNone: true }), { buttonLabels: [], quiet: 1 });
});
