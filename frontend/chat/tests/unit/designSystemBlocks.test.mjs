// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/designSystemBlocks.test.mjs
//
// Design system (product inventory): the shared blocks render with their roles, navigate by keyboard,
// colour only exceptions, and the side panel closes by Escape, ✕ and the dimmed list, and returns the focus.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const HERE = path.dirname(new URL(import.meta.url).pathname);
const SRC = path.resolve(HERE, "../../src");

function load(relative, sandbox = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file);
    const exports = {};
    cache.set(file, exports);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    vm.runInNewContext(output, {
      exports, console, ...sandbox,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (!name.startsWith(".")) return require(name);
        const base = path.resolve(path.dirname(file), name);
        return loadFile([".ts", ".tsx"].map((ext) => base + ext).find((candidate) => fs.existsSync(candidate)));
      },
    });
    return exports;
  };
  return loadFile(path.join(SRC, relative));
}

function documentStub() {
  const listeners = new Set();
  return {
    listeners,
    activeElement: null,
    addEventListener: (_type, listener) => listeners.add(listener),
    removeEventListener: (_type, listener) => listeners.delete(listener),
    key: (key) => { for (const listener of [...listeners]) listener({ key, defaultPrevented: false, preventDefault() {} }); },
  };
}

const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));

test("StatusLabel colours only exceptions, with one fixed meaning per tone", () => {
  const { StatusLabel, statusTone } = load("layout/StatusLabel.ts");
  assert.equal(statusTone("Failed"), "problem");
  assert.equal(statusTone("sync_failed"), "problem");
  assert.equal(statusTone("Needs you"), "attention");
  assert.equal(statusTone("needs_configuration"), "attention");
  assert.equal(statusTone("Passed"), "success");
  assert.equal(statusTone("Running"), "info");
  for (const normal of ["Open", "Merged", "Synced", "Finished", "In review", "", null]) assert.equal(statusTone(normal), "neutral", String(normal));
  const html = renderToStaticMarkup(createElement(StatusLabel, { label: "Sync failed", title: "The token expired." }));
  assert.match(html, /class="ds-status ds-status--problem"/);
  assert.match(html, /title="The token expired."/);
  assert.match(renderToStaticMarkup(createElement(StatusLabel, { label: "Open", tone: "attention" })), /ds-status--attention/);
});

test("EmptyLine is one line with at most one action", () => {
  const { EmptyLine } = load("layout/EmptyLine.ts");
  const html = renderToStaticMarkup(createElement(EmptyLine, { text: "No sources yet.", action: { label: "Add source", href: "/chat?area=knowledge" } }));
  assert.match(html, /^<p class="ds-empty" role="status"/);
  assert.equal((html.match(/<a /g) ?? []).length, 1);
  assert.doesNotMatch(html, /<div|<h\d/);
});

test("SegmentedTabs is a tablist with roving focus and arrow keys", async () => {
  const { SegmentedTabs, nextTabKey } = load("layout/SegmentedTabs.ts");
  const tabs = [{ key: "open", label: "Open", count: 4 }, { key: "merged", label: "Merged" }, { key: "all", label: "All", disabled: true }];
  assert.equal(nextTabKey(tabs, "open", "ArrowRight"), "merged");
  assert.equal(nextTabKey(tabs, "merged", "ArrowRight"), "open", "skips the disabled tab and wraps");
  assert.equal(nextTabKey(tabs, "open", "ArrowLeft"), "merged");
  assert.equal(nextTabKey(tabs, "merged", "Home"), "open");
  assert.equal(nextTabKey(tabs, "open", "Enter"), null);
  const changes = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(SegmentedTabs, { tabs, value: "open", onChange: (key) => changes.push(key), label: "Pull request views", idPrefix: "pr" }),
      { createNodeMock: () => ({ focus() {} }) });
  });
  const list = view.root.find((node) => node.props.role === "tablist");
  assert.equal(list.props["aria-label"], "Pull request views");
  const buttons = view.root.findAll((node) => node.type === "button");
  assert.deepEqual(buttons.map((button) => button.props["aria-selected"]), [true, false, false]);
  assert.deepEqual(buttons.map((button) => button.props.tabIndex), [0, -1, -1]);
  assert.equal(buttons[0].props["aria-controls"], "pr-panel-open");
  assert.equal(text(buttons[0]), "Open4");
  await act(async () => list.props.onKeyDown({ key: "ArrowRight", preventDefault() {} }));
  await act(async () => buttons[1].props.onClick());
  assert.deepEqual(changes, ["merged", "merged"]);
});

