import type { AdminTab } from "../types/adminPanelTypes.governance";
import { ADMIN_ENTRIES, entryPages, resolveAdminEntryTab } from "./adminEntries";


// Pure navigation data for every admin-shell area (no JSX), so unit tests can
// prove that each page has exactly one home. Icons are joined in
// adminPanelAreaTabGroups.ts.
// Settings, Runtime and Automation are one Admin area; Observability is Operations. The page ids
// (AdminTab) never change, so stored links resolve through resolveAdminAreaForTab.
export type AdminAreaKey =
  | "knowledge"
  | "workflows"
  | "admin"
  | "operations";

// Platform feature switches set in server config only (never from the UI).
export type AdminPlatformFeature = "branding";
export type AdminPlatformFeatures = Partial<Record<AdminPlatformFeature, boolean>>;

export type AdminAreaTabRef = {
  id: AdminTab;
  label?: string;
  // Presentation only: hides the entry for non-admins. Every page keeps its
  // own server-side authorization.
  adminOnly?: boolean;
  // Reachable by deep link and from its owning page, but not a peer entry in
  // the sidebar.
  hidden?: boolean;
  // The visible entry this hidden page belongs to: the sidebar keeps that entry
  // selected while the page is open, and the page offers a way back to it.
  parent?: AdminTab;
  // Off-by-default platform feature: no sidebar entry while it is off; a deep
  // link still resolves and the page shows a "disabled on this platform" state.
  feature?: AdminPlatformFeature;
  // Presentation only: shown to platform admins and to admins/owners of the active Workspace (the Problems scope;
  // Operations › Costs, Knowledge › Sources);
  // a deep link still opens the page, and the server's refusal is shown there.
  workspaceAdmin?: boolean;
};

export type AdminAreaGroupRef = {
  label: string;
  tabs: AdminAreaTabRef[];
};

export type AdminAreaConfig = {
  sectionLabel: string;
  title: string;
  defaultTab: AdminTab;
  groups: AdminAreaGroupRef[];
};

// Pages of an Admin entry other than its own: hidden, with the entry as parent. Approval rule stays admin-only and
// Branding stays behind its platform feature.
const ADMIN_ENTRY_PAGE_FLAGS: Partial<Record<AdminTab, Partial<AdminAreaTabRef>>> = {
  approvalRule: { adminOnly: true },
  branding: { feature: "branding" },
};

function adminEntryChildRefs(): AdminAreaTabRef[] {
  return ADMIN_ENTRIES.flatMap((entry) =>
    entryPages(entry)
      .filter((tab) => tab !== entry.tab)
      .map((tab) => ({ id: tab, label: entry.label, hidden: true, parent: entry.tab, ...ADMIN_ENTRY_PAGE_FLAGS[tab] })),
  );
}

export const ADMIN_AREA_CONFIGS: Record<AdminAreaKey, AdminAreaConfig> = {
  knowledge: {
    sectionLabel: "Workspace",
    title: "Knowledge",
    defaultTab: "knowledgeLibrary",
    groups: [
      {
        label: "Find",
        tabs: [
          { id: "knowledgeLibrary", label: "Search" },
          // One Explore page; Relationships is its List view, Graph its Graph view (hidden child).
          { id: "knowledgeRelationships", label: "Explore" },
          { id: "knowledgeGraph", label: "Explore", adminOnly: true, hidden: true, parent: "knowledgeRelationships" },
        ],
      },
      {
        // Sources lists every source of the Workspace.
        label: "Sources",
        tabs: [
          // Also for admins/owners of the Workspace in focus, who configure its sources (the server's author check).
          { id: "workspaceKnowledge", label: "Sources", workspaceAdmin: true },
          { id: "knowledgeSources", label: "Documents" },
          { id: "knowledgeResearch", label: "Research websites" },
          { id: "researchPolicies", label: "Research profiles", adminOnly: true },
        ],
      },
      {
        // The maintained Workspace knowledge pages. "Structured graph" is where an admin builds the structured
        // graph.
        label: "Advanced",
        tabs: [
          { id: "knowledgePackages", label: "Packages", adminOnly: true },
          { id: "knowledgeBindings", label: "Bindings", adminOnly: true },
          { id: "knowledgeChanges", label: "Changes", adminOnly: true },
          { id: "knowledgeMemory", label: "Memory", adminOnly: true },
          { id: "knowledgeEpisodes", label: "Episodes", adminOnly: true },
          { id: "knowledge", label: "Engineering knowledge", adminOnly: true },
          { id: "knowledgeHandbook", label: "Structured graph", adminOnly: true },
        ],
      },
    ],
  },
  // The builder pages of the one Agents area (Clients · Build · Rules · Reference, chat/agents/
  // agentsAreaMenu.ts); the Clients and Rules pages of the Agents component join this menu as external entries.
  workflows: {
    sectionLabel: "Agent coordination",
    title: "Agents",
    defaultTab: "agents",
    groups: [
      {
        label: "Build",
        tabs: [
          { id: "agents", label: "Agents" },
          // One Workflows entry with Check results (`workflowChecks`) as its tab. The Canvas is the
          // Workflows page's main view.
          { id: "workflowList", label: "Workflows" },
          { id: "workflowChecks", label: "Workflows · Check results", hidden: true, parent: "workflowList" },
          // The designer (D2b1): one workflow open on the canvas; its own page key for the help.
          { id: "workflowDesigner", label: "Workflow designer", hidden: true, parent: "workflowList" },
          // Frozen: no nav entry; existing scenario profiles keep running.
          { id: "scenarios", label: "Scenarios", hidden: true, parent: "workflowList" },
          // Instructions and Effective setup left the navigation for Admin › Rules (linked there until the
          // unified Rules page holds them); their links still open them here.
          { id: "instructions", label: "Instructions", hidden: true },
          { id: "skills", label: "Skills" },
          { id: "effectiveSetup", label: "Effective setup", hidden: true },
        ],
      },
      {
        label: "Reference",
        tabs: [
          { id: "toolCatalog", label: "Tools" },
        ],
      },
    ],
  },
  operations: {
    sectionLabel: "Operations",
    title: "Operations",
    defaultTab: "observabilityOverview",
    groups: [
      {
        // The home page stands alone, without a group label (approved mock).
        label: "",
        tabs: [{ id: "observabilityOverview", label: "Overview" }],
      },
      {
        label: "Operate",
        tabs: [
          // Operations › Live: every active run, where it works, its last sign of life and its cost.
          { id: "operationsLive", label: "Live" },
          // Operations › Costs: what the runs cost and what they delivered.
          { id: "operationsCosts", label: "Costs", workspaceAdmin: true },
          { id: "observabilityHealth", label: "Health" },
          { id: "observabilityRuns", label: "Runs" },
        ],
      },
      {
        label: "Govern",
        tabs: [
          { id: "observabilityDecisions", label: "Decisions" },
          // One approval, opened from the REST calls audit, the Decisions drawer and a run's history.
          { id: "approvalDetail", label: "Approval", hidden: true, parent: "observabilityDecisions" },
          { id: "observabilityAudit", label: "Audit log" },
        ],
      },
      {
        label: "Cost",
        tabs: [{ id: "usage", label: "Usage & costs" }],
      },
    ],
  },
  // Admin: seven menu entries, each one page; their views are segments (adminEntries.ts). Every
  // other Admin page is a hidden child of its entry, so its id and links keep working and the entry stays selected.
  admin: {
    sectionLabel: "Platform",
    title: "Admin",
    defaultTab: "adminProblems",
    groups: [
      { label: "", tabs: ADMIN_ENTRIES.map((entry) => ({ id: entry.tab, label: entry.label })) },
      { label: "Views", tabs: adminEntryChildRefs() },
    ],
  },
};

