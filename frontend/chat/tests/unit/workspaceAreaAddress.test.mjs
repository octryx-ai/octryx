// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/workspaceAreaAddress.test.mjs
//
// The workspace area address: only current area keys name an area, an area switch keeps only what the target area
// needs from the address (concept finding 11), and a Coding page opens by its own `coding_view`.
import assert from "node:assert/strict";
import { test } from "node:test";

import { areaSwitchHref, workspaceAreaFromKey } from "../../src/chat/areaNavigation.ts";
import { load } from "./workCodingSupport.mjs";

const BASE = "https://octryx.test/chat";

test("only current area keys name an area", () => {
  for (const area of ["chat", "knowledge", "work", "coding", "agents", "workflows", "admin", "operations", "personal", "help"]) {
    assert.equal(workspaceAreaFromKey(area), area);
  }
  for (const key of ["nope", "toString", "", null, undefined]) {
    assert.equal(workspaceAreaFromKey(key), null, String(key));
  }
});

test("an area switch drops foreign fields and keeps what the target needs", () => {
  const from = `${BASE}?area=work&work_view=writeback&phased=8d2d&tab=x&workspace_id=ws-1&work_item_id=i-1`;
  assert.equal(areaSwitchHref(from, "admin"), `${BASE}?area=admin&workspace_id=ws-1`);
  assert.equal(areaSwitchHref(from, "coding"), `${BASE}?area=coding&workspace_id=ws-1&work_item_id=i-1`);
  assert.equal(areaSwitchHref(from, "coding", { coding_view: "rules" }),
    `${BASE}?area=coding&workspace_id=ws-1&work_item_id=i-1&coding_view=rules`);
  assert.equal(areaSwitchHref(`${BASE}?area=admin&session_id=s-1&workspace_id=ws-1`, "chat"), `${BASE}?workspace_id=ws-1&session_id=s-1`);
  assert.equal(areaSwitchHref(`${BASE}?area=admin&tab=cedarPolicies&policy=p-1`, "operations"), `${BASE}?area=operations&policy=p-1`,
    "Show decisions of a policy keeps its filter");
});

test("a Coding page opens by its own address; the Delivery pipeline only by delivery_pipeline", () => {
  const { codingNavFromSearch, codingViewParam } = load("chat/coding/CodingAreaNav.tsx");
  assert.equal(codingViewParam("pipelines"), "delivery_pipeline");
  assert.equal(codingNavFromSearch("?area=coding&coding_view=delivery_pipeline"), "pipelines");
  assert.equal(codingNavFromSearch("?area=coding&coding_view=rules"), "rules");
  assert.equal(codingNavFromSearch("?area=coding&coding_view=pipelines"), "sessions");
  assert.equal(codingNavFromSearch("?area=coding&coding_view=toString"), "sessions");
});
