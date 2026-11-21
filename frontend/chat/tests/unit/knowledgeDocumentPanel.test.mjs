// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgeDocumentPanel.test.mjs
//
// Knowledge › Documents (inventory "Original im Fenster anzeigen … Diff nebeneinander"): a document opens in the side
// panel with View | Revisions | Diff. The original is shown in place (HTML in a sandboxed frame, text as text, PDF
// inline), refusals read as one sentence, two revisions compare side by side. Every request is a stub.
import assert from "node:assert/strict";
import { test } from "node:test";
import { registerHooks } from "node:module";
import { readFileSync } from "node:fs";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { transpileModule, ModuleKind, JsxEmit } from "typescript";
import {
  diffStatsText, documentHref, isMarkdown, originalErrorText, requestedDocument, sideBySide, stripActiveContent, viewDocument,
} from "../../src/chat/knowledge/document/documentViewModel.ts";

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
const { KnowledgeDocumentPanel } = await import("../../src/chat/knowledge/document/KnowledgeDocumentPanel.tsx");
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const { act } = TestRenderer;

const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id && typeof node.type === "string");
const flush = () => act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });

const revision = (ordinal, media = "text/html", state = "projected") => ({
  revision_id: `r${ordinal}`, revision_ordinal: ordinal, media_type: media, byte_size: 2048, span_count: 3, state, content_sha256: "x",
});
const detail = (revisions) => ({ source_id: "src-1", display_title: "Onboarding guide", revisions });

function stubFetch(routes) {
  const calls = [];
  const original = globalThis.fetch;
  globalThis.fetch = async (url) => {
    calls.push(String(url));
    const route = routes.find(([match]) => String(url).includes(match));
    const [status, body] = route ? route[1] : [404, { detail: "Not Found" }];
    return { ok: status >= 200 && status < 300, status, json: async () => body };
  };
  return { calls, restore: () => { globalThis.fetch = original; } };
}

async function mount(props) {
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(KnowledgeDocumentPanel, {
      workspaceId: "ws-1", sourceId: "src-1", title: "Onboarding guide", error: null, mayAuthor: false,
      pageHref: "?area=knowledge&document=src-1&document_view=page", backHref: "?area=knowledge",
      onRemoved: () => {}, onClose: () => {}, ...props,
    }));
  });
  await flush();
  return view;
}
const selectTab = async (view, key) => {
  await act(async () => view.root.find((node) => node.props.role === "tab" && node.props.id?.endsWith(`-tab-${key}`)).props.onClick());
  await flush();
};

test("active content never reaches the frame: scripts, frames, handlers and script URLs are stripped", () => {
  const html = '<p onclick="steal()">Hi<script>alert(1)</script></p><iframe src="x"></iframe><a href="javascript:alert(1)">x</a>'
    + '<img src="data:text/html,evil" onerror="x()"><style>body{}</style><a href="https://ok.example">ok</a>';
  const clean = stripActiveContent(html);
  assert.doesNotMatch(clean, /script|iframe|onclick|onerror|javascript:|data:|<style/i);
  assert.match(clean, /<p>Hi<\/p>/);
  assert.match(clean, /href="https:\/\/ok\.example"/);
  assert.match(viewDocument("<b>x</b>"), /^<!doctype html>.*<body><b>x<\/b><\/body><\/html>$/s);
});

test("a unified diff becomes side-by-side rows with line numbers; stats read +n −m", () => {
  const rows = sideBySide("--- a\n+++ b\n@@ -1,3 +1,3 @@\n keep\n-old line\n+new line\n+extra\n tail");
  assert.equal(rows[0].hunk, "@@ -1,3 +1,3 @@");
  assert.deepEqual(rows[1], { left: { line: 1, text: "keep", kind: "same" }, right: { line: 1, text: "keep", kind: "same" } });
  assert.deepEqual(rows[2], { left: { line: 2, text: "old line", kind: "removed" }, right: { line: 2, text: "new line", kind: "added" } });
  assert.deepEqual(rows[3], { left: null, right: { line: 3, text: "extra", kind: "added" } });
  assert.deepEqual(rows[4], { left: { line: 3, text: "tail", kind: "same" }, right: { line: 4, text: "tail", kind: "same" } });
  assert.equal(diffStatsText({ added_lines: 12, removed_lines: 3 }), "+12 −3");
});

