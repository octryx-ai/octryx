// Render guards for admin runtime and people parts split into smaller functions: the gateway fields, the add-provider
// panel, the Google and local-bootstrap provider cards, voice & speech, the user accounts panel, plus the identity
// provider hook behave and render the same after being split up.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { load } from "./adminPartsLoader.mjs";
import { act, byTestId, server, text, tick } from "./settingsRenderHarness.mjs";

const noop = () => {};

function create(element) {
  let view;
  act(() => { view = TestRenderer.create(element); });
  return view;
}

const all = (view, type) => view.root.findAll((node) => node.type === type);
const same = (actual, expected) => assert.equal(JSON.stringify(actual), JSON.stringify(expected));

test("the gateway fields render address, models and technical details and patch the draft", () => {
  const { LiteLlmGatewayConfigFields } = load("admin/components/providerTab/LiteLlmGatewayConfigFields.tsx");
  const { emptyGatewayDraft, emptyGatewayAliasDraft } = load("admin/components/providerTab/litellmGatewayDrafts.ts");
  const changes = [];
  const draft = { ...emptyGatewayDraft(), endpointUrl: "ftp://x", aliases: [emptyGatewayAliasDraft(), emptyGatewayAliasDraft()] };
  const view = create(createElement(LiteLlmGatewayConfigFields, { draft, idPrefix: "gw", onChange: (next) => changes.push(next) }));
  const page = text(view.root);
  for (const part of ["Gateway", "Address", "Allowed hosts", "Timeout in seconds (optional)", "Models", "Add model", "Technical details",
    "Models path", "Response format", "Model name field"]) assert.ok(page.includes(part), part);
  same(all(view, "select").map((node) => node.props.id).slice(-3), ["gw-probe-path", "gw-probe-shape", "gw-probe-field"]);
  same(all(view, "select").map((node) => node.findAll((child) => child.type === "option").length).slice(-3), [2, 1, 2]);
  assert.equal(all(view, "select").length, 7);
  assert.equal(byTestId(view, "litellm-gateway-problems").length, 1);
  assert.equal(view.root.findAll((node) => node.props.id === "gw-endpoint")[0].props.value, "ftp://x");
  view.root.findAll((node) => node.props.id === "gw-timeout")[0].props.onChange({ target: { value: "30" } });
  assert.equal(changes[0].requestTimeoutSeconds, "30");
  all(view, "button").find((node) => text(node) === "Add model").props.onClick();
  assert.equal(changes[1].aliases.length, 3);
  view.root.findAll((node) => node.props.id === "gw-probe-field")[0].props.onChange({ target: { value: "model_name" } });
  assert.equal(changes[2].probeModelGroupField, "model_name");
  const disabled = create(createElement(LiteLlmGatewayConfigFields, { draft, idPrefix: "gw", onChange: noop, disabled: true }));
  assert.ok(all(disabled, "select").every((node) => node.props.disabled === true));
});

const providerCtx = (patch = {}) => ({
  showAddProvider: true, setShowAddProvider: noop, handleAddProvider: noop, providerFormError: null, providerFormLoading: false,
  newProviderDriver: "openai_compatible", newProviderDisplay: "", newProviderEndpointUrl: "", newProviderKey: "", newProviderRegion: "",
  newProviderArn: "", newProviderSecretKey: "", newProviderSessionToken: "", newProviderAuthMode: "oauth", newGoogleClientId: "",
  newGoogleClientSecret: "", newGoogleCloudProject: "", setNewProviderDriver: noop, setNewProviderDisplay: noop, setNewProviderEndpointUrl: noop,
  setNewProviderKey: noop, setNewProviderRegion: noop, setNewProviderArn: noop, setNewProviderSecretKey: noop, setNewProviderSessionToken: noop,
  setNewProviderAuthMode: noop, setNewGoogleClientId: noop, setNewGoogleClientSecret: noop, setNewGoogleCloudProject: noop, ...patch,
});

const labels = (view) => view.root.findAll((node) => node.type === "label" && node.props.className === "admin-panel__field")
  .map((node) => text(node.children[0]));

