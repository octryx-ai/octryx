// The user editor keeps every assigned role: saving sends all of them, never only the first ("Primary role"), so no
// role (incl. SSO-mapped roles) is silently dropped.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { registerHooks } from "node:module";
import { readFileSync } from "node:fs";
import { transpileModule, ModuleKind, JsxEmit } from "typescript";

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.startsWith(".") && !/\.[a-z]+$/.test(specifier)) {
      try { return nextResolve(`${specifier}.tsx`, context); } catch { /* Shared hook resolves pure TS. */ }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.endsWith(".css")) return { format: "module", source: "", shortCircuit: true };
    if (url.endsWith(".tsx")) return { format: "module", shortCircuit: true, source: transpileModule(readFileSync(new URL(url), "utf8"), {
      compilerOptions: { module: ModuleKind.ESNext, jsx: JsxEmit.ReactJSX },
    }).outputText };
    return nextLoad(url, context);
  },
});

const { AdminUserEditPanel } = await import("../../src/admin/components/usersTab/AdminUserEditPanel.tsx");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;

const text = (node) => (typeof node === "string" ? node : (node.children || []).map(text).join(""));
const noop = () => {};

function renderPanel(onSaveRole) {
  const user = {
    id: "u-1", username: "rivka", email: "rivka@example.com", display_name: "Rivka", account_type: "human",
    roles: ["operator", "sso-auditor"], groups: [], is_active: true,
  };
  let renderer;
  act(() => {
    renderer = TestRenderer.create(createElement(AdminUserEditPanel, {
      user, roleNames: ["operator", "viewer", "technical"], groups: [], apiKeys: [], apiKeyName: "", apiKeyScopes: "",
      apiKeyExpiresAt: "", apiKeyCreatedSecret: null, apiKeyError: null, apiKeyLoading: null, oidcIdentities: [],
      oidcIdentityError: null, oidcIdentityLoading: false, userActionLoading: null, setApiKeyName: noop,
      setApiKeyScopes: noop, setApiKeyExpiresAt: noop, onClose: noop, onSaveProfile: async () => {}, onSaveRole,
      onSaveGroups: noop, onResetPassword: async () => {}, onCreateApiKey: noop, onRevokeApiKey: noop,
    }));
  });
  return renderer;
}

function rolesSection(renderer) {
  return renderer.root.findAll((node) => node.props.className === "user-edit-panel__section")
    .find((section) => text(section).startsWith("Roles"));
}

test("saving roles sends every assigned role, including one not in the catalog list", async () => {
  const saved = [];
  const renderer = renderPanel((userId, roles) => { saved.push({ userId, roles }); });
  const section = rolesSection(renderer);
  assert.ok(section, "the editor has a Roles section");
  assert.match(text(section), /2 roles selected/);

  const save = section.findAll((node) => node.type === "button" && text(node) === "Save")[0];
  await act(async () => { save.props.onClick(); });

  assert.deepEqual(saved, [{ userId: "u-1", roles: ["operator", "sso-auditor"] }]);
});

test("adding a role keeps the existing ones", async () => {
  const saved = [];
  const renderer = renderPanel((_userId, roles) => { saved.push(roles); });
  const section = rolesSection(renderer);
  const trigger = section.find((node) => node.props.className === "user-edit-panel__multi-trigger");
  await act(async () => { trigger.props.onClick(); });
  const viewer = rolesSection(renderer).findAll((node) => node.type === "button" && text(node).trim() === "viewer")[0];
  await act(async () => { viewer.props.onClick(); });
  const save = rolesSection(renderer).findAll((node) => node.type === "button" && text(node) === "Save")[0];
  await act(async () => { save.props.onClick(); });

  assert.deepEqual(saved, [["operator", "sso-auditor", "viewer"]]);
});
