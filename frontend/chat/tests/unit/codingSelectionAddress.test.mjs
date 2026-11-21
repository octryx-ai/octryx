// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/codingSelectionAddress.test.mjs
//
// UI check (R2): opening Coding › Sessions appended `&work_item_id=<first session>` to the address
// although nobody chose that session. Only a chosen session (click, link, a session just started) is written.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import {
  addressSelectionAfterRead,
  codingSelectionHref,
  selectedWorkItemIdFromSearch,
} from "../../src/chat/coding/codingSelectionAddress.ts";

// The page and its address helpers (the URL write lives in codingAreaBrowser.ts).
const page = ["CodingAreaWorkspace.tsx", "codingAreaBrowser.ts"]
  .map((file) => readFileSync(new URL(`../../src/chat/coding/${file}`, import.meta.url), "utf8")).join("\n");

test("the first session picked for the person is not written into the address", () => {
  assert.equal(addressSelectionAfterRead({ asked: null, shown: "first" }), null);
});

test("a session asked for by the address or the caller stays in the address", () => {
  assert.equal(addressSelectionAfterRead({ asked: "chosen", shown: "chosen" }), "chosen");
});

test("an asked-for session that is gone leaves the address, the fallback pick is not written", () => {
  assert.equal(addressSelectionAfterRead({ asked: "gone", shown: "first" }), null);
  assert.equal(addressSelectionAfterRead({ asked: "gone", shown: null }), null);
});

test("the address names a session by work_item_id only", () => {
  assert.equal(selectedWorkItemIdFromSearch("?area=coding&work_item_id=a"), "a");
  // One address: any other parameter selects nothing.
  assert.equal(selectedWorkItemIdFromSearch("?area=coding&coding_session_id=b"), null);
  assert.equal(selectedWorkItemIdFromSearch("?area=coding&coding_view=sessions"), null);
});

test("writing a selection keeps the page; no selection removes it", () => {
  const base = "https://octryx.example/chat?area=coding&coding_view=sessions";
  assert.equal(codingSelectionHref(base, null), base);
  assert.equal(codingSelectionHref(base, "a"), `${base}&work_item_id=a`);
  assert.equal(codingSelectionHref(`${base}&work_item_id=a`, null), base);
});

test("a click on a session writes it (shareable link); the page does not write on arriving at Sessions", () => {
  assert.match(page, /onSelect=\{\(id\) => \{\s*setSelectedId\(id\);\s*replaceCodingWorkItemUrl\(id\);/);
  assert.doesNotMatch(page, /activeNavNow/);
  // Nothing is written when the address already says it.
  assert.match(page, /if \(nextUrl !== window\.location\.href\) window\.history\.replaceState/);
});
