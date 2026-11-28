// Render guard for the admin panel container: the shell and the content get the same props when the container is
// split into smaller hooks and parts. All state hooks and heavy children are stubbed by module name.
import assert from "node:assert/strict";
import { test } from "node:test";
import { createElement } from "react";
import { act, load, noop, render } from "./renderGuardHarness.mjs";

const json = (value) => JSON.stringify(value);

const CTX_KEYS = ["agentsTabCtx", "brandingTabCtx", "channelsTabCtx", "knowledgeTabCtx", "mcpTabCtx", "projectsTabCtx",
  "providersTabCtx", "runtimesTabCtx", "schedulersTabCtx", "skillsTabCtx", "tasksTabCtx",
  "toolCatalogTabCtx", "ttsTabCtx", "usersTabCtx", "webhooksTabCtx", "connectorsTabCtx"];
const SLICE_KEYS = ["projectState", "agentState", "webhookState", "usageBrandingState",
  "taskState", "knowledgeState", "channelState", "mcpState", "runtimeState", "connectorCoreState",
  "connectorFormState", "workflowState", "providerState", "createUserState", "officeTemplates", "corpIdentity"];

test("the admin panel container wires the slices, controllers and tab contexts into shell and content", async () => {
  const seen = { loads: [], urls: [] };
  const slices = Object.fromEntries(SLICE_KEYS.map((key) => [key, { key }]));
  slices.connectorCoreState.agentModes = ["mode"];
  slices.mcpState.mcpWorkspaceId = "ws-1";
  const { AdminPanelContainer } = load("admin/AdminPanelContainer.tsx", {
    AdminPanelContent: { AdminPanelContent: (p) => { seen.content = p; return createElement("main", { "data-testid": "content" }); } },
    AdminPanelShell: { AdminPanelShell: (p) => { seen.shell = p; return createElement("section", { "data-testid": "shell" }, p.children); } },
    adminAgentFormsArgs: { adminAgentFormsArgs: (readJson, modes, agentState) => ({ modes, agentState }) },
    useAdminAgentForms: { useAdminAgentForms: (args) => { seen.agentFormArgs = args; return { forms: true }; } },
    useAdminPanelContainerControllers: {
      useAdminPanelContainerControllers: (args) => { seen.controllerArgs = args; return { loadTab: async (tab) => seen.loads.push(tab) }; },
    },
    useAdminPanelContainerDerived: {
      useAdminPanelContainerDerived: (args) => {
        seen.derivedArgs = args;
        return { ...Object.fromEntries(CTX_KEYS.map((key) => [key, { key }])), currentTabLabel: "Fallback label" };
      },
    },
    useAdminPanelContainerEffects: { useAdminPanelContainerEffects: (args) => { seen.effectArgs = args; } },
    useAdminPanelContainerSlices: { useAdminPanelContainerSlices: () => slices },
    adminPanelHelpers: { readJson: noop, sanitizeOfficeTemplateKey: noop },
    areaNavigation: { writeAreaTabToUrl: (tab) => seen.urls.push(tab) },
    useWorkspaceAdmin: { useWorkspaceAdmin: (isAdmin, projects, needed) => `admin:${isAdmin}:${needed}`,
      useAnyWorkspaceAdmin: (isAdmin, needed) => `any:${isAdmin}:${needed}` },
  });
  const view = await render(AdminPanelContainer, {
    area: "admin", projects: [{ id: "p1" }], currentUserId: "u1", branding: { enabled: true }, onClose: noop,
  });
  assert.equal(seen.shell.area, "admin");
  assert.equal(seen.shell.tab, "adminProblems");
  assert.equal(seen.shell.currentTabLabel, "Problems");
  assert.equal(json(seen.shell.features), json({ branding: true }));
  assert.equal(seen.shell.isAdmin, true);
  assert.equal(seen.content.tab, "adminProblems");
  assert.equal(seen.content.brandingEnabled, true);
  assert.equal(seen.content.currentUserId, "u1");
  assert.equal(seen.content.loadingTab, false);
  assert.equal(seen.content.tabError, null);
  for (const key of CTX_KEYS) assert.deepEqual(seen.content[key], { key }, key);
  assert.equal(Object.keys(seen.content).length, 25);
  assert.equal(json(seen.agentFormArgs), json({ modes: ["mode"], agentState: slices.agentState }));
  assert.equal(Object.keys(seen.controllerArgs).length, 26);
  for (const key of SLICE_KEYS) assert.equal(seen.controllerArgs[key], slices[key], key);
  assert.equal(Object.keys(seen.derivedArgs).length, 25);
  assert.equal(seen.derivedArgs.controllers.loadTab, seen.effectArgs.loadTab);
  assert.equal(seen.effectArgs.mcpWorkspaceId, "ws-1");
  assert.equal(seen.effectArgs.tab, "adminProblems");
  assert.equal(json(seen.urls), json(["adminProblems"]));
  act(() => seen.shell.setTab("users"));
  assert.equal(seen.shell.tab, "users");
  assert.equal(json(seen.urls), json(["adminProblems", "users"]));
  act(() => seen.content.onRetry());
  assert.equal(json(seen.loads), json(["users"]));
  act(() => view.unmount());
});