test("every coded refusal reads as one plain sentence; the address carries the open document", () => {
  for (const code of ["workspace_not_found", "revision_not_found", "original_not_stored", "original_object_missing",
    "original_location_mismatch", "original_not_displayable"]) {
    assert.match(originalErrorText(code), /^[A-Z].*\.$/, code);
  }
  assert.equal(originalErrorText("unknown_code"), "The original could not be loaded.");
  assert.equal(documentHref("?area=knowledge&tab=knowledgeSources", "src 1", true),
    "?area=knowledge&tab=knowledgeSources&document=src+1&document_view=page");
  assert.equal(documentHref("?area=knowledge&document=a&document_view=page", null), "?area=knowledge");
  assert.deepEqual(requestedDocument("?document=src-1&document_view=page"), { sourceId: "src-1", page: true });
  assert.deepEqual(requestedDocument("?area=knowledge"), { sourceId: null, page: false });
});

test("rendered View: the newest revision's HTML sits in a sandboxed frame without scripts; Open as page is offered", async () => {
  const fetch = stubFetch([["/revisions/r2/view", [200, { revision_id: "r2", content_type: "text/html", state: "ok",
    html: "<h1>Welcome</h1><script>x()</script>", text: "Welcome", source_changed_at: "2024-03-12T08:00:00+00:00" }]]]);
  try {
    const view = await mount({ detail: detail([revision(1), revision(2)]) });
    assert.ok(fetch.calls.some((url) => url === "/api/v1/workspaces/ws-1/knowledge/sources/src-1/revisions/r2/view"));
    const frame = byTestId(view, "document-view-html")[0];
    assert.equal(frame.type, "iframe");
    assert.equal(frame.props.sandbox, "", "no scripts, no same origin");
    assert.match(frame.props.srcDoc, /<h1>Welcome<\/h1>/);
    assert.doesNotMatch(frame.props.srcDoc, /<script/);
    assert.match(text(byTestId(view, "document-view-meta")[0]), /^Revision 2 · changed /);
    assert.equal(byTestId(view, "knowledge-document-open-page")[0].props.href, "?area=knowledge&document=src-1&document_view=page");
    assert.deepEqual(view.root.findAll((node) => node.props.role === "tab").map(text), ["View", "Revisions2", "Diff"]);
  } finally { fetch.restore(); }
});

test("rendered View: text as text, too large and refusals as one line with Download original, PDF inline", async () => {
  let fetch = stubFetch([["/view", [200, { revision_id: "r1", content_type: "text/plain", state: "ok", html: null, text: "line 1\nline 2" }]]]);
  try {
    const view = await mount({ detail: detail([revision(1, "text/plain")]) });
    assert.equal(text(byTestId(view, "document-view-text")[0]), "line 1\nline 2");
  } finally { fetch.restore(); }
  fetch = stubFetch([["/view", [200, { revision_id: "r1", content_type: "text/plain", state: "too_large", html: null, text: null }]]]);
  try {
    const view = await mount({ detail: detail([revision(1, "text/plain")]) });
    const line = byTestId(view, "document-view-too-large")[0];
    assert.match(text(line), /too large to show here/);
    assert.match(line.findByType("a").props.href, /\/revisions\/r1\/original$/);
  } finally { fetch.restore(); }
  fetch = stubFetch([["/view", [404, { detail: { code: "original_object_missing", detail: "…" } }]]]);
  try {
    const view = await mount({ detail: detail([revision(1, "text/plain")]) });
    assert.match(text(byTestId(view, "document-view-error")[0]), /^The original of this revision is missing in storage\./);
  } finally { fetch.restore(); }
  fetch = stubFetch([]);
  try {
    const view = await mount({ detail: detail([revision(1, "application/pdf")]) });
    const pdf = view.root.findByType("object");
    assert.equal(pdf.props.type, "application/pdf");
    assert.match(pdf.props.data, /\/revisions\/r1\/original$/);
    assert.equal(fetch.calls.length, 0, "a PDF is shown from its original, without the text view");
  } finally { fetch.restore(); }
});

