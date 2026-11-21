// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workItemsPagedList.test.mjs
//
// Lean, paged Work Items list (backend fix/work-items-list-presence): the list pages through next_offset (an older
// server answers one page), the detail reads the item itself, and "Close item" says where it closes and what
// happened, with a plain sentence per refusal code.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import { loadWorkItems, loadWorkItemsPage } from "../../src/chat/work/workApi.ts";
import { mergeWorkItem } from "../../src/chat/work/useFullWorkItem.ts";
import {
  closeRefusalText, closeResultText, closeWhereText, isClosedItem,
} from "../../src/chat/work/workItemClose.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

const row = (index) => ({ id: `wi-${index}`, source_type: "jira", source_key: `BRD-${index}`, title: `Item ${index}`,
  work_state: "ready", sync_state: "synced" });

function serve(answer) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), method: init.method || "GET", body: init.body });
    const { status = 200, body } = answer(String(url), init);
    return { ok: status < 400, status, statusText: "", json: async () => body };
  };
  return calls;
}

test("the list pages through next_offset; an answer without next_offset ends after one request", async () => {
  const all = Array.from({ length: 450 }, (_, index) => row(index));
  const calls = serve((url) => {
    const params = new URL(url, "http://x").searchParams;
    const offset = Number(params.get("offset")); const limit = Number(params.get("limit"));
    const items = all.slice(offset, offset + limit);
    const next = offset + limit < all.length ? offset + limit : null;
    return { body: { items, total: all.length, limit, offset, next_offset: next } };
  });
  const items = await loadWorkItems(1000, "ws-1");
  assert.equal(items.length, 450);
  assert.equal(calls.length, 3);
  assert.match(calls[0].url, /limit=200&offset=0&project_id=ws-1$/);
  assert.match(calls[2].url, /offset=400/);

  const capped = await loadWorkItems(250, "ws-1");
  assert.equal(capped.length, 250, "never more than the limit");

  const old = serve(() => ({ body: { items: all.slice(0, 300) } }));
  assert.equal((await loadWorkItems(1000)).length, 300);
  assert.equal(old.length, 1);
  const page = await loadWorkItemsPage(0);
  assert.equal(page.nextOffset, null);
  assert.equal(page.total, null);
});

test("the detail overlays the list row with the item itself", () => {
  const listRow = row(1);
  const full = { ...row(1), description: "Steps", comments: [{ body: "hi" }], source_fields: { raw: { fields: {} } } };
  assert.equal(mergeWorkItem(listRow, null), listRow, "until the item arrives the row is the detail");
  assert.deepEqual(mergeWorkItem(listRow, full).comments, [{ body: "hi" }]);
  assert.equal(mergeWorkItem(null, full).description, "Steps", "an item not in the loaded pages still opens");
  assert.equal(mergeWorkItem(null, null), null);
});

