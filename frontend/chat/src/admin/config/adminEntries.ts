import type { AdminTab } from "../types/adminPanelTypes.governance";

// Admin = seven entries, each one page. An entry's views are segments at the top of
// the page; a view with several pages shows them as a second, small row of segments. At most two levels of tabs:
// a page that has its own sections (Policies, Content security) must be a view of its own, so its
// sections are the second row. Every page keeps its page id, so links open it inside its entry
// without a redirect. Pure data, so tests can prove that every Admin page has exactly one (entry, view).

export type AdminEntryKey = "problems" | "workspaces" | "connections" | "models" | "rules" | "people" | "platform";

// A page inside a view; `also` are pages reached from it (no segment of their own) that keep it selected.
export type AdminViewPage = { tab: AdminTab; label: string; also?: AdminTab[] };

// A view opens a page of this shell (`pages`, first = its target) or another component of the area (`external`,
// matched against the shell's external entries by key).
export type AdminEntryView = { key: string; label: string; pages?: AdminViewPage[]; external?: string; pointers?: AdminViewPointer[] };

// A setting that lives elsewhere but is looked for in this view: a link to its home, not a page of its own (the
// setting is never duplicated). `section` selects a register inside the target page (adminPageSection).
export type AdminViewPointer = { label: string; tab: AdminTab; section?: string };

export type AdminEntry = {
  key: AdminEntryKey;
  label: string;
  // The page the menu entry opens (its first view).
  tab: AdminTab;
  views: AdminEntryView[];
};

const page = (tab: AdminTab, label: string, also?: AdminTab[]): AdminViewPage => ({ tab, label, also });
const view = (key: string, label: string, pages: AdminViewPage[]): AdminEntryView => ({ key, label, pages });
// Platform › Advanced also points to the platform coding engine, which lives in Models › Defaults.
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
      // The connector settings page has no segment of its own: this list is its overview.
      // It stays a page of this view for what only it holds today (built-in connector setup, private hosts), opened
      // from a connection's ⋯ menu and the page's "More" menu (?tab=connectors&connector=jira).
      view("connections", "Connections", [page("adminConnections", "Connections", ["connectors"])]),
      view("mcp", "MCP servers", [page("mcp", "MCP servers")]),
      // Custom REST APIs (backend): the APIs with their operations and grants, and the audit of their calls.
      view("restApis", "REST APIs", [page("restApis", "APIs"), page("restApiCalls", "Calls")]),
      view("databases", "Databases", [page("databases", "Databases")]),
      view("channels", "Channels", [page("channels", "Channels")]),
      view("webhooks", "Webhooks", [page("webhooks", "Webhooks")]),
      // Until each use carries its own schedule.
      view("schedules", "Schedules", [page("schedulers", "Schedulers"), page("tasks", "Actions")]),
      // Pages of Work and Coding (E2 step 2/3 moves them into the connection).
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
    // Rules opens on its first real page. The one rule list ("adminRules") waits
    // for the server's central rules, so it is no view (alias below).
    tab: "cedarPolicies",
    views: [
      // The rule pages. Each is a view of its own: Policies,
      // Tool & approval policies and Content security have sections, which must be the second level, not a third.
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
      // Work roles (board 8): roles made of functions, assigned per Workspace. The platform RBAC roles are
      // "Platform access" so the two are not confused; their page id stays identityRoles.
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
        page("runtimeCompression", "Tool output compression"),
        page("tts", "Voice & speech"),
        page("backupRestore", "Backup & restore"),
        page("branding", "Branding"),
        page("corpIdentity", "Corporate identity"),
        page("promptCatalog", "System prompt texts"),
      ]),
    ],
  },
];

// Every page an entry holds, in order: its views' pages and their `also` pages.
export function entryPages(entry: AdminEntry): AdminTab[] {
  const pages = entry.views.flatMap((v) => (v.pages ?? []).flatMap((p) => [p.tab, ...(p.also ?? [])]));
  return Array.from(new Set([entry.tab, ...pages]));
}

export type AdminEntryLocation = { entry: AdminEntry; view: AdminEntryView | null; page: AdminViewPage | null };

// Where a page sits: its entry, view and page (an `also` page resolves to the page it belongs to).
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

// Short entry ids for links that name an entry instead of a page (?tab=adminModels): the entry's first view.
export const ADMIN_ENTRY_ALIASES: Record<string, AdminTab> = {
  adminWorkspaces: "projects",
  adminModels: "providers",
  adminPeople: "users",
  adminPlatform: "platformVersion",
  // The Rules entry opens on its first page, Policies.
  adminRules: "cedarPolicies",
};

/** The page a requested tab opens: an entry id opens the entry's first view, a page id itself. */
export function resolveAdminEntryTab<T extends string | null | undefined>(tab: T): T | AdminTab {
  return (tab && ADMIN_ENTRY_ALIASES[tab]) || tab;
}
