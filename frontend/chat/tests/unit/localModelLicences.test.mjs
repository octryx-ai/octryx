// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/localModelLicences.test.mjs
//
// Local model licences: the platform switch's state and body, the licence tag of a catalog model, refusals.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  licenceTag,
  loadOutcome,
  localModelsBody,
  localModelsSaveError,
  readLocalModelsSetting,
} from "../../src/admin/components/localModels/localModelsModel.ts";

test("the switch reads on unless the server says false, and only can_edit true makes it editable", () => {
  assert.deepEqual(readLocalModelsSetting({ permissive_only: true, can_edit: true }), { permissiveOnly: true, canEdit: true });
  assert.deepEqual(readLocalModelsSetting({ permissive_only: false, can_edit: false }), { permissiveOnly: false, canEdit: false });
  assert.deepEqual(readLocalModelsSetting({ permissive_only: null }), { permissiveOnly: true, canEdit: false });
  assert.equal(readLocalModelsSetting({ default: "claude_code" }), null);
  assert.equal(readLocalModelsSetting(null), null);
});

test("the PUT sends exactly the one field the server accepts", () => {
  assert.deepEqual(localModelsBody(false), { permissive_only: false });
});

test("a forbidden GET hides the card; other failures show a problem", () => {
  assert.equal(loadOutcome(403), "hidden");
  assert.equal(loadOutcome(500), "problem");
  assert.equal(loadOutcome(null), "problem");
});

test("403 and 422 refusals are words, not codes", () => {
  assert.match(localModelsSaveError(403, null), /only platform admins/);
  assert.match(localModelsSaveError(422, { detail: { errors: [{ code: "invalid_flag" }] } }), /must be on or off/);
  assert.match(localModelsSaveError(422, { detail: { errors: [{ code: "unknown_setting" }] } }), /does not know this setting/);
  assert.match(localModelsSaveError(422, { detail: "x" }), /was refused/);
  assert.equal(localModelsSaveError(500, null), "Not saved: the request failed.");
});

test("a permissive licence is a plain tag with its link and note", () => {
  const tag = licenceTag({ id: "Apache-2.0", url: "https://www.apache.org/licenses/LICENSE-2.0",
    note: "Apache License 2.0: commercial use allowed.", commercial_restriction: null, permissive: true });
  assert.deepEqual(tag, { label: "Apache-2.0", url: "https://www.apache.org/licenses/LICENSE-2.0",
    detail: "Apache License 2.0: commercial use allowed.", restricted: false });
});

test("a restricted licence is marked and names the restriction first", () => {
  const tag = licenceTag({ id: "LFM Open License v1.0", url: "javascript:alert(1)", note: "Liquid AI licence.",
    commercial_restriction: "annual revenue below USD 10M", permissive: false });
  assert.equal(tag.restricted, true);
  assert.equal(tag.url, null);
  assert.equal(tag.detail, "Commercial use only with annual revenue below USD 10M. Liquid AI licence.");
});

test("a missing licence is never shown as permissive", () => {
  assert.equal(licenceTag(undefined).restricted, true);
  assert.equal(licenceTag({ id: "" }).label, "Licence unknown");
  assert.equal(licenceTag({ id: "MIT" }).restricted, true);
});