test("DataTable: a full-width table, rows open by click and Enter, arrows move, the menu does not open the row", async () => {
  const { DataTable, nextRowIndex } = load("layout/DataTable.ts");
  assert.equal(nextRowIndex(3, 0, "ArrowDown"), 1);
  assert.equal(nextRowIndex(3, 2, "ArrowDown"), 2);
  assert.equal(nextRowIndex(3, 1, "ArrowUp"), 0);
  assert.equal(nextRowIndex(3, 1, "End"), 2);
  assert.equal(nextRowIndex(0, 0, "ArrowDown"), null);
  const rows = [{ id: "8", title: "Add capitalize_words", state: "Open" }, { id: "7", title: "Add last_word", state: "Build failed" }];
  const opened = [];
  const focused = [];
  const props = {
    label: "Pull requests", rows, rowKey: (row) => row.id, onOpen: (row) => opened.push(row.id), selectedKey: "7",
    columns: [
      { key: "id", header: "#", render: (row) => `#${row.id}`, nowrap: true },
      { key: "title", header: "Title", render: (row) => row.title, grow: true },
      { key: "state", header: "State", render: (row) => row.state },
    ],
    rowMenu: (row) => createElement("span", { "data-menu": row.id }, "⋯"),
  };
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(DataTable, props), { createNodeMock: (element) => ({ focus() { focused.push(element.props["data-row-key"]); } }) });
  });
  const table = view.root.find((node) => node.type === "table");
  assert.equal(table.props["aria-label"], "Pull requests");
  assert.deepEqual(view.root.findAll((node) => node.type === "th").map(text), ["#", "Title", "State", "Actions"]);
  const trs = view.root.findAll((node) => node.type === "tr" && node.props["data-row-key"]);
  assert.deepEqual(trs.map((row) => row.props.tabIndex), [-1, 0], "the selected row carries the focus stop");
  assert.equal(trs[1].props["aria-selected"], true);
  assert.match(trs[1].props.className, /is-selected/);
  await act(async () => trs[0].props.onClick());
  await act(async () => trs[1].props.onKeyDown({ key: "Enter", target: "row", currentTarget: "row", preventDefault() {} }));
  await act(async () => trs[1].props.onKeyDown({ key: "ArrowUp", target: "row", currentTarget: "row", preventDefault() {} }));
  assert.deepEqual(opened, ["8", "7"]);
  assert.deepEqual(focused, ["8"]);
  const menuCell = view.root.findAll((node) => node.type === "td").find((cell) => /ds-table__menu-cell/.test(cell.props.className));
  let stopped = false;
  menuCell.props.onClick({ stopPropagation: () => { stopped = true; } });
  assert.ok(stopped, "a click in the row menu does not reach the row");
});

test("DataTable: loading uses the shared loading state, no rows the one-line empty state", () => {
  const { DataTable } = load("layout/DataTable.ts");
  const base = { label: "Sources", columns: [{ key: "n", header: "Name", render: (row) => row.n }], rowKey: (row) => row.n };
  assert.match(renderToStaticMarkup(createElement(DataTable, { ...base, rows: [], loading: true })), /data-testid="loading-state"/);
  const empty = renderToStaticMarkup(createElement(DataTable, { ...base, rows: [], empty: { text: "No sources yet.", action: { label: "Add source", onClick() {} } } }));
  assert.match(empty, /class="ds-empty"/);
  assert.match(empty, /No sources yet\./);
  assert.doesNotMatch(empty, /<table/);
  assert.match(renderToStaticMarkup(createElement(DataTable, { ...base, rows: [] })), /No sources yet\./, "default text names the list");
});

