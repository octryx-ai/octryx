// Render guards for admin forms and panels split into smaller functions: a connector's access panel, the user,
// group and API key forms, tool output compression, the schedule fields, a REST operation's setup, the knowledge
// lookup limits, a provider's model table and GitHub sign-in, and the workspace storage fields render the same
// structure after being split up.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";
import { load } from "./adminPartsLoader.mjs";
import { act, text, tick } from "./settingsRenderHarness.mjs";

function create(element) {
  let view;
  act(() => { view = TestRenderer.create(element); });
  return view;
}

const all = (view, type) => view.root.findAll((node) => node.type === type);
const buttons = (view) => all(view, "button").map((node) => text(node));
const includesAll = (page, parts) => { for (const part of parts) assert.ok(page.includes(part), part); };
const noop = () => {};

test("a connector's access panel shows the switch, the workspace limits and the inherited limits", () => {
  const { ProjectConnectorAccessPanel } = load("admin/components/projectsTab/ProjectConnectorAccessPanel.tsx");
  const connector = { connector_name: "custom", label: "Custom API", global_configured: false, global_active: false,
    limit_fields: ["jira_allowed_projects", "bitbucket_allowed_repos", "custom_allowed_paths"], global_limits: {}, project_limits: {} };
  const draft = { enabled: true, jiraProjects: "OPS", confluenceSpaces: "", confluencePages: [], bitbucketRepos: "", genericLimits: { custom_allowed_paths: "/a" } };
  const updates = [];
  const view = create(createElement(ProjectConnectorAccessPanel, { connector, projectId: "p1", readJson: async () => ({}), draft,
    update: (patch) => updates.push(patch), ownReady: false, markOwnReady: noop, named: false, saving: false, saved: true,
    accessError: "No access", onSave: noop, onClose: noop }));
  includesAll(text(view.root), ["Custom API", "Connector access in this Workspace", "Global setup required", "cannot run here until the platform connector is set up and on",
    "No access", "Connector access saved.", "In this Workspace", "Use Custom API in this Workspace", "Workspace limits",
    "Allowed Jira project keys", "Allowed Bitbucket repositories", "Cancel", "Save access"]);
  assert.equal(all(view, "textarea").length, 3);
  assert.deepEqual(all(view, "textarea").map((node) => node.props.value), ["OPS", "", "/a"]);
  all(view, "textarea")[2].props.onChange({ target: { value: "/b" } });
  assert.equal(JSON.stringify(updates), JSON.stringify([{ genericLimits: { custom_allowed_paths: "/b" } }]));
  act(() => view.unmount());
});

test("the new user form shows the account fields and switches the role with the account type", () => {
  const { AdminUserCreateForm } = load("admin/components/usersTab/AdminUserCreateForm.tsx");
  const roles = [];
  const props = { roleNames: ["admin", "technical", "viewer"], newUsername: "ada", newEmail: "", newPassword: "", newDisplayName: "",
    newAccountType: "human", newRole: "technical", formError: "Taken", formLoading: false, setNewUsername: noop, setNewEmail: noop,
    setNewPassword: noop, setNewDisplayName: noop, setNewAccountType: noop, setNewRoles: (role) => roles.push(role), onCreateUser: noop, onClose: noop };
  const view = create(createElement(AdminUserCreateForm, props));
  includesAll(text(view.root), ["New user", "Account", "Username", "Email", "Password", "At least 8 characters.", "Display name",
    "Account type", "Primary role", "Select role", "Taken", "Cancel", "Create user"]);
  assert.equal(all(view, "input").length, 4);
  assert.equal(all(view, "select").length, 2);
  assert.equal(all(view, "option").length, 6);
  all(view, "select")[0].props.onChange({ target: { value: "human" } });
  all(view, "select")[0].props.onChange({ target: { value: "technical" } });
  assert.deepEqual(roles, ["viewer", "technical"]);
  act(() => view.unmount());
});

