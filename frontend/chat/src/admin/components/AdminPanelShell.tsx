import { useState, type ReactNode } from "react";
import { areaWithWorkspace, useActiveWorkspaceName } from "../../chat/workspace/activeWorkspaceName";
import { AdminHeaderSlotContext } from "./adminHeaderSlotContext";
import {
  ADMIN_AREA_CONFIGS,
  resolveAdminSidebarTab,
  type AdminAreaKey,
  type AdminPlatformFeatures,
} from "../config/adminPanelAreas";
import { getAdminAreaTabGroups } from "../config/adminPanelAreaTabGroups";
import type { AdminTab } from "../types/adminPanelTypes.governance";
import { ADMIN_PAGE_PURPOSE } from "../config/pagePurpose";
import { PageHeader } from "../../layout/PageHeader";
import { AdminExternalNavButtons, externalOnlyGroups, type AdminExternalNavEntry } from "./AdminExternalNav";
import { AdminEntryTabs } from "./AdminEntryTabs";

const SIDEBAR_COLLAPSED_STORAGE_KEY = "octryx.admin.sidebarCollapsed";
let sidebarCollapsedMemoryPreference = false;
let hasSidebarCollapsedMemoryPreference = false;

function readSidebarCollapsedPreference(): boolean {
  if (typeof window === "undefined") return false;
  if (hasSidebarCollapsedMemoryPreference) return sidebarCollapsedMemoryPreference;
  try {
    const storedPreference = window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY);
    if (storedPreference === "true" || storedPreference === "false") {
      sidebarCollapsedMemoryPreference = storedPreference === "true";
      hasSidebarCollapsedMemoryPreference = true;
    }
    return sidebarCollapsedMemoryPreference;
  } catch {
    return sidebarCollapsedMemoryPreference;
  }
}

function storeSidebarCollapsedPreference(collapsed: boolean) {
  sidebarCollapsedMemoryPreference = collapsed;
  hasSidebarCollapsedMemoryPreference = true;

  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(collapsed));
  } catch {
    // The visible navigation state still updates when persistent storage is unavailable.
  }
}

// The sidebar's collapsed state, remembered across visits.
function useSidebarCollapsed() {
  const [sidebarCollapsed, setSidebarCollapsed] = useState(
    readSidebarCollapsedPreference,
  );
  function toggleSidebarCollapsed() {
    setSidebarCollapsed((current) => {
      const next = !current;
      storeSidebarCollapsedPreference(next);
      return next;
    });
  }
  return { sidebarCollapsed, toggleSidebarCollapsed };
}

// Areas whose pages follow the active Workspace; their head writes it out ("Knowledge · Test"). Admin
// and Operations are platform-wide and show no Workspace.
const WORKSPACE_AREAS = new Set<AdminAreaKey>(["knowledge", "workflows"]);

type TabGroups = ReturnType<typeof getAdminAreaTabGroups>;
type TabGroup = TabGroups[number];
type TabEntry = TabGroup["tabs"][number];

type AdminPanelShellProps = {
  area?: AdminAreaKey;
  onClose?: () => void;
  tab: AdminTab;
  setTab: (tab: AdminTab) => void;
  currentTabLabel: string;
  isAdmin?: boolean;
  features?: AdminPlatformFeatures;
  // Platform admin, or admin/owner of the active Workspace (shows the Workspace-admin entries such as Costs).
  canAdminWorkspace?: boolean;
  // Platform admin, or admin/owner of any Workspace (shows Compliance audit).
  canAdminAnyWorkspace?: boolean;
  // Entries that open a page in another component of the same area (AdminExternalNav.tsx).
  externalNav?: AdminExternalNavEntry[];
  children: ReactNode;
};

// The label of the group holding the open page (or its parent entry), else the area's title.
function activeGroupLabelOf(groups: TabGroups, sidebarTab: AdminTab, tab: AdminTab, fallback: string) {
  return groups.find((group) =>
    group.tabs.some(
      (entry) =>
        entry.id === sidebarTab || entry.children?.some((child) => child.id === tab),
    ),
  )?.label || fallback;
}

