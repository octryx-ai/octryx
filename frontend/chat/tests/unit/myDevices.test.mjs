// My settings → Devices: the owner's device list is read defensively, the status says what the device can
// do now, and a refusal shows its fixed reason in words, never a server text.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  deviceErrorText,
  deviceStatus,
  readMyDevices,
  relativeTime,
} from "../../src/chat/devices/devicesModel.ts";

const device = (overrides = {}) => ({
  id: "dev_a", name: "Laptop", os: "macos", paused: false, connected: true, running_jobs: 0, max_parallel_jobs: 4,
  profiles: ["governed"], folders: ["/home/sample/src"], last_seen_at: null, ...overrides,
});

test("reads the owner's list and drops malformed entries", () => {
  const listed = readMyDevices({ items: [device(), { id: 3 }, null], all_paused: false });
  assert.equal(listed.items.length, 1);
  assert.deepEqual(listed.items[0].folders, ["/home/sample/src"]);
  assert.equal(readMyDevices({ items: "x" }), null);
  assert.equal(readMyDevices(null), null);
});

test("status: paused beats everything, offline is not selectable, running jobs are counted", () => {
  const read = (raw) => readMyDevices({ items: [device(raw)] }).items[0];
  assert.deepEqual(deviceStatus(read({ paused: true })), { label: "Paused", tone: "attention", offline: false });
  assert.equal(deviceStatus(read({ connected: false })).offline, true);
  assert.deepEqual(deviceStatus(read({ connected: false, needs_login: true })),
    { label: "Needs login", tone: "attention", offline: true });
  assert.equal(deviceStatus(read({ running_jobs: 2 })).label, "2 jobs");
  assert.equal(deviceStatus(read({})).label, "Online");
});

test("refusals map to fixed words; unknown codes and texts never leak", () => {
  assert.equal(deviceErrorText({ code: "device_folders_platform_cannot_add" }),
    "Folders can only be added on the device itself.");
  assert.equal(deviceErrorText({ code: "internal", message: "Traceback secret" }),
    "The change could not be saved. Try again.");
});

test("relative time reads naive server timestamps as UTC", () => {
  const now = Date.parse("2026-10-07T12:00:00Z");
  assert.equal(relativeTime("2026-10-07T09:00:00", now), "3 h ago");
  assert.equal(relativeTime(null, now), "never");
});