test("the group panel shows the info, the description, the toggle and the danger zone", () => {
  const { AdminGroupEditPanel } = load("admin/components/usersTab/AdminGroupEditPanel.tsx");
  const group = { id: "g1", name: "Ops", description: "Operators", member_count: 2, is_active: true, rls_attributes: [{ key: "region", value: "eu" }], created_at: null };
  const updates = [];
  const view = create(createElement(AdminGroupEditPanel, { group, groupLoading: "toggle:g1", onClose: noop,
    onUpdateGroup: (_, payload) => updates.push(payload), onToggleGroup: noop, onDeleteGroup: noop }));
  includesAll(text(view.root), ["Edit group", "Ops", "Members", "Status", "Active", "Data access attributes", "Created", "—",
    "Description", "Save", "Saving…", "Danger zone", "This group has 2 members and cannot be deleted."]);
  const description = all(view, "input")[0];
  assert.equal(description.props.value, "Operators");
  act(() => description.props.onChange({ target: { value: "Ops team" } }));
  act(() => all(view, "button").find((node) => text(node) === "Save").props.onClick());
  assert.equal(JSON.stringify(updates), JSON.stringify([{ description: "Ops team" }]));
  act(() => view.unmount());

  const empty = create(createElement(AdminGroupEditPanel, { group: { ...group, member_count: 0, is_active: false }, groupLoading: null,
    onClose: noop, onUpdateGroup: noop, onToggleGroup: noop, onDeleteGroup: noop }));
  assert.ok(buttons(empty).includes("Reactivate"));
  assert.ok(buttons(empty).includes("Delete group"));
  act(() => empty.unmount());
});

test("tool output compression shows the summary, the filters, the tools and the log", () => {
  const { RuntimeCompressionSection } = load("admin/components/runtimeTab/RuntimeCompressionSection.tsx");
  const ctx = {
    formatRelativeTime: () => "just now", handleSaveToolResultCompressor: async () => {}, setToolResultCompressorDrafts: noop,
    toolResultCompressionLogs: [{ id: "l1", tool_name: "search", strategy: "truncate", original_tokens: 100, compressed_tokens: 40, compression_ratio: 60, created_at: null }],
    toolResultCompressionSaving: null, toolResultCompressorDrafts: {},
    toolResultCompressors: [{ id: "c1", tool_name: "search", strategy: "truncate", config: {}, is_active: true },
      { id: "c2", tool_name: "fetch", strategy: "none", config: {}, is_active: false }],
  };
  const view = create(createElement(RuntimeCompressionSection, { ctx }));
  includesAll(text(view.root), ["Tool output compression", "1 on", "2 tools", "Recent compression log", "search", "fetch", "100", "40", "60 %", "just now"]);
  assert.equal(all(view, "table").length, 2);
  assert.equal(all(view, "tr").length, 5);
  assert.ok(!buttons(view).includes("Reset"));
  act(() => all(view, "input")[0].props.onChange({ target: { value: "zzz" } }));
  includesAll(text(view.root), ["No tools match this filter.", "No log entries match this search.", "Reset"]);
  act(() => view.unmount());
});

const apiKey = (patch = {}) => ({ id: "k1", name: "CI", key_prefix: "oc_ab", created_at: null, last_used_at: null, expires_at: null,
  revoked_at: null, scopes: ["read"], ...patch });
const keyProps = { apiKeys: [apiKey(), apiKey({ id: "k2", name: "Old", revoked_at: "2026-01-01T00:00:00Z", scopes: [] })], apiKeyName: "", apiKeyScopes: "",
  apiKeyExpiresAt: "", apiKeyCreatedSecret: "oc_secret", apiKeyLoading: "revoke:k1", apiKeyError: "Refused", setApiKeyName: noop,
  setApiKeyScopes: noop, setApiKeyExpiresAt: noop, onCreateApiKey: noop, onRevokeApiKey: noop };

test("the API keys section shows the secret, the form and the key rows", () => {
  const { AdminUserApiKeysSection } = load("admin/components/usersTab/AdminUserApiKeysSection.tsx");
  const view = create(createElement(AdminUserApiKeysSection, keyProps));
  includesAll(text(view.root), ["API keys", "Refused", "Copy this key — it will not be shown again.", "Key name", "Scopes", "Expires at",
    "Create key", "CI", "oc_ab · Last used Never · Expires Never", "Active", "Revoking…", "Revoked"]);
  assert.equal(all(view, "input").length, 3);
  assert.equal(view.root.findAll((node) => node.props.className === "user-edit-panel__apikey-row").length, 2);
  act(() => view.unmount());
  const empty = create(createElement(AdminUserApiKeysSection, { ...keyProps, apiKeys: [], apiKeyCreatedSecret: null, apiKeyError: null }));
  assert.ok(text(empty.root).includes("No API keys yet."));
  act(() => empty.unmount());
});

