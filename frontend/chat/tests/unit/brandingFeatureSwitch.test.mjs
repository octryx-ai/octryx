// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/brandingFeatureSwitch.test.mjs
//
// Branding is an off-by-default platform feature (server config only): no sidebar entry while
// it is off, a deep link still resolves to the page (which shows the disabled state), and the
// chat treats a missing flag as off.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  isAdminTabRefEnabled,
  listAdminAreaTabRefs,
  resolveAdminAreaTab,
} from "../../src/admin/config/adminPanelAreas.ts";
import { resolveBranding } from "../../src/chat/branding.ts";

const brandingRef = () => listAdminAreaTabRefs("admin").find((ref) => ref.id === "branding");

test("the Branding entry is gated by the branding platform feature, off by default", () => {
  assert.equal(brandingRef().feature, "branding");
  assert.equal(isAdminTabRefEnabled(brandingRef()), false);
  assert.equal(isAdminTabRefEnabled(brandingRef(), { branding: false }), false);
  assert.equal(isAdminTabRefEnabled(brandingRef(), { branding: true }), true);
});

test("ungated Organization pages stay visible", () => {
  for (const id of ["projects", "backupRestore", "corpIdentity"]) {
    const ref = listAdminAreaTabRefs("admin").find((entry) => entry.id === id);
    assert.equal(isAdminTabRefEnabled(ref), true, id);
  }
});

test("a Branding deep link still resolves to its page", () => {
  assert.equal(resolveAdminAreaTab("admin", "branding"), "branding");
});

test("resolveBranding treats a missing or false flag as off", () => {
  assert.equal(resolveBranding(undefined).enabled, false);
  assert.equal(resolveBranding({ app_name: "Acme", enabled: false }).enabled, false);
  assert.equal(resolveBranding({ app_name: "Acme", enabled: true }).enabled, true);
});
