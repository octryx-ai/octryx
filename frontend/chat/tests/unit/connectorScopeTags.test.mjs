// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/connectorScopeTags.test.mjs
//
// Connector UX (delivery 5): scope keys are tags, one key per tag. Confluence's allowed spaces keep their
// stored shape [{space_key, enabled}] (labels and disabled entries are kept), the JSON stays under "Advanced", and
// a named connection's bound keys use the same input with the descriptor's pattern and case.
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
  addKeys,
  removeKey,
  spaceTags,
  spacesDraft,
  splitKeys,
} from "../../src/admin/components/keyTags/keyTagsModel.ts";
import { buildConnectorSaveBody } from "../../src/admin/hooks/connectorSaveBody.ts";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

function load(relative) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file).exports;
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    }).outputText;
    const module = { exports: {} };
    cache.set(file, module);
    vm.runInNewContext(output, {
      module, exports: module.exports, console, Date, URL, URLSearchParams, Error, encodeURIComponent, JSON,
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

const SPACE = { pattern: "~?[A-Za-z0-9_]{1,64}" };

test("typed or pasted keys become tags without repeats; invalid keys are named, not saved", () => {
  assert.deepEqual(splitKeys(" SPACE1, space1;SPACE2\nSPACE3 "), ["SPACE1", "SPACE2", "SPACE3"]);
  assert.deepEqual(addKeys(["SPACE1"], "space1 SPACE2 bad-key", SPACE), { keys: ["SPACE1", "SPACE2"], invalid: ["bad-key"] });
  assert.deepEqual(addKeys([], "~user1", SPACE).keys, ["~user1"], "personal spaces are space keys");
  assert.deepEqual(addKeys([], "proj1", { canonical: (key) => key.toUpperCase() }).keys, ["PROJ1"]);
  assert.deepEqual(removeKey(["SPACE1", "SPACE2"], "space1"), ["SPACE2"]);
});

test("allowed spaces keep their stored shape: entries, labels and disabled entries survive the tags", () => {
  const stored = JSON.stringify([
    { space_key: "SPACE1", enabled: true, label: "First" },
    { space_key: "SPACE2", enabled: false },
    "SPACE3",
  ]);
  assert.deepEqual(spaceTags(stored), { keys: ["SPACE1", "SPACE3"], disabled: ["SPACE2"], unreadable: false });
  assert.deepEqual(JSON.parse(spacesDraft(stored, ["SPACE1", "SPACE4"])), [
    { space_key: "SPACE1", enabled: true, label: "First" },
    { space_key: "SPACE4", enabled: true },
    { space_key: "SPACE2", enabled: false },
  ]);
  assert.deepEqual(JSON.parse(spacesDraft(stored, ["space2"])), [{ space_key: "SPACE2", enabled: true }],
    "a tag for a disabled key enables its stored entry");
  assert.deepEqual(JSON.parse(spacesDraft("", [])), [], "removing every tag saves an explicit empty list");
  assert.equal(spaceTags('{"space_key": "SPACE1"}').unreadable, true, "a hand-edited non-list is not guessed");
});

function mountScope(initialDraft) {
  const { ConfluenceScopeFields } = load("admin/components/connectorsTab/ConfluenceScopeFields.tsx");
  const draft = { ...initialDraft };
  let view;
  const render = () => createElement(ConfluenceScopeFields, {
    toolName: "confluence", draft: { ...draft }, set: (field, value) => { draft[field] = value; view.update(render()); },
  });
  act(() => { view = TestRenderer.create(render()); });
  const entry = () => view.root.find((node) => node.type === "input" && node.props.id === "connector-field-confluence-confluence_allowed_spaces");
  return {
    draft,
    all: () => text(view.root),
    type: (value) => act(() => entry().props.onChange({ target: { value } })),
    enter: () => act(() => entry().props.onKeyDown({ key: "Enter", preventDefault() {} })),
    remove: (key) => act(() => view.root.find((node) => node.type === "button" && node.props["aria-label"] === `Remove space ${key}`).props.onClick()),
    tags: () => view.root.findAll((node) => node.props.className?.startsWith?.("key-tags__tag")).map((node) => node.props["data-key"]),
    textareas: () => view.root.findAll((node) => node.type === "textarea").map((node) => node.props.id),
  };
}

test("rendered: the Confluence card shows spaces as tags; typing and removing write the stored JSON shape", () => {
  const ui = mountScope({ confluence_allowed_spaces: JSON.stringify([{ space_key: "SPACE1", enabled: true }]) });
  assert.deepEqual(ui.tags(), ["SPACE1"]);
  assert.doesNotMatch(ui.all(), /JSON array, e\.g\./, "no raw JSON hint in the main view");
  ui.type("space2");
  ui.enter();
  assert.deepEqual(JSON.parse(ui.draft.confluence_allowed_spaces), [
    { space_key: "SPACE1", enabled: true }, { space_key: "space2", enabled: true }]);
  ui.type("SPACE3,");
  assert.deepEqual(ui.tags(), ["SPACE1", "space2", "SPACE3"], "a separator commits the key");
  ui.type("bad-key");
  ui.enter();
  assert.match(ui.all(), /Not a valid space key: bad-key/);
  assert.equal(JSON.parse(ui.draft.confluence_allowed_spaces).length, 3);
  ui.remove("SPACE1");
  assert.deepEqual(ui.tags(), ["space2", "SPACE3"]);
  // The stored values stay editable as JSON, but only under Advanced.
  assert.deepEqual(ui.textareas(), [
    "connector-field-confluence-confluence_allowed_spaces-json", "connector-field-confluence-confluence_allowed_pages-json"]);
});

test("the save body sends the tags' list in the stored shape", () => {
  const connector = { tool_name: "confluence", fields: ["confluence_url", "confluence_allowed_spaces"], secret_fields: [],
    secret_status: {}, public_fields: {}, configured: true };
  const body = buildConnectorSaveBody(connector, {
    confluence_allowed_spaces: spacesDraft("", ["SPACE1", "SPACE2"]),
  }, { tool_instructions: "", extra_tools: [], disabled_tools: [] });
  assert.deepEqual(body.confluence_allowed_spaces, [
    { space_key: "SPACE1", enabled: true }, { space_key: "SPACE2", enabled: true }]);
});

test("rendered: the guided Confluence form shows the scope as tags and no raw JSON field in the main view", () => {
  const { ConfluenceConnectorSetupFields } = load("admin/components/connectorsTab/ConfluenceConnectorSetupFields.tsx");
  const { atlassianAuthView } = load("admin/components/connectorsTab/atlassianAuthView.ts");
  const connector = {
    tool_name: "confluence", configured: true, secret_fields: ["confluence_token"], secret_status: {},
    fields: ["confluence_url", "confluence_auth_mode", "confluence_token", "confluence_allowed_spaces", "confluence_allowed_pages"],
    public_fields: { confluence_url: "https://wiki.example.test/wiki", confluence_auth_mode: "bearer_pat" },
  };
  const draft = { confluence_url: "https://wiki.example.test/wiki", confluence_auth_mode: "bearer_pat",
    confluence_allowed_spaces: '[{"space_key": "SPACE1", "enabled": true}]' };
  let view;
  act(() => {
    view = TestRenderer.create(createElement(ConfluenceConnectorSetupFields, {
      connector, draft, view: atlassianAuthView("confluence", connector, draft),
      ctx: { setConnectorField: () => {} }, rebind: { flow: null, fieldEdited: () => {} }, showAllErrors: false,
    }));
  });
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "confluence-scope").length, 1);
  const outsideAdvanced = view.root.findAll((node) => node.type === "textarea" && !String(node.props.id).endsWith("-json"));
  assert.deepEqual(outsideAdvanced.map((node) => node.props.id), [], "no JSON textarea outside Advanced");
  assert.doesNotMatch(text(view.root), /JSON array/);
});
