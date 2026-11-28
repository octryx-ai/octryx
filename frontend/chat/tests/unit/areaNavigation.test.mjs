import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ADMIN_AREA_CONFIGS,
  ADMIN_AREA_KEYS,
  listAdminAreaTabRefs,
  resolveAdminAreaForTab,
  resolveAdminAreaTab,
} from "../../src/admin/config/adminPanelAreas.ts";
import { withAreaTab, readAreaTabFromSearch } from "../../src/chat/areaNavigation.ts";
import { resolveActiveWorkspaceId } from "../../src/chat/activeWorkspace.ts";
import { ADMIN_ENTRIES } from "../../src/admin/config/adminEntries.ts";

// Pages reachable from the area navigation.
const REACHABLE = [
  "users", "identityRoles", "identityGroups", "identityProviders", "identityAccess",
  "projects", "backupRestore", "branding", "corpIdentity", "usage",
  "providers", "mcp", "tts", "policies", "researchPolicies", "connectors", "channels", "webhooks",
  "agents", "promptCatalog", "workspaceKnowledge", "knowledge", "toolCatalog", "skills",
  "schedulers", "tasks",
];

function homes(tab) {
  return ADMIN_AREA_KEYS.filter((area) => listAdminAreaTabRefs(area).some((ref) => ref.id === tab));
}

test("every reachable page has exactly one home", () => {
  for (const tab of REACHABLE) {
    assert.equal(homes(tab).length, 1, `${tab} must live in exactly one area, found ${homes(tab).join(",")}`);
  }
});

test("no page is registered twice across all areas", () => {
  const all = ADMIN_AREA_KEYS.flatMap((area) => listAdminAreaTabRefs(area).map((ref) => ref.id));
  assert.equal(new Set(all).size, all.length);
});

test("coherent homes: knowledge, agents with prompts, security in settings", () => {
  assert.equal(resolveAdminAreaForTab("workspaceKnowledge"), "knowledge");
  // Engineering knowledge is Knowledge › Advanced.
  assert.equal(resolveAdminAreaForTab("knowledge"), "knowledge");
  assert.equal(resolveAdminAreaForTab("knowledgeGraph"), "knowledge");
  assert.equal(resolveAdminAreaForTab("agents"), "workflows");
  // System prompt texts are platform settings.
  assert.equal(resolveAdminAreaForTab("promptCatalog"), "admin");
  assert.equal(resolveAdminAreaForTab("workflowChecks"), "workflows");
  assert.equal(resolveAdminAreaForTab("instructions"), "workflows");
  assert.equal(resolveAdminAreaForTab("policies"), "admin");
  assert.equal(resolveAdminAreaForTab("commandSafety"), "admin");
});

test("an unknown page id names no page; Admin groups by subject", () => {
  for (const retired of ["runtimeSignIn", "dataClassification", "runtimeSecurity"]) {
    assert.equal(resolveAdminAreaTab("admin", retired), ADMIN_AREA_CONFIGS.admin.defaultTab, retired);
  }
  // Seven menu entries, each one page; their pages are views (segments) of the entry.
  const menu = listAdminAreaTabRefs("admin").filter((tab) => !tab.hidden).map((tab) => tab.label);
  assert.deepEqual(menu, ["Problems", "Workspaces", "Connections", "Models", "Rules", "People & sign-in", "Platform"]);
  const views = Object.fromEntries(ADMIN_ENTRIES.map((entry) => [entry.label, entry.views.map((view) => view.label)]));
  assert.deepEqual(views, {
    Problems: [],
    Workspaces: [],
    Connections: ["Connections", "MCP servers", "REST APIs", "Databases", "Channels", "Webhooks", "Schedules",
      "Repositories", "Jira write-back"],
    Models: ["Overview", "Providers", "Catalog", "Defaults", "Budgets"],
    Rules: ["Policies", "Approval rule", "Tool & approval policies", "Command safety", "Content security", "Classification"],
    "People & sign-in": ["Users", "Roles & functions", "Platform access", "Groups", "Sign-in", "Access check"],
    Platform: ["Version", "Devices", "Plugins", "Advanced"],
  });
  // The Classification matrix left the navigation; its links open it as a page of Rules.
  assert.equal(resolveAdminAreaTab("admin", "classificationPolicy"), "classificationPolicy");
  assert.equal(resolveAdminAreaForTab("runtimeExecution"), "admin");
});

