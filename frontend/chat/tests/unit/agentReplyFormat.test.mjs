// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/agentReplyFormat.test.mjs
//
// Agent output format (shared contract). Free text stays the default and an
// ordinary free-text agent is saved (no reply_contract sent). Structured data sends
// the exact contract under the shared request key reply_contract, and only when it changed. A saved
// value this form cannot represent is invalid on the server too, which refuses every save of the agent
// (HTTP 422) until a valid format is chosen: the form says so, offers Free text or new fields, never
// sends null or text on its own, and shows the server's refusal. Local checks mirror the shared rules;
// the server stays the authority.
import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement, useState } from "react";
import TestRenderer from "react-test-renderer";
import * as format from "../../src/admin/components/agentsTab/agentReplyFormat.ts";
import { defaultReplyFormat, newReplyField } from "../../src/admin/components/agentsTab/agentReplyFields.ts";
import * as replyFields from "../../src/admin/components/agentsTab/agentReplyFields.ts";
import { replyFormatFromAgent } from "../../src/admin/components/agentsTab/agentReplyContract.ts";
import { hydrateAgentFormState, resetAgentFormState } from "../../src/admin/hooks/useAdminAgentForms.helpers.ts";
import { useAdminAgentForms } from "../../src/admin/hooks/useAdminAgentForms.ts";
import { readJson } from "../../src/admin/utils/adminPanelHelpers.ts";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));

const contract = (properties, required = Object.keys(properties)) => ({
  kind: "json_object", schema: { type: "object", properties, required },
});
const SAVED = contract({ summary: { type: "string" }, tags: { type: "array", items: { type: "string" } }, score: { type: "number" } }, ["summary"]);
const agentWith = (replyContract) => ({ id: "a", name: "A", description: "", agent_type: "diagnosis", step_count: 0, is_active: true, ...(replyContract === undefined ? {} : { replyContract }) });

function recordingSetters() {
  const values = {};
  return { values, setters: new Proxy({}, { get: (_t, name) => (value) => { values[String(name).replace(/^set/, "")] = value; } }) };
}

test("a new agent is free text; a saved agent's format is read exactly, unknown values stay unrecognised", () => {
  const fresh = recordingSetters();
  resetAgentFormState(fresh.setters, "diagnosis");
  assert.deepEqual(fresh.values.AgentFormReplyFormat, { mode: "text", fields: [], baseline: "absent" });

  const hydrate = (saved) => {
    const { values, setters } = recordingSetters();
    hydrateAgentFormState(setters, agentWith(saved));
    return values.AgentFormReplyFormat;
  };
  assert.equal(hydrate(undefined).mode, "text", "legacy absent means free text");
  assert.equal(hydrate({ kind: "text" }).mode, "text");
  const checked = hydrate(SAVED);
  assert.equal(checked.mode, "json_object");
  assert.deepEqual(checked.fields.map(({ name, type, list, required }) => [name, type, list, required]), [
    ["summary", "string", false, true], ["tags", "string", true, false], ["score", "number", false, false],
  ]);
  const noRequiredKey = hydrate({ kind: "json_object", schema: { type: "object", properties: { ok: { type: "boolean" } } } });
  assert.deepEqual([noRequiredKey.mode, noRequiredKey.fields[0].required], ["json_object", false], "a missing required list means none");

  const many = Object.fromEntries(Array.from({ length: 33 }, (_, i) => [`f${i}`, { type: "string" }]));
  for (const [label, saved] of [
    ["null", null], ["text with extra key", { kind: "text", note: 1 }], ["unknown kind", { kind: "xml" }], ["string", "text"],
    ["schemaRef", { kind: "json_object", schemaRef: "x" }],
    ["extra schema keyword", { kind: "json_object", schema: { type: "object", properties: { a: { type: "string" } }, additionalProperties: false } }],
    ["enum", contract({ a: { type: "string", enum: ["x"] } })],
    ["nested object", contract({ a: { type: "object", properties: {} } })],
    ["array without items", contract({ a: { type: "array" } })],
    ["array of arrays", contract({ a: { type: "array", items: { type: "array", items: { type: "string" } } } })],
    ["external ref", contract({ a: { $ref: "https://example.test/x" } })],
    ["undeclared required", contract({ a: { type: "string" } }, ["b"])],
    ["duplicate required", contract({ a: { type: "string" } }, ["a", "a"])],
    ["no fields", contract({})], ["33 fields", contract(many, [])],
    ["bad field name", contract({ Bad: { type: "string" } })],
    ["root not object", { kind: "json_object", schema: { type: "array", properties: { a: { type: "string" } } } }],
  ]) {
    assert.equal(hydrate(saved).mode, "unsupported", label);
  }
});

