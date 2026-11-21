// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/observabilityHealth.test.mjs
import assert from "node:assert/strict";
import { test } from "node:test";

import { listAdminAreaTabRefs } from "../../src/admin/config/adminPanelAreas.ts";
import { countByStatus, HEALTH_BADGES, worstStatus } from "../../src/admin/components/observability/healthModel.ts";

const row = (status) => ({ component: status, status, since: null, last_check: null, detail: "", link: null });

test("Health is the first Operate page", () => {
  assert.ok(listAdminAreaTabRefs("operations").some((ref) => ref.id === "observabilityHealth" && !ref.hidden));
});

test("unknown and disabled are their own states, never ok, each with an icon and a word", () => {
  assert.deepEqual(HEALTH_BADGES.unknown, ["neutral", "? unknown"]);
  assert.deepEqual(HEALTH_BADGES.disabled, ["neutral", "– disabled"]);
  assert.equal(worstStatus([row("ok"), row("unknown")]), "unknown");
  assert.equal(worstStatus([row("ok"), row("failing"), row("degraded")]), "failing");
  assert.equal(worstStatus([row("disabled")]), "disabled");
  assert.equal(worstStatus([]), "unknown");
  assert.deepEqual(countByStatus([row("ok"), row("ok"), row("failing")]), { ok: 2, failing: 1 });
});
