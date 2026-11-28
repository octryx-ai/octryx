// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/sessionRunControl.test.mjs
//
// Stop and continue of a chat session: a failed coordinator status request on stop shows the server's error and calls
// no other endpoint; a direct session stops through the session endpoint, a coordinator session through the
// coordinator control; continue always uses the session endpoint.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

const require = createRequire(import.meta.url);
const ts = require("typescript");
const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");

function loadRunControl(mocks) {
  const file = path.join(SRC, "chat/useSessionActions.runControl.ts");
  const output = ts.transpileModule(fs.readFileSync(file, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, esModuleInterop: true },
  }).outputText;
  const module = { exports: {} };
  vm.runInNewContext(output, {
    module, exports: module.exports, Error, JSON, Promise,
    require: (name) => mocks[path.basename(name)] ?? require(name),
  });
  return module.exports;
}

function harness({ statusResult, coordinatorMode = "direct" }) {
  const calls = [];
  const errors = [];
  const contract = {
    coordinator_mode: coordinatorMode, root_session_id: "s-1", can_stop: true, aggregate_status: "",
  };
  const coordinatorClient = {
    loadSessionCoordinatorStatus: async (id) => {
      calls.push(`status:${id}`);
      if (statusResult instanceof Error) throw statusResult;
      return contract;
    },
    applySessionCoordinatorStop: async (id) => { calls.push(`coordinator-stop:${id}`); return { contract }; },
    shouldUseCoordinatorStop: (value) => value.coordinator_mode === "deterministic_workflow",
    describeCoordinatorStopBlockedState: () => "stop blocked",
  };
  const appHelpers = {
    buildChatSearch: () => "?session_id=s-1",
    readJson: async (url) => { calls.push(`session:${url}`); return { selectedSession: { id: "s-1" } }; },
  };
  const { createSessionRunControlHandlers } = loadRunControl({
    sessionCoordinatorClient: coordinatorClient, appHelpers, chatApiClient: appHelpers,
  });
  const args = (running) => ({
    selectedSession: { id: "s-1" }, selectedSessionIsRunning: running, selectedSessionIsArchived: false,
    selectedRuntimeTargetId: null, selectedThinkingLevel: null,
    setSending() {}, setError: (value) => errors.push(value), applyState() {}, loadState: async () => {},
  });
  return { calls, errors, handlers: (running) => createSessionRunControlHandlers(args(running)) };
}

test("a failed coordinator status shows the server's error and calls no session endpoint", async () => {
  const stop = harness({ statusResult: new Error("Session not found") });
  await stop.handlers(true).handleStop();
  assert.deepEqual(stop.calls, ["status:s-1"]);
  assert.deepEqual(stop.errors, [null, "Session not found"]);
});

test("a direct session stops through the session endpoint; continue never asks the coordinator", async () => {
  const stop = harness({ statusResult: "ok" });
  await stop.handlers(true).handleStop();
  assert.deepEqual(stop.calls, ["status:s-1", "session:/chat/api/sessions/s-1/stop"]);

  const resume = harness({ statusResult: "ok" });
  await resume.handlers(false).handleContinue();
  assert.deepEqual(resume.calls, ["session:/chat/api/sessions/s-1/continue"]);
});

test("a coordinator session stops through the coordinator control", async () => {
  const stop = harness({ statusResult: "ok", coordinatorMode: "deterministic_workflow" });
  await stop.handlers(true).handleStop();
  assert.deepEqual(stop.calls, ["status:s-1", "coordinator-stop:s-1"]);
});
