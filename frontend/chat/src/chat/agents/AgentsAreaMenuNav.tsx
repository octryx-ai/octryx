import type { AdminTab } from "../../admin/types/adminPanelTypes.governance";
import { AgentsNavIcon, type AgentsNavKey } from "./AgentsAreaNav";
import { AGENTS_AREA_ENTRIES } from "./agentsAreaMenu";
import { getAdminAreaTabGroups } from "../../admin/config/adminPanelAreaTabGroups";

// The builder pages' icons are the admin shell's own, so both sides of the one menu look the same.
const BUILDER_ICONS = new Map(getAdminAreaTabGroups("workflows").flatMap((group) => group.tabs).map((tab) => [tab.id, tab.icon]));

// The one menu of the Agents area (agentsAreaMenu.ts) on the Agents component's side: an Agents page switches in
// place, a builder page opens in the admin shell (`onOpenTab`).
export function AgentsAreaMenuNav({ activeKey, onSelectLocal, onOpenTab, showBuilder = true }: {
  activeKey: AgentsNavKey;
  onSelectLocal: (key: AgentsNavKey) => void;
  onOpenTab: (tab: AdminTab) => void;
  /** False for a member: the builder pages (Agents, Workflows, Skills, Tools) are admin pages; what the menu shows
   * opens (members do not manage agents). */
  showBuilder?: boolean;
}) {
  let currentGroup = "";
  return (
    <nav className="work-area__nav" aria-label="Agents navigation">
      {AGENTS_AREA_ENTRIES.filter((entry) => showBuilder || entry.host === "agents").map((entry) => {
        const showGroup = entry.group !== currentGroup;
        currentGroup = entry.group;
        const id = entry.host === "agents" ? entry.key : entry.tab;
        const active = entry.host === "agents" && entry.key === activeKey;
        return (
          <div key={`${entry.host}:${id}`} className="work-area__nav-row">
            {showGroup ? <div className="work-area__nav-section">{entry.group}</div> : null}
            <button type="button" className={`work-area__nav-button ${active ? "is-active" : ""}`}
              aria-current={active ? "page" : undefined} title={entry.label} data-testid={`agents-nav-${id}`}
              onClick={() => (entry.host === "agents" ? onSelectLocal(entry.key) : onOpenTab(entry.tab))}>
              {entry.host === "agents" ? <AgentsNavIcon navKey={entry.key} /> : BUILDER_ICONS.get(entry.tab) ?? null}
              <span>{entry.label}</span>
            </button>
          </div>
        );
      })}
    </nav>
  );
}
