import assert from "node:assert/strict";
import test from "node:test";

import {
  composerTargetOf,
  readRuntimeTargetChoices,
  runtimeTargetReason,
  runtimeTargetText,
  runtimeTargetsPath,
} from "../../src/chat/workflowRun/runtimeTargetModel.ts";
import { runActionRequest, startRunBody } from "../../src/chat/workflowRun/workflowRunRequests.ts";
import { runStatusLabel } from "../../src/chat/workflowRun/workflowRunStatus.ts";

const device = { kind: "device", device_id: "dev_1", folder: "/Users/dev/pay", profile: "seat" };
const choices = {
  options: [
    { key: "server", label: "Server", target: { kind: "server" } },
    { key: "terminal", label: "octryx-claude terminal", target: { kind: "terminal" } },
    { key: "device:dev_1:seat:/Users/dev/pay", label: "Mac · /Users/dev/pay · seat (online)", target: device },
    { key: "broken", label: "no target" },
  ],
  default: "device:dev_1:seat:/Users/dev/pay",
};

test("the start dialog lists the valid choices and keeps the last choice as default", () => {
  const read = readRuntimeTargetChoices(choices);
  assert.deepEqual(read.options.map((option) => option.key), ["server", "terminal", "device:dev_1:seat:/Users/dev/pay"]);
  assert.equal(read.default, "device:dev_1:seat:/Users/dev/pay");
  assert.equal(readRuntimeTargetChoices({ ...choices, default: "gone" }).default, "server");
  assert.equal(runtimeTargetsPath("ws 1"), "/api/v1/workflow-runs/runtime-targets?project_id=ws%201");
});

test("a start names the chosen target; without one it is the Server's default", () => {
  assert.deepEqual(startRunBody("epic-delivery", "item-1", "", "", device),
    { workflow_key: "epic-delivery", work_item_id: "item-1", runtime_target: device });
  assert.equal("runtime_target" in startRunBody("epic-delivery", "item-1"), false);
});

test("change_runtime posts the chosen option's target", () => {
  const action = { key: "change_runtime", label: "Change where the run executes",
    input: { name: "runtime_target", kind: "runtime_target", label: "Run on", default: "server",
      options: readRuntimeTargetChoices(choices).options } };
  const request = runActionRequest({ id: "run-1", waiting: null }, action, "device:dev_1:seat:/Users/dev/pay");
  assert.deepEqual(request.body, { action: "change_runtime", runtime_target: device });
});

test("the card says where the run executes and a device run's composer sends from it", () => {
  const target = { kind: "device", label: "Mac (/Users/dev/pay, seat)", device_id: "dev_1", folder: "/Users/dev/pay",
    profile: "seat", online: false };
  assert.equal(runtimeTargetText(target), "Runs on Mac (/Users/dev/pay, seat) · offline");
  assert.equal(runtimeTargetText({ kind: "server", label: "the Server" }), "Runs on the Server");
  assert.deepEqual(composerTargetOf(target), { kind: "device", deviceId: "dev_1", folder: "/Users/dev/pay",
    profile: "seat", model: "" });
  assert.equal(composerTargetOf({ kind: "server", label: "the Server" }), null);
  assert.equal(runStatusLabel({ status: "waiting", waiting_kind: "waiting_for_device", pause_reason: null,
    outcome: null }), "Waiting for the device");
});

test("auto is offered and kept as the default; a run chosen automatically says why", () => {
  const read = readRuntimeTargetChoices({ default: "auto", options: [
    { key: "auto", label: "Automatic (your device with a seat first, governed when a rule or the seat allowance says so)", target: { kind: "auto" } },
    { key: "server", label: "Server", target: { kind: "server" } },
  ] });
  assert.deepEqual(read.options.map((option) => option.key), ["auto", "server"], "auto is not filtered out");
  assert.equal(read.default, "auto");
  const chosen = { kind: "device", label: "Studio Mac (/Users/dev/src, seat)", device_id: "dev_1", folder: "/Users/dev/src",
    profile: "seat", resolved_from: "auto", reason: "seat on Studio Mac" };
  assert.equal(runtimeTargetText(chosen), "Runs on Studio Mac (/Users/dev/src, seat)");
  assert.equal(runtimeTargetReason(chosen), "Chosen automatically: seat on Studio Mac");
  assert.equal(runtimeTargetReason({ kind: "server", label: "the Server" }), "Chosen when started",
    "an explicit choice says so at the same place");
  assert.equal(runtimeTargetReason(null), null);
});