test("the schedule fields show the guided controls per mode and the cron for custom", () => {
  const { SchedulerScheduleFields } = load("admin/components/scheduler/SchedulerScheduleFields.tsx");
  const crons = [];
  const minutes = create(createElement(SchedulerScheduleFields, { value: "*/15 * * * *", onChange: (cron) => crons.push(cron) }));
  includesAll(text(minutes.root), ["Schedule *", "Choose frequency…", "Every", "minutes", "Technical details", "*/15 * * * *"]);
  assert.equal(all(minutes, "select").length, 2);
  act(() => all(minutes, "select")[0].props.onChange({ target: { value: "weekdays" } }));
  includesAll(text(minutes.root), ["Days", "Mon", "Sun", "At"]);
  assert.equal(all(minutes, "input").filter((node) => node.props.type === "checkbox").length, 7);
  assert.equal(crons.length, 1);
  act(() => all(minutes, "select")[0].props.onChange({ target: { value: "custom" } }));
  assert.equal(all(minutes, "input").filter((node) => node.props["aria-label"] === "Cron expression").length, 1);
  act(() => minutes.unmount());
  const unset = create(createElement(SchedulerScheduleFields, { value: "", onChange: noop }));
  assert.ok(text(unset.root).includes("Choose how often the action runs"));
  act(() => unset.unmount());
});

test("a REST operation's setup shows the offer, the write, the parameters and the answer sections", () => {
  const { RestOperationSetup } = load("admin/components/restApis/RestOperationSetup.tsx");
  const { operationDraft } = load("admin/components/restApis/restOperationEditorModel.ts");
  const op = { id: "op1", op_key: "update_ticket", tool_name: "rest__demo__update_ticket", method: "PUT", path: "/tickets/{id}", summary: "Update",
    parameters: [{ name: "id", in: "path", required: true, description: "", schema: { type: "string" } }],
    request_body: null, enabled: false, read_only: false, is_read: false, llm_name: "", llm_description: "", params_overlay: {},
    grants: [], response_select: [], records_path: "", pagination: { type: "cursor" } };
  const changes = [];
  const draft = { ...operationDraft(op), pagination: { ...operationDraft(op).pagination, type: "cursor" } };
  const view = create(createElement(RestOperationSetup, { operation: op, draft, onChange: (next) => changes.push(next), error: { field: "overlay", text: "Bad overlay" } }));
  includesAll(text(view.root), ["Offer to agents", "Enabled (only roles with a grant get it; every write waits for an approval)", "Name for the model (optional)",
    "rest__…__update_ticket", "Write", "Run class it needs", "Safe to repeat (idempotent): a failed PUT may be sent again", "Parameters", "id",
    "path · required · string", "Hidden from the model", "Bad overlay", "Answer", "Records path (optional)", "Pages", "Cursor in the answer"]);
  assert.equal(view.root.findAll((node) => node.props["data-testid"] === "rest-param-id").length, 1);
  assert.equal(all(view, "select").length, 2);
  all(view, "input").find((node) => node.props["data-testid"] === "rest-op-idempotent").props.onChange({ target: { checked: true } });
  assert.equal(changes[0].idempotent, true);
  act(() => view.unmount());
});

