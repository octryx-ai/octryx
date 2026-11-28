import type { AdminTab } from "../types/adminPanelTypes.governance";

// Every page keeps its page id, so links open it inside its entry without a redirect.

export type AdminEntryKey = "problems" | "workspaces" | "connections" | "models" | "rules" | "people" | "platform";

export type AdminViewPage = { tab: AdminTab; label: string; also?: AdminTab[] };

export type AdminEntryView = { key: string; label: string; pages?: AdminViewPage[]; external?: string; pointers?: AdminViewPointer[] };

export type AdminViewPointer = { label: string; tab: AdminTab; section?: string };

export type AdminEntry = {
  key: AdminEntryKey;
  label: string;
  tab: AdminTab;
  views: AdminEntryView[];
};

const page = (tab: AdminTab, label: string, also?: AdminTab[]): AdminViewPage => ({ tab, label, also });
const view = (key: string, label: string, pages: AdminViewPage[]): AdminEntryView => ({ key, label, pages });
const advanced = (pages: AdminViewPage[]): AdminEntryView => ({
  ...view("advanced", "Advanced", pages),
  pointers: [{ label: "Coding engine → Models › Defaults", tab: "modelOrder", section: "engine" }],
});

export const ADMIN_ENTRIES: AdminEntry[] = [
  { key: "problems", label: "Problems", tab: "adminProblems", views: [] },
  { key: "workspaces", label: "Workspaces", tab: "projects", views: [] },
  {
    key: "connections",
    label: "Connections",
    tab: "adminConnections",
    views: [
      // The connector settings page has no segment of its own but stays a page for built-in connector setup and private hosts.
      view("connections", "Connections", [page("adminConnections", "Connections", ["connectors"])]),
      view("mcp", "MCP servers", [page("mcp", "MCP servers")]),
      view("restApis", "REST APIs", [page("restApis", "APIs"), page("restApiCalls", "Calls")]),
      view("databases", "Databases", [page("databases", "Databases")]),
      view("channels", "Channels", [page("channels", "Channels")]),
      view("webhooks", "Webhooks", [page("webhooks", "Webhooks")]),
      view("schedules", "Schedules", [page("schedulers", "Schedulers"), page("tasks", "Actions")]),
      { key: "repositories", label: "Repositories", external: "coding:repositories" },
      { key: "writeback", label: "Jira write-back", external: "work:writeback" },
    ],
  },
  {
    key: "models",
    label: "Models",
    tab: "modelsOverview",
    views: [
      view("overview", "Overview", [page("modelsOverview", "Overview")]),
      view("providers", "Providers", [page("providers", "Providers")]),
      view("catalog", "Catalog", [page("modelCatalog", "Catalog")]),
      view("defaults", "Defaults", [page("modelOrder", "Defaults", ["runtimePolicyLists"])]),
      view("budgets", "Budgets", [page("runtimeLimits", "Budgets")]),
    ],
  },
  {
    key: "rules",
    label: "Rules",
    // The one rule list ("adminRules") waits for the server's central rules, so it is no view.
    tab: "cedarPolicies",
    views: [
      // Pages with sections are views of their own, so their sections stay the second tab level, not a third.
      view("policies", "Policies", [page("cedarPolicies", "Policies", ["policyTestBench"])]),
      view("approval", "Approval rule", [page("approvalRule", "Approval rule")]),
      view("tools", "Tool & approval policies", [page("policies", "Tool & approval policies")]),
      view("commands", "Command safety", [page("commandSafety", "Command safety")]),
      view("content", "Content security", [page("contentSecurity", "Content security")]),
      view("classification", "Classification", [page("classificationPolicy", "Classification")]),
    ],
  },
  {
    key: "people",
    label: "People & sign-in",
    tab: "users",
    views: [
      view("users", "Users", [page("users", "Users")]),
      // Called "Platform access" so the RBAC roles are not confused with work roles; their page id stays identityRoles.
      view("workroles", "Roles & functions", [
        page("workRoles", "Roles"),
        page("workRoleFunctions", "Functions"),
        page("workRoleAudit", "Changes"),
      ]),
      view("roles", "Platform access", [page("identityRoles", "Platform access")]),
      view("groups", "Groups", [page("identityGroups", "Groups")]),
      view("signin", "Sign-in", [page("identityProviders", "Sign-in")]),
      view("access", "Access check", [page("identityAccess", "Access check")]),
    ],
  },
  {
    key: "platform",
    label: "Platform",
    tab: "platformVersion",
    views: [
      view("version", "Version", [page("platformVersion", "Version")]),
      view("devices", "Devices", [page("platformDevices", "Devices")]),
      view("plugins", "Plugins", [page("plugins", "Plugins")]),
      advanced([
        page("runtimeExecution", "Execution & storage"),
        page("tts", "Voice & speech"),
        page("backupRestore", "Backup & restore"),
        page("branding", "Branding"),
        page("corpIdentity", "Corporate identity"),
        page("promptCatalog", "System prompt texts"),
      ]),
    ],
  },
];

export function entryPages(entry: AdminEntry): AdminTab[] {
  const pages = entry.views.flatMap((v) => (v.pages ?? []).flatMap((p) => [p.tab, ...(p.also ?? [])]));
  return Array.from(new Set([entry.tab, ...pages]));
}

export type AdminEntryLocation = { entry: AdminEntry; view: AdminEntryView | null; page: AdminViewPage | null };

export function locateAdminPage(tab: AdminTab): AdminEntryLocation | null {
  for (const entry of ADMIN_ENTRIES) {
    for (const v of entry.views) {
      const match = (v.pages ?? []).find((p) => p.tab === tab || p.also?.includes(tab));
      if (match) return { entry, view: v, page: match };
    }
    if (entry.tab === tab) return { entry, view: null, page: null };
  }
  return null;
}

export const ADMIN_ENTRY_ALIASES: Record<string, AdminTab> = {
  adminWorkspaces: "projects",
  adminModels: "providers",
  adminPeople: "users",
  adminPlatform: "platformVersion",
  adminRules: "cedarPolicies",
};

export function resolveAdminEntryTab<T extends string | null | undefined>(tab: T): T | AdminTab {
  return (tab && ADMIN_ENTRY_ALIASES[tab]) || tab;
}
