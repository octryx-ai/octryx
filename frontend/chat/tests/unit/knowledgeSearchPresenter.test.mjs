import assert from "node:assert/strict";
import { test } from "node:test";
import {
  activeOptionCount, availabilityRows, availabilitySummary, hitMetaLine, optionsLabel, passageNeedsExpand,
  resultCountLabel, searchHint, searchRefusal,
} from "../../src/admin/components/workspaceKnowledge/knowledgeSearchPresenter.ts";

test("results header counts the returned passages for the submitted query", () => {
  assert.equal(resultCountLabel(3, "Jackson 2"), "3 source passages for “Jackson 2”");
  assert.equal(resultCountLabel(1, "x"), "1 source passage for “x”");
  assert.equal(resultCountLabel(0, "x"), "No source passages for “x”");
});

test("a passage is clamped only when it is likely longer than three lines", () => {
  assert.equal(passageNeedsExpand("Short passage."), false);
  assert.equal(passageNeedsExpand(`  ${"a".repeat(220)}  `), false);
  assert.equal(passageNeedsExpand("a".repeat(221)), true);
  assert.equal(passageNeedsExpand("one\ntwo\nthree"), false);
  assert.equal(passageNeedsExpand("one\ntwo\nthree\nfour"), true);
});

test("hit meta line names a shared workspace and the product scope", () => {
  assert.equal(hitMetaLine({ products: [], version: "4.0" }), "");
  assert.equal(hitMetaLine({ products: ["spring-boot", "jackson"], version: "4.0" }), "spring-boot, jackson · 4.0");
  assert.equal(hitMetaLine({ products: [], version: null, bound: true, workspace: "Team B" }), "Shared from Team B");
  assert.equal(hitMetaLine({ products: [], version: null, bound: true }), "Shared from another workspace");
});

test("options label counts only options that change the request", () => {
  assert.equal(activeOptionCount({ mode: "hybrid", products: " ", version: "4.0" }), 0);
  assert.equal(activeOptionCount({ mode: "lexical", products: "", version: "" }), 1);
  assert.equal(activeOptionCount({ mode: "hybrid", products: "boot", version: "4.0" }), 2);
  assert.equal(optionsLabel(0), "Options");
  assert.equal(optionsLabel(2), "Options (2 active)");
});

test("availability keeps every reported mode, humanised, with a truthful summary", () => {
  const rows = availabilityRows({ lexical: "ok", vector: "needs_configuration", rerank: "store_down" });
  assert.deepEqual(rows.map((row) => [row.label, row.state, row.ok]), [
    ["Keyword search", "Available", true],
    ["Meaning search", "Needs configuration", false],
    ["Reranking", "Store down", false],
  ]);
  assert.equal(availabilitySummary(rows), "1 of 3 available");
  assert.equal(availabilitySummary(availabilityRows({ lexical: "ok", vector: "ok" })), "all 2 available");
  assert.equal(availabilitySummary(availabilityRows({ lexical: "ok" })), "available");
  assert.deepEqual(availabilityRows(undefined), []);
});

test("search hint is one line and names shared knowledge for an empty workspace", () => {
  assert.match(searchHint(true), /^No documents yet; .*shared/);
  assert.doesNotMatch(searchHint(false), /\n/);
});

test("an instance without knowledge storage reads as that state with the step for the person who can take it", () => {
  const admin = searchRefusal("needs_configuration", true);
  assert.match(admin.title, /not set up on this instance/);
  assert.match(admin.text, /deployment's configuration/);
  assert.equal(admin.link.href, "https://octryx.ai/docs/install/knowledge-storage#object-store");
  const member = searchRefusal("needs_configuration", false);
  assert.match(member.text, /Your administrator has not set up knowledge storage/);
  assert.doesNotMatch(member.text, /deployment/);
  assert.equal(member.link, undefined);
  assert.match(searchRefusal("unavailable", false).text, /again in a moment/);
  // Any other refusal keeps the server's sentence.
  assert.equal(searchRefusal("invalid_request", true), null);
  assert.equal(searchRefusal(null, true), null);
});
