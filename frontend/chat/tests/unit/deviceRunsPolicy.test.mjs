// Device-run policy in the UI: devices are not pickable while the platform or the Workspace keeps them
// off, and seat is offered only where the Workspace allows it (D2).
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  deviceRunsBlocked,
  readDeviceRunsPolicy,
  workspaceAllowsSeat,
} from "../../src/chat/devices/deviceRunsPolicyModel.ts";

const payload = (overrides = {}) => ({ project_id: "ws-1", policy_valid: true, enabled: true,
  allowed_profiles: ["governed", "seat"], platform_enabled: true, classification_allows: true, seat_allowed: true,
  can_edit: false, ...overrides });

test("off by default, platform switch first, then the Workspace, then the classification", () => {
  assert.equal(deviceRunsBlocked(readDeviceRunsPolicy(payload()), "Sample"), null);
  assert.match(deviceRunsBlocked(readDeviceRunsPolicy(payload({ enabled: false })), "Sample"), /off for the Workspace “Sample”/);
  assert.match(deviceRunsBlocked(readDeviceRunsPolicy(payload({ platform_enabled: false, enabled: false })), "S"),
    /switched off on this platform/);
  assert.match(deviceRunsBlocked(readDeviceRunsPolicy(payload({ classification_allows: false })), "S"), /classification/);
  assert.match(deviceRunsBlocked(readDeviceRunsPolicy({ project_id: "ws-1" }), "S"), /off for the Workspace/);
});

test("seat needs both the Workspace's profile list and its seat decision", () => {
  assert.equal(workspaceAllowsSeat(readDeviceRunsPolicy(payload())), true);
  assert.equal(workspaceAllowsSeat(readDeviceRunsPolicy(payload({ seat_allowed: false }))), false);
  assert.equal(workspaceAllowsSeat(readDeviceRunsPolicy(payload({ allowed_profiles: ["governed"] }))), false);
  assert.equal(workspaceAllowsSeat(null), false);
});

test("chat approvals count as change confirmation by default; the stale-turn time is read", () => {
  const defaults = readDeviceRunsPolicy(payload());
  assert.equal(defaults.chatApprovalsConfirmChanges, true);
  assert.equal(defaults.staleTurnMinutes, 10);
  const off = readDeviceRunsPolicy(payload({ chat_approvals_confirm_changes: false, stale_turn_minutes: 30 }));
  assert.equal(off.chatApprovalsConfirmChanges, false);
  assert.equal(off.staleTurnMinutes, 30);
});