test("the knowledge lookup limits load, show one field per limit and save", async () => {
  const { ProjectKnowledgeLookupSection } = load("admin/components/projectsTab/ProjectKnowledgeLookupSection.tsx");
  const calls = [];
  const readJson = async (url, init) => { calls.push([url, init?.method ?? "GET", init?.body ? JSON.parse(init.body) : null]);
    return { config: { knowledge_lookup: { overview_graph_depth: 99 } } }; };
  let view;
  await act(async () => { view = TestRenderer.create(createElement(ProjectKnowledgeLookupSection, { ctx: { configuringProjectQuality: { id: "p1" }, readJson } })); });
  await tick();
  includesAll(text(view.root), ["Knowledge lookup limits", "Save defaults", "Open Knowledge", "Initial knowledge search limit", "Graph depth",
    "Range 1–10.", "Overview key catalog limit"]);
  assert.deepEqual(all(view, "input").map((node) => node.props.value), [30, 40, 10, 120, 200]);
  await act(async () => { all(view, "button")[0].props.onClick(); });
  assert.deepEqual(calls[1].slice(0, 2), ["/admin/chat/api/panel/projects/p1/config", "PUT"]);
  assert.equal(calls[1][2].knowledge_lookup.overview_graph_depth, 10);
  act(() => view.unmount());
  assert.equal(create(createElement(ProjectKnowledgeLookupSection, { ctx: { configuringProjectQuality: null, readJson } })).toJSON(), null);
});

test("GitHub sign-in shows the connected account, the device code or the failure", () => {
  const { ProviderCopilotAuth } = load("admin/components/providerTab/ProviderCopilotAuth.tsx");
  const base = { handleCopilotConnect: async () => {}, handleCopilotDisconnect: noop };
  const idle = create(createElement(ProviderCopilotAuth, { ctx: { ...base, copilotFlow: null }, provider: { id: "p1", auth_login: "ada", auth_name: "Ada" } }));
  includesAll(text(idle.root), ["GitHub Auth", "Ada", "@ada", "https://github.com", "Reconnect with GitHub"]);
  act(() => idle.unmount());
  const pending = create(createElement(ProviderCopilotAuth, { ctx: { ...base, copilotFlow: { providerId: "p1", status: "pending", userCode: "AB-12", verificationUri: "https://github.com/login/device" } }, provider: { id: "p1" } }));
  includesAll(text(pending.root), ["AB-12", "and enter the code above.", "Waiting for authorization…", "Cancel"]);
  act(() => pending.unmount());
  const failed = create(createElement(ProviderCopilotAuth, { ctx: { ...base, copilotFlow: { providerId: "p1", status: "failed", error: "" } }, provider: { id: "p1" } }));
  assert.deepEqual(buttons(failed), ["Retry", "Cancel"]);
  assert.ok(text(failed.root).includes("Login failed: unknown error"));
  act(() => failed.unmount());
  const none = create(createElement(ProviderCopilotAuth, { ctx: { ...base, copilotFlow: null }, provider: { id: "p1" } }));
  includesAll(text(none.root), ["Not connected", "Connect with GitHub"]);
  act(() => none.unmount());
});

test("the workspace storage fields show eight inputs with the default exclusions", () => {
  const { RuntimeWorkspaceStorageFields } = load("admin/components/runtimeTab/RuntimeWorkspaceStorageFields.tsx");
  const ctx = { runtimeSettings: { session_workspace_sync_default_excluded_dirs: [".git"], session_workspace_sync_default_excluded_globs: [] },
    runtimeWorkspaceBaseDirDraft: "/tmp/ws", runtimeWorkspaceStorageBackendDraft: "s3", runtimeWorkspaceStorageBucketDraft: "b",
    runtimeWorkspaceStoragePrefixDraft: "p", runtimeWorkspaceSyncExcludedDirsDraft: "", runtimeWorkspaceSyncExcludedGlobsDraft: "",
    runtimeWorkspaceSyncMaxFileCountDraft: "10", runtimeWorkspaceSyncMaxFileSizeDraft: "20" };
  for (const name of ["BaseDir", "StorageBackend", "StorageBucket", "StoragePrefix", "SyncExcludedDirs", "SyncExcludedGlobs", "SyncMaxFileCount", "SyncMaxFileSize"]) {
    ctx[`setRuntimeWorkspace${name}Draft`] = noop;
  }
  const view = create(createElement(RuntimeWorkspaceStorageFields, { ctx }));
  includesAll(text(view.root), ["Workspace storage", "Session folder base directory", "Durable storage", "Bucket / root", "Prefix",
    "Always excluded: .git.", "Always excluded: none.", "Max mirrored file size (bytes)", "Max mirrored files"]);
  assert.deepEqual(all(view, "input").map((node) => node.props.value), ["/tmp/ws", "b", "p", "", "", "20", "10"]);
  assert.equal(all(view, "select")[0].props.value, "s3");
  act(() => view.unmount());
});