test("SidePanel: a dialog over the dimmed list with Open as page, closed by Escape, ✕ and the backdrop; focus returns", async () => {
  const document = documentStub();
  const opener = { focused: 0, focus() { this.focused += 1; } };
  document.activeElement = opener;
  const { SidePanel, trappedIndex } = load("layout/SidePanel.ts", { document });
  assert.equal(trappedIndex(3, 2, false), 0, "Tab wraps from the last to the first");
  assert.equal(trappedIndex(3, 0, true), 2, "Shift+Tab wraps from the first to the last");
  assert.equal(trappedIndex(3, -1, false), 0);
  assert.equal(trappedIndex(0, 0, false), -1);
  const closed = [];
  const tabChanges = [];
  let sheetFocus = 0;
  const panel = (round) => createElement(SidePanel, {
    title: "#7 Add last_word to textkit", subtitle: "BRD-19 · demo-team/test", pageHref: "/chat?area=coding&pr=7",
    onClose: () => closed.push(round),
    tabs: { tabs: [{ key: "overview", label: "Overview" }, { key: "changes", label: "Changes" }], value: "overview", onChange: (key) => tabChanges.push(key), label: "Pull request", idPrefix: "pr7" },
    footer: createElement("a", { className: "admin-panel__action-btn admin-panel__action-btn--primary", href: "https://example.test" }, "Open in Bitbucket"),
  }, "Feature last_word(text) in textkit");
  let view;
  await act(async () => {
    view = TestRenderer.create(panel(1), { createNodeMock: () => ({ focus() { sheetFocus += 1; } }) });
  });
  await act(async () => view.update(panel(2)));
  assert.equal(sheetFocus, 1, "focus moves in once, not on every render");
  const dialog = view.root.find((node) => node.props.role === "dialog");
  assert.equal(dialog.props["aria-modal"], "true");
  const titleId = dialog.props["aria-labelledby"];
  assert.equal(text(view.root.find((node) => node.type === "h2")), "#7 Add last_word to textkit");
  assert.equal(view.root.find((node) => node.type === "h2").props.id, titleId);
  const openPage = view.root.find((node) => node.props["data-testid"] === "side-panel-open-page");
  assert.equal(openPage.props.href, "/chat?area=coding&pr=7");
  assert.equal(text(openPage), "Open as page");
  const body = view.root.find((node) => node.props.role === "tabpanel");
  assert.equal(body.props.id, "pr7-panel-overview");
  assert.equal(body.props["aria-labelledby"], "pr7-tab-overview");
  await act(async () => document.key("Escape"));
  assert.deepEqual(closed, [2], "Escape closes with the newest handler");
  await act(async () => view.root.find((node) => node.props["data-testid"] === "side-panel-close").props.onClick());
  const backdrop = view.root.find((node) => node.props["data-testid"] === "side-panel-backdrop");
  await act(async () => backdrop.props.onMouseDown({ target: "inside", currentTarget: "backdrop" }));
  await act(async () => backdrop.props.onMouseDown({ target: "backdrop", currentTarget: "backdrop" }));
  assert.deepEqual(closed, [2, 2, 2], "✕ and the dimmed list close; a click inside the sheet does not");
  assert.equal(document.listeners.size, 1);
  await act(async () => view.unmount());
  assert.equal(document.listeners.size, 0);
  assert.equal(opener.focused, 1, "focus returns to the row that opened the panel");
});

test("SidePanel mode=page renders the same content full width without backdrop, ✕ or Open as page", () => {
  const { SidePanel } = load("layout/SidePanel.ts");
  const html = renderToStaticMarkup(createElement(SidePanel, { title: "Source jira-shop", pageHref: "/x", onClose() {}, mode: "page" }, "Content"));
  assert.match(html, /^<section class="ds-panel ds-panel--page"/);
  assert.doesNotMatch(html, /ds-panel__backdrop|Open as page|aria-label="Close/);
  assert.match(html, /Content/);
});

test("FormSection and a collapsed Advanced section", () => {
  const { FormSection, AdvancedSection } = load("layout/FormSection.ts");
  const section = renderToStaticMarkup(createElement(FormSection, { title: "Connection" }, "fields"));
  assert.match(section, /^<fieldset class="ds-form-section"><legend class="ds-form-section__title">Connection<\/legend>/);
  const advanced = renderToStaticMarkup(createElement(AdvancedSection, null, "expert"));
  assert.match(advanced, /^<details class="ds-advanced" data-testid="ds-advanced"><summary class="ds-advanced__summary">Advanced<\/summary>/);
  assert.doesNotMatch(advanced, / open/);
  assert.match(renderToStaticMarkup(createElement(AdvancedSection, { defaultOpen: true }, "x")), /<details class="ds-advanced" open=""/);
});

test("the stylesheet is imported once, and the tokens cover every tone in both themes", () => {
  const chatCss = fs.readFileSync(path.join(SRC, "styles/chat.css"), "utf8");
  assert.equal((chatCss.match(/chat\/design-system\.css/g) ?? []).length, 1);
  assert.equal((chatCss.match(/ds-tokens\.css/g) ?? []).length, 1);
  const tokens = fs.readFileSync(path.join(SRC, "styles/chat/ds-tokens.css"), "utf8");
  for (const tone of ["neutral", "attention", "problem", "success", "info"]) assert.match(tokens, new RegExp(`--ds-tone-${tone}-ink`));
  assert.match(tokens, /--ds-row-height: 36px/);
  assert.match(tokens, /\[data-theme="light"\]/);
});
