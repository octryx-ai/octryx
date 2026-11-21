// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/knowledgeSetupFirstRun.test.mjs
//
// Knowledge setup in an empty Workspace starts with "Connect your first source" in three
// steps (Connectors, add here, Search), Add source is the only bright button and enables Knowledge, the source form opens only on
// "Add source" with a visible label on every field and the optional ones under a closed "Advanced", and a run's
// per-item log is closed by default. Requests are stubs.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const byTestId = (view, id) => view.root.findAll((node) => node.props["data-testid"] === id);
const button = (view, label) => view.root.findAll((node) => node.type === "button" && text(node) === label)[0];

function loader(extra = {}) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, ...extra,
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
  return (relative) => loadFile(path.join(SRC, relative));
}

async function mountEmpty({ mayAuthor = true, search = "" } = {}) {
  const listing = { connectors: [], may_author: mayAuthor, knowledge: { state: "unknown", outcome: null, checked_at: null } };
  const fetch = async () => ({ ok: true, status: 200, json: async () => listing });
  const load = loader({ fetch, window: { confirm: () => false, location: { search } } });
  const { AdminNavigationContext } = load("admin/adminNavigation.ts");
  const { KnowledgeConnectorsPanel } = load("admin/components/workspaceKnowledge/KnowledgeConnectorsPanel.tsx");
  const opened = [];
  let view;
  await act(async () => {
    view = TestRenderer.create(createElement(AdminNavigationContext.Provider, { value: { openAdminTab: (tab) => opened.push(tab) } },
      createElement(KnowledgeConnectorsPanel, { workspaceId: "ws-1" })));
  });
  return { view, opened };
}

// Design-system pilot: the empty Workspace shows one line and one action; the add form opens in the side panel,
// which says in one line that a source needs a connection first (link to Admin › Connections).
test("an empty Workspace shows one line with Add source; one bright button, no form yet", async () => {
  const { view } = await mountEmpty();
  assert.equal(text(byTestId(view, "sources-empty")[0]), "No sources yet.Add source");
  assert.equal(view.root.findAllByType("form").length, 0, "no raw form before Add source");
  const primary = view.root.findAll((node) => node.type === "button" && String(node.props.className || "").includes("--primary"));
  assert.deepEqual(primary.map(text), ["Add source"], "one bright button: Add source (it enables Knowledge)");
  act(() => view.unmount());
});

test("Add source opens the side panel: connect-first line, every field labelled, optional ones under a closed Advanced", async () => {
  const { view, opened } = await mountEmpty();
  act(() => button(view, "Add source").props.onClick());
  const [panel] = byTestId(view, "source-form-panel");
  assert.ok(panel, "the form opens in the side panel, not at the bottom of the page");
  assert.equal(panel.props.role, "dialog");
  const [hint] = byTestId(view, "knowledge-first-source");
  const link = hint.find((node) => node.type === "a");
  assert.equal(link.props.href, "/chat?area=admin&tab=adminConnections");
  act(() => link.props.onClick({ preventDefault() {} }));
  assert.deepEqual(opened, ["adminConnections"]);
  const form = panel.findByType("form");
  for (const control of form.findAll((node) => (node.type === "input" && node.props.type !== "checkbox" && node.props.type !== "radio") || node.type === "select" || node.type === "textarea")) {
    if (control.props["aria-label"] === "Schedule interval" || control.props["aria-label"] === "Schedule interval in minutes") continue;
    const label = control.parent?.type === "label" ? control.parent : null;
    assert.ok(label && text(label.findByType("span")).length > 0, `${control.props["aria-label"]} has a visible label`);
  }
  const [advanced] = byTestId(view, "connector-advanced");
  assert.equal(advanced.props.open, undefined, "Advanced is closed");
  const inside = advanced.findAll((node) => node.type === "input").map((node) => node.props["aria-label"]);
  assert.deepEqual(inside, ["Connection id", "Products", "Version", "Items per run"]);
  // One title (the panel's), the actions in the panel footer at the right like Add connection.
  assert.doesNotMatch(text(panel), /Add a source/i);
  assert.equal(form.findAllByType("button").filter((node) => node.props.type === "submit").length, 0, "no buttons inside the form");
  const footer = panel.findByType("footer");
  assert.deepEqual(footer.findAllByType("button").map(text), ["Cancel", "Add source"]);
  const submit = byTestId(view, "source-form-submit")[0];
  assert.equal(submit.props.type, "submit");
  assert.equal(submit.props.form, form.props.id, "the footer button submits the form");
  assert.equal(String(form.props.className).includes("user-edit-panel__section"), false, "no extra indent");
  act(() => button(view, "Cancel").props.onClick());
  assert.equal(byTestId(view, "source-form-panel").length, 0, "Cancel closes the panel");
  assert.equal(byTestId(view, "sources-empty").length, 1);
  act(() => view.unmount());
});

// The Repository explorer's empty line links here (sourceLinks.ts): the link opens Sources with Add source open.
test("a link with ?source=new opens Sources with Add source open", async () => {
  const { addSourceHref } = loader()("admin/components/workspaceKnowledge/sourceLinks.ts");
  const href = addSourceHref("ws 1");
  assert.equal(href, "/chat?area=knowledge&tab=workspaceKnowledge&workspace_id=ws%201&source=new");
  const { view } = await mountEmpty({ search: new URL(href, "http://octryx.test").search });
  assert.equal(byTestId(view, "source-form-panel").length, 1, "Add source is open");
  act(() => button(view, "Cancel").props.onClick());
  assert.equal(byTestId(view, "source-form-panel").length, 0);
  act(() => view.unmount());
  const reader = await mountEmpty({ mayAuthor: false, search: "?source=new" });
  assert.equal(byTestId(reader.view, "source-form-panel").length, 0, "a reader gets no form");
  act(() => reader.view.unmount());
});

test("a reader sees the empty line without Add source", async () => {
  const { view } = await mountEmpty({ mayAuthor: false });
  assert.equal(text(byTestId(view, "sources-empty")[0]), "No sources yet.");
  assert.equal(button(view, "Add source"), undefined);
  act(() => view.unmount());
});

test("a run's per-item log is closed by default and shows its count", () => {
  const load = loader();
  const { KnowledgeConnectorRun } = load("admin/components/workspaceKnowledge/KnowledgeConnectorRun.tsx");
  const outcomes = Array.from({ length: 3 }, (_, index) => ({ external_id: `P-${index}`, title: `Page ${index}`, outcome: "created", reason: null }));
  const run = { id: "r1", state: "completed", reason: null, started_at: "2026-10-05T10:00:00Z", finished_at: "2026-10-05T10:01:00Z",
    report: { created: 3, listed: 3 }, outcomes };
  let view;
  act(() => { view = TestRenderer.create(createElement(KnowledgeConnectorRun, { connectorKey: "wiki", run })); });
  const [log] = byTestId(view, "run-outcomes");
  assert.equal(log.type, "details");
  assert.equal(log.props.open, undefined);
  assert.equal(text(log.findByType("summary")), "Items of this run (3)");
  act(() => view.unmount());
});
