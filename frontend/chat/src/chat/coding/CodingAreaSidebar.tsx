// The Coding page's navigation rail: the Work menu with its collapse toggle.

import { AreaTitle } from "../workspace/AreaTitle";
import { WorkAreaNav } from "../work/WorkAreaNav";
import { entryViewParam } from "../work/workAreaMenu";
import { pagesOfArea } from "../../admin/components/plugins/pluginUiModel";
import type { CodingNavKey } from "./CodingAreaNav";

type PluginEntries = Parameters<typeof pagesOfArea>[0];

export function CodingAreaSidebar({ sidebarCollapsed, toggleSidebarCollapsed, activeNav, setActiveNav, onOpenArea,
  pluginEntries }: {
  sidebarCollapsed: boolean;
  toggleSidebarCollapsed: () => void;
  activeNav: CodingNavKey;
  setActiveNav: (key: CodingNavKey) => void;
  onOpenArea?: (area: "work", params: Record<string, string>) => void;
  pluginEntries: PluginEntries;
}) {
  return (
    <aside className="work-area__sidebar">
      <div className="work-area__brand">
        <div>
          <div className="work-area__eyebrow">Area</div>
          <AreaTitle area="Work" className="work-area__title" />
        </div>
        <button
          type="button"
          className="work-area__collapse"
          onClick={toggleSidebarCollapsed}
          aria-label={sidebarCollapsed ? "Expand Coding navigation" : "Collapse Coding navigation"}
          title={sidebarCollapsed ? "Expand navigation" : "Collapse navigation"}
        >
          <svg viewBox="0 0 20 20" aria-hidden="true">
            <path d={sidebarCollapsed ? "M7 5l5 5-5 5" : "M13 5l-5 5 5 5"} />
          </svg>
        </button>
      </div>
      <WorkAreaNav host="coding" activeKey={activeNav} onSelectLocal={(key) => setActiveNav(key as CodingNavKey)}
        onOpenOther={(entry) => { const view = entryViewParam(entry); onOpenArea?.("work", { [view.name]: view.value }); }}
        plugins={pagesOfArea(pluginEntries, "work")} onOpenPlugin={(key) => onOpenArea?.("work", { plugin_page: key })} />
    </aside>
  );
}
