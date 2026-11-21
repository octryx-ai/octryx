import assert from "node:assert/strict";
import { test } from "node:test";
import {
  jsonFieldError,
  knownValueOptions,
  parseJsonArray,
  toggleListValue,
} from "../../src/chat/coding/codingGovernanceForm.ts";
import { EMPTY_PIPELINE_FORM, pipelineFormToPayload, pipelineStageRows } from "../../src/chat/coding/codingPipelineForm.ts";

test("JSON fields report inline errors with the same rules the save path enforces", () => {
  assert.equal(jsonFieldError("", "object"), null);
  assert.equal(jsonFieldError("", "array"), null);
  assert.equal(jsonFieldError("{\"a\": 1}", "object"), null);
  assert.equal(jsonFieldError("{\"a\": ", "object"), "Not valid JSON. Check quotes, commas and brackets.");
  assert.equal(jsonFieldError("[]", "object"), "Must be a JSON object, for example {}.");
  assert.equal(jsonFieldError("{}", "objectList"), "Must be a JSON list, for example [].");
  assert.deepEqual(parseJsonArray('["docs/**", {"issue_keys": ["RIVER-1"]}]', "Exceptions JSON"), [
    "docs/**",
    { issue_keys: ["RIVER-1"] },
  ]);
});

test("editor payloads keep their API keys", () => {
  assert.deepEqual(Object.keys(pipelineFormToPayload(EMPTY_PIPELINE_FORM)).sort(), [
    "controls", "description", "id", "is_active", "name", "project_id", "required_stage_keys", "review_status", "stages",
  ]);
});


test("checkbox lists toggle one value and keep unknown entries", () => {
  assert.equal(toggleListValue("read_logs\ncustom", "trigger", true), "read_logs\ncustom\ntrigger");
  assert.equal(toggleListValue("read_logs, trigger", "trigger", false), "read_logs");
  assert.deepEqual(knownValueOptions("needs_review", ["approved", "needs_review", null, " "]), ["needs_review", "approved"]);
});

test("pipeline steps come from the stages JSON and disappear while it is invalid", () => {
  assert.equal(pipelineStageRows(EMPTY_PIPELINE_FORM.stages).length, 12);
  assert.deepEqual(pipelineStageRows('[{"key": "intake"}, "x", {"label": "no key"}]'), [{ key: "intake", label: "intake" }]);
  assert.equal(pipelineStageRows("{"), null);
});

