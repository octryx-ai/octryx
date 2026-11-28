// The Admin menu has exactly seven entries, every Admin page has one home (one of the seven, Knowledge › Advanced, or a redirect), and Problems and Rules link the
// pages that hold the same things today until their own page exists.
import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ADMIN_AREA_CONFIGS,
  ADMIN_AREA_KEYS,
  listAdminAreaTabRefs,
  resolveAdminAreaForTab,
  resolveAdminAreaTab,
} from "../../src/admin/config/adminPanelAreas.ts";
import { ADMIN_ENTRIES, ADMIN_ENTRY_ALIASES, locateAdminPage } from "../../src/admin/config/adminEntries.ts";

const SEVEN = ["Problems", "Workspaces", "Connections", "Models", "Rules", "People & sign-in", "Platform"];

// Every page the Admin area had before E6, with where it lives now.
const BEFORE_E6 = {
  users: "People & sign-in", identityRoles: "People & sign-in", identityGroups: "People & sign-in",
  identityProviders: "People & sign-in", identityAccess: "People & sign-in",
  projects: "Workspaces",
  knowledgePackages: "knowledge", knowledgeBindings: "knowledge", knowledgeChanges: "knowledge",
  knowledgeHandbook: "knowledge", knowledgeMemory: "knowledge", knowledgeEpisodes: "knowledge", knowledge: "knowledge",
  classificationPolicy: "Rules", cedarPolicies: "Rules", policyTestBench: "Rules",
  approvalRule: "Rules", policies: "Rules", commandSafety: "Rules", contentSecurity: "Rules",
  providers: "Models", modelCatalog: "Models", modelOrder: "Models", runtimePolicyLists: "Models", runtimeLimits: "Models",
  connectors: "Connections", mcp: "Connections", databases: "Connections", channels: "Connections",
  webhooks: "Connections", schedulers: "Connections", tasks: "Connections",
  runtimeExecution: "Platform", tts: "Platform", backupRestore: "Platform",
  branding: "Platform", corpIdentity: "Platform", promptCatalog: "Platform",
};

// The entry a page belongs to (an Admin page is one of the seven entries, or a view of one).
const groupOf = (tab) => locateAdminPage(tab)?.entry.label;

test("the Admin menu has exactly the seven entries (N1: entries, not headings), in order; it opens on Problems", () => {
  const visible = listAdminAreaTabRefs("admin").filter((ref) => !ref.hidden);
  assert.deepEqual(visible.map((ref) => ref.label), SEVEN);
  assert.deepEqual(ADMIN_ENTRIES.map((entry) => entry.label), SEVEN);
  assert.equal(ADMIN_AREA_CONFIGS.admin.defaultTab, "adminProblems");
  assert.equal(resolveAdminAreaTab("admin", null), "adminProblems");
  for (const ref of listAdminAreaTabRefs("admin").filter((entry) => entry.hidden)) {
    assert.ok(visible.some((entry) => entry.id === ref.parent), `${ref.id} sits under one of the seven`);
  }
});

test("every Admin page has exactly one (entry, view) and links naming an entry open its first view", () => {
  for (const ref of listAdminAreaTabRefs("admin")) {
    const location = locateAdminPage(ref.id);
    assert.ok(location, `${ref.id} has an entry`);
    assert.equal(location.entry.tab, ref.parent ?? ref.id, `${ref.id} sits under its menu entry`);
  }
  for (const [alias, tab] of Object.entries(ADMIN_ENTRY_ALIASES)) {
    assert.equal(resolveAdminAreaTab("admin", alias), tab, alias);
  }
});

test("every Admin page has one home: one of the seven, or Knowledge › Advanced", () => {
  for (const [tab, home] of Object.entries(BEFORE_E6)) {
    if (home === "knowledge") {
      assert.equal(resolveAdminAreaForTab(tab), "knowledge", tab);
      assert.equal(resolveAdminAreaTab("knowledge", tab), tab, `${tab} still opens`);
    } else {
      assert.equal(groupOf(tab), home, tab);
      assert.equal(resolveAdminAreaTab("admin", tab), tab, `${tab} still opens`);
    }
  }
  const all = ADMIN_AREA_KEYS.flatMap((area) => listAdminAreaTabRefs(area).map((ref) => ref.id));
  assert.equal(new Set(all).size, all.length, "no page is registered twice");
});

test("pages that left the navigation stay reachable by link", () => {
  // "knowledgeHandbook" is back in the menu as "Structured graph" (Build structured graph must be reachable).
  for (const [area, tab] of [["admin", "classificationPolicy"],
    ["workflows", "instructions"], ["workflows", "effectiveSetup"]]) {
    const ref = listAdminAreaTabRefs(area).find((entry) => entry.id === tab);
    assert.equal(ref.hidden, true, `${tab} is out of the menu`);
    assert.equal(resolveAdminAreaTab(area, tab), tab, `${tab} still opens`);
  }
});

test("Rules opens on Policies; the not yet served rule list is no view and its old links open Policies", () => {
  assert.equal(resolveAdminAreaTab("admin", "adminRules"), "cedarPolicies");
  assert.equal(groupOf("adminProblems"), "Problems");
  assert.equal(groupOf("cedarPolicies"), "Rules");
});
