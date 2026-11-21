// Render guards for admin parts split into smaller functions: the tool policy controls, the LiteLLM gateway add form,
// the add-model form, the REST read test call and the artifact store fields render the same structure and make the
// same calls.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, byTestId, text, tick } from "./settingsRenderHarness.mjs";
import { all, buttons, create, includesAll, plain } from "./adminGuardRenderers.mjs";
import { loadStubbed, stubs } from "./adminGuardStubLoader.mjs";
import { button, hostCount } from "./adminGuardTreeReaders.mjs";

test("the LiteLLM gateway add form reports its state, refuses an incomplete draft and creates the provider", async () => {
  const states = [], created = [];
  const contract = { emptyGatewayDraft: () => ({ endpoint: "" }), isGatewayDraftSubmittable: (draft) => Boolean(draft.displayName && draft.endpoint),
    buildGatewayCreatePayload: (draft) => ({ built: draft }) };
  const { LiteLlmGatewayAddForm } = loadStubbed("admin/components/providerTab/LiteLlmGatewayAddForm.tsx", ["./LiteLlmGatewayConfigFields",
    "./LiteLlmGatewaySecretNotice", "./ProviderTypeSelect"], {}, { "./litellmGatewayContract": contract, "./litellmGatewayDrafts": contract, "./litellmGatewayPayload": contract, "./litellmGatewayTypes": contract, "./litellmGatewayValidation": contract });
  let answer = { ok: false, error: "Taken" };
  const display = [];
  const ctx = { handleCreateLiteLlmGatewayProvider: async (payload) => { created.push(payload); return answer; }, newProviderDisplay: "GW",
    newProviderDriver: "litellm_gateway", setNewProviderDisplay: (value) => display.push(value), setNewProviderDriver() {} };
  const onStateChange = (state) => states.push(state);
  const view = create(createElement(LiteLlmGatewayAddForm, { ctx, formId: "f1", onStateChange }));
  assert.equal(all(view, "form")[0].props.id, "f1");
  assert.equal(all(view, "input")[0].props.value, "GW");
  assert.equal(stubs(view, "LiteLlmGatewaySecretNotice")[0].props.idPrefix, "litellm-gateway-new");
  assert.equal(hostCount(view), 7);
  await act(async () => all(view, "form")[0].props.onSubmit({ preventDefault() {} }));
  includesAll(text(view.root), ["The governed fields are incomplete."]);
  act(() => stubs(view, "LiteLlmGatewayConfigFields")[0].props.onChange({ endpoint: "https://gw" }));
  await act(async () => all(view, "form")[0].props.onSubmit({ preventDefault() {} }));
  includesAll(text(view.root), ["Taken"]);
  answer = { ok: true };
  await act(async () => all(view, "form")[0].props.onSubmit({ preventDefault() {} }));
  assert.deepEqual(plain(created), [{ built: { endpoint: "https://gw", displayName: "GW" } }, { built: { endpoint: "https://gw", displayName: "GW" } }]);
  assert.deepEqual(display, [""]);
  assert.equal(stubs(view, "LiteLlmGatewayConfigFields")[0].props.draft.endpoint, "");
  assert.deepEqual(plain(states.at(-1)), { saving: false, submittable: false });
  assert.deepEqual(plain(states.filter((state) => state.submittable).at(0)), { saving: false, submittable: true });
});

const operation = { id: "op1", method: "GET", path: "/t", params_overlay: { fixed: { value: "1" } }, request_body: null,
  parameters: [{ name: "group", in: "query", required: true, description: "The group", schema: { type: "string" } },
    { name: "fixed", in: "query", required: false, schema: { type: "string" } }] };