test("add provider shows the access fields per provider type, the footer and the error", () => {
  const { AddProviderForm } = load("admin/components/providerTab/AddProviderForm.tsx");
  const closed = [];
  const openai = create(createElement(AddProviderForm, { ctx: providerCtx({ setShowAddProvider: (value) => closed.push(value), providerFormError: "Boom" }) }));
  assert.equal(byTestId(openai, "provider-add-panel").length, 1);
  same(labels(openai).slice(-3), ["Display name", "API base URL", "API key (optional for local gateways)"]);
  assert.equal(text(byTestId(openai, "provider-add-submit")[0]), "Add provider");
  assert.ok(text(openai.root).includes("Boom"));
  byTestId(openai, "provider-add-cancel")[0].props.onClick();
  same(closed, [false]);

  const bedrock = create(createElement(AddProviderForm, { ctx: providerCtx({ newProviderDriver: "bedrock_api", providerFormLoading: true }) }));
  same(labels(bedrock).slice(-5), ["AWS region", "IAM role ARN (optional)", "AWS access key ID (optional for local dev)", "AWS secret access key",
    "AWS session token (optional)"]);
  assert.equal(text(byTestId(bedrock, "provider-add-submit")[0]), "Adding…");
  assert.equal(all(bedrock, "input").filter((node) => node.props.type === "password").length, 2);

  const google = create(createElement(AddProviderForm, { ctx: providerCtx({ newProviderDriver: "gemini_api" }) }));
  same(labels(google).slice(-4), ["Google auth mode", "Google OAuth client ID", "Google OAuth client secret", "Google Cloud project"]);
  const gemini = create(createElement(AddProviderForm, { ctx: providerCtx({ newProviderDriver: "gemini_api", newProviderAuthMode: "api_key" }) }));
  same(labels(gemini).slice(-2), ["Google auth mode", "Gemini API key"]);
  const ollama = create(createElement(AddProviderForm, { ctx: providerCtx({ newProviderDriver: "ollama" }) }));
  same(labels(ollama).slice(-2), ["Display name", "Ollama URL"]);
  assert.equal(all(ollama, "input").filter((node) => node.props.type === "password").length, 0);
  const hidden = create(createElement(AddProviderForm, { ctx: providerCtx({ showAddProvider: false }) }));
  assert.equal(hidden.toJSON(), null);
});

test("the Google provider card switches between login, key display and key editing, and saves its OAuth config", () => {
  const { ProviderGoogleAuth } = load("admin/components/providerTab/ProviderGoogleAuth.tsx");
  const saved = [];
  const drafts = [];
  const ctx = { editingKey: null, googleConnectLoading: null, handleGoogleConnect: noop, handleSaveApiKey: noop, newKeyValue: "",
    handleProviderDraftChange: (...args) => drafts.push(args), handleSaveGoogleProviderConfig: (id) => saved.push(id),
    providerDrafts: { g1: { google_cloud_project: "proj-x" } }, savingProviderConfig: null, setEditingKey: noop, setNewKeyValue: noop };
  const oauth = create(createElement(ProviderGoogleAuth, { ctx, provider: { id: "g1", auth_mode: "oauth", auth_login: "ada", google_oauth_client_configured: true } }));
  const page = text(oauth.root);
  for (const part of ["Google Gemini", "ada · no project", "Reconnect with Google", "OAuth Config", "Save Config"]) assert.ok(page.includes(part), part);
  same(all(oauth, "input").map((node) => node.props.placeholder), ["Google OAuth Client ID", "Leave blank to keep current client secret", "Google Cloud Project"]);
  assert.equal(all(oauth, "input")[2].props.value, "proj-x");
  all(oauth, "input")[1].props.onChange({ target: { value: "s" } });
  same(drafts[0], ["g1", "google_oauth_client_secret", "s"]);
  all(oauth, "button").find((node) => text(node) === "Save Config").props.onClick();
  same(saved, ["g1"]);
  const key = create(createElement(ProviderGoogleAuth, { ctx, provider: { id: "g2", auth_mode: "api_key", has_api_key: true, api_key_masked: "AI…12" } }));
  assert.ok(text(key.root).includes("AI…12"));
  assert.ok(all(key, "button").some((node) => text(node) === "Change"));
  const editing = create(createElement(ProviderGoogleAuth, { ctx: { ...ctx, editingKey: "g2", savingProviderConfig: "g2" }, provider: { id: "g2", auth_mode: "api_key" } }));
  same(all(editing, "button").map((node) => text(node)), ["Save", "Cancel", "Saving…"]);
  assert.equal(all(editing, "input")[0].props.placeholder, "Enter Gemini API key");
});

