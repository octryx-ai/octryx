// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/contentSecurity.test.mjs
//
// Settings → Security → Content security — coverage from the server, the detector editor here
// (Policies keeps a read-only list), approved models read-only.
import assert from "node:assert/strict";
import { test } from "node:test";

import { act, byTestId, click, render, server, text, tick } from "./settingsRenderHarness.mjs";

const OVERVIEW = {
  coverage: {
    categories: [{ id: "secrets", label: "Credentials" }, { id: "pii", label: "Personal data" }],
    rows: [
      { key: "prompt", label: "User prompt", sub: "company gateway & seats", cells: [
        { category: "secrets", outcome: "refuse", text: "Refuse", tone: "refuse" },
        { category: "pii", outcome: "scanned", text: "Scanned, no rule", tone: "report" }] },
      { key: "ingest", label: "Uploads & ingest", sub: "files, Knowledge", cells: [
        { category: "secrets", outcome: "none", text: "Not scanned", tone: "none" },
        { category: "pii", outcome: "none", text: "Not scanned", tone: "none" }] },
    ],
    mode: "shadow", detectors: 8, custom_detectors: 1, content_policies: 2, published_version: 4,
    platform_policies: [{ id: "platform:prompt-injection-refused", label: "Prompt injection is refused", outcome: "refuse" }],
  },
  edit_target: { version: 4, digest: "sha256:x", creates_draft: true },
  approved_models: [{ alias: "eu-sonnet", cleared_up_to: "internal", approved_for: ["pii"], levels: ["public", "internal"] }],
  levels: [{ key: "public", label: "Public", color: "public" }, { key: "internal", label: "Internal", color: "internal" }],
};
test("rendered Content security: the coverage, then the approved models", async () => {
  const srv = server(() => ({ status: 200, body: OVERVIEW }));
  const view = await render("admin/components/contentSecurity/ContentSecurityPage.tsx", "ContentSecurityPage", srv);
  try {
    const coverage = text(byTestId(view, "content-coverage")[0]);
    assert.match(coverage, /User prompt.*Refuse.*Scanned, no rule/);
    assert.match(coverage, /Uploads & ingest.*Not scanned/);
    assert.match(text(view.root), /the policy engine is in shadow/);
    assert.match(text(byTestId(view, "content-platform-policies")[0]), /every driver: Prompt injection is refused/);
    assert.deepEqual(byTestId(view, "subtab-filters"), [], "no message filter view");
    await click(view, "subtab-models");
    assert.match(text(byTestId(view, "content-models")[0]), /eu-sonnet.*Internal.*Personal data.*Public, Internal/);
  } finally { act(() => view.unmount()); }
});