test("Knowledge is Find, Sources and Advanced (E6); Sources keeps the Knowledge setup page id", () => {
  const knowledge = ADMIN_AREA_CONFIGS.knowledge.groups.map((group) => [group.label, group.tabs.filter((tab) => !tab.hidden).map((tab) => `${tab.id}:${tab.label}`)]);
  assert.deepEqual(knowledge, [
    ["Find", ["knowledgeLibrary:Search", "knowledgeRelationships:Explore"]],
    ["Sources", ["workspaceKnowledge:Sources", "knowledgeSources:Documents", "knowledgeResearch:Research websites",
      "researchPolicies:Research profiles"]],
    ["Advanced", ["knowledgePackages:Packages", "knowledgeBindings:Bindings", "knowledgeChanges:Changes",
      "knowledgeMemory:Memory", "knowledgeEpisodes:Episodes", "knowledge:Engineering knowledge",
      "knowledgeHandbook:Structured graph"]],
  ]);
  for (const tab of ["knowledgePackages", "knowledgeBindings", "knowledgeChanges", "knowledgeHandbook", "knowledgeMemory", "knowledgeEpisodes"]) {
    assert.equal(resolveAdminAreaForTab(tab), "knowledge", tab);
    assert.equal(resolveAdminAreaTab("knowledge", tab), tab, tab);
  }
  assert.equal(resolveAdminAreaTab("knowledge", "workspaceKnowledge"), "workspaceKnowledge");
});

test("each area's default page belongs to that area", () => {
  for (const area of ADMIN_AREA_KEYS) {
    assert.deepEqual(homes(ADMIN_AREA_CONFIGS[area].defaultTab), [area]);
  }
});

test("a tab from another area or an unknown tab never renders under the wrong header", () => {
  assert.equal(resolveAdminAreaTab("operations", "users"), "observabilityOverview");
  assert.equal(resolveAdminAreaTab("admin", "not-a-tab"), "adminProblems");
  assert.equal(resolveAdminAreaTab("admin", "runtimeLimits"), "runtimeLimits");
  assert.equal(resolveAdminAreaTab("knowledge", null), "knowledgeLibrary");
});

test("admin-only knowledge pages are hidden from members without changing the default", () => {
  const memberTabs = listAdminAreaTabRefs("knowledge", false).map((ref) => ref.id);
  assert.ok(memberTabs.includes("knowledgeLibrary") && memberTabs.includes("knowledgeSources"));
  assert.equal(memberTabs.includes("knowledge"), false);
  assert.equal(memberTabs.includes("knowledgePackages"), false);
  assert.equal(resolveAdminAreaTab("knowledge", "knowledgePackages", false), "knowledgeLibrary");
  // Sources is a Workspace-admin entry (its menu entry needs the Workspace role, see knowledgeSourceAcl.test);
  // a member's deep link opens the read-only list, the server decides every action.
  assert.equal(resolveAdminAreaTab("knowledge", "workspaceKnowledge", false), "workspaceKnowledge");
});

test("the page is part of the URL so reloads and links open it", () => {
  const href = withAreaTab("http://localhost:8090/chat?area=runtime", "runtimeLimits");
  assert.equal(readAreaTabFromSearch(new URL(href).search), "runtimeLimits");
  assert.equal(new URL(withAreaTab(href, null)).searchParams.has("tab"), false);
});

test("the active workspace is never guessed from the first project", () => {
  const projects = [{ id: "a3-temp" }, { id: "petclinic" }];
  assert.equal(resolveActiveWorkspaceId(projects, null, null), "");
  assert.equal(resolveActiveWorkspaceId(projects, "gone", "petclinic"), "petclinic");
  assert.equal(resolveActiveWorkspaceId(projects, "petclinic", "a3-temp"), "petclinic");
  assert.equal(resolveActiveWorkspaceId(projects, "", "petclinic"), "", "an explicit clear is kept");
});
