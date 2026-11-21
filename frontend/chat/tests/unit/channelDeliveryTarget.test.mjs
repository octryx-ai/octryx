// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/channelDeliveryTarget.test.mjs
//
// The Teams delivery target keeps the backend's
// pipe format. The explanation must name exactly the formats the backend
// accepts (admin_channel_service.py), so its format detail is read as text.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

import {
  TEAMS_TARGET_EXAMPLES,
  describeTeamsTarget,
} from "../../src/admin/components/channelDeliveryTarget.ts";

const repoRoot = new URL("../../../../", import.meta.url);

describe("Teams delivery target", () => {
  test("the explained formats are the backend's accepted formats", () => {
    const source = readFileSync(
      new URL("backend/app/services/admin/connector/admin_channel_service.py", repoRoot),
      "utf8",
    );
    for (const example of TEAMS_TARGET_EXAMPLES) {
      assert.ok(source.includes(example.format), example.format);
      assert.equal(describeTeamsTarget(example.example).state, "valid", example.example);
    }
  });

  test("names each part of a new-thread target", () => {
    const description = describeTeamsTarget("thread|https://smba.example/|t1|team1|19:c@thread");
    assert.equal(description.state, "valid");
    assert.deepEqual(
      description.parts.map((part) => part.label),
      ["Service URL", "Tenant ID", "Team ID", "Channel ID"],
    );
  });

  test("names the parts of an existing conversation and flags incomplete values", () => {
    const description = describeTeamsTarget(" https://smba.example/|19:conv ");
    assert.equal(description.state, "valid");
    assert.deepEqual(description.parts.map((part) => part.value), ["https://smba.example/", "19:conv"]);
    assert.equal(describeTeamsTarget("").state, "empty");
    assert.equal(describeTeamsTarget("thread|https://smba.example/|t1|team1").state, "invalid");
    assert.equal(describeTeamsTarget("https://smba.example/").state, "invalid");
  });
});
