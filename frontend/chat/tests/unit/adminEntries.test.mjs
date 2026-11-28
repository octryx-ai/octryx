// Run: node --import ./tests/unit/register-ts.mjs --test tests/unit/adminEntries.test.mjs
// Admin has seven entries, each one page; every other page is a view
// (segment) of one entry, keeps its page id and deep-link parameters, and Admin opens on Problems.
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";
import { test } from "node:test";
import { createElement } from "react";
import TestRenderer from "react-test-renderer";

import { ADMIN_ENTRIES, ADMIN_ENTRY_ALIASES, entryPages, locateAdminPage } from "../../src/admin/config/adminEntries.ts";
import { listAdminAreaTabRefs, resolveAdminAreaTab, resolveAdminSidebarTab } from "../../src/admin/config/adminPanelAreas.ts";
import { withAreaTab, readAreaTabFromSearch } from "../../src/chat/areaNavigation.ts";

const require = createRequire(import.meta.url), ts = require("typescript");
const { act } = TestRenderer;
globalThis.IS_REACT_ACT_ENVIRONMENT = true;
const HERE = path.dirname(new URL(import.meta.url).pathname);
const SRC = path.resolve(HERE, "../../src");

function load(relative) {
  const cache = new Map();
  const loadFile = (file) => {
    if (cache.has(file)) return cache.get(file);
    const exports = {};
    cache.set(file, exports);
    const output = ts.transpileModule(fs.readFileSync(file, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
    vm.runInNewContext(output, {
      exports, console,
      require: (name) => {
        if (name.endsWith(".css")) return {};
        if (!name.startsWith(".")) return require(name);
        const base = path.resolve(path.dirname(file), name);
        return loadFile([".ts", ".tsx"].map((ext) => base + ext).find((candidate) => fs.existsSync(candidate)));
      },
    });
    return exports;
  };
  return loadFile(path.join(SRC, relative));
}

const text = (node) => (typeof node === "string" ? node : (node.children ?? []).map(text).join(""));

// Every page the Admin menu listed before N1, with its (entry, view key).
const OLD_MENU = {
  adminProblems: ["problems", null], projects: ["workspaces", null],
  adminConnections: ["connections", "connections"], connectors: ["connections", "connections"], mcp: ["connections", "mcp"],
  restApis: ["connections", "restApis"], restApiCalls: ["connections", "restApis"],
  databases: ["connections", "databases"], channels: ["connections", "channels"], webhooks: ["connections", "webhooks"],
  schedulers: ["connections", "schedules"], tasks: ["connections", "schedules"],
  modelsOverview: ["models", "overview"], providers: ["models", "providers"], modelCatalog: ["models", "catalog"], modelOrder: ["models", "defaults"],
  runtimePolicyLists: ["models", "defaults"], runtimeLimits: ["models", "budgets"],
  cedarPolicies: ["rules", "policies"], policyTestBench: ["rules", "policies"],
  approvalRule: ["rules", "approval"], policies: ["rules", "tools"],
  commandSafety: ["rules", "commands"], contentSecurity: ["rules", "content"], classificationPolicy: ["rules", "classification"],
  users: ["people", "users"], identityRoles: ["people", "roles"],
  // Work roles (board 8): a view of People & sign-in with three pages.
  workRoles: ["people", "workroles"], workRoleFunctions: ["people", "workroles"], workRoleAudit: ["people", "workroles"], identityGroups: ["people", "groups"],
  identityProviders: ["people", "signin"], identityAccess: ["people", "access"],
  platformVersion: ["platform", "version"], platformDevices: ["platform", "devices"], plugins: ["platform", "plugins"],
  runtimeExecution: ["platform", "advanced"], tts: ["platform", "advanced"],
  backupRestore: ["platform", "advanced"], branding: ["platform", "advanced"], corpIdentity: ["platform", "advanced"],
  promptCatalog: ["platform", "advanced"],
};

test("the menu renders exactly seven entries; Admin opens on Problems", () => {
  const menu = listAdminAreaTabRefs("admin").filter((ref) => !ref.hidden);
  assert.deepEqual(menu.map((ref) => ref.label), ["Problems", "Workspaces", "Connections", "Models", "Rules", "People & sign-in", "Platform"]);
  assert.equal(resolveAdminAreaTab("admin", null), "adminProblems");
  assert.equal(resolveAdminAreaTab("admin", "no-such-page"), "adminProblems");
  // Without a page in the link, the app and the panel start on Problems, not on a valid page of another entry
  // (Admin opened on People & sign-in because the start tab was "users").
  const appState = fs.readFileSync(path.join(SRC, "chat/useAppContainerState.ts"), "utf8");
  assert.match(appState, /readAreaTabFromSearch\(window\.location\.search\) \|\| "adminProblems"/);
  assert.match(fs.readFileSync(path.join(SRC, "admin/AdminPanelContainer.tsx"), "utf8"), /initialTab = "adminProblems"/);
  // The profile menu's "Platform settings" opens Admin on Problems too.
  assert.match(fs.readFileSync(path.join(SRC, "chat/AreaRail.tsx"), "utf8"), /openSettingsTab\("adminProblems", "admin"\)/);
});

test("every old admin page id maps to one (entry, view), still opens and keeps its entry selected", () => {
  for (const [tab, [entryKey, viewKey]] of Object.entries(OLD_MENU)) {
    const location = locateAdminPage(tab);
    assert.equal(location?.entry.key, entryKey, tab);
    assert.equal(location?.view?.key ?? null, viewKey, tab);
    assert.equal(resolveAdminAreaTab("admin", tab), tab, `${tab} still opens`);
    assert.equal(resolveAdminSidebarTab("admin", tab), location.entry.tab, `${tab} keeps ${entryKey} selected`);
  }
  const all = ADMIN_ENTRIES.flatMap(entryPages);
  assert.equal(new Set(all).size, all.length, "no page sits in two entries");
  for (const tab of all) assert.ok(tab in OLD_MENU, `${tab} is listed`);
});

test("links naming an entry open its first view; deep-link parameters stay on the page", () => {
  assert.equal(resolveAdminAreaTab("admin", "adminModels"), "providers");
  for (const [alias, tab] of Object.entries(ADMIN_ENTRY_ALIASES)) assert.equal(resolveAdminAreaTab("admin", alias), tab);
  // The page id is the view, so ?model=, ?connector= and ?connection= ride along untouched.
  for (const [tab, param] of [["modelCatalog", "model=m1"], ["connectors", "connector=jira"], ["adminConnections", "connection=c1"]]) {
    const href = withAreaTab(`http://localhost/chat?area=admin&${param}`, tab);
    assert.equal(readAreaTabFromSearch(new URL(href).search), tab);
    assert.ok(href.includes(param), `${param} kept`);
  }
});

function renderTabs(props) {
  const { AdminEntryTabs } = load("admin/components/AdminEntryTabs.ts");
  const opened = [], external = [];
  let view;
  act(() => {
    view = TestRenderer.create(createElement(AdminEntryTabs, {
      setTab: (tab) => opened.push(tab), onExternal: (key) => external.push(key),
      externalKeys: ["coding:repositories", "work:writeback"], ...props,
    }));
  });
  return { view, opened, external };
}

test("an entry page shows its views as segments and a second row for a view with several pages, never a third", () => {
  const models = renderTabs({ tab: "modelCatalog" });
  const tabs = models.view.root.findAll((node) => node.props?.role === "tab");
  assert.deepEqual(tabs.map(text), ["Overview", "Providers", "Catalog", "Defaults", "Budgets"]);
  assert.equal(tabs.find((node) => node.props["aria-selected"]).props.id.endsWith("catalog"), true);
  act(() => tabs.find((node) => text(node) === "Budgets").props.onClick());
  assert.deepEqual(models.opened, ["runtimeLimits"]);

  const schedules = renderTabs({ tab: "tasks" });
  const rows = schedules.view.root.findAll((node) => node.props?.role === "tablist");
  assert.equal(rows.length, 2, "views + the Schedules pages");
  assert.deepEqual(rows[1].findAll((node) => node.props?.role === "tab").map(text), ["Schedulers", "Actions"]);
  const repositories = schedules.view.root.findAll((node) => node.props?.role === "tab").find((node) => text(node) === "Repositories");
  act(() => repositories.props.onClick());
  assert.deepEqual(schedules.external, ["coding:repositories"]);

  // Access check is a view like the others, not a button that looks selected.
  const people = renderTabs({ tab: "users" });
  const access = people.view.root.findAll((node) => node.props?.role === "tab").find((node) => text(node) === "Access check");
  act(() => access.props.onClick());
  assert.deepEqual(people.opened, ["identityAccess"]);
  assert.equal(people.view.root.findAllByType("button").filter((node) => node.props.role !== "tab").length, 0, "no other buttons");

  // Rules: today's rule pages are views of their own, so Policies' sections are the second level, not a third.
  const rules = renderTabs({ tab: "cedarPolicies" });
  const ruleRows = rules.view.root.findAll((node) => node.props?.role === "tablist");
  assert.equal(ruleRows.length, 1, "a one-page view adds no second row");
  assert.deepEqual(ruleRows[0].findAll((node) => node.props?.role === "tab").map(text),
    ["Policies", "Approval rule", "Tool & approval policies", "Command safety", "Content security", "Classification"]);

  const problems = renderTabs({ tab: "adminProblems" });
  assert.equal(problems.view.toJSON(), null, "Problems has no views");

  const platform = renderTabs({ tab: "branding", features: {} });
  const advanced = platform.view.root.findAll((node) => node.props?.role === "tablist")[1];
  assert.equal(advanced.findAll((node) => node.props?.role === "tab").some((node) => text(node) === "Branding"), false,
    "a switched-off feature is no segment");
});

test("Platform › Advanced points to the coding engine in Models › Defaults instead of repeating the setting", () => {
  const { requestAdminSection, takeAdminSection } = load("admin/config/adminPageSection.ts");
  const platformEntry = ADMIN_ENTRIES.find((entry) => entry.key === "platform");
  assert.deepEqual(platformEntry.views.find((v) => v.key === "advanced").pointers,
    [{ label: "Coding engine → Models › Defaults", tab: "modelOrder", section: "engine" }]);
  const advanced = renderTabs({ tab: "runtimeExecution" });
  const pointers = advanced.view.root.findAll((node) => node.props?.["data-testid"] === "admin-entry-pointer" && node.type === "button");
  assert.deepEqual(pointers.map(text), ["Coding engine → Models › Defaults"]);
  act(() => pointers[0].props.onClick());
  assert.deepEqual(advanced.opened, ["modelOrder"]);
  requestAdminSection("modelOrder", "engine");
  assert.equal(takeAdminSection("providers"), null, "only the named page takes it");
  assert.equal(takeAdminSection("modelOrder"), "engine", "Defaults opens on its Coding engine tab");
  assert.equal(takeAdminSection("modelOrder"), null, "taken once");
  assert.equal(renderTabs({ tab: "platformVersion" }).view.root.findAll((node) => node.props?.["data-testid"] === "admin-entry-pointer").length, 0,
    "only the Advanced view points there");
});
