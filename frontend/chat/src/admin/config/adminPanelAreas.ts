import type { AdminTab } from "../types/adminPanelTypes.governance";
import { ADMIN_ENTRIES, entryPages, resolveAdminEntryTab } from "./adminEntries";


// Page ids (AdminTab) never change, so stored links resolve through resolveAdminAreaForTab.
export type AdminAreaKey =
  | "knowledge"
  | "workflows"
  | "admin"
  | "operations";

export type AdminPlatformFeature = "branding";
export type AdminPlatformFeatures = Partial<Record<AdminPlatformFeature, boolean>>;

export type AdminAreaTabRef = {
  id: AdminTab;
  label?: string;
  // Presentation only: every page keeps its own server-side authorization.
  adminOnly?: boolean;
  hidden?: boolean;
  parent?: AdminTab;
  feature?: AdminPlatformFeature;
  // Presentation only: a deep link still opens the page, which shows the server's refusal.
  workspaceAdmin?: boolean;
  anyWorkspaceAdmin?: boolean;
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
          { id: "knowledgeRelationships", label: "Explore" },
          { id: "knowledgeGraph", label: "Explore", adminOnly: true, hidden: true, parent: "knowledgeRelationships" },
        ],
      },
      {
        label: "Sources",
        tabs: [
          { id: "workspaceKnowledge", label: "Sources", workspaceAdmin: true },
          { id: "knowledgeSources", label: "Documents" },
          { id: "knowledgeResearch", label: "Research websites" },
          { id: "researchPolicies", label: "Research profiles", adminOnly: true },
        ],
      },
      {
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
  workflows: {
    sectionLabel: "Agent coordination",
    title: "Agents",
    defaultTab: "agents",
    groups: [
      {
        label: "Build",
        tabs: [
          { id: "agents", label: "Agents" },
          { id: "workflowList", label: "Workflows" },
          { id: "workflowChecks", label: "Workflows · Check results", hidden: true, parent: "workflowList" },
          { id: "workflowDesigner", label: "Workflow designer", hidden: true, parent: "workflowList" },
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
        label: "",
        tabs: [{ id: "observabilityOverview", label: "Overview" }],
      },
      {
        label: "Operate",
        tabs: [
          { id: "operationsLive", label: "Live" },
          { id: "operationsCosts", label: "Costs", workspaceAdmin: true },
          { id: "observabilityHealth", label: "Health" },
          { id: "observabilityRuns", label: "Runs" },
        ],
      },
      {
        label: "Govern",
        tabs: [
          { id: "observabilityDecisions", label: "Decisions" },
          { id: "approvalDetail", label: "Approval", hidden: true, parent: "observabilityDecisions" },
          { id: "observabilityAudit", label: "Audit log" },
          { id: "complianceAudit", label: "Compliance audit", anyWorkspaceAdmin: true },
        ],
      },
      {
        label: "Cost",
        tabs: [{ id: "usage", label: "Usage & costs" }],
      },
    ],
  },
  // Every other Admin page is a hidden child of its entry, so its id and links keep working and the entry stays selected.
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

export const WORKSPACE_ADMIN_ENTRY_AREAS: ReadonlySet<AdminAreaKey> = new Set(ADMIN_AREA_KEYS.filter((area) =>
  ADMIN_AREA_CONFIGS[area].groups.some((group) => group.tabs.some((tabRef) => tabRef.workspaceAdmin))));

export const ANY_WORKSPACE_ADMIN_ENTRY_AREAS: ReadonlySet<AdminAreaKey> = new Set(ADMIN_AREA_KEYS.filter((area) =>
  ADMIN_AREA_CONFIGS[area].groups.some((group) => group.tabs.some((tabRef) => tabRef.anyWorkspaceAdmin))));

export function isAdminAreaKey(value: string): value is AdminAreaKey {
  return (ADMIN_AREA_KEYS as string[]).includes(value);
}

export function listAdminAreaTabRefs(area: AdminAreaKey, isAdmin = true): AdminAreaTabRef[] {
  return ADMIN_AREA_CONFIGS[area].groups
    .flatMap((group) => group.tabs)
    .filter((tabRef) => isAdmin || !tabRef.adminOnly);
}

export function isAdminTabRefVisible(tabRef: AdminAreaTabRef, isAdmin: boolean, features: AdminPlatformFeatures = {},
  canAdminWorkspace = isAdmin, canAdminAnyWorkspace = canAdminWorkspace): boolean {
  return (isAdmin || !tabRef.adminOnly) && (canAdminWorkspace || !tabRef.workspaceAdmin)
    && (canAdminAnyWorkspace || canAdminWorkspace || !tabRef.anyWorkspaceAdmin) && !tabRef.hidden
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

// A stale tab from another area never renders under the wrong header.
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

export function resolveAdminSidebarTab(area: AdminAreaKey, tab: AdminTab): AdminTab {
  return listAdminAreaTabRefs(area).find((tabRef) => tabRef.id === tab)?.parent ?? tab;
}

export function listAdminChildPages(area: AdminAreaKey, parent: AdminTab): AdminAreaTabRef[] {
  return listAdminAreaTabRefs(area).filter((tabRef) => tabRef.parent === parent);
}
