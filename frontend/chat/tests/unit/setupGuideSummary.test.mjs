import assert from "node:assert/strict";
import { test } from "node:test";
import { setupGuideOpenSummary } from "../../src/admin/components/providerTab/setupGuideSummary.ts";

test("an optional recommendation is not counted as a required open step", () => {
  const steps = [
    { status: "pending", blocking: false },
    { status: "pending", blocking: true },
    { status: "completed", blocking: true },
  ];
  assert.equal(setupGuideOpenSummary(steps), "1 required step open · 1 optional recommendation");
  assert.equal(setupGuideOpenSummary([{ status: "pending", blocking: false }]), "1 optional recommendation");
  assert.equal(setupGuideOpenSummary([{ status: "completed", blocking: true }]), "All steps done");
});