test("close: the confirmation says where it closes; the result and each refusal read as one sentence", () => {
  const jira = { ...row(12), source_key: "BRD-12" };
  assert.equal(closeWhereText({ ...jira, write_back: { enabled: true } }), "Closes BRD-12 in Jira.");
  assert.equal(closeWhereText({ ...jira, write_back: { enabled: false } }), "Closes BRD-12 here only; Jira is not changed.");
  assert.match(closeWhereText(jira), /^Closes BRD-12 in Jira when write-back is set up for it; otherwise here only/);
  assert.equal(closeWhereText({ ...jira, close_mode: "source_transition" }), "Closes BRD-12 in Jira.");
  assert.equal(closeWhereText({ ...jira, close_mode: "local_only", write_back_reason: "not configured" }),
    "Closes BRD-12 here only; Jira is not changed.");
  assert.equal(closeWhereText({ ...jira, source_type: "servicenow", source_key: "INC1", write_back: { enabled: true } }),
    "Closes INC1 in ServiceNow.");
  assert.equal(closeResultText(jira, { closed: true, mode: "source_transition", jira: { resulting_status: "Done" } }),
    'BRD-12 closed in Jira (now "Done").');
  assert.equal(closeResultText(jira, { closed: true, mode: "local_only" }), "BRD-12 closed here; Jira was not changed.");
  assert.equal(closeResultText(jira, { closed: true, mode: "already_closed" }), "BRD-12 was already closed.");
  const refusal = (code) => closeRefusalText(Object.assign(new Error("raw"), { code }));
  assert.match(refusal("transition_not_available"), /offers no transition to a done status/);
  assert.match(refusal("scope_not_allowed"), /may not change this item's project/);
  assert.match(refusal("write_back_not_configured"), /Write-back to the source is not set up/);
  assert.match(refusal("write_back_failed"), /The source refused the change/);
  assert.equal(refusal("something_else"), "raw", "an unknown code keeps the server's sentence");
  assert.equal(isClosedItem({ work_state: "done" }), true);
  assert.equal(isClosedItem({ work_state: "ready" }), false);
});

function load(relative, extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, Number, Object, Math, Promise, Intl,
      encodeURIComponent, JSON, setTimeout, clearTimeout, fetch: (...args) => globalThis.fetch(...args), ...extra,
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

test("rendered: Close item posts the reason, shows the result and refreshes; a refusal stays in the dialog", async () => {
  const document = { addEventListener: () => {}, removeEventListener: () => {}, activeElement: null };
  const window = { location: { origin: "http://x" }, innerWidth: 1440, addEventListener: () => {}, removeEventListener: () => {} };
  const { WorkItemHeaderActions } = load("chat/work/WorkItemHeaderActions.tsx", { document, window });
  // Review: Close item is in the panel's "⋯" menu, not a button beside ✕.
  const closeItem = async () => {
    const more = view.root.find((node) => node.type === "button" && node.props["aria-label"] === "More actions for BRD-12");
    await act(async () => { more.props.onClick({ currentTarget: { getBoundingClientRect: () => ({ bottom: 40, right: 1400 }) } }); });
    await act(async () => { view.root.find((node) => node.props["data-testid"] === "work-item-close").props.onClick(); });
  };
  const item = { ...row(12), source_key: "BRD-12", source_url: "https://jira.example/browse/BRD-12" };
  let refusal = null;
  const calls = serve(() => (refusal
    ? { status: 409, body: { detail: { closed: false, mode: "source_transition", code: refusal, message: "raw" } } }
    : { body: { closed: true, mode: "local_only", item_id: "wi-12", source_key: "BRD-12" } }));
  let closed = 0;
  let view;
  await act(async () => { view = TestRenderer.create(createElement(WorkItemHeaderActions, { item, onClosed: () => { closed += 1; } })); });
  const link = view.root.find((node) => node.props["data-testid"] === "work-item-source-link");
  assert.equal(link.props.href, "https://jira.example/browse/BRD-12");
  assert.equal(text(link), "Open in Jira");
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "work-item-close").length, 0, "not on the header itself");
  await closeItem();
  assert.ok(text(view.root).includes("Closes BRD-12 in Jira when write-back is set up"));
  const field = view.root.find((node) => node.type === "textarea");
  await act(async () => { field.props.onChange({ target: { value: "Done in 4.2" } }); });
  const confirm = () => view.root.find((node) => node.type === "button" && text(node) === "Close BRD-12");
  await act(async () => { confirm().props.onClick(); });
  await act(async () => { await new Promise((resolve) => setImmediate(resolve)); });
  assert.equal(calls[0].method, "POST");
  assert.match(calls[0].url, /\/work-items\/wi-12\/close$/);
  assert.deepEqual(JSON.parse(calls[0].body), { reason: "Done in 4.2" });
  assert.equal(text(view.root.find((node) => node.props["data-testid"] === "work-item-close-result")),
    "BRD-12 closed here; Jira was not changed.");
  assert.equal(closed, 1);

  refusal = "write_back_not_configured";
  await closeItem();
  await act(async () => { confirm().props.onClick(); });
  await act(async () => { await new Promise((resolve) => setImmediate(resolve)); });
  assert.ok(text(view.root).includes("Write-back to the source is not set up, so it was not closed there."));
  assert.equal(closed, 1, "a refusal does not refresh");
  act(() => view.unmount());
});
