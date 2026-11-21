import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import {
  SecretRebindRequiredError,
  formWithSecretRebindConfirmation,
  formWithoutSecretRebindConfirmation,
  parseSecretRebindRefusal,
  withSecretRebindConfirmation,
} from "../../src/admin/secretRebind/secretRebindModel.ts";
import { blockedReentry, flowAtStep, refusedFlow } from "../../src/admin/secretRebind/secretRebindFlow.ts";
import { readJson } from "../../src/admin/utils/adminPanelHelpers.ts";
import { classifyToolsConfigResponse } from "../../src/admin/toolsConfigGuard/toolsConfigSubmit.ts";
import { reasonNotice, runReasonNotice } from "../../src/admin/components/workspaceKnowledge/runReasonNotice.ts";

// The 409 body of backend/app/services/tool_config/secret_rebind.py (SecretRebindRequiredError.detail()).
const REFUSED = {
  detail: {
    state: "secret_rebind_required",
    tool_name: "confluence",
    changed_target_fields: ["confluence_url"],
    kept_fields: ["confluence_password"],
    remediation: "Re-enter the listed secrets for the new target, or confirm the rebind explicitly with confirm_secret_rebind=true.",
  },
};

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

test("only a 409 secret_rebind_required is a refusal, and only field names survive parsing", () => {
  assert.deepEqual(parseSecretRebindRefusal(409, REFUSED), {
    toolName: "confluence",
    changedTargetFields: ["confluence_url"],
    keptFields: ["confluence_password"],
  });
  assert.equal(parseSecretRebindRefusal(400, REFUSED), null);
  assert.equal(parseSecretRebindRefusal(409, { detail: { state: "refused", reason: "run_in_progress" } }), null);
  assert.equal(parseSecretRebindRefusal(409, { detail: "secret_rebind_required" }), null);
  const hostile = parseSecretRebindRefusal(409, {
    detail: { ...REFUSED.detail, changed_target_fields: ["confluence_url", "https://wiki-b.example.test"], kept_fields: ["pw-1 value", 7] },
  });
  assert.deepEqual(hostile.changedTargetFields, ["confluence_url"]);
  assert.deepEqual(hostile.keptFields, []);
});

test("confirming resends the same body plus the explicit flag; a first submission never carries it", () => {
  const body = { confluence_url: "https://wiki-b.example.test/wiki", is_active: true };
  assert.deepEqual(withSecretRebindConfirmation(body), { ...body, confirm_secret_rebind: true });
  assert.equal("confirm_secret_rebind" in body, false);

  const form = new URLSearchParams({ tool_name: "confluence", config_json: "{}" });
  const confirmed = formWithSecretRebindConfirmation(form);
  assert.equal(confirmed.get("confirm_secret_rebind"), "true");
  assert.equal(confirmed.get("config_json"), "{}");
  assert.equal(form.has("confirm_secret_rebind"), false);
  assert.equal(formWithoutSecretRebindConfirmation(confirmed).has("confirm_secret_rebind"), false);
});

test("the re-enter step stops a save until every kept secret has a new value", () => {
  const flow = refusedFlow(parseSecretRebindRefusal(409, REFUSED), { any: "body" });
  assert.equal(blockedReentry(flow, {}), null, "the choose step checks nothing");
  const reenter = flowAtStep(flow, "reenter");
  const blocked = blockedReentry(reenter, { confluence_password: "  " });
  assert.deepEqual(blocked.missing, ["confluence_password"]);
  assert.match(blocked.error, /confluence password/);
  assert.equal(blockedReentry(reenter, { confluence_password: "pw-2" }), null);
});

test("the admin JSON reader raises the explicit refusal instead of an opaque error", async () => {
  globalThis.fetch = async () => new Response(JSON.stringify(REFUSED), { status: 409, headers: { "Content-Type": "application/json" } });
  await assert.rejects(readJson("/admin/chat/api/panel/connectors/confluence", { method: "PUT", body: "{}" }), (err) => {
    assert.ok(err instanceof SecretRebindRequiredError);
    assert.deepEqual(err.refusal.keptFields, ["confluence_password"]);
    return true;
  });
});

test("the /admin/tools post outcome: refusal, redirect after save, test page, anything else fails", () => {
  assert.equal(classifyToolsConfigResponse(409, false, "application/json"), "refused");
  assert.equal(classifyToolsConfigResponse(200, true, "text/html; charset=utf-8"), "navigate");
  assert.equal(classifyToolsConfigResponse(200, false, "text/html; charset=utf-8"), "replace_page");
  assert.equal(classifyToolsConfigResponse(400, false, "application/json"), "failed");
  assert.equal(classifyToolsConfigResponse(200, false, "application/json"), "failed");
});

test("egress_refused in a run or item reason is an explicit notice with its code and no URL", () => {
  const notice = reasonNotice("egress_refused");
  assert.equal(notice.code, "egress_refused");
  assert.equal(notice.title, "Outbound connection refused by the egress policy");
  assert.doesNotMatch(notice.text, /https?:\/\//);
  assert.equal(reasonNotice("source_unavailable"), null);
  assert.equal(runReasonNotice("egress_refused", []).code, "egress_refused");
  assert.equal(runReasonNotice(null, [null, "source_not_found", "egress_refused"]).code, "egress_refused");
  assert.equal(runReasonNotice("source_unavailable", ["source_not_found"]), null);
});