test("rendered Revisions and Diff: a revision row opens it in View; two revisions compare side by side", async () => {
  const fetch = stubFetch([
    ["/revisions/r1/view", [200, { revision_id: "r1", content_type: "text/plain", state: "ok", html: null, text: "first" }]],
    ["/revisions/r2/view", [200, { revision_id: "r2", content_type: "text/plain", state: "ok", html: null, text: "second" }]],
    ["/diff?from_revision_id=r1&to_revision_id=r2", [200, { state: "ok", diff: "@@ -1 +1 @@\n-first\n+second",
      stats: { added_lines: 1, removed_lines: 1 }, from: { revision_id: "r1", revision_ordinal: 1 }, to: { revision_id: "r2", revision_ordinal: 2 } }]],
  ]);
  try {
    const view = await mount({ detail: detail([revision(1, "text/plain"), revision(2, "text/plain")]) });
    await selectTab(view, "revisions");
    const rows = byTestId(view, "document-revisions")[0].findAll((node) => node.type === "tr" && node.props["data-row-key"]);
    assert.deepEqual(rows.map((row) => row.props["data-row-key"]), ["r1", "r2"]);
    await act(async () => rows[0].props.onClick());
    await flush();
    assert.equal(text(byTestId(view, "document-view-text")[0]), "first");
    await selectTab(view, "diff");
    assert.equal(text(byTestId(view, "document-diff-stats")[0]), "+1 −1 lines");
    const cells = byTestId(view, "document-diff-table")[0].findAll((node) => node.type === "td" && node.props["data-kind"]);
    assert.deepEqual(cells.map((cell) => [cell.props["data-kind"], text(cell)]), [["removed", "Removed: first"], ["added", "Added: second"]]);
  } finally { fetch.restore(); }
});

test("rendered Diff: identical revisions say so; one revision has no Diff; page mode has no close and a way back", async () => {
  const fetch = stubFetch([["/diff", [200, { state: "identical", diff: "", stats: { added_lines: 0, removed_lines: 0 }, from: {}, to: {} }]],
    ["/view", [200, { revision_id: "r2", content_type: "text/plain", state: "ok", html: null, text: "same" }]]]);
  try {
    let view = await mount({ detail: detail([revision(1, "text/plain"), revision(2, "text/plain")]) });
    await selectTab(view, "diff");
    assert.match(text(byTestId(view, "document-diff-identical")[0]), /same text/);
    view = await mount({ detail: detail([revision(1, "text/plain")]) });
    assert.equal(view.root.find((node) => node.props.role === "tab" && node.props.id?.endsWith("-tab-diff")).props.disabled, true);
    view = await mount({ detail: detail([revision(1, "text/plain")]), mode: "page" });
    assert.equal(byTestId(view, "knowledge-document-close").length, 0);
    assert.equal(byTestId(view, "knowledge-document-open-page").length, 0);
    assert.ok(view.root.findAll((node) => node.type === "a" && text(node) === "← All documents" && node.props.href === "?area=knowledge").length);
  } finally { fetch.restore(); }
});

// A Markdown original (an uploaded .md, a synced page or record) showed as raw monospace text.
test("rendered View: a Markdown original is rendered, not shown as raw text", async () => {
  assert.equal(isMarkdown("text/markdown"), true);
  assert.equal(isMarkdown("text/markdown; charset=utf-8"), true);
  assert.equal(isMarkdown("text/plain"), false);
  const fetch = stubFetch([["/view", [200, { revision_id: "r1", content_type: "text/markdown", state: "ok", html: null,
    text: "# INC0000106: Memory WARN\n\n- Table: incident\n- State: In Progress" }]]]);
  try {
    const view = await mount({ detail: detail([revision(1, "text/markdown")]) });
    await flush();
    assert.equal(byTestId(view, "document-view-text").length, 0, "no raw text block");
    const shown = byTestId(view, "document-view-markdown");
    assert.equal(shown.length, 1);
    assert.equal(shown[0].findAllByType("h1").length, 1, "the heading is a heading");
    assert.equal(shown[0].findAllByType("li").length, 2, "the list is a list");
  } finally { fetch.restore(); }
});
