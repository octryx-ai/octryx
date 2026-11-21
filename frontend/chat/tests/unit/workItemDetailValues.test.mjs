import assert from "node:assert/strict";
import { test } from "node:test";

import { optionalSourceObject } from "../../src/chat/work/workItemDetailValues.ts";

test("source details prefer plain fields and read current prefixed fields", () => {
  assert.deepEqual(optionalSourceObject({ source_fields: { checks: ["plain"], octryx_checks: ["current"] } }, "checks"), ["plain"]);
  assert.deepEqual(optionalSourceObject({ source_fields: { octryx_checks: ["current"] } }, "checks"), ["current"]);
  assert.deepEqual(optionalSourceObject({ source_fields: { oe_checks: ["obsolete"], octryx_checks: ["current"] } }, "checks"), ["current"]);
  assert.equal(optionalSourceObject({ source_fields: { oe_checks: ["obsolete"] } }, "checks"), undefined);
});
