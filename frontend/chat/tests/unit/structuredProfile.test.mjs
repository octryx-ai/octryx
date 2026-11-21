import assert from "node:assert/strict";
import fs from "node:fs";
import { createRequire } from "node:module";
import { test } from "node:test";
import vm from "node:vm";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import * as model from "../../src/admin/components/workspaceKnowledge/structuredProfileModel.ts";
import {
  applyForm, formatDocument, formOf, getAt, linesToTicketPatterns, parseDocument, setAt, ticketPatternsToLines,
} from "../../src/admin/components/workspaceKnowledge/structuredProfileModel.ts";

const DOCUMENT = {
  key: "structured",
  version: 4,
  layers: { configuration: { connector_kinds: ["git_repository"], files: [
    { glob: "*.ini", format: "ini", manual_documented: true },
    { glob: "values*.yaml", format: "yaml", manual_documented: false },
  ] } },
  manual: { parameter_name_headers: ["Parameter"], default_headers: ["Default", "Standardwert"],
    description_headers: ["Description", "Beschreibung"], allowed_headers: ["Possible values"], units: { seconds: "s" } },
  configuration: { comment_prefixes: { ini: [";", "#"], properties: ["#", "!"], yaml: ["#"] },
    variant_patterns: ["^(?P<base>.+\\.ini)-(?P<variant>[^/]+)$"], placeholder_sources: ["*_config.properties"] },
  operations: { ticket_patterns: { Incident: "\\bINC[0-9]{7}\\b", Change: "\\bCHG[0-9]{7}\\b" } },
};

test("the form shows the common lists of the document", () => {
  const form = formOf(DOCUMENT);
  assert.equal(form.defaultHeaders, "Default\nStandardwert");
  assert.equal(form.descriptionHeaders, "Description\nBeschreibung");
  assert.deepEqual(form.files.map((rule) => rule.glob), ["*.ini", "values*.yaml"]);
  assert.equal(form.files[1].manual_documented, false);
  assert.deepEqual(form.commentPrefixes, { ini: "; #", properties: "# !", yaml: "#" });
  assert.equal(form.ticketPatterns, "Incident = \\bINC[0-9]{7}\\b\nChange = \\bCHG[0-9]{7}\\b");
});

test("applying the form writes only its lists and keeps everything else", () => {
  const form = { ...formOf(DOCUMENT), parameterHeaders: "Parameter\n  Einstellung \n\n",
    commentPrefixes: { ini: ";", properties: "# ! ;", yaml: "#" },
    files: [...formOf(DOCUMENT).files, { glob: "  ", format: "ini", manual_documented: true }],
    ticketPatterns: "Incident = \\bINC[0-9]{7}\\b\nProblem = \\bPRB[0-9]{7}\\b" };
  const { document, error } = applyForm(DOCUMENT, form);
  assert.equal(error, null);
  assert.deepEqual(document.manual.parameter_name_headers, ["Parameter", "Einstellung"]);
  assert.deepEqual(document.configuration.comment_prefixes.properties, ["#", "!", ";"]);
  assert.equal(document.layers.configuration.files.length, 2); // an empty glob row is dropped
  assert.deepEqual(document.layers.configuration.connector_kinds, ["git_repository"]);
  assert.deepEqual(document.manual.units, { seconds: "s" });
  assert.deepEqual(Object.keys(document.operations.ticket_patterns), ["Incident", "Problem"]);
  assert.deepEqual(DOCUMENT.manual.parameter_name_headers, ["Parameter"]); // the input is not mutated
});

test("ticket pattern lines need a type and a pattern, each type once", () => {
  assert.match(linesToTicketPatterns("Incident").error, /Type = pattern/);
  assert.match(linesToTicketPatterns("A = x\nA = y").error, /listed twice/);
  assert.deepEqual(linesToTicketPatterns("Change = CHG = 1").value, { Change: "CHG = 1" });
  assert.equal(ticketPatternsToLines(null), "");
});

test("the JSON view accepts only an object and round-trips", () => {
  assert.match(parseDocument("[1]").error, /JSON object/);
  assert.match(parseDocument("{").error, /Not valid JSON/);
  assert.deepEqual(parseDocument(formatDocument(DOCUMENT)).document, DOCUMENT);
  assert.equal(getAt(DOCUMENT, ["manual", "missing", "deeper"]), undefined);
  assert.deepEqual(setAt({}, ["a", "b"], 1), { a: { b: 1 } });
});


const require = createRequire(import.meta.url);
const ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

function loadPanel(fakeApi, confirm) {
  const exports = {};
  const source = fs.readFileSync(new URL("../../src/admin/components/workspaceKnowledge/StructuredProfilePanel.tsx", import.meta.url), "utf8");
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
    exports, window: { confirm }, require(name) {
      if (name.endsWith("structuredGraphApi")) return { structuredProfileApi: fakeApi };
      if (name.endsWith("structuredProfileModel")) return model;
      return require(name);
    },
  });
  return exports.StructuredProfilePanel;
}

const SETTINGS = { workspace_id: "ws", source: "default", profile_id: "structured-v4", revision: null,
  document: DOCUMENT, default_document: DOCUMENT, may_author: true, history: [] };

test("the panel edits a list in the form, mirrors it in the JSON and saves only after confirmation", async () => {
  const saved = [];
  const fakeApi = {
    get: async () => SETTINGS,
    validate: async () => ({ valid: true, profile_id: "structured-v4-w1" }),
    save: async (id, document) => {
      saved.push(document);
      return { ...SETTINGS, source: "workspace", revision: 1, profile_id: "structured-v4-w1", document,
        build: { id: "b", state: "pending" } };
    },
  };
  const answers = [false, true];
  const Panel = loadPanel(fakeApi, () => answers.shift());
  let view;
  await act(async () => { view = TestRenderer.create(createElement(Panel, { workspaceId: "ws" })); });
  const textareas = () => view.root.findAllByType("textarea");
  const defaults = textareas().find((item) => item.props.value === "Default\nStandardwert");
  await act(async () => defaults.props.onChange({ target: { value: "Default\nStandardwert\nVorgabe" } }));
  const json = textareas().at(-1).props.value;
  assert.deepEqual(JSON.parse(json).manual.default_headers, ["Default", "Standardwert", "Vorgabe"]);
  const button = (label) => view.root.findAll((node) => node.type === "button" && node.children.includes(label))[0];
  await act(async () => button("Save and re-extract").props.onClick());
  assert.deepEqual(saved, []); // declined
  assert.match(JSON.stringify(view.toJSON()), /Not saved/);
  await act(async () => button("Save and re-extract").props.onClick());
  assert.equal(saved.length, 1);
  assert.deepEqual(saved[0].manual.default_headers, ["Default", "Standardwert", "Vorgabe"]);
  assert.match(JSON.stringify(view.toJSON()), /structured-v4-w1/);
  act(() => view.unmount());
});
