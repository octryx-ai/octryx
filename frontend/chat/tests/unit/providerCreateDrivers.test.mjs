// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// The Admin provider create catalog submits exact backend driver ids.
//
// The backend driver catalog is read as text (never imported), so a create choice
// that is not a `DRIVER_SPECS` key fails here instead of being refused at save time.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

import {
  DEFAULT_PROVIDER_CREATE_DRIVER,
  PROVIDER_CREATE_CHOICES,
  PROVIDER_CREATE_ENDPOINT_CHOICES,
} from "../../src/admin/components/providerTab/providerCreateChoices.ts";

const REPO = new URL("../../../../", import.meta.url);

function source(relativePath) {
  return readFileSync(new URL(relativePath, REPO), "utf8").replace(/\r\n/g, "\n");
}

const REGISTRY_SOURCE = source("backend/app/agent/providers/provider_registry.py");
const TYPE_SELECT_SOURCE = source("frontend/chat/src/admin/components/providerTab/ProviderTypeSelect.tsx");
const CREATE_ACTIONS_SOURCE = source("frontend/chat/src/admin/hooks/useAdminProviderCreateActions.ts");

/** Keys of the backend `DRIVER_SPECS` dict (`"<id>": ProviderDriverSpec(`). */
function backendDriverIds() {
  const ids = Array.from(REGISTRY_SOURCE.matchAll(/^    "([a-z_]+)": ProviderDriverSpec\(/gm), (match) => match[1]);
  assert.ok(ids.length >= 6, "backend driver catalog scrape looks broken");
  return ids;
}

describe("provider create choices are backend driver ids", () => {
  test("every choice, endpoint choice and the default is a supported driver id", () => {
    const supported = new Set(backendDriverIds());
    for (const choice of PROVIDER_CREATE_CHOICES) {
      assert.ok(supported.has(choice.value), `create choice ${choice.value} is not a driver id`);
    }
    for (const value of PROVIDER_CREATE_ENDPOINT_CHOICES) {
      assert.ok(supported.has(value), `${value} carries an endpoint input but is not a driver id`);
    }
    assert.ok(supported.has(DEFAULT_PROVIDER_CREATE_DRIVER));
    assert.deepEqual(
      PROVIDER_CREATE_CHOICES.map((choice) => choice.value).sort(),
      [...supported].sort(),
    );
  });

  test("the form renders the catalog and submits the choice as the driver", () => {
    assert.match(TYPE_SELECT_SOURCE, /PROVIDER_CREATE_CHOICES\.map/);
    assert.doesNotMatch(TYPE_SELECT_SOURCE, /<option value="/);
    assert.match(CREATE_ACTIONS_SOURCE, /driver: newProviderDriver,/);
    assert.doesNotMatch(CREATE_ACTIONS_SOURCE, /name: newProviderDriver/);
  });
});
