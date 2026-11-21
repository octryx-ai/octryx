// State of the Work area: the data, the page in the address (nav, items mode, plans tab, plugin page), filters,
// the sidebar preference, and the filtered items with the selected item's detail.
import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from "react";
import { visibleToReader } from "./workAccess";
import { useWorkAreaData } from "./useWorkAreaData";
import { workFilterOptions } from "./workFilterOptions";
import { assigneeFilterOptions } from "./workPeople";
import { readSidebarCollapsedPreference, storeSidebarCollapsedPreference } from "./workSidebarPreference";
import type { WorkFilters as WorkFiltersValue, WorkNavKey } from "./workTypes";
import type { WorkItem } from "./workItemTypes";
import { EMPTY_WORK_FILTERS, filterWorkItems } from "./workUtils";
import type { WorkEmptyAction } from "./workEmptyStates";
import type { AdminTab } from "../../admin/types/adminPanelTypes.governance";
import { useWorkDetailSelection } from "./useWorkDetailSelection";
import { useFullWorkItem } from "./useFullWorkItem";
import { isWorkItemPage } from "./workDetailLink";
import { workLocation, writeWorkView, type WorkItemsMode, type WorkPlansTab } from "./workNavRedirects";
import { requestWorkspaceSettings } from "../../admin/components/projectsTab/workspaceSettingsLink";
import { useMyWork } from "./myWork/useMyWork";
import { itemsInScope, needsChoice } from "./myWork/myWorkModel";
import { usePluginSlots } from "../../admin/components/plugins/usePluginSlots";
import { desktopFetch } from "../../admin/components/plugins/pluginUiApi";
import { pagesOfArea } from "../../admin/components/plugins/pluginUiModel";
import { readPluginPage, writePluginPage } from "./workNavRedirects";

// Plans and Intake load their own data.
const SELF_LOADING = new Set<WorkNavKey>(["runs", "changePlans", "intake"]);

// A plugin's page in the Work menu (plugins contract §4), kept in the address as `plugin_page=<install>:<page>`.
function useWorkPluginPage(workspaceId: string) {
  const [pluginPage, setPluginPage] = useState<string | null>(() => readPluginPage(window.location.search));
  const pluginSlots = usePluginSlots(workspaceId, desktopFetch);
  const pluginGroups = useMemo(() => pagesOfArea(pluginSlots.entries, "work"), [pluginSlots.entries]);
  const pluginEntry = pluginGroups.flatMap((group) => group.pages).find((page) => page.key === pluginPage) ?? null;
  useEffect(() => writePluginPage(pluginPage), [pluginPage]);
  return { pluginPage, setPluginPage, pluginGroups, pluginEntry };
}

function toggleSidebarPreference(setSidebarCollapsed: Dispatch<SetStateAction<boolean>>) {
  setSidebarCollapsed((current) => {
    const next = !current;
    storeSidebarCollapsedPreference(next);
    return next;
  });
}

export function useWorkAreaNavigation(
  workspaceId: string,
  canManageWork: boolean,
  onOpenAdminTab: ((tab: AdminTab) => void) | undefined,
) {
  const data = useWorkAreaData(workspaceId, canManageWork);
  const { refresh } = data;
  // The address decides the first page: today's entries, the removed ones redirected (workNavRedirects.ts).
  const [initial] = useState(() => workLocation(window.location.search));
  // A reader asked for a manager page (a link) lands on Work items instead of a refusal.
  const [activeNav, setActiveNav] = useState<WorkNavKey>(
    canManageWork || visibleToReader("work", initial.nav) ? initial.nav : "board");
  const [itemsMode, setItemsMode] = useState<WorkItemsMode>(initial.itemsMode);
  const [plansTab, setPlansTab] = useState<WorkPlansTab>(initial.plansTab);
  const [filters, setFilters] = useState<WorkFiltersValue>(EMPTY_WORK_FILTERS);
  const [reloadToken, setReloadToken] = useState(0);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsedPreference);
  const plugin = useWorkPluginPage(workspaceId);

  // The chosen page stays in the address: a remount of the area reopens it instead of falling back to Work items.
  useEffect(() => writeWorkView({ nav: activeNav, itemsMode, plansTab }), [activeNav, itemsMode, plansTab]);

  // Switching the Workspace switches every Work page.
  useEffect(() => {
    void refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workspaceId]);

  const toggleSidebarCollapsed = () => toggleSidebarPreference(setSidebarCollapsed);

  // Workspace settings → a section of the active Workspace (Connectors, Repositories, Access).
  function openWorkspaceSettings(section: "connectors" | "repositories" | "access") {
    if (workspaceId) requestWorkspaceSettings(workspaceId, section);
    onOpenAdminTab?.("projects");
  }

  function handleEmptyAction(action: WorkEmptyAction) {
    if (action === "connectJira") openWorkspaceSettings("connectors");
    else if (action === "openSyncSettings") setActiveNav("intake");
    else { setActiveNav("board"); setItemsMode("table"); }
  }

  return {
    data, initial, activeNav, setActiveNav, itemsMode, setItemsMode, plansTab, setPlansTab, filters, setFilters,
    reloadToken, setReloadToken, sidebarCollapsed, plugin, toggleSidebarCollapsed, openWorkspaceSettings,
    handleEmptyAction,
  };
}

export function useWorkAreaItems(
  workspaceId: string,
  { items, loading, error }: { items: WorkItem[]; loading: boolean; error: string | null },
  { filters, reloadToken, activeNav }: { filters: WorkFiltersValue; reloadToken: number; activeNav: WorkNavKey },
) {
  const myWork = useMyWork(workspaceId);
  const filteredItems = useMemo(() => itemsInScope(filterWorkItems(items, filters), myWork.scope, myWork.state),
    [items, filters, myWork.scope, myWork.state]);
  const askMyWork = needsChoice(myWork.scope, myWork.state, myWork.changing);
  const options = useMemo(() => workFilterOptions(items), [items]);
  const assigneeLabels = useMemo(() => assigneeFilterOptions(items).labels, [items]);
  const detail = useWorkDetailSelection(items, reloadToken);
  const [detailRevision, setDetailRevision] = useState(0);
  // Lean list rows: the detail reads the item itself (useFullWorkItem.ts), also when it is not in the loaded pages.
  const selectedItem = useFullWorkItem(detail.selectedItemId, detail.selection.item,
    items.some((entry) => entry.id === detail.selectedItemId), reloadToken + detailRevision);
  const selfLoading = SELF_LOADING.has(activeNav);
  // "Open as page": the same detail full width in place of the list (work_item_view=page).
  const location = typeof window === "undefined" ? { search: "", pathname: "/chat" } : window.location;
  const asPage = Boolean(selectedItem) && isWorkItemPage(location.search);
  const ready = !loading && !error;
  const showItems = ready && activeNav === "board" && !askMyWork;
  return {
    myWork, filteredItems, askMyWork, options, assigneeLabels, detail, setDetailRevision, selectedItem, selfLoading,
    location, asPage, ready, showItems,
  };
}
