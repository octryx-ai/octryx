// The Model pill of a device run (model picker): rows come from the platform (no model names here), the
// choice rides with the target, a model the profile no longer offers falls back to the device default, and the
// job header shows the effective model.
import assert from "node:assert/strict";
import { test } from "node:test";

import { buildChatSendBody } from "../../src/chat/chatSendPayload.ts";
import { keptModel, modelPillText, readDeviceModels } from "../../src/chat/devices/deviceModelsModel.ts";
import { jobModelLabel, readJob } from "../../src/chat/devices/deviceJobsModel.ts";
import { readableModelName } from "../../src/chat/devices/modelNames.ts";

const rows = readDeviceModels({ profile: "seat", reason: null, models: [
  { id: "sub-model", display_name: "sub-model", source: "subscription" },
  { id: "company/co-x", display_name: "Co X (company)", source: "company", description: "billed" },
  { display_name: "no id" },
] });

test("rows are read defensively and label the pill", () => {
  assert.deepEqual(rows.models.map((model) => model.id), ["sub-model", "company/co-x"]);
  assert.equal(readDeviceModels({ models: [] }), null);
  assert.equal(modelPillText("", rows), "Model: device default");
  assert.equal(modelPillText("company/co-x", rows), "Model: Co X (company)");
  assert.equal(modelPillText("unknown", null), "Model: Unknown");
  assert.equal(rows.models[0].label, "Sub Model"); // a row whose display name is its id
});

test("the pill never shows a bare model id", () => {
  const seat = readDeviceModels({ profile: "seat", models: [
    { id: "claude-opus-5-5", display_name: "Claude Opus 5.5", source: "subscription" },
    { id: "claude-sonnet-5", display_name: "claude-sonnet-5", source: "subscription" },
  ] });
  assert.equal(modelPillText("claude-opus-5-5", seat), "Model: Claude Opus 5.5");
  assert.equal(modelPillText("claude-sonnet-5", seat), "Model: Claude Sonnet 5");
  assert.equal(modelPillText("claude-opus-5-5", null), "Model: Claude Opus 5.5"); // rows not loaded (yet)
  assert.equal(readableModelName("claude-haiku-4-5-20251001"), "Claude Haiku 4.5");
  assert.equal(readableModelName("company/co-x"), "company/co-x");
  assert.equal(modelPillText("", null), "Model: device default");
});

test("a model the profile does not offer falls back to the device default", () => {
  assert.equal(keptModel("company/co-x", rows), "company/co-x");
  assert.equal(keptModel("governed-only", rows), "");
  assert.equal(keptModel("company/co-x", null), "company/co-x"); // rows not loaded: nothing is changed
  assert.equal(keptModel(undefined, rows), "");
});

test("the chosen model is sent with the device target", () => {
  const body = buildChatSendBody("Run", {
    sessionId: "s", projectId: "ws", runtimeTargetId: "", thinkingLevel: "light", routingOverridesEnabled: true,
    agentId: "", workflowKey: "",
    executionTarget: { kind: "device", deviceId: "dev_a", folder: "/f", profile: "seat", model: "company/co-x" },
  });
  assert.equal(body.execution_target.model, "company/co-x");
  assert.equal(body.runtime_target_id, "");
});

test("the job header names the effective model", () => {
  const job = (fields) => readJob({ id: "dj_1", profile: "seat", ...fields });
  assert.equal(jobModelLabel(job({ model: "claude-opus-5-5", requested_model: "sub-model" })), "seat · Claude Opus 5.5");
  assert.equal(jobModelLabel(job({ requested_model: "sub-model" })), "seat · Sub Model");
  assert.equal(jobModelLabel(job({})), "seat · device default model");
});