export const ADMIN_AREA_KEYS = Object.keys(ADMIN_AREA_CONFIGS) as AdminAreaKey[];

/** The areas with Workspace-admin entries: only there the menu asks whether the viewer administers the Workspace. */
export const WORKSPACE_ADMIN_ENTRY_AREAS: ReadonlySet<AdminAreaKey> = new Set(ADMIN_AREA_KEYS.filter((area) =>
  ADMIN_AREA_CONFIGS[area].groups.some((group) => group.tabs.some((tabRef) => tabRef.workspaceAdmin))));

export function isAdminAreaKey(value: string): value is AdminAreaKey {
  return (ADMIN_AREA_KEYS as string[]).includes(value);
}

export function listAdminAreaTabRefs(area: AdminAreaKey, isAdmin = true): AdminAreaTabRef[] {
  return ADMIN_AREA_CONFIGS[area].groups
    .flatMap((group) => group.tabs)
    .filter((tabRef) => isAdmin || !tabRef.adminOnly);
}

/** Whether a menu entry shows: admin-only, Workspace-admin and feature entries hidden as marked; hidden pages never. */
export function isAdminTabRefVisible(tabRef: AdminAreaTabRef, isAdmin: boolean, features: AdminPlatformFeatures = {},
  canAdminWorkspace = isAdmin): boolean {
  return (isAdmin || !tabRef.adminOnly) && (canAdminWorkspace || !tabRef.workspaceAdmin) && !tabRef.hidden
    && isAdminTabRefEnabled(tabRef, features);
}

export function isAdminTabRefEnabled(tabRef: AdminAreaTabRef, features: AdminPlatformFeatures = {}): boolean {
  return !tabRef.feature || features[tabRef.feature] === true;
}

export function resolveAdminAreaForTab(requested: AdminTab): AdminAreaKey {
  const tab = resolveAdminEntryTab(requested);
  for (const area of ADMIN_AREA_KEYS) {
    if (listAdminAreaTabRefs(area).some((tabRef) => tabRef.id === tab)) {
      return area;
    }
  }
  return "admin";
}

// Returns the requested page when it belongs to the area and is visible to the
// user, otherwise the area's first visible page. A stale tab from another area
// therefore never renders under the wrong header.
export function resolveAdminAreaTab(
  area: AdminAreaKey,
  requested: string | null | undefined,
  isAdmin = true,
): AdminTab {
  const tab = resolveAdminEntryTab(requested);
  const visible = listAdminAreaTabRefs(area, isAdmin);
  const match = visible.find((tabRef) => tabRef.id === tab);
  if (match) return match.id;
  const fallback = visible.find((tabRef) => tabRef.id === ADMIN_AREA_CONFIGS[area].defaultTab);
  return (fallback ?? visible[0])?.id ?? ADMIN_AREA_CONFIGS[area].defaultTab;
}

export function resolveAdminAreaTabLabel(area: AdminAreaKey, tab: AdminTab): string | null {
  return listAdminAreaTabRefs(area).find((tabRef) => tabRef.id === tab)?.label ?? null;
}

// The sidebar entry to show as selected for a page: the page itself, or the
// visible entry a hidden page belongs to.
export function resolveAdminSidebarTab(area: AdminAreaKey, tab: AdminTab): AdminTab {
  return listAdminAreaTabRefs(area).find((tabRef) => tabRef.id === tab)?.parent ?? tab;
}

// Hidden pages that belong to ``parent``, in configuration order.
export function listAdminChildPages(area: AdminAreaKey, parent: AdminTab): AdminAreaTabRef[] {
  return listAdminAreaTabRefs(area).filter((tabRef) => tabRef.parent === parent);
}
