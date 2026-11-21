// Run: node --import ./tests/unit/register-ts.mjs --test "tests/unit/*.test.mjs"
//
// The governed LiteLLM gateway admin surface. Guards the four things
// that must not drift or regress:
//   1. the create/edit payloads are exactly the canonical safe fields,
//   2. no gateway surface asks for or renders a key or a secret reference,
//   3. (moved: the fallback choice is covered by modelSelectionContract.test.mjs),
//   4. readiness is rendered from fixed codes only.
//
// Backend sources are read as text (never imported) and their literal tables are
// compared, so a backend change to any closed set fails here instead of silently
// producing an admin form that submits an invalid value.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { describe, test } from "node:test";

import { GATEWAY_CAPABILITIES, GATEWAY_COST_SOURCES, GATEWAY_DATA_POLICY_CLASSES, GATEWAY_MAX_REQUEST_TIMEOUT_SECONDS, GATEWAY_MIN_REQUEST_TIMEOUT_SECONDS, GATEWAY_PROBE_MODEL_GROUP_FIELDS, GATEWAY_PROBE_PATHS, GATEWAY_PROBE_RESPONSE_SHAPES } from "../../src/admin/components/providerTab/litellmGatewayTypes.ts";
import { boundedAdminErrorText } from "../../src/admin/components/providerTab/litellmGatewayContract.ts";
import { buildGatewayCreatePayload, buildGatewayUpdatePayload } from "../../src/admin/components/providerTab/litellmGatewayPayload.ts";
import { emptyGatewayDraft, gatewayDraftFromProvider } from "../../src/admin/components/providerTab/litellmGatewayDrafts.ts";
import { gatewayValidationCodes, isGatewayDraftSubmittable, parseHostAllowlist } from "../../src/admin/components/providerTab/litellmGatewayValidation.ts";
import {
  GATEWAY_READINESS_REASON_LABELS,
  PROVIDER_READINESS_REASON_LABELS,
  presentProviderReadiness,
} from "../../src/admin/components/providerTab/litellmGatewayReadiness.ts";

const REPO = new URL("../../../../", import.meta.url);

function source(relativePath) {
  return readFileSync(new URL(relativePath, REPO), "utf8").replace(/\r\n/g, "\n");
}

const LITELLM = "backend/app/services/model_gateway/litellm/";
const ENDPOINT_SOURCE = source(`${LITELLM}endpoint.py`);
const CONFIG_SOURCE = source(`${LITELLM}config.py`);
const ALIAS_SOURCE = source(`${LITELLM}alias_catalog.py`);
const LEVELS_SOURCE = source("backend/app/services/data_classification/levels.py");
// The cost-source enum is shared with model-catalog sync, so it is owned by
// `services/model_gateway/cost_contract.py`, which the alias catalog imports.
// Read it where it is defined, or this guard silently stops guarding anything.
const COST_CONTRACT_SOURCE = source(
  "backend/app/services/model_gateway/cost_contract.py",
);
const GATEWAY_READINESS_SOURCE = source(`${LITELLM}readiness.py`);
const TRANSPORT_SOURCE = source(`${LITELLM}transport_policy.py`);
const PROXY_TRUST_SOURCE = source(`${LITELLM}proxy_trust.py`);
const CONTENT_LOGGING_SOURCE = source(`${LITELLM}content_logging.py`);
const PROVIDER_READINESS_SOURCE = source("backend/app/services/provider/readiness.py");
const PROVIDER_SCHEMA_SOURCE = source(
  "backend/app/schemas/admin/admin_provider_panel.py",
);

/** One `NAME = "literal"` module constant. */
function constantValue(pySource, name) {
  const match = new RegExp(`^${name} = "([^"]+)"$`, "m").exec(pySource);
  assert.ok(match, `missing backend constant: ${name}`);
  return match[1];
}

/**
 * Members of a `NAME = {...}` / `NAME = frozenset({...})` literal block, which
 * the backend may wrap across lines. A bare identifier member is resolved
 * through its own module constant, which is how most of these sets are spelled.
 */