test("local checks mirror the shared rules, with clear messages", () => {
  const field = (name, extra = {}) => ({ ...newReplyField(), name, ...extra });
  assert.equal(format.replyFieldsError([]), "Add at least one field, or choose Free text.");
  assert.equal(format.replyFieldsError([field("")]), "Field 1 needs a name.");
  for (const bad of ["Summary", "1st", "_x", "has-dash", "has space", "é", "a".repeat(65)]) {
    assert.match(format.replyFieldsError([field(bad)]), /must start with a lowercase letter/, bad);
  }
  assert.equal(format.replyFieldsError([field("a".repeat(64))]), null, "64 characters is allowed");
  assert.equal(format.replyFieldsError([field("summary"), field("summary")]), 'The field name "summary" is used more than once.');
  assert.match(format.replyFieldsError(Array.from({ length: 33 }, (_, i) => field(`f${i}`))), /at most 32 fields/);
  assert.equal(format.replyFieldsError(Array.from({ length: 32 }, (_, i) => field(`f${i}`))), null);
});

function formArgs(overrides) {
  const calls = { requests: [], errors: [] };
  const noop = () => {};
  const args = new Proxy(
    {
      readJson: async (url, init) => {
        calls.requests.push({ url, method: init?.method, body: init?.body ? JSON.parse(init.body) : null });
        return url.endsWith("/meta") ? {} : init?.method ? { id: "a" } : [];
      },
      agentModes: [], panelAgents: [], editingAgent: { id: "a", name: "A" },
      agentFormName: "A", agentFormDescription: "", agentFormGoal: "", agentFormType: "diagnosis", agentFormThinking: "light",
      agentFormRuntimeId: "", agentFormGroupId: "", agentFormBranchPrefix: "octryx",
      agentFormRequireSelfReview: false, agentFormToolSurface: "governed", agentFormSystemPrompt: "", agentFormOutputPrompt: "",
      agentFormSetup: { capabilityCeiling: "read_only", defaultWorkflowKey: "", executionMode: "" }, agentFormPreferredSkillIds: [], agentFormBlockedSkillIds: [], agentFormActive: true,
      setAgentFormError: (value) => value && calls.errors.push(value),
      ...overrides,
    },
    { get: (target, name) => (name in target ? target[name] : noop) },
  );
  return { args, calls };
}

async function save(overrides) {
  const { args, calls } = formArgs(overrides);
  let forms;
  function Probe() { forms = useAdminAgentForms(args); return null; }
  act(() => { TestRenderer.create(createElement(Probe)); });
  await act(async () => { await forms.handleSaveAgent({ preventDefault() {} }); });
  const write = calls.requests.find((request) => request.method === "PUT" || request.method === "POST");
  return { ...calls, write };
}

test("an ordinary free-text agent is saved without reply_contract; a changed format is sent once, under reply_contract", async () => {
  const legacy = await save({ agentFormReplyFormat: replyFormatFromAgent(agentWith(undefined)) });
  assert.equal("reply_contract" in legacy.write.body, false, "legacy agent: nothing sent");
  const explicitText = await save({ agentFormReplyFormat: replyFormatFromAgent(agentWith({ kind: "text" })) });
  assert.equal("reply_contract" in explicitText.write.body, false);
  const createText = await save({ editingAgent: null, agentFormReplyFormat: defaultReplyFormat() });
  assert.equal(createText.write.method, "POST");
  assert.equal("reply_contract" in createText.write.body, false, "a new free-text agent stays the default");

  const fields = [{ ...newReplyField(), name: "summary" }, { ...newReplyField(), name: "count", type: "integer", required: false }];
  const create = await save({ editingAgent: null, agentFormReplyFormat: { mode: "json_object", fields, baseline: "absent" } });
  assert.deepEqual(create.write.body.reply_contract, contract({ summary: { type: "string" }, count: { type: "integer" } }, ["summary"]));
  assert.equal("replyContract" in create.write.body, false, "one spelling only, never both");

  const loaded = replyFormatFromAgent(agentWith(SAVED));
  const unchanged = await save({ agentFormReplyFormat: loaded });
  assert.equal("reply_contract" in unchanged.write.body, false, "an unchanged checked format is omitted (kept)");
  const edited = await save({ agentFormReplyFormat: { ...loaded, fields: loaded.fields.map((field) => field.name === "score" ? { ...field, required: true } : field) } });
  assert.deepEqual(edited.write.body.reply_contract.schema.required, ["summary", "score"]);
  const toText = await save({ agentFormReplyFormat: { ...loaded, mode: "text" } });
  assert.deepEqual(toText.write.body.reply_contract, { kind: "text" }, "turning the check off is explicit");
});

