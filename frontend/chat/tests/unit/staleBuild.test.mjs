// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/staleBuild.test.mjs
//
// A tab opened before a deploy fails on its next lazy import (Preview, Knowledge showed "This page could
// not be displayed"). It must recognise that error and reload once, never in a loop.
import assert from "node:assert/strict";
import { test } from "node:test";

import { isStaleBuildError, shouldReload } from "../../src/staleBuild.ts";

test("the browsers' wordings for a missing lazy chunk count as a stale build", () => {
  assert.equal(isStaleBuildError(new TypeError("Failed to fetch dynamically imported module: https://x/assets/AdminPanel-Be7NNBQf.js")), true);
  assert.equal(isStaleBuildError(new TypeError("Importing a module script failed.")), true);
  assert.equal(isStaleBuildError(new TypeError("error loading dynamically imported module")), true);
  assert.equal(isStaleBuildError(new TypeError("Cannot read properties of undefined (reading 'map')")), false);
  assert.equal(isStaleBuildError(undefined), false);
});

test("reloads once, not again within a minute", () => {
  assert.equal(shouldReload(null, 1_000_000), true);
  assert.equal(shouldReload(1_000_000, 1_030_000), false);
  assert.equal(shouldReload(1_000_000, 1_061_000), true);
  assert.equal(shouldReload(Number.NaN, 5), true);
});
