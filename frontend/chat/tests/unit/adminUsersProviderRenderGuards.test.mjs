// Render guards for People and Models admin parts: the CLI profile fields, a gateway alias row, a provider model row,
// the identity providers page and the People page model hook render the same structure after being split up.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { act, load, text } from "./settingsRenderHarness.mjs";

const noop = () => {};

function create(element) {
  let view;
  act(() => { view = TestRenderer.create(element); });
  return view;
}

const aliasDraft = (patch = {}) => ({
  alias: "", modelGroup: "gpt-4o", contextLimit: "128000", dataPolicyClass: "internal",
  capabilities: { tools: true, structured_output: false, reasoning: true, vision: false },
  cost: { source: "catalog_pricing", inputPerMillionUsd: "2", outputPerMillionUsd: "8", contractReference: "" },
  approvedDataCategories: [], ...patch,
});

test("a new gateway alias row asks for policy, capabilities and price; a stored one shows its governed summary", () => {
  const { LiteLlmGatewayAliasRow } = load("admin/components/providerTab/LiteLlmGatewayAliasRow.tsx");
  const patches = [];
  const props = { position: 1, idPrefix: "gw", codes: [], removable: true, disabled: false, onPatch: (p) => patches.push(p), onRemove: noop };
  const fresh = create(createElement(LiteLlmGatewayAliasRow, { ...props, alias: aliasDraft() }));
  const page = text(fresh.root);
  assert.match(page, /^Model 2Remove/);
  for (const label of ["Model name", "Gateway model", "Context limit", "Cleared up to", "Requested capabilities", "Price",
    "Input USD / 1M tokens", "Output USD / 1M tokens"]) assert.ok(page.includes(label), label);
  assert.equal(fresh.root.findAll((node) => node.type === "input" && node.props.type === "checkbox").length, 4);
  fresh.root.findAll((node) => node.props.id === "gw-alias-1-cap-vision")[0].props.onChange({ target: { checked: true } });
  assert.equal(patches[0].capabilities.vision, true);
  assert.equal(patches[0].capabilities.tools, true);

  const governed = create(createElement(LiteLlmGatewayAliasRow, { ...props, codes: ["alias_missing"],
    alias: aliasDraft({ alias: "fast", stored: true, cost: { ...aliasDraft().cost, source: "gateway_reported" } }) }));
  assert.equal(governed.root.findAll((node) => node.props["data-testid"] === "gateway-alias-governed").length, 1);
  assert.ok(!text(governed.root).includes("Requested capabilities"));
  assert.equal(governed.root.findAll((node) => node.type === "li").length, 1);

  const contract = create(createElement(LiteLlmGatewayAliasRow, { ...props,
    alias: aliasDraft({ cost: { ...aliasDraft().cost, source: "governed_free", contractReference: "REF-1" } }) }));
  assert.ok(text(contract.root).includes("Governance record"));
  assert.equal(contract.root.findAll((node) => node.props.id === "gw-alias-1-cost-ref")[0].props.value, "REF-1");
});

test("identity providers list rows and register a provider from the side panel", () => {
  const { AdminIdentityProvidersPanel } = load("admin/components/usersTab/AdminIdentityProvidersPanel.tsx");
  const created = [];
  const providers = [
    { id: "idp1", name: "Corp SSO", providerType: "oidc", issuerUrl: "https://login.example.com", isActive: true, autoProvisionUsers: true },
    { id: "idp2", name: "Legacy", providerType: "oidc", issuerUrl: "", isActive: false, autoProvisionUsers: false },
  ];
  const view = create(createElement(AdminIdentityProvidersPanel, {
    providers, drafts: {}, roles: [], groups: [], loading: null, error: "Boom", onRefresh: noop,
    onCreateProvider: (payload) => created.push(payload), onUpdateDraft: noop, onSave: noop,
  }));
  const page = text(view.root);
  for (const part of ["Refresh", "Register OIDC provider", "Boom", "Corp SSO", "Created at first sign-in", "Legacy", "Must exist first"]) {
    assert.ok(page.includes(part), part);
  }
  act(() => { view.root.findAll((node) => node.props["data-testid"] === "oidc-provider-create-open")[0].props.onClick(); });
  const form = view.root.findAll((node) => node.type === "form" && node.props.id === "oidc-provider-create-form")[0];
  assert.deepEqual(form.findAll((node) => node.type === "label").map((node) => text(node.children[0])),
    ["Provider name", "Issuer URL", "Discovery URL (optional)", "Client ID", "Client secret", "Scopes"]);
  act(() => { form.findAll((node) => node.type === "input")[0].props.onChange({ target: { value: "New IdP" } }); });
  act(() => { view.root.findAll((node) => node.type === "form")[0].props.onSubmit({ preventDefault: noop }); });
  assert.equal(JSON.stringify(created), JSON.stringify([{ name: "New IdP", issuerUrl: "", discoveryUrl: "", clientId: "", clientSecret: "",
    scopes: "openid, profile, email" }]));
  assert.equal(view.root.findAll((node) => node.type === "form" && node.props.id === "oidc-provider-create-form").length, 0);
});

test("the People page model loads roles, catalog and groups and filters users", async () => {
  const { useAdminUsersTabModel } = load("admin/components/usersTab/useAdminUsersTabModel.ts");
  const urls = [];
  const readJson = async (url) => {
    urls.push(url);
    if (url.endsWith("/roles")) return [{ id: "r1", name: "operator", description: "", is_core: true, user_count: 1, permissions: [] }];
    if (url.endsWith("/role-permission-catalog")) return [{ resource: "auth", action: "login" }];
    if (url.endsWith("/identity-groups")) return [{ id: "g1", name: "Ops" }];
    return [];
  };
  const users = [
    { id: "u1", username: "ada", email: "ada@example.com", display_name: "Ada", is_active: true, roles: [], groups: [] },
    { id: "u2", username: "bob", email: "bob@example.com", display_name: "", is_active: false, roles: [], groups: [] },
  ];
  let model;
  function Probe() {
    model = useAdminUsersTabModel({ users, readJson, onRoleChange: noop, onDeactivateUser: noop, onUpdateUser: noop,
      onResetUserPassword: noop, section: "users", ask: async () => true });
    return null;
  }
  let view;
  await act(async () => { view = TestRenderer.create(createElement(Probe)); });
  await act(async () => { await new Promise((resolve) => setTimeout(resolve, 0)); });
  assert.deepEqual(urls.slice(0, 3), ["/admin/chat/api/panel/roles", "/admin/chat/api/panel/role-permission-catalog",
    "/admin/chat/api/panel/identity-groups"]);
  assert.deepEqual(model.roleNames, ["operator"]);
  assert.equal(model.groups.length, 1);
  assert.equal(model.rolePermissionCatalog.length, 1);
  assert.equal(model.filteredUsers.length, 2);
  await act(async () => { model.setUserStatusFilter("inactive"); });
  assert.deepEqual(model.filteredUsers.map((user) => user.id), ["u2"]);
  await act(async () => { model.setUserStatusFilter("all"); model.setUserQuery("ADA"); });
  assert.deepEqual(model.filteredUsers.map((user) => user.id), ["u1"]);
  for (const key of ["handleCreateRole", "handleDeleteGroup", "openEditUser", "handleGroupChange", "userApiKeys", "identityProviders",
    "loadAccessDiagnostics", "setEditingRole", "setShowCreateGroup"]) assert.ok(key in model, key);
  assert.equal(Object.keys(model).length, 59);
  act(() => view.unmount());
});