test("the local bootstrap card hides without state and shows its fields, actions and anchor line", () => {
  const { ProvidersLocalBootstrapCard } = load("admin/components/providerTab/ProvidersLocalBootstrapCard.tsx");
  const base = { handleCheckLocalBootstrap: noop, handleSetupLocalBootstrap: noop, localBootstrap: null, localBootstrapActionLoading: null,
    localBootstrapDisplayDraft: "", localBootstrapEndpointDraft: "", localBootstrapError: null, localBootstrapLoading: false,
    localBootstrapMakePrimary: false, localBootstrapModelDraft: "", localBootstrapPullModel: true, setLocalBootstrapDisplayDraft: noop,
    setLocalBootstrapEndpointDraft: noop, setLocalBootstrapMakePrimary: noop, setLocalBootstrapModelDraft: noop, setLocalBootstrapPullModel: noop,
    providers: [] };
  assert.equal(create(createElement(ProvidersLocalBootstrapCard, { ctx: base })).toJSON(), null);
  const bootstrap = { setup_complete: true, health_status: "ok", endpoint_url: "http://localhost:11434", available_models: ["gemma4:e4b"],
    provider_display_name: "Anchor", model_id: "gemma4", is_primary: true, last_health_error: "" };
  const view = create(createElement(ProvidersLocalBootstrapCard, { ctx: { ...base, localBootstrap: bootstrap, localBootstrapError: "Down",
    localBootstrapActionLoading: "setup" } }));
  const page = text(view.root);
  for (const part of ["Local Gemma 4 Anchor", "Ollama endpoint", "Bootstrap model", "Display name", "Pull model automatically",
    "Set as primary runtime", "Check Ollama", "Bootstrapping…", "Configured · ok · http://localhost:11434 · models: gemma4:e4b",
    "Current anchor: Anchor · model gemma4 · primary runtime", "Down"]) assert.ok(page.includes(part), part);
  assert.equal(all(view, "input").length, 5);
  const loading = create(createElement(ProvidersLocalBootstrapCard, { ctx: { ...base, localBootstrapLoading: true } }));
  assert.ok(text(loading.root).includes("Loading local status…"));
});

test("voice & speech loads both cards, switches the TTS provider fields and saves the provider, config and speech requests", async () => {
  const tts = { enabled: true, default_voice: "nova", providers: [{ provider: "openai", enabled: true, config: { model: "tts-1-hd" } }] };
  const srv = server((call) => {
    if (call.url.endsWith("/tts/config") && call.url.startsWith("/chat")) return { status: 200, body: tts };
    if (call.url.endsWith("/tts/config")) return { status: 200, body: { openai_api_key: "sk-…" } };
    if (call.url.endsWith("/stt/config")) return { status: 200, body: { active_provider: "azure_speech", language: "", providers: {} } };
    return { status: 200, body: {} };
  });
  const { AdminVoiceAndSpeech } = load("admin/components/voice/AdminVoiceAndSpeech.tsx", { fetch: srv.fetch });
  let view;
  await act(async () => { view = TestRenderer.create(createElement(AdminVoiceAndSpeech)); });
  await tick();
  const page = text(view.root);
  for (const part of ["Text to speech", "Speech to text", "Voice", "Quality", "Text to speech is on", "Configured", "Subscription key",
    "Used by Teams calling", "Play a test sentence", "Save voice & speech"]) assert.ok(page.includes(part), part);
  assert.equal(byTestId(view, "tts-setting")[0].props.value, "tts-1-hd");
  assert.equal(byTestId(view, "tts-voice")[0].props.value, "nova");
  assert.equal(all(view, "input").filter((node) => node.props.type === "password").length, 2);
  await act(async () => { byTestId(view, "tts-provider")[0].props.onChange({ target: { value: "aws_polly" } }); });
  assert.equal(all(view, "input").filter((node) => node.props.type === "password").length, 3);
  await act(async () => { byTestId(view, "voice-save")[0].props.onClick(); });
  await tick();
  same(srv.calls.filter((call) => call.method !== "GET").map((call) => [call.method, call.url]), [
    ["POST", "/chat/api/v1/tts/providers"], ["PUT", "/chat/api/v1/tts/config"], ["PUT", "/admin/chat/api/panel/stt/config"]]);
  assert.ok(text(view.root).includes("Saved: voice & speech only."));
  act(() => view.unmount());
});

const accountsProps = (patch = {}) => ({
  users: [{ id: "u1", username: "ada", email: "ada@example.com", display_name: "Ada", is_active: true, roles: [], groups: [] }],
  totalUsers: 4, roleNames: ["operator"], groups: [], currentUserId: "u1", userQuery: "", userStatusFilter: "all", userActionError: "Nope",
  userActionLoading: null, showCreateUser: false, newUsername: "", newEmail: "", newPassword: "", newDisplayName: "", newAccountType: "human",
  newRole: "", formError: null, formLoading: false, editingUser: null, apiKeys: [], apiKeyName: "", apiKeyScopes: "", apiKeyExpiresAt: "",
  apiKeyCreatedSecret: null, apiKeyError: null, apiKeyLoading: null, oidcIdentities: [], oidcIdentityError: null, oidcIdentityLoading: false,
  setShowCreateUser: noop, setUserQuery: noop, setUserStatusFilter: noop, setNewUsername: noop, setNewEmail: noop, setNewPassword: noop,
  setNewDisplayName: noop, setNewAccountType: noop, setNewRoles: noop, setApiKeyName: noop, setApiKeyScopes: noop, setApiKeyExpiresAt: noop,
  onCreateUser: noop, onEditUser: noop, onCloseEditPanel: noop, onSaveProfile: async () => {}, onSaveRole: noop, onSaveGroups: noop,
  onResetPassword: async () => {}, onToggleUserStatus: noop, onCreateApiKey: noop, onRevokeApiKey: noop, ...patch,
});

