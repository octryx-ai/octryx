// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/schemaForm*.test.mjs"
// Contract tests of the generic schema form helpers over small inline JSON Schemas.
import assert from "node:assert/strict";
import { test } from "node:test";

import { defaultValueFor } from "../../src/admin/components/schemaForm/schemaDefaults.ts";
import { classifySchema, fieldOrder, normalizeField, resolveRef } from "../../src/admin/components/schemaForm/schemaResolve.ts";
import { pickOneOfBranch, switchUnionVariant } from "../../src/admin/components/schemaForm/schemaUnion.ts";
import { clientFieldErrors } from "../../src/admin/components/schemaForm/schemaValidate.ts";

const step = {
  type: "object",
  additionalProperties: false,
  required: ["kind", "agent", "model"],
  properties: {
    kind: { const: "agent_step" },
    agent: { type: "string", pattern: "^[a-z][a-z0-9-]*$" },
    model: { type: "string" },
    tools: { type: "array", items: { type: "string", pattern: "^[a-z_]+$" } },
    next: { anyOf: [{ type: "string" }, { type: "null" }], "x-ui": { widget: "edge", port: "next" } },
    loop: { anyOf: [{ $ref: "#/$defs/Loop" }, { type: "null" }] },
    reducer: { enum: ["merge", "first"] },
  },
  $defs: {
    Loop: {
      title: "Loop",
      type: "object",
      additionalProperties: false,
      required: ["backTo", "maxIterations", "onExhausted"],
      properties: {
        backTo: { type: "string" },
        maxIterations: { type: "integer", exclusiveMinimum: 0 },
        onExhausted: {
          oneOf: [
            { title: "StopAction", type: "object", required: ["action"], properties: { action: { const: "stop" } } },
            {
              title: "RouteAction",
              type: "object",
              required: ["action", "to"],
              properties: { action: { const: "route" }, to: { type: "string" } },
            },
          ],
          discriminator: { propertyName: "action" },
        },
      },
    },
  },
};

test("required fields come first and a skeleton fills only const values", () => {
  const order = fieldOrder(step);
  assert.deepEqual(new Set(order.slice(0, 3)), new Set(["kind", "agent", "model"]));
  assert.deepEqual(defaultValueFor(step, step), { kind: "agent_step" });
  const route = resolveRef(step, step.$defs.Loop.properties.onExhausted.oneOf[1]);
  assert.deepEqual(defaultValueFor(step, route), { action: "route" });
});

test("nullable anyOf unwraps with outer x-ui preserved; $ref siblings override the target", () => {
  const next = normalizeField(step, step.properties.next);
  assert.equal(next.nullable, true);
  assert.equal(next.schema.type, "string");
  assert.deepEqual(next.schema["x-ui"], { widget: "edge", port: "next" });
  const loop = normalizeField(step, step.properties.loop);
  assert.equal(loop.nullable, true);
  assert.deepEqual(loop.schema.required, ["backTo", "maxIterations", "onExhausted"]);
  const merged = resolveRef(step, { $ref: "#/$defs/Loop", description: "Override" });
  assert.equal(merged.description, "Override");
  assert.equal(merged.title, "Loop");
  assert.deepEqual(resolveRef(step, { $ref: "#/$defs/Missing" }), { $ref: "#/$defs/Missing" });
  assert.equal(classifySchema({}), "any");
});

test("discriminated oneOf picks the branch by discriminator; switching keeps shared fields", () => {
  const exhausted = step.$defs.Loop.properties.onExhausted;
  assert.equal(pickOneOfBranch(step, exhausted, { action: "stop" }).index, 0);
  const route = pickOneOfBranch(step, exhausted, { action: "route", to: "review" });
  assert.equal(route.index, 1);
  assert.equal(route.branch.title, "RouteAction");
  assert.equal(pickOneOfBranch(step, exhausted, { action: "retry" }), null);
  assert.equal(pickOneOfBranch(step, exhausted, undefined), null);
  assert.deepEqual(switchUnionVariant(step, route.branch, { action: "stop" }), { action: "route" });

  const structural = { oneOf: [{ const: "off" }, { type: "integer" }, { type: "object", properties: { mode: { const: "x" } } }] };
  assert.equal(pickOneOfBranch(structural, structural, "off").index, 0);
  assert.equal(pickOneOfBranch(structural, structural, 3).index, 1);
  assert.equal(pickOneOfBranch(structural, structural, { mode: "x" }).index, 2);
  assert.equal(pickOneOfBranch(structural, structural, { mode: "y" }), null);
});

test("client checks: pattern, required, bounds, integer, enum, const, unknown keys, variants", () => {
  const errors = clientFieldErrors(step, step, {
    kind: "agent_step",
    agent: "Bad Agent",
    loop: { backTo: "plan", maxIterations: 0, onExhausted: { action: "route" } },
    tools: ["ok", "Not-Ok"],
    reducer: "concat",
    extra: true,
  });
  assert.match(errors["/agent"][0], /^Invalid format/);
  assert.deepEqual(errors["/model"], ["Required"]);
  assert.deepEqual(errors["/loop/maxIterations"], ["Must be greater than 0"]);
  assert.deepEqual(errors["/loop/onExhausted/to"], ["Required"]);
  assert.equal(errors["/tools/0"], undefined);
  assert.match(errors["/tools/1"][0], /^Invalid format/);
  assert.deepEqual(errors["/reducer"], ["Not an allowed option"]);
  assert.deepEqual(errors["/extra"], ["Unknown field"]);

  assert.deepEqual(clientFieldErrors(step, step, { kind: "tool_step", agent: "a", model: "m", loop: { backTo: "a", maxIterations: 1.5, onExhausted: { action: "other" } } }), {
    "/kind": ['Must be "agent_step"'],
    "/loop/maxIterations": ["Must be a whole number"],
    "/loop/onExhausted": ["Choose a variant"],
  });
});