export function AdminPanelShell({
  area = "admin", onClose, tab, setTab, currentTabLabel, isAdmin = true, features, canAdminWorkspace = isAdmin,
  canAdminAnyWorkspace = canAdminWorkspace, externalNav = [], children,
}: AdminPanelShellProps) {
  const { sidebarCollapsed, toggleSidebarCollapsed } = useSidebarCollapsed();
  const [headerSlot, setHeaderSlot] = useState<HTMLDivElement | null>(null);
  const workspaceName = useActiveWorkspaceName();
  const areaConfig = ADMIN_AREA_CONFIGS[area];
  // Admin's menu is its seven entries; external pages (Repositories, Jira write-back) are views of
  // Connections instead of menu entries.
  const entryArea = area === "admin";
  const sidebarExternalNav = entryArea ? [] : externalNav;
  const visibleTabGroups = getAdminAreaTabGroups(area, isAdmin, features, canAdminWorkspace, canAdminAnyWorkspace);
  // A hidden page (e.g. the workflow designer under Workflows) keeps its parent entry selected.
  const sidebarTab = resolveAdminSidebarTab(area, tab);
  const activeGroupLabel = activeGroupLabelOf(visibleTabGroups, sidebarTab, tab, areaConfig.title);

  const panel = (
      <div
        className={["admin-panel admin-panel--workspace admin-panel--area", `admin-panel--${area}`,
          sidebarCollapsed ? "admin-panel--sidebar-collapsed" : ""].filter(Boolean).join(" ")}
        onClick={(e) => e.stopPropagation()}
      >
        <aside className="admin-panel__sidebar">
          <SidebarHead area={area} title={WORKSPACE_AREAS.has(area) ? areaWithWorkspace(areaConfig.title, workspaceName) : areaConfig.title}
            sidebarCollapsed={sidebarCollapsed} onToggle={toggleSidebarCollapsed} />
          {externalOnlyGroups(sidebarExternalNav, visibleTabGroups.map((group) => group.label)).map((group) => (
            <section key={`external:${group.label}`} className="admin-panel__tab-group">
              <div className="admin-panel__tab-group-label">{group.label}</div>
              <AdminExternalNavButtons entries={group.entries} />
            </section>
          ))}
          {visibleTabGroups.map((group) => (
            <SidebarGroup key={group.label} group={group} tab={tab} sidebarTab={sidebarTab} setTab={setTab}
              externalNav={sidebarExternalNav} />
          ))}
        </aside>

        <ShellHeader eyebrow={entryArea ? areaConfig.title : `${areaConfig.title} · ${activeGroupLabel}`} tab={tab}
          currentTabLabel={currentTabLabel} setHeaderSlot={setHeaderSlot} onClose={onClose} />

        <ShellBody entryArea={entryArea} tab={tab} setTab={setTab} isAdmin={isAdmin} features={features}
          externalNav={externalNav} headerSlot={headerSlot}>{children}</ShellBody>
      </div>
  );

  if (!onClose) {
    return panel;
  }

  return (
    <div
      className="admin-panel-backdrop admin-panel-backdrop--workspace"
      onClick={onClose}
    >
      {panel}
    </div>
  );
}

type NavProps = { tab: AdminTab; sidebarTab: AdminTab; setTab: (tab: AdminTab) => void };

function SidebarHead({ area, title, sidebarCollapsed, onToggle }: {
  area: AdminAreaKey; title: string; sidebarCollapsed: boolean; onToggle: () => void;
}) {
  const areaConfig = ADMIN_AREA_CONFIGS[area];
  const toggleSidebarCollapsed = onToggle;
  return (
    <div className="admin-panel__sidebar-logo">
      <div className="admin-panel__sidebar-brand">
        <span className="admin-panel__sidebar-title">
          {areaConfig.sectionLabel}
        </span>
        <span className="admin-panel__sidebar-subtitle">
          {title}
        </span>
      </div>
      <button
        type="button"
        className="admin-panel__sidebar-collapse"
        onClick={toggleSidebarCollapsed}
        aria-expanded={!sidebarCollapsed}
        aria-label={
          sidebarCollapsed ? "Expand navigation" : "Collapse navigation"
        }
        title={sidebarCollapsed ? "Expand navigation" : "Collapse navigation"}
      >
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d={sidebarCollapsed ? "M7 5l5 5-5 5" : "M13 5l-5 5 5 5"} />
        </svg>
      </button>
    </div>
  );
}