test("the REST read test call fills arguments, runs the call and shows the answer", async () => {
  const calls = [];
  let answer = { status_code: 200, record_count: 2, dropped_out_of_scope: 1, scope: { params: { group: "a" } }, data: [{ id: 1 }],
    run: { duration_ms: 12 } };
  const { RestTestCall } = loadStubbed("admin/components/restApis/RestTestCall.tsx", ["/StatusLabel", "/AdminDetailFacts"], {},
    { "./restApisApi": { testOperation: async (...args) => { calls.push(args); if (answer instanceof Error) throw answer; return answer; } } });
  const props = { definition: { id: "d1" }, operation, workspaces: [{ id: "w1", name: "Harbor" }], write: false };
  const view = create(createElement(RestTestCall, props));
  includesAll(text(view.root), ["Workspace (optional)", "No Workspace (platform connection)", "Harbor", "Arguments as", "Form", "JSON", "group",
    "The group", "Run test call"]);
  assert.equal(byTestId(view, "rest-test-arg-fixed").length, 0);
  assert.equal(hostCount(view), 21);
  act(() => byTestId(view, "rest-test-workspace")[0].props.onChange({ target: { value: "w1" } }));
  act(() => byTestId(view, "rest-test-arg-group")[0].props.onChange({ target: { value: "a" } }));
  await act(async () => byTestId(view, "rest-test-run")[0].props.onClick());
  await tick();
  assert.deepEqual(plain(calls[0].slice(0, 2)), ["d1", "op1"]);
  assert.equal(calls[0][2].workspace_id, "w1");
  includesAll(text(view.root), ["Call succeeded", "[\n  {\n    \"id\": 1\n  }\n]"]);
  assert.deepEqual(plain(stubs(view, "AdminDetailFacts")[0].props.facts.map((fact) => fact.label)), ["HTTP status", "Applied scope",
    "Records kept", "Dropped as out of scope", "Duration"]);
  assert.equal(stubs(view, "StatusLabel")[0].props.tone, "neutral");
  act(() => all(view, "select")[1].props.onChange({ target: { value: "json" } }));
  act(() => all(view, "textarea")[0].props.onChange({ target: { value: "[1]" } }));
  await act(async () => byTestId(view, "rest-test-run")[0].props.onClick());
  includesAll(text(view.root), ["The arguments must be a JSON object."]);
  answer = new Error("boom");
  act(() => all(view, "textarea")[0].props.onChange({ target: { value: "{}" } }));
  await act(async () => byTestId(view, "rest-test-run")[0].props.onClick());
  assert.equal(byTestId(view, "rest-test-result").length, 0);
  const bare = create(createElement(RestTestCall, { ...props, operation: { ...operation, parameters: [] } }));
  includesAll(text(bare.root), ["No arguments to fill in"]);
  const write = create(createElement(RestTestCall, { ...props, write: true }));
  assert.equal(byTestId(write, "rest-test-write-note").length, 1);
});

test("the artifact store fields edit the backend and paths and save only those fields", async () => {
  const requests = [];
  let fail = false;
  const readJson = async (url, init) => { requests.push([url, init.method, JSON.parse(init.body)]); if (fail) throw new Error("Denied");
    return { artifact_store_backend: "s3", artifact_store_bucket: "b2" }; };
  const { RuntimeArtifactStoreFields } = loadStubbed("admin/components/runtimeTab/RuntimeArtifactStoreFields.tsx", ["./RuntimeSettingsGroup"]);
  const view = create(createElement(RuntimeArtifactStoreFields, { ctx: { readJson, runtimeSettings: { artifact_store_bucket: "b1" } } }));
  assert.deepEqual(stubs(view, "RuntimeField").map((node) => node.props.label), ["Backend", "Bucket", "Prefix", "S3 region",
    "S3 endpoint URL (for MinIO)"]);
  assert.deepEqual(all(view, "input").map((node) => [node.props.id, node.props.value, node.props.placeholder]), [
    ["runtime-artifact_store_bucket", "b1", "my-artifacts-bucket"], ["runtime-artifact_store_prefix", "", "artifacts"],
    ["runtime-artifact_store_s3_region", "", "us-east-1"], ["runtime-artifact_store_s3_endpoint_url", "", "https://minio.local:9000"]]);
  assert.equal(all(view, "select")[0].props.value, "filesystem");
  assert.equal(hostCount(view), 17);
  act(() => all(view, "input")[1].props.onChange({ target: { value: "p" } }));
  await act(async () => button(view, "Save artifact store").props.onClick());
  assert.deepEqual(plain(requests[0]), ["/admin/chat/api/panel/runtime-settings", "PUT", { artifact_store_backend: "filesystem",
    artifact_store_bucket: "b1", artifact_store_prefix: "p", artifact_store_s3_region: "", artifact_store_s3_endpoint_url: "" }]);
  includesAll(text(view.root), ["Artifact store settings saved."]);
  assert.equal(all(view, "input")[0].props.value, "b2");
  fail = true;
  await act(async () => button(view, "Save artifact store").props.onClick());
  assert.equal(all(view, "div").filter((node) => node.props.role === "alert" && text(node) === "Denied").length, 1);
});