function setMembers(pySource, name) {
  const start = new RegExp(`^${name} = `, "m").exec(pySource);
  assert.ok(start, `missing backend set: ${name}`);
  const open = pySource.indexOf("{", start.index);
  const close = pySource.indexOf("}", open);
  assert.ok(open !== -1 && close > open, `unreadable set: ${name}`);
  return pySource
    .slice(open + 1, close)
    .split(",")
    .map((token) => token.trim())
    .filter(Boolean)
    .map((token) =>
      /^["']/.test(token)
        ? token.replace(/^["']|["']$/g, "")
        : constantValue(pySource, token),
    )
    .sort();
}

/** Values of `PREFIX_... = "literal"` module constants. */
function constantValues(pySource, prefix) {
  const pattern = new RegExp(`^${prefix}[A-Z_]* = "([^"]+)"$`, "gm");
  return Array.from(pySource.matchAll(pattern), (match) => match[1]).sort();
}

const SENSITIVE_KEY_MARKERS = [
  "access_key",
  "access_token",
  "api_key",
  "apikey",
  "auth_header",
  "auth_token",
  "authorization",
  "bearer",
  "client_secret",
  "cookie",
  "credential",
  "password",
  "private_key",
  "refresh_token",
  "secret",
  "token",
  "virtual_key",
];

function sensitiveKeysIn(value, path = "") {
  if (Array.isArray(value)) {
    return value.flatMap((item, index) => sensitiveKeysIn(item, `${path}[${index}]`));
  }
  if (value && typeof value === "object") {
    return Object.entries(value).flatMap(([key, item]) => {
      const normalized = key.toLowerCase().replace(/-/g, "_");
      const hit = SENSITIVE_KEY_MARKERS.some((marker) => normalized.includes(marker));
      return [
        ...(hit ? [`${path}.${key}`] : []),
        ...sensitiveKeysIn(item, `${path}.${key}`),
      ];
    });
  }
  return [];
}

function governedDraft() {
  return {
    ...emptyGatewayDraft(),
    displayName: "Governed LiteLLM",
    endpointUrl: "https://litellm.internal.example/v1",
    hostAllowlist: "LiteLLM.internal.example\n127.0.0.1",
    requestTimeoutSeconds: "90",
    aliases: [
      {
        alias: "octryx-fast",
        modelGroup: "azure/gpt-4o-mini",
        contextLimit: "128000",
        dataPolicyClass: "internal",
        capabilities: {
          tools: true,
          structured_output: false,
          reasoning: false,
          vision: false,
        },
        cost: {
          source: "catalog_pricing",
          inputPerMillionUsd: "0.15",
          outputPerMillionUsd: "0.6",
          contractReference: "",
        },
      },
      {
        alias: "octryx-free",
        modelGroup: "self-hosted/llama",
        contextLimit: "32000",
        dataPolicyClass: "restricted",
        capabilities: {
          tools: false,
          structured_output: false,
          reasoning: false,
          vision: false,
        },
        cost: {
          source: "governed_free",
          inputPerMillionUsd: "",
          outputPerMillionUsd: "",
          contractReference: "GOV-2026-014",
        },
      },
    ],
  };
}

const EXPECTED_SECTION = {
  host_allowlist: ["127.0.0.1", "litellm.internal.example"],
  probe_contract: {
    models_path: "/models",
    response_shape: "openai_model_list",
    model_group_field: "id",
  },
  aliases: {
    "octryx-fast": {
      model_group: "azure/gpt-4o-mini",
      context_limit: 128000,
      data_policy_class: "internal",
      capabilities: {
        tools: true,
        structured_output: false,
        reasoning: false,
        vision: false,
      },
      cost: {
        source: "catalog_pricing",
        input_per_million_usd: 0.15,
        output_per_million_usd: 0.6,
      },
    },
    "octryx-free": {
      model_group: "self-hosted/llama",
      context_limit: 32000,
      data_policy_class: "restricted",
      capabilities: {
        tools: false,
        structured_output: false,
        reasoning: false,
        vision: false,
      },
      cost: { source: "governed_free", contract_reference: "GOV-2026-014" },
    },
  },
  request_timeout_seconds: 90,
};

describe("LiteLLM gateway provider payloads", () => {
  test("creation submits exactly the canonical governed fields", () => {
    const payload = buildGatewayCreatePayload(governedDraft());

    assert.deepEqual(payload, {
      driver: "litellm_gateway",
      display_name: "Governed LiteLLM",
      endpoint_url: "https://litellm.internal.example/v1",
      config_json: { litellm_gateway: EXPECTED_SECTION },
      is_global: true,
    });
    // Every key must exist on ProviderCreateRequest; none may be a credential.
    for (const key of Object.keys(payload)) {
      assert.match(
        PROVIDER_SCHEMA_SOURCE,
        new RegExp(`^    ${key}: `, "m"),
        `${key} is not a ProviderCreateRequest field`,
      );
    }
    assert.deepEqual(sensitiveKeysIn(payload), []);
  });

  test("editing submits only the governed fields and keeps unrelated config", () => {
    const payload = buildGatewayUpdatePayload(governedDraft(), {
      unrelated_runtime_hint: "keep-me",
      litellm_gateway: { host_allowlist: ["stale.example"] },
    });

    assert.deepEqual(Object.keys(payload).sort(), [
      "config_json",
      "display_name",
      "endpoint_url",
    ]);
    assert.equal(payload.config_json.unrelated_runtime_hint, "keep-me");
    assert.deepEqual(payload.config_json.litellm_gateway, EXPECTED_SECTION);
    assert.deepEqual(sensitiveKeysIn(payload), []);
  });

  test("an edit keeps the governed sections the form does not render", () => {
    // Dropping tls / content_logging / proxy would leave the provider
    // permanently `needs_configuration` after an unrelated alias edit.
    const governedSections = {
      tls: { mode: "private_ca_bundle", ca_bundle_path: "/etc/octryx/ca/internal.pem" },
      proxy: {
        mode: "governed_proxy",
        url: "https://egress.internal.example:3128",
        host_allowlist: ["egress.internal.example"],
      },
      content_logging: {
        mode: "no_content_retention",
        prompt_retention: "disabled",
        response_retention: "disabled",
        header_retention: "disabled",
        key_metadata_retention: "disabled",
        success_callbacks: [],
        failure_callbacks: [],
        attestation_reference: "GOV-2026-021",
        attested_on: "2026-09-27",
        verified_against: "live_gateway_configuration",
      },
    };

    const payload = buildGatewayUpdatePayload(governedDraft(), {
      litellm_gateway: {
        host_allowlist: ["stale.example"],
        request_timeout_seconds: 5,
        ...governedSections,
      },
    });

    assert.deepEqual(payload.config_json.litellm_gateway, {
      ...governedSections,
      ...EXPECTED_SECTION,
    });
    // The form's own keys are still replaced, not merged.
    assert.deepEqual(
      payload.config_json.litellm_gateway.host_allowlist,
      EXPECTED_SECTION.host_allowlist,
    );
    assert.equal(
      payload.config_json.litellm_gateway.request_timeout_seconds,
      EXPECTED_SECTION.request_timeout_seconds,
    );
    assert.deepEqual(sensitiveKeysIn(payload), []);
  });

  test("a stored provider round-trips through the edit form unchanged", () => {
    const stored = buildGatewayCreatePayload(governedDraft());
    const reopened = gatewayDraftFromProvider({
      display_name: stored.display_name,
      endpoint_url: stored.endpoint_url,
      config_json: stored.config_json,
    });

    assert.deepEqual(
      buildGatewayUpdatePayload(reopened, stored.config_json).config_json,
      stored.config_json,
    );
  });

  test("an edit keeps the alias fields the form does not render", () => {
    // Runtime audit P-1: display name, served model ids and cache prices feed
    // octryx-claude /model and transcript pricing; a form save must not drop them.
    const stored = buildGatewayCreatePayload(governedDraft()).config_json;
    const fast = stored.litellm_gateway.aliases["octryx-fast"];
    const extras = {
      display_name: "Fast (Azure)",
      served_model_ids: ["gpt-4o-mini-2024-07-18"],
      future_alias_field: { kept: true },
    };
    const cachePrices = { cache_read_per_million_usd: 0.075, cache_write_per_million_usd: 0.3 };
    Object.assign(fast, extras);
    Object.assign(fast.cost, cachePrices);

    const reopened = gatewayDraftFromProvider({ config_json: stored });
    reopened.aliases[0] = { ...reopened.aliases[0], alias: "octryx-fast-2", contextLimit: "64000" };
    const saved = buildGatewayUpdatePayload(reopened, stored).config_json.litellm_gateway.aliases;

    assert.equal(saved["octryx-fast"], undefined);
    assert.deepEqual(saved["octryx-fast-2"], {
      ...EXPECTED_SECTION.aliases["octryx-fast"],
      ...extras,
      context_limit: 64000,
      cost: { ...EXPECTED_SECTION.aliases["octryx-fast"].cost, ...cachePrices },
    });
    // A rendered field cleared in the form stays cleared: it is never resurrected.
    assert.equal("approved_data_categories" in saved["octryx-fast-2"], false);

    // Another pricing contract drops the cache prices but keeps the alias fields.
    reopened.aliases[0].cost = {
      ...reopened.aliases[0].cost,
      source: "governed_free",
      contractReference: "ADR-17",
    };
    const switched = buildGatewayUpdatePayload(reopened, stored).config_json.litellm_gateway.aliases["octryx-fast-2"];
    assert.deepEqual(switched.cost, { source: "governed_free", contract_reference: "ADR-17" });
    assert.equal(switched.display_name, "Fast (Azure)");
  });

  test("an incomplete draft reports fixed codes and stays unsubmittable", () => {
    const blank = emptyGatewayDraft();
    assert.equal(isGatewayDraftSubmittable(blank), false);
    assert.deepEqual(gatewayValidationCodes(blank).form, [
      "endpoint_not_configured",
      "endpoint_host_allowlist_not_configured",
    ]);
    assert.deepEqual(gatewayValidationCodes(blank).aliases, [
      {
        index: 0,
        codes: [
          "alias_not_requested",
          "alias_model_group_missing",
          "alias_context_limit_invalid",
          "alias_cost_pricing_invalid",
        ],
      },
    ]);

    const wildcardHost = { ...governedDraft(), hostAllowlist: "*.example" };
    assert.deepEqual(gatewayValidationCodes(wildcardHost).form, [
      "endpoint_host_allowlist_invalid",
    ]);

    // Each required rate has to be billable on its own, matching what the backend
    // admits: a zero rate in either direction, not only two zeroes.
    for (const rates of [
      ["0", "0"],
      ["0", "0.6"],
      ["0.15", "0"],
    ]) {
      const freeButBillable = governedDraft();
      freeButBillable.aliases[0].cost.inputPerMillionUsd = rates[0];
      freeButBillable.aliases[0].cost.outputPerMillionUsd = rates[1];
      assert.deepEqual(gatewayValidationCodes(freeButBillable).aliases, [
        { index: 0, codes: ["alias_cost_pricing_not_billable"] },
      ]);
      assert.equal(isGatewayDraftSubmittable(freeButBillable), false);
    }

    const twice = governedDraft();
    twice.aliases[1].alias = "octryx-fast";
    assert.deepEqual(gatewayValidationCodes(twice).form, [
      "form_alias_declared_twice",
    ]);

    const slowTimeout = { ...governedDraft(), requestTimeoutSeconds: "601" };
    assert.deepEqual(gatewayValidationCodes(slowTimeout).form, [
      "form_request_timeout_seconds_out_of_range",
    ]);
  });

  test("the host allowlist stays an exact bare-host set", () => {
    assert.deepEqual(
      parseHostAllowlist(" Gateway.Example , gateway.example\nother.example "),
      ["gateway.example", "other.example"],
    );
  });
});

describe("LiteLLM gateway closed sets match the backend", () => {
  test("probe contract, policy classes, capabilities and cost sources", () => {
    assert.deepEqual(
      [...GATEWAY_PROBE_PATHS].sort(),
      setMembers(CONFIG_SOURCE, "PROBE_PATHS"),
    );
    assert.deepEqual(
      [...GATEWAY_PROBE_RESPONSE_SHAPES].sort(),
      setMembers(CONFIG_SOURCE, "PROBE_RESPONSE_SHAPES"),
    );
    assert.deepEqual(
      [...GATEWAY_PROBE_MODEL_GROUP_FIELDS].sort(),
      setMembers(CONFIG_SOURCE, "PROBE_MODEL_GROUP_FIELDS"),
    );
    // The backend set is a live view of the level registry; the closed set the gateway form
    // offers is the built-in levels a model may be cleared for (custom levels come with Runtime's catalog work).
    assert.match(ALIAS_SOURCE, /^DATA_POLICY_CLASSES = MODEL_DATA_POLICY_CLASSES$/m);
    assert.deepEqual(
      [...GATEWAY_DATA_POLICY_CLASSES].sort(),
      Array.from(LEVELS_SOURCE.matchAll(/^\s+LevelDef\("([a-z_]+)", \d+, "[^"]*", "[^"]*", "[^"]*", (True|False), True\),$/gm))
        .filter((match) => match[2] === "True").map((match) => match[1]).sort(),
    );
    assert.deepEqual(
      [...GATEWAY_COST_SOURCES].sort(),
      setMembers(COST_CONTRACT_SOURCE, "COST_SOURCES"),
    );
    // GATEWAY_CAPABILITIES is a tuple of the CAPABILITY_* constants.
    assert.deepEqual(
      [...GATEWAY_CAPABILITIES].sort(),
      constantValues(ALIAS_SOURCE, "CAPABILITY_"),
    );
  });

  test("the request timeout bounds match the backend bounds", () => {
    for (const [name, value] of [
      ["MIN_REQUEST_TIMEOUT_SECONDS", GATEWAY_MIN_REQUEST_TIMEOUT_SECONDS],
      ["MAX_REQUEST_TIMEOUT_SECONDS", GATEWAY_MAX_REQUEST_TIMEOUT_SECONDS],
    ]) {
      const match = new RegExp(`^${name} = ([0-9.]+)$`, "m").exec(CONFIG_SOURCE);
      assert.ok(match, `missing backend bound: ${name}`);
      assert.equal(Number(match[1]), value);
    }
  });
});

describe("no gateway surface asks for or renders a key", () => {
  const GATEWAY_UI_FILES = [
    "frontend/chat/src/admin/components/providerTab/litellmGatewayContract.ts",
    "frontend/chat/src/admin/components/providerTab/litellmGatewayTypes.ts",
    "frontend/chat/src/admin/components/providerTab/litellmGatewayDrafts.ts",
    "frontend/chat/src/admin/components/providerTab/litellmGatewayValidation.ts",
    "frontend/chat/src/admin/components/providerTab/litellmGatewayPayload.ts",
    "frontend/chat/src/admin/components/providerTab/LiteLlmGatewayConfigFields.tsx",
    "frontend/chat/src/admin/components/providerTab/LiteLlmGatewayAliasRow.tsx",
    "frontend/chat/src/admin/components/providerTab/LiteLlmGatewayAddForm.tsx",
    "frontend/chat/src/admin/components/providerTab/LiteLlmGatewaySecretNotice.tsx",
    "frontend/chat/src/admin/components/providerTab/ProviderLiteLlmGatewaySection.tsx",
    "frontend/chat/src/admin/hooks/useAdminLiteLlmGatewayActions.ts",
  ];

  test("no password input and no credential-bearing binding", () => {
    for (const file of GATEWAY_UI_FILES) {
      const text = source(file);
      // Comments legitimately name the fields being refused, so only the JSX
      // attribute / object-property forms are searched.
      const code = text
        .replace(/\/\*[\s\S]*?\*\//g, "")
        .replace(/^\s*\/\/.*$/gm, "");
      for (const forbidden of [
        'type="password"',
        "api_key:",
        "api_key_masked",
        "api_key_secret_ref",
        "newProviderKey",
        "newKeyValue",
      ]) {
        assert.equal(
          code.includes(forbidden),
          false,
          `${file} must not contain ${forbidden}`,
        );
      }
      // The only secret-reference state the UI may hold is the boolean flag.
      for (const mention of code.match(/secretRef\w*/g) ?? []) {
        assert.equal(mention, "secretRefConfigured", `${file} holds ${mention}`);
      }
    }
  });

  test("the secret notice shows a linked flag, never a reference value", () => {
    const notice = source(
      "frontend/chat/src/admin/components/providerTab/LiteLlmGatewaySecretNotice.tsx",
    );
    assert.match(notice, /secretRefConfigured \? "Secret Reference linked"/);
    assert.match(notice, /readOnly/);
    assert.match(notice, /disabled/);
    // The copy says the key is never shown, in user words: no issue numbers or reason codes.
    assert.match(notice, /never shown/);
    assert.doesNotMatch(notice, /#\d{3}|litellm_gateway_virtual_key_secret_ref_not_configured/);
  });

  test("the raw-key editor is excluded for the gateway driver", () => {
    const authSection = source(
      "frontend/chat/src/admin/components/providerTab/ProviderAuthSection.tsx",
    );
    assert.match(authSection, /p\.driver !== LITELLM_GATEWAY_DRIVER/);
    const keyGuard = authSection.slice(
      authSection.indexOf("p.driver !== \"copilot_api\" &&\n      p.driver !== \"gemini_api\" &&"),
      authSection.indexOf("<ProviderApiKeyAuth"),
    );
    assert.match(keyGuard, /LITELLM_GATEWAY_DRIVER/);
  });

  test("the add form routes the gateway away from the credential form", () => {
    const addForm = source(
      "frontend/chat/src/admin/components/providerTab/AddProviderForm.tsx",
    );
    const branch = addForm.indexOf("LiteLlmGatewayAddForm ctx={ctx}");
    assert.notEqual(branch, -1);
    assert.ok(
      branch < addForm.indexOf('type="password"'),
      "the gateway branch must return before any password input is rendered",
    );
  });
});

describe("readiness is rendered from fixed codes", () => {
  test("every backend readiness reason has admin copy", () => {
    const prefix = /^READINESS_REASON_PREFIX = "([a-z_]+)"$/m.exec(
      GATEWAY_READINESS_SOURCE,
    );
    assert.ok(prefix, "missing backend READINESS_REASON_PREFIX");

    const gatewayReasons = [
      ...constantValues(ENDPOINT_SOURCE, "ENDPOINT_DENIAL_"),
      ...constantValues(CONFIG_SOURCE, "PROBE_DENIAL_"),
      ...constantValues(CONFIG_SOURCE, "CATALOG_DENIAL_"),
      // Transport trust store, governed proxy and content-logging posture.
      ...constantValues(TRANSPORT_SOURCE, "TLS_DENIAL_"),
      ...constantValues(TRANSPORT_SOURCE, "PROXY_DENIAL_"),
      // The proxy's own TLS leg is decided in its own module.
      ...constantValues(PROXY_TRUST_SOURCE, "PROXY_DENIAL_"),
      ...constantValues(CONTENT_LOGGING_SOURCE, "CONTENT_LOGGING_DENIAL_"),
      // Only these two alias codes reach the readiness surface.
      ...["alias_catalog_missing", "alias_catalog_contains_credential_material"],
    ].map((reason) => `${prefix[1]}${reason}`);
    const virtualKeyReason =
      /^READINESS_REASON_VIRTUAL_KEY_NOT_CONFIGURED = f"\{READINESS_REASON_PREFIX\}([a-z_]+)"$/m.exec(
        GATEWAY_READINESS_SOURCE,
      );
    assert.ok(virtualKeyReason, "missing backend virtual-key readiness reason");
    gatewayReasons.push(`${prefix[1]}${virtualKeyReason[1]}`);

    for (const reason of gatewayReasons) {
      assert.ok(
        reason in GATEWAY_READINESS_REASON_LABELS,
        `no admin copy for gateway readiness reason ${reason}`,
      );
    }
    // The two alias codes above must still be the ones the backend uses.
    for (const alias of [
      "ALIAS_DENIAL_CATALOG_MISSING",
      "ALIAS_DENIAL_CATALOG_CONTAINS_CREDENTIAL",
    ]) {
      assert.match(GATEWAY_READINESS_SOURCE, new RegExp(alias));
    }

    const genericReasons = new Set([
      ...Array.from(
        PROVIDER_READINESS_SOURCE.matchAll(/^\s*return "([a-z_]+)"$/gm),
        (match) => match[1],
      ),
      ...Array.from(
        PROVIDER_READINESS_SOURCE.matchAll(
          /_readiness\(\s*\n?\s*READINESS_[A-Z_]+,\s*\n?\s*"([a-z_]+)"/g,
        ),
        (match) => match[1],
      ),
      ...setMembers(PROVIDER_READINESS_SOURCE, "_DEGRADED_HEALTH_STATUSES"),
      ...setMembers(
        PROVIDER_READINESS_SOURCE,
        "_UNAVAILABLE_HEALTH_STATUSES",
      ).map((status) => `health_${status}`),
    ]);
    assert.ok(genericReasons.size > 10, "backend reason scrape looks broken");
    for (const reason of genericReasons) {
      assert.ok(
        reason in PROVIDER_READINESS_REASON_LABELS,
        `no admin copy for provider readiness reason ${reason}`,
      );
    }
  });

  test("a known code presents its fixed status, code and copy", () => {
    const presented = presentProviderReadiness({
      status: "needs_configuration",
      reason: "litellm_gateway_virtual_key_secret_ref_not_configured",
      runtime_attempt_allowed: false,
    });
    assert.equal(presented.statusLabel, "Needs configuration");
    assert.equal(presented.tone, "blocked");
    assert.equal(presented.recognized, true);
    assert.equal(presented.runtimeAttemptAllowed, false);
    assert.equal(
      presented.label,
      GATEWAY_READINESS_REASON_LABELS
        .litellm_gateway_virtual_key_secret_ref_not_configured,
    );
  });

  test("a remote body or unknown code is never echoed", () => {
    const hostile = presentProviderReadiness({
      status: '<b>500</b> from https://litellm.internal.example',
      reason:
        'upstream said: {"error":"invalid key sk-live-abcdef","url":"https://litellm.internal.example/v1"}',
      runtime_attempt_allowed: true,
    });
    assert.equal(hostile.code, "unrecognized");
    assert.equal(hostile.statusCode, "unrecognized");
    assert.equal(hostile.statusLabel, "Unrecognized");
    assert.equal(hostile.recognized, false);
    assert.equal(
      hostile.label,
      "This readiness code has no admin description yet.",
    );
    const rendered = JSON.stringify(hostile);
    for (const leak of ["sk-live", "litellm.internal.example", "https://", "<b>"]) {
      assert.equal(rendered.includes(leak), false, `leaked ${leak}`);
    }
  });

  test("a missing readiness payload degrades instead of throwing", () => {
    const presented = presentProviderReadiness(undefined);
    assert.equal(presented.code, "unrecognized");
    assert.equal(presented.runtimeAttemptAllowed, false);
  });
});

describe("admin error text stays bounded", () => {
  test("a governed fixed message survives", () => {
    assert.equal(
      boundedAdminErrorText(
        new Error("runtime_fallback_mode must be one of: all_runtimes, first_runtime_only"),
        "fallback copy",
      ),
      "runtime_fallback_mode must be one of: all_runtimes, first_runtime_only",
    );
  });

  test("a remote body, URL, header or oversized text collapses to fixed copy", () => {
    for (const hostile of [
      new Error("upstream: https://litellm.internal.example/v1 returned 502"),
      new Error("Authorization: Bearer sk-live-abcdef @proxy"),
      new Error("x".repeat(500)),
      new Error("  "),
      "not an error",
      undefined,
    ]) {
      assert.equal(boundedAdminErrorText(hostile, "fallback copy"), "fallback copy");
    }
  });
});