test("the user accounts panel shows the toolbar, the error, the table and opens the create form", () => {
  const { AdminUserAccountsPanel } = load("admin/components/usersTab/AdminUserAccountsPanel.tsx");
  const opened = [];
  const queries = [];
  const view = create(createElement(AdminUserAccountsPanel, accountsProps({ setShowCreateUser: (value) => opened.push(value),
    setUserQuery: (value) => queries.push(value) })));
  const page = text(view.root);
  for (const part of ["New user", "User accounts (1/4)", "All users", "Active users", "Inactive users", "Nope", "ada"]) assert.ok(page.includes(part), part);
  byTestId(view, "user-create-open")[0].props.onClick();
  same(opened, [true]);
  view.root.findAll((node) => node.props["aria-label"] === "Search users")[0].props.onChange({ target: { value: "bo" } });
  same(queries, ["bo"]);
  assert.equal(view.root.findAll((node) => node.type === "form").length, 0);
  const creating = create(createElement(AdminUserAccountsPanel, accountsProps({ showCreateUser: true, userActionError: null })));
  assert.equal(creating.root.findAll((node) => node.type === "form").length, 1);
  assert.ok(!text(creating.root).includes("Nope"));
  const editing = create(createElement(AdminUserAccountsPanel, accountsProps({ editingUser: accountsProps().users[0] })));
  assert.ok(editing.root.findAll((node) => node.type === "form").length >= 1);
});

test("the identity provider hook loads, creates, edits a draft and saves the provider", async () => {
  const { useAdminIdentityProviders } = load("admin/components/usersTab/useAdminIdentityProviders.ts");
  const calls = [];
  const row = (patch) => ({ id: "p1", name: "Corp", providerType: "oidc", issuerUrl: "https://i", discoveryUrl: "", clientId: "c",
    scopes: ["openid"], claimMappings: {}, groupRoleMappings: {}, groupGroupMappings: {}, defaultRoles: [], defaultGroupIds: [],
    autoProvisionUsers: true, isActive: true, ...patch });
  const readJson = async (url, init) => {
    calls.push([url, init?.method ?? "GET", init?.body ? JSON.parse(init.body) : null]);
    if (!init) return [row({})];
    if (init.method === "POST") return row({ id: "p0", name: "Alpha" });
    if (url.endsWith("/p1")) return row({ name: "Corp 2" });
    throw new Error("refused");
  };
  let model;
  function Probe() {
    model = useAdminIdentityProviders(readJson);
    return null;
  }
  let view;
  await act(async () => { view = TestRenderer.create(createElement(Probe)); });
  await act(async () => { await model.loadIdentityProviders(); });
  same(model.providers.map((item) => item.id), ["p1"]);
  assert.equal(model.providerDrafts.p1.scopes, "openid");
  assert.equal(model.providerDrafts.p1.claimMappings.subject, "sub");
  await act(async () => { await model.createIdentityProvider({ name: "Alpha", issuerUrl: "https://a", discoveryUrl: "", clientId: "a",
    clientSecret: "", scopes: "openid, email" }); });
  same(model.providers.map((item) => item.name), ["Alpha", "Corp"]);
  same(calls[1][2].scopes, ["openid", "email"]);
  assert.equal(calls[1][2].client_secret, undefined);
  await act(async () => { model.updateDraft("p1", (draft) => ({ ...draft, name: "Corp 2", scopes: "a, b" })); });
  await act(async () => { model.updateDraft("missing", (draft) => ({ ...draft, name: "x" })); });
  assert.equal(model.providerDrafts.missing, undefined);
  await act(async () => { await model.saveIdentityProvider(model.providers[1], [], []); });
  same([calls[2][0], calls[2][1], calls[2][2].name, calls[2][2].scopes], ["/admin/chat/api/panel/identity-providers/p1", "PUT", "Corp 2", ["a", "b"]]);
  assert.equal(model.providers[1].name, "Corp 2");
  assert.equal(model.providerError, null);
  await act(async () => { await model.saveIdentityProvider(model.providers[0], [], []); });
  assert.equal(model.providerError, "refused");
  assert.equal(model.providerLoading, null);
  act(() => view.unmount());
});
