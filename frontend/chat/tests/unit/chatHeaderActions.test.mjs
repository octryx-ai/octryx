// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/chatHeaderActions.test.mjs
//
// Review point 7: the chat header's icons name themselves (accessible name and a visible tooltip), and the
// theme switch is the rail's alone: the header carries it only where the rail is hidden (compact and phone widths).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { readCssWithImports } from "./cssWithImports.mjs";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");

function load(relative, mocks = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Object, Array, String,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        const key = path.basename(name);
        if (key in mocks) return mocks[key];
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

const { WorkspaceHeaderActions } = load("chat/header/WorkspaceHeaderActions.tsx", { StatsPopover: { StatsPopover: () => null } });

function render(layoutMode) {
  const props = {
    layoutMode, hasSelectedSession: true, taskError: "", taskErrorSummary: "", taskErrorOpen: false, setTaskErrorOpen() {},
    selectedSessionIsRunning: false, onContinue() {}, workspaceOpen: false, onToggleWorkspace() {}, onExportEvidencePdf() {},
    onExportAnalysisJson() {}, chatTheme: "dark", setChatTheme() {}, statsOpen: false, setStatsOpen() {}, stats: null,
    codeIntelligence: null, traceEventCount: 3, onOpenTrace() {},
  };
  let view;
  act(() => { view = TestRenderer.create(createElement(WorkspaceHeaderActions, props)); });
  return view;
}

// Design review: on wide screens each action shows its name next to its icon; the two exports share one menu.
test("on wide screens every header action is labelled, and there is no theme switch (the rail has it)", () => {
  const view = render("desktop");
  const buttons = view.root.findAllByType("button");
  const label = (button) => button.findAllByType("span").map((span) => span.children.join("")).join(" ");
  assert.deepEqual(buttons.map(label), ["Files", "Export", "Usage", "Trace 3"]);
  assert.equal(buttons[1].props["aria-haspopup"], "menu");
  for (const button of buttons) assert.ok(button.props["aria-label"], "accessible name");
  assert.equal(buttons.filter((button) => /theme/.test(button.props["aria-label"])).length, 0);
  assert.equal(buttons.at(-1).props["aria-label"], "Open execution trace (3 events)");
  act(() => view.unmount());
});

test("where the rail is hidden (compact width) the header keeps the one theme switch", () => {
  const view = render("compact");
  const theme = view.root.findAllByType("button").filter((button) => /theme/.test(button.props["aria-label"]));
  assert.equal(theme.length, 1);
  assert.equal(theme[0].props["data-tooltip"], "Switch to light theme");
  act(() => view.unmount());
});

test("the header tooltip is styled like the rail's and shows on hover and keyboard focus", () => {
  const css = readCssWithImports(path.join(SRC, "styles/chat/approvals-workspace/workspace-feed.css"));
  assert.match(css, /\.workspace__actions \.icon-action-button\[data-tooltip\]::after \{[^}]*content: attr\(data-tooltip\)/);
  assert.match(css, /\[data-tooltip\]:focus-visible::after/);
});