// The write rule (reply_contract_column_for_write): a save that declares no reply_contract
// re-validates the stored value, and an invalid stored value is refused with a typed 422; a save that
// declares a valid one is stored. The real readJson turns the typed detail into its message.
const SERVER_REFUSAL = "The reply format is not a valid contract.";
async function saveAgainstServer(state) {
  const original = globalThis.fetch;
  const writes = [];
  globalThis.fetch = async (url, init = {}) => {
    const body = init.body ? JSON.parse(init.body) : null;
    if (init.method === "PUT") {
      writes.push(body);
      if (!("reply_contract" in body) || body.reply_contract === null) {
        return { ok: false, status: 422, statusText: "Unprocessable Entity",
          json: async () => ({ detail: { message: SERVER_REFUSAL, code: "agent_reply_contract_invalid", field: "reply_contract" } }) };
      }
      return { ok: true, status: 200, json: async () => ({ id: "a", replyContract: body.reply_contract }) };
    }
    return { ok: true, status: 200, json: async () => (String(url).endsWith("/meta") ? {} : []) };
  };
  try {
    const result = await save({ readJson, agentFormReplyFormat: state, agentFormName: "Renamed" });
    return { ...result, writes };
  } finally {
    globalThis.fetch = original;
  }
}

test("an invalid saved format blocks every save until a valid one is chosen; the refusal is shown, nothing is replaced", async () => {
  const invalid = replyFormatFromAgent(agentWith({ kind: "json_object", schema: { type: "object", properties: { a: { type: "string", enum: ["x"] } } } }));
  assert.equal(invalid.mode, "unsupported");
  const refused = await saveAgainstServer(invalid);
  assert.equal(refused.writes.length, 1, "the save is attempted, so the server decides");
  assert.deepEqual(Object.keys(refused.writes[0]).filter((key) => /reply/i.test(key)), [], "never null, never text on its own");
  assert.equal(refused.errors.length, 1);
  assert.ok(refused.errors[0].includes(SERVER_REFUSAL), "the server's message is shown verbatim");
  assert.match(refused.errors[0], /saved output format is not valid/);
  assert.match(refused.errors[0], /Choose Free text, or define the fields again/);

  const toText = await saveAgainstServer({ ...invalid, mode: "text" });
  assert.deepEqual(toText.writes[0].reply_contract, { kind: "text" }, "free text only when the author chooses it");
  assert.deepEqual(toText.errors, []);
  const redefined = await saveAgainstServer({ ...invalid, mode: "json_object", fields: [{ ...newReplyField(), name: "a" }] });
  assert.deepEqual(redefined.writes[0].reply_contract, contract({ a: { type: "string" } }));
  assert.deepEqual(redefined.errors, []);

  // An ordinary refusal of a valid agent is shown as the server sent it, without the format note.
  assert.equal(format.replyFormatSaveError(defaultReplyFormat(), "Agent name is required"), "Agent name is required");
});

test("invalid fields are refused before any request", async () => {
  for (const [fields, message] of [
    [[], /Add at least one field/],
    [[{ ...newReplyField(), name: "Bad" }], /must start with a lowercase letter/],
    [[{ ...newReplyField(), name: "a" }, { ...newReplyField(), name: "a" }], /used more than once/],
  ]) {
    const refused = await save({ agentFormReplyFormat: { mode: "json_object", fields, baseline: "absent" } });
    assert.equal(refused.write, undefined, "nothing is sent");
    assert.match(refused.errors[0], message);
    assert.match(refused.errors[0], /^Output format: /);
  }
});

test("the detail page summary distinguishes checked structured data from free text and unknown values", () => {
  assert.deepEqual(format.replyFormatSummary(agentWith(undefined)), { label: "Free text (not checked)", fields: [] });
  const checked = format.replyFormatSummary(agentWith(SAVED));
  assert.equal(checked.label, "Structured data (JSON, checked)");
  assert.deepEqual(checked.fields, [
    { name: "summary", type: "Text", required: true },
    { name: "tags", type: "List of texts", required: false },
    { name: "score", type: "Number", required: false },
  ]);
  assert.match(format.replyFormatSummary(agentWith({ kind: "xml" })).label, /^The saved output format is not valid\. The agent cannot be saved until/);
  assert.match(format.replyFormatSummary(agentWith(null)).label, /^The saved output format is not valid/, "null is not free text");
});

