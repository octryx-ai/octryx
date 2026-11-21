// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminReturnLink.test.mjs
// Admin › Connections › Repositories and Jira write-back open pages of Coding and Work, and nothing
// led back. The address carries `return_to=admin-connections`; the page shows "← Admin › Connections" above it, and
// the area keeps its layout below the bar (its full-height rule gives way to the remaining height).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";

import { adminReturnOf, RETURN_TO_CONNECTIONS } from "../../src/chat/navigation/adminReturn.ts";

const SRC = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../src");

test("an address opened from Admin › Connections leads back there; any other does not", () => {
  assert.deepEqual(RETURN_TO_CONNECTIONS, { return_to: "admin-connections" });
  assert.deepEqual(adminReturnOf("?area=work&work_view=writeback&return_to=admin-connections"),
    { key: "admin-connections", label: "Admin › Connections", tab: "adminConnections" });
  assert.equal(adminReturnOf("?area=work&work_view=writeback"), null);
  assert.equal(adminReturnOf("?return_to=https://evil.example"), null, "only known places, never an address");
});

test("the area below the bar takes the remaining height instead of the full window", () => {
  const css = fs.readFileSync(path.join(SRC, "chat/navigation/admin-return.css"), "utf8");
  assert.match(css, /\.admin-return \{[^}]*height: 100vh;[^}]*\}/);
  assert.match(css, /\.admin-return > :not\(\.admin-return__bar\) \{[^}]*height: auto;[^}]*min-height: 0;|\.admin-return > :not\(\.admin-return__bar\) \{[^}]*min-height: 0;[^}]*height: auto;/);
});

test("the pending Connections page links to both pages with the way back", () => {
  const page = fs.readFileSync(path.join(SRC, "admin/components/connections/ConnectionsPage.tsx"), "utf8");
  assert.match(page, /coding_view=repositories&return_to=admin-connections/);
  assert.match(page, /work_view=writeback&return_to=admin-connections/);
});
