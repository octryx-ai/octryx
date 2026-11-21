// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/skillDetailRefresh.test.mjs
//
// The skill detail page reloads when the skill changed elsewhere (live acceptance): after a self-approved
// publish in the review drawer the head and draft bar show the published version, not "Draft v1".
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import { act, byTestId, load, server, text, tick } from "./policyEngineHarness.mjs";

const version = (state) => ({ version: 1, state, digest: `d-${state}`, note: null, files: [], findings: [], extension: null,
  merge_report: null, created_by: "u1", author_name: "Casey", security_report: { summary: { high: 0, medium: 0, info: 0 }, findings: [] } });

test("a revision change reloads the detail: the draft bar goes once v1 is published", async () => {
  let published = false;
  const { fetch, calls } = server((call) => {
    if (/\/skills\/sk_1$/.test(call.url)) {
      return { status: 200, body: { id: "sk_1", name: "Review helper", kind: "skill", source: null, tags: [], owner_id: "u1",
        open: published ? null : version("in_review"), published: published ? version("published") : null,
        versions: [version(published ? "published" : "in_review")], review: { single_admin: true }, upstream_status: null } };
    }
    return { status: 200, body: {} };
  });
  const { SkillDetailPage } = load("admin/components/skillCatalog/SkillDetailPage.tsx", { fetch, window: { location: { origin: "http://x" } } });
  const props = { skillId: "sk_1", categories: { categories: [] }, onBack() {}, onEdit() {}, onReviewUpdate() {},
    onOpenReview() {}, onOpenCategory() {}, onOpenWorkspaces() {}, onChanged() {} };
  let view;
  await act(async () => { view = TestRenderer.create(createElement(SkillDetailPage, { ...props, revision: 0 })); });
  await tick();
  assert.match(text(byTestId(view, "skill-detail-draft-bar")[0]), /Draft v1/);
  published = true;
  await act(async () => { view.update(createElement(SkillDetailPage, { ...props, revision: 1 })); });
  await tick();
  assert.equal(byTestId(view, "skill-detail-draft-bar").length, 0);
  assert.equal(text(byTestId(view, "skill-detail-edit")[0]), "Edit (new draft)");
  assert.equal(calls.filter((call) => /\/skills\/sk_1$/.test(call.url)).length, 2);
  view.unmount();
});
