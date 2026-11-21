import { Fragment, useRef } from "react";
import { ADMIN_ENTRIES } from "../admin/config/adminEntries";
import type { AdminTab } from "../admin/types/adminPanelTypes.governance";
import type { WorkspaceArea } from "./workspaceAreas";
import { getWorkspaceDestinations, isDestinationActive } from "./workspaceDestinations";
import { CompanionLogoTrigger } from "./companion/CompanionHost";
import { entryViewParam, WORK_AREA_ENTRIES } from "./work/workAreaMenu";
import { visibleToReader } from "./work/workAccess";
import { GlobalWorkspaceSwitch } from "./workspace/GlobalWorkspaceSwitch";
import type { ProjectOption } from "../chatOptionTypes";
import "./compact-area-menu.css";

export function CompactAreaMenu({ activeArea, isAdmin, canReadWork, canManageWork = false, onSelectArea, onSelectAdminTab,
  projects = [], fallbackWorkspaceId = null }: {
  activeArea: WorkspaceArea;
  canManageWork?: boolean;
  projects?: ProjectOption[];
  fallbackWorkspaceId?: string | null;
  isAdmin: boolean;
  canReadWork: boolean;
  /** A Work page opens with its address field (`work_view` / `coding_view`), the area page reads it on open. */
  onSelectArea: (area: WorkspaceArea, params?: Record<string, string>) => void;
  onSelectAdminTab: (tab: AdminTab) => void;
}) {
  const menu = useRef<HTMLDetailsElement>(null);
  const summary = useRef<HTMLElement>(null);
  const destinations = getWorkspaceDestinations(isAdmin, canReadWork);
  const currentLabel = destinations.find((item) => isDestinationActive(item, activeArea))?.label ?? "Workspace";
  const close = () => {
    if (menu.current) menu.current.open = false;
    summary.current?.focus();
  };

  return (
    <div className="compact-area-menu">
      <details ref={menu} onKeyDown={(event) => {
        if (event.key === "Escape") { event.preventDefault(); close(); }
      }}>
        <summary ref={summary} aria-label={`Navigation menu: ${currentLabel}`}>
          Menu <span aria-hidden="true">·</span> {currentLabel}
        </summary>
        <nav aria-label="Workspace navigation">
          {destinations.map((item) => (
            <Fragment key={item.area}>
              <button type="button" aria-current={isDestinationActive(item, activeArea) ? "page" : undefined}
                onClick={() => {
                  close();
                  if (item.adminTab) onSelectAdminTab(item.adminTab);
                  else onSelectArea(item.area);
                }}>{item.label}</button>
              {/* On a phone Admin's own menu is hidden like every area's sub-navigation; its seven
                  entries are reachable here instead of between the page header and the page. */}
              {item.area === "admin" ? ADMIN_ENTRIES.map((entry) => (
                <button key={entry.key} type="button" className="compact-area-menu__sub" data-testid={`compact-admin-${entry.key}`}
                  onClick={() => { close(); onSelectAdminTab(entry.tab); }}>{entry.label}</button>
              )) : null}
              {/* Outsider walkthrough: on a phone Work opened Runs and no other Work page was reachable
                  (Work items among them). Its pages are listed here like Admin's. */}
              {item.area === "work" ? WORK_AREA_ENTRIES.filter((entry) => canManageWork || visibleToReader(entry.host, entry.key))
                .map((entry) => {
                  const view = entryViewParam(entry);
                  return (
                    <button key={`${entry.host}:${entry.key}`} type="button" className="compact-area-menu__sub"
                      data-testid={`compact-work-${entry.key}`}
                      onClick={() => { close(); onSelectArea(entry.host, { [view.name]: view.value }); }}>{entry.label}</button>
                  );
                }) : null}
            </Fragment>
          ))}
        </nav>
      </details>
      {/* On narrow screens the rail is hidden; the one Workspace switch and Octryx sit at the end of this bar. */}
      <GlobalWorkspaceSwitch variant="compact" projects={projects} fallbackWorkspaceId={fallbackWorkspaceId}
        allowGlobal={isAdmin} />
      <CompanionLogoTrigger className="octryx-trigger--compact" testId="octryx-button-compact" />
    </div>
  );
}
