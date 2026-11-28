// Admin › Models: the bundled LiteLLM's model panel asks only for what the provider type needs, keeps credentials
// write-only on an edit and adds the route under the name Octryx uses.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { load } from "./adminPartsLoader.mjs";
import { act, byTestId, text } from "./settingsRenderHarness.mjs";

const noop = () => {};
const CATALOG = {
  routes: [],
  provider_types: {
    anthropic: { fields: ["api_key"], required: ["api_key"] },
    bedrock: { fields: ["aws_region_name", "aws_access_key_id", "aws_secret_access_key", "aws_session_token"],
      required: ["aws_region_name"] },
  },
  data_policy_classes: ["internal", "public"],
};

function create(element) {
  let view;
  act(() => { view = TestRenderer.create(element); });
  return view;
}

const inputs = (view) => view.root.findAll((node) => node.type === "input");
const byId = (view, id) => view.root.findAll((node) => node.props.id === id)[0];

test("a new model asks for the provider's own fields and the name Octryx uses", () => {
  const { ModelRouteDrawer } = load("admin/components/providerTab/modelRoutes/ModelRouteDrawer.tsx");
  const { emptyDraft } = load("admin/components/providerTab/modelRoutes/modelRoutesApi.ts");
  const view = create(createElement(ModelRouteDrawer, { draft: emptyDraft({ providerType: "anthropic", dataClass: "internal" }),
    editing: false, catalog: CATALOG, onClose: noop, onChanged: noop }));
  assert.equal(byId(view, "route-api_key").props.type, "password");
  assert.equal(byId(view, "route-api_key").props.required, true);
  assert.ok(byId(view, "route-alias"));
  assert.equal(text(byTestId(view, "model-route-save")[0]), "Add model");
  assert.equal(byTestId(view, "model-route-test").length, 0);
  act(() => byId(view, "route-type").props.onChange({ target: { value: "bedrock" } }));
  assert.deepEqual(inputs(view).map((node) => String(node.props.id ?? "")).filter((id) => id.startsWith("route-aws")),
    ["route-aws_region_name", "route-aws_access_key_id", "route-aws_secret_access_key", "route-aws_session_token"]);
  assert.equal(byId(view, "route-aws_session_token").props.type, "password");
  assert.equal(byId(view, "route-api_key"), undefined);
});

test("an edit keeps credentials write-only and offers test and remove", () => {
  const { ModelRouteDrawer } = load("admin/components/providerTab/modelRoutes/ModelRouteDrawer.tsx");
  const { draftFromRoute } = load("admin/components/providerTab/modelRoutes/modelRoutesApi.ts");
  const route = { alias: "claude-work", provider_type: "anthropic", model: "claude-sonnet-4-5", settings: {},
    data_policy_class: "internal", context_limit: 200000, input_per_million_usd: 3, output_per_million_usd: 15, tools: true,
    state: "ok", problem: "" };
  const view = create(createElement(ModelRouteDrawer, { draft: draftFromRoute(route), editing: true, catalog: CATALOG,
    onClose: noop, onChanged: noop }));
  const key = byId(view, "route-api_key");
  assert.equal(key.props.value, "");
  assert.equal(key.props.required, false);
  assert.equal(key.props.placeholder, "Unchanged");
  assert.equal(byId(view, "route-alias"), undefined);
  assert.equal(byTestId(view, "model-route-test").length, 1);
  assert.equal(byTestId(view, "model-route-remove").length, 1);
  assert.equal(text(byTestId(view, "model-route-save")[0]), "Save changes");
});
