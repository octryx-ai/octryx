// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/schemaForm*.test.mjs"
// Value-shaping helpers of the schema form: pointer updates, omission rules, labels, component guards.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

import { getAtPointer, setAtPointer } from "../../src/admin/components/schemaForm/schemaPointer.ts";
import { fieldLabel, humanizeKey } from "../../src/admin/components/schemaForm/schemaResolve.ts";
import { orphanErrors } from "../../src/admin/components/schemaForm/schemaValidate.ts";
import {
  emptyCollectionValue,
  mapKeyProblem,
  parseNumberInput,
  parseTagInput,
  textInputValue,
} from "../../src/admin/components/schemaForm/schemaWidgets.ts";

const FORM_DIR = new URL("../../src/admin/components/schemaForm/", import.meta.url);

test("setAtPointer updates immutably and removes on undefined", () => {
  const value = { loop: { backTo: "a", maxIterations: 2 }, tools: ["x", "y"], "a/b": 1 };
  const frozen = structuredClone(value);
  const updated = setAtPointer(value, "/loop/maxIterations", 3);
  assert.equal(updated.loop.maxIterations, 3);
  assert.notEqual(updated.loop, value.loop);
  assert.equal(updated.tools, value.tools);
  assert.deepEqual(value, frozen);

  assert.deepEqual(setAtPointer(value, "/loop/backTo", undefined).loop, { maxIterations: 2 });
  assert.equal("loop" in setAtPointer(value, "/loop", undefined), false);
  assert.deepEqual(setAtPointer(value, "/tools/0", undefined).tools, ["y"]);
  assert.equal(setAtPointer(value, "/a~1b", undefined)["a/b"], undefined);
  assert.deepEqual(setAtPointer({}, "/output/schemaRef", "Report"), { output: { schemaRef: "Report" } });
  assert.deepEqual(setAtPointer({}, "/output/schemaRef", undefined), {});
  assert.equal(getAtPointer(updated, "/tools/1"), "y");
});

test("inputs omit unset values instead of writing null or empty strings", () => {
  assert.equal(textInputValue(""), undefined);
  assert.equal(textInputValue(" a "), " a ");
  assert.equal(parseNumberInput(""), undefined);
  assert.equal(parseNumberInput("abc"), undefined);
  assert.equal(parseNumberInput("4"), 4);
  assert.equal(parseTagInput("  plan  ", "string"), "plan");
  assert.equal(parseTagInput("   ", "string"), undefined);
  assert.equal(parseTagInput("7", "integer"), 7);
  assert.equal(emptyCollectionValue([], false), undefined);
  assert.deepEqual(emptyCollectionValue([], true), []);
  assert.equal(emptyCollectionValue({}, false), undefined);
});

test("labels humanize the property key; x-ui.label wins over Pydantic titles", () => {
  assert.equal(humanizeKey("maxIterations"), "Max iterations");
  assert.equal(humanizeKey("schemaRef"), "Schema ref");
  assert.equal(humanizeKey("on_exhausted"), "On exhausted");
  assert.equal(humanizeKey("mcpURLPrefix"), "Mcp URL prefix");
  assert.equal(fieldLabel("maxIterations", { title: "Maxiterations" }), "Max iterations");
  assert.equal(fieldLabel("mcp", { title: "Mcp", "x-ui": { label: "MCP servers" } }), "MCP servers");
});

test("map keys are checked against propertyNames and patternProperties before adding", () => {
  const branches = { type: "object", additionalProperties: { type: "string" }, propertyNames: { minLength: 1, maxLength: 3 } };
  assert.equal(mapKeyProblem(branches, "yes", ["no"]), undefined);
  assert.equal(mapKeyProblem(branches, "no", ["no"]), "Key already exists");
  assert.equal(mapKeyProblem(branches, "four", []), "Key allows at most 3 characters");
  const args = { type: "object", patternProperties: { "^[a-z][A-Za-z0-9_]{0,63}$": { type: "string" } } };
  assert.equal(mapKeyProblem(args, "query", []), undefined);
  assert.match(mapKeyProblem(args, "Query", []), /^Key must match/);
});

test("errors no field can show are surfaced, hidden fields are left to the host", () => {
  const root = { type: "object", properties: { kind: { const: "end" }, title: { type: "string" } } };
  const errors = { "": ["Graph invalid"], "/kind": ["Required"], "/title": ["Too long"], "/ghost": ["Unknown field"] };
  assert.deepEqual(orphanErrors(root, errors, ["kind"]), [
    ["", "Graph invalid"],
    ["/ghost", "Unknown field"],
  ]);
});

test("component sources keep the contract: exports, accessibility wiring, tokens only", () => {
  const files = readdirSync(FORM_DIR);
  const sources = files.filter((name) => /\.tsx?$/.test(name)).map((name) => readFileSync(new URL(name, FORM_DIR), "utf8")).join("\n");
  for (const name of ["SchemaForm", "resolveRef", "fieldOrder", "pickOneOfBranch", "defaultValueFor", "setAtPointer", "clientFieldErrors"]) {
    assert.match(sources, new RegExp(`export (async )?(function|const) ${name}\\b`), name);
  }
  const form = readFileSync(new URL("SchemaForm.tsx", FORM_DIR), "utf8");
  assert.match(form, /export function SchemaForm\(/);
  assert.match(form, /clientFieldErrors\(schema, schema, value\)/);
  const field = readFileSync(new URL("SchemaField.tsx", FORM_DIR), "utf8");
  assert.match(field, /htmlFor=\{id\}/);
  assert.match(field, /aria-describedby/);
  assert.match(field, /context\.renderField\?\.\(/);
  const scalar = readFileSync(new URL("SchemaScalarWidgets.tsx", FORM_DIR), "utf8");
  assert.match(scalar, /"aria-invalid": props\.invalid/);
  assert.match(scalar, /Unsupported field type/);
  for (const name of files.filter((file) => /\.(tsx|css)$/.test(file))) {
    const source = readFileSync(new URL(name, FORM_DIR), "utf8");
    assert.doesNotMatch(source, /#[0-9a-fA-F]{3,8}\b/, `${name} must use tokens, not hex colors`);
    assert.ok(source.split("\n").length <= 500, `${name} exceeds 500 lines`);
  }
});