function SidebarGroup({ group, tab, sidebarTab, setTab, externalNav }: NavProps & {
  group: TabGroup; externalNav: AdminExternalNavEntry[];
}) {
  return (
    <section className="admin-panel__tab-group">
      {group.label ? <div className="admin-panel__tab-group-label">{group.label}</div> : null}
      {/* Entries of the same group from the area's other component come first, in the menu's order. */}
      <AdminExternalNavButtons entries={externalNav.filter((entry) => entry.group === group.label && entry.position !== "end")} />
      {group.tabs.map((entry) => (
        <SidebarEntry key={entry.id} entry={entry} tab={tab} sidebarTab={sidebarTab} setTab={setTab} />
      ))}
      <AdminExternalNavButtons entries={externalNav.filter((entry) => entry.group === group.label && entry.position === "end")} />
    </section>
  );
}

function SidebarEntry({ entry, tab, sidebarTab, setTab }: NavProps & { entry: TabEntry }) {
  const childActive = entry.children?.some(
    (child) => child.id === tab,
  );
  return (
    <div className="admin-panel__tab-tree">
      <button
        type="button"
        className={`admin-panel__tab ${
          sidebarTab === entry.id || childActive
            ? "admin-panel__tab--active"
            : ""
        }`}
        onClick={() => setTab(entry.id)}
        aria-current={tab === entry.id ? "page" : sidebarTab === entry.id ? "location" : undefined}
        aria-label={entry.label}
        title={entry.label}
      >
        {entry.icon}
        <span className="admin-panel__tab-label">
          {entry.label}
        </span>
      </button>
      {entry.children && (tab === entry.id || childActive) ? (
        <div className="admin-panel__subtabs">
          {entry.children.map((child) => (
            <button
              key={child.id}
              type="button"
              className={`admin-panel__subtab ${
                tab === child.id
                  ? "admin-panel__subtab--active"
                  : ""
              }`}
              onClick={() => setTab(child.id)}
              aria-current={tab === child.id ? "page" : undefined}
            >
              {child.label}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function ShellHeader({ eyebrow, tab, currentTabLabel, setHeaderSlot, onClose }: {
  eyebrow: string; tab: AdminTab; currentTabLabel: string; setHeaderSlot: (node: HTMLDivElement | null) => void;
  onClose?: () => void;
}) {
  return (
  <div className="admin-panel__header">
    <PageHeader eyebrow={eyebrow} title={currentTabLabel}
      purpose={ADMIN_PAGE_PURPOSE[tab]} actionsRef={setHeaderSlot}
      trailing={onClose ? (
      <button
        type="button"
        className="admin-panel__close-btn"
        onClick={onClose}
        aria-label="Close settings"
      >
        <svg viewBox="0 0 20 20" aria-hidden="true">
          <path d="M5 5L15 15M15 5L5 15" />
        </svg>
      </button>
    ) : null} />
  </div>

  );
}

type BodyProps = Pick<AdminPanelShellProps, "tab" | "setTab" | "isAdmin" | "features" | "children"> & {
  entryArea: boolean; externalNav: AdminExternalNavEntry[]; headerSlot: HTMLDivElement | null;
};

function ShellBody({ entryArea, tab, setTab, isAdmin, features, externalNav, headerSlot, children }: BodyProps) {
  return (
    <div className="admin-panel__body">
      {entryArea ? (
        <AdminEntryTabs tab={tab} setTab={setTab} isAdmin={isAdmin} features={features}
          externalKeys={externalNav.map((entry) => entry.key)}
          onExternal={(key) => externalNav.find((entry) => entry.key === key)?.onSelect()} />
      ) : null}
      <AdminHeaderSlotContext.Provider value={headerSlot}>{children}</AdminHeaderSlotContext.Provider>
    </div>
  );
}