// The field and its sibling modules, each transpiled on its own.
function loadField(file = "AgentReplyFormatField") {
  const exports = {};
  const base = new URL(`../../src/admin/components/agentsTab/${file}`, import.meta.url);
  const source = fs.readFileSync(fs.existsSync(`${base.pathname}.tsx`) ? `${base.pathname}.tsx` : `${base.pathname}.ts`, "utf8");
  vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText, {
    exports, TextEncoder,
    require: (name) => (name.endsWith(".css") ? {} : name.endsWith("/agentReplyFormat") ? format
      : name.endsWith("/agentReplyFields") ? replyFields
      : name.startsWith("./") ? loadField(name.slice(2)) : require(name)),
  });
  return file === "AgentReplyFormatField" ? exports.AgentReplyFormatField : exports;
}

test("the field guides the author: choose structured data, edit fields, preview, and switching keeps the fields", () => {
  const Field = loadField();
  let current;
  function Harness({ initial }) {
    const [value, setValue] = useState(initial);
    current = value;
    return createElement(Field, { value, onChange: setValue });
  }
  let view;
  act(() => { view = TestRenderer.create(createElement(Harness, { initial: defaultReplyFormat() })); });
  const radios = () => view.root.findAll((node) => node.type === "input" && node.props.type === "radio");
  const byLabel = (label) => view.root.find((node) => node.props["aria-label"] === label);
  assert.deepEqual(radios().map((input) => [input.props.value, input.props.checked]), [["text", true], ["json_object", false]]);

  act(() => radios()[1].props.onChange());
  assert.equal(current.mode, "json_object");
  assert.equal(current.fields.length, 1, "one empty field to start with");
  // No error before the author has left the field (or tried to save).
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "agent-reply-format-row-error").length, 0);
  act(() => byLabel("Field 1 name").props.onBlur());
  assert.equal(text(view.root.find((node) => node.props["data-testid"] === "agent-reply-format-row-error")), "Field 1 needs a name.");
  act(() => byLabel("Field 1 name").props.onChange({ target: { value: "summary" } }));
  act(() => view.root.find((node) => node.type === "button" && text(node) === "+ Add field").props.onClick());
  act(() => byLabel("Field 2 name").props.onChange({ target: { value: "tags" } }));
  act(() => byLabel("Field 2 type").props.onChange({ target: { value: "list:integer" } }));
  const requiredBoxes = view.root.findAll((node) => node.type === "input" && node.props.type === "checkbox");
  act(() => requiredBoxes[1].props.onChange({ target: { checked: false } }));
  // Copied into this realm: the component builds its arrays in the module's own realm.
  assert.deepEqual(Array.from(current.fields, ({ name, type, list, required }) => [name, type, list, required]), [
    ["summary", "string", false, true], ["tags", "integer", true, false],
  ]);
  assert.deepEqual(JSON.parse(text(view.root.find((node) => node.props["data-testid"] === "agent-reply-format-preview"))), { summary: "text", tags: [1] });

  act(() => radios()[0].props.onChange());
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "agent-reply-format-fields").length, 0);
  act(() => radios()[1].props.onChange());
  assert.deepEqual(Array.from(current.fields, (field) => field.name), ["summary", "tags"], "switching back keeps the fields");
  act(() => byLabel("Remove field 1").props.onClick());
  assert.deepEqual(Array.from(current.fields, (field) => field.name), ["tags"]);

  act(() => view.unmount());
  act(() => { view = TestRenderer.create(createElement(Harness, { initial: replyFormatFromAgent(agentWith({ kind: "xml" })) })); });
  assert.deepEqual(radios().map((input) => input.props.checked), [false, false], "nothing preselected for an unknown saved value");
  const invalidNote = view.root.find((node) => node.props["data-testid"] === "agent-reply-format-invalid");
  assert.match(text(invalidNote), /The server refuses to save the agent until a valid format is chosen/);
  assert.doesNotMatch(text(invalidNote), /keeps it unchanged/);
  act(() => invalidNote.find((node) => node.type === "button" && text(node) === "Use free text").props.onClick());
  assert.equal(current.mode, "text", "the author's explicit choice");
  act(() => view.unmount());
  act(() => { view = TestRenderer.create(createElement(Harness, { initial: replyFormatFromAgent(agentWith({ kind: "xml" })) })); });
  act(() => view.root.find((node) => node.type === "button" && text(node) === "Define fields again").props.onClick());
  assert.deepEqual([current.mode, current.fields.length], ["json_object", 1], "one empty field to define");
  act(() => view.unmount());
});
