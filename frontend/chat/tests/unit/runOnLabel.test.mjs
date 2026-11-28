import assert from "node:assert/strict";
import { test } from "node:test";

import { POOL_DEVICE_ID, runOnLabel, runsOnOwnDevice } from "../../src/chat/devices/executionTarget.ts";

const device = (deviceId) => ({ kind: "device", deviceId, folder: "/workspace", profile: "governed" });

test("a chat on the server runners says Server, not your device", () => {
  assert.equal(runOnLabel(device(POOL_DEVICE_ID), null), "Run on: Server");
  assert.equal(runsOnOwnDevice(device(POOL_DEVICE_ID)), false);
  assert.equal(runOnLabel({ kind: "server" }), "Run on: Server");
});

test("a chat on one of the person's devices names it", () => {
  assert.equal(runOnLabel(device("d-1"), "Mac"), "Run on: Mac");
  assert.equal(runOnLabel(device("d-1"), null), "Run on: your device");
  assert.equal(runsOnOwnDevice(device("d-1")), true);
});
